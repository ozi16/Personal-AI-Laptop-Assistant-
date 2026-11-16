"""Preview, apply, and undo file moves. A move requires an explicit approval flag."""

import logging
import os
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from database.repositories.file_repository import FileRepository
from modules.file_manager.models import FileOperation, MovePlan, OperationResult, ScannedFile
from modules.file_manager.organizer import destination_block_reason, destination_for, plan_organization
from modules.file_manager.path_validator import (
    PathValidationError,
    ensure_inside,
    is_reparse_point,
    paths_equal,
    validate_scan_root,
)

logger = logging.getLogger("nexus.file_manager")


class OperationManager:
    """Move files inside one approved folder and record each attempt."""

    def __init__(self, repository: FileRepository, allowed_root: Path) -> None:
        self.repository = repository
        self.allowed_root = validate_scan_root(allowed_root)

    def preview(self, files: Sequence[ScannedFile]) -> tuple[MovePlan, ...]:
        """Build the move plan. This does not create folders or move files."""
        return plan_organization(files, self.allowed_root)

    def execute(
        self,
        plans: Sequence[MovePlan],
        *,
        approved: bool,
    ) -> tuple[OperationResult, ...]:
        """Move the approved plans. Conflicts are recorded as failed and left in place."""
        if approved is not True:
            raise PermissionError("Pemindahan file membutuhkan persetujuan pengguna.")
        results: list[OperationResult] = []
        for plan in plans:
            if plan.already_organized:
                continue
            results.append(self._execute_move(plan))
        return tuple(results)

    def undo(self, operation_id: int) -> OperationResult:
        """Move a successful operation back. An occupied original path is left untouched."""
        operation = self.repository.get_operation(operation_id)
        if operation is None:
            raise ValueError("Operasi tidak ditemukan.")
        if operation.operation_type != "move" or operation.status != "success":
            raise ValueError("Undo hanya untuk pemindahan yang berhasil.")

        created = datetime.now()
        self.repository.begin_undo(operation.id)
        current = Path(operation.destination_path)
        original = Path(operation.source_path)
        try:
            current_resolved = ensure_inside(self.allowed_root, current)
            original_resolved = ensure_inside(self.allowed_root, original)
        except PathValidationError as exc:
            return self._abort_undo(operation.id, created, str(exc))

        if original_resolved.exists() or original_resolved.is_symlink():
            return self._abort_undo(
                operation.id,
                created,
                "Lokasi asal sudah terisi. File yang ada tidak dihapus.",
            )
        if not _regular_file(current_resolved):
            return self._abort_undo(
                operation.id,
                created,
                "File hasil pemindahan tidak ditemukan.",
            )
        if current_resolved.name != original_resolved.name:
            return self._abort_undo(
                operation.id,
                created,
                "Nama file tidak sama dengan lokasi asal.",
            )
        try:
            safe_move(current_resolved, original_resolved, self.allowed_root)
        except PermissionError:
            return self._abort_undo(operation.id, created, "Tidak ada izin untuk mengembalikan file.")
        except OSError as exc:
            logger.warning("Undo failed for %s: %s", operation.id, exc)
            return self._abort_undo(operation.id, created, "Pengembalian file gagal.")

        try:
            undone = self.repository.complete_undo(
                operation.id,
                current_resolved,
                original_resolved,
                created,
            )
        except Exception:
            logger.exception("Undo moved %s but the history could not be saved", operation.id)
            pending = self.repository.get_operation(operation.id)
            return OperationResult(
                pending,
                "File sudah dikembalikan, tetapi pencatatan belum selesai. Periksa pemulihan.",
                False,
            )
        logger.info("Undid move %s", operation.id)
        return OperationResult(undone, "Pemindahan diurungkan.", True)

    def recover(self) -> tuple[OperationResult, ...]:
        """Reconcile pending rows from the files already on disk.

        This never renames, overwrites, or deletes a file. An ambiguous pair of
        paths is marked ``recovery_required`` for the user.
        """
        results: list[OperationResult] = []
        for operation in self.repository.list_open_operations():
            results.append(self._recover_one(operation))
        return tuple(results)

    def _execute_move(self, plan: MovePlan) -> OperationResult:
        created = datetime.now()
        if plan.conflict:
            return self._fail(plan, created, plan.conflict_reason or "Rencana ini bentrok.")
        try:
            source = ensure_inside(self.allowed_root, plan.source_path)
        except PathValidationError as exc:
            return self._fail(plan, created, str(exc))
        if not _regular_file(source):
            return self._fail(plan, created, "File sumber tidak ditemukan atau bukan file biasa.")
        try:
            _category, expected = destination_for(self.allowed_root, source)
            destination = ensure_inside(self.allowed_root, expected)
            planned = ensure_inside(self.allowed_root, plan.destination_path)
        except PathValidationError as exc:
            return self._fail(plan, created, str(exc))
        if source.name != destination.name:
            return self._fail(plan, created, "Nama file tidak boleh diubah.")
        if not paths_equal(destination, planned):
            return self._fail(plan, created, "Tujuan tidak sesuai rencana pengorganisasian.")
        if paths_equal(source, destination):
            return self._fail(plan, created, "File sudah berada di lokasi tujuan.")
        blocked = destination_block_reason(self.allowed_root, source, destination)
        if blocked:
            return self._fail(plan, created, blocked)
        if destination.exists() or destination.is_symlink():
            return self._fail(plan, created, "File tujuan sudah ada. Tidak ada penimpaan.")

        pending = self.repository.add_operation(
            source, destination, "move", "pending", created, None
        )
        try:
            safe_move(source, destination, self.allowed_root)
        except FileExistsError:
            return self._fail_pending(pending.id, "File tujuan sudah ada. Tidak ada penimpaan.")
        except PermissionError:
            return self._fail_pending(pending.id, "Tidak ada izin untuk memindahkan file.")
        except OSError as exc:
            logger.warning("Move failed %s -> %s: %s", source, destination, exc)
            return self._fail_pending(pending.id, "Pemindahan gagal.")

        try:
            operation = self.repository.complete_move(pending.id, source, destination, datetime.now())
        except Exception:
            logger.exception("Move of %s succeeded but the history could not be saved", pending.id)
            current = self.repository.get_operation(pending.id)
            return OperationResult(
                current,
                "File sudah berpindah, tetapi pencatatan belum selesai. Periksa pemulihan.",
                False,
            )
        logger.info("Moved %s to %s", source, destination)
        return OperationResult(operation, "File dipindahkan.", True)

    def _recover_one(self, operation: FileOperation) -> OperationResult:
        if operation.status == "pending":
            return self._recover_pending_move(operation)
        if operation.status == "undo_pending":
            return self._recover_pending_undo(operation)
        return self._mark_ambiguous(operation, "Status operasi tidak dikenali.")

    def _recover_pending_move(self, operation: FileOperation) -> OperationResult:
        try:
            source = ensure_inside(self.allowed_root, Path(operation.source_path))
            destination = ensure_inside(self.allowed_root, Path(operation.destination_path))
        except PathValidationError as exc:
            return OperationResult(operation, str(exc), False)
        source_ready = _regular_file(source)
        destination_ready = _regular_file(destination)
        source_present = _path_present(source)
        destination_present = _path_present(destination)
        if source_ready and not destination_present:
            failed = self.repository.fail_operation(
                operation.id,
                "Pemindahan terputus sebelum file berpindah.",
                datetime.now(),
            )
            return OperationResult(failed, failed.error_message or "", False)
        if (
            not source_present
            and destination_ready
            and source.name == destination.name
        ):
            try:
                completed = self.repository.complete_move(
                    operation.id, source, destination, datetime.now()
                )
            except Exception:
                logger.exception("Could not reconcile pending move %s", operation.id)
                return self._mark_ambiguous(
                    operation,
                    "File sudah berada di tujuan, tetapi catatan belum bisa diperbarui.",
                )
            return OperationResult(completed, "Catatan diselaraskan dengan file yang sudah berpindah.", True)
        return self._mark_ambiguous(
            operation,
            "Kondisi file ambigu. NEXUS tidak memindahkan, menimpa, atau menghapus file.",
        )

    def _recover_pending_undo(self, operation: FileOperation) -> OperationResult:
        try:
            current = ensure_inside(self.allowed_root, Path(operation.destination_path))
            original = ensure_inside(self.allowed_root, Path(operation.source_path))
        except PathValidationError as exc:
            return OperationResult(operation, str(exc), False)
        current_ready = _regular_file(current)
        original_ready = _regular_file(original)
        current_present = _path_present(current)
        original_present = _path_present(original)
        if current_ready and not original_present:
            restored = self.repository.restore_successful_move(operation.id)
            return OperationResult(
                restored,
                "Undo terputus sebelum file dikembalikan. Status kembali menjadi berhasil.",
                True,
            )
        if not current_present and original_ready and current.name == original.name:
            try:
                undone = self.repository.complete_undo(
                    operation.id,
                    current,
                    original,
                    datetime.now(),
                )
            except Exception:
                logger.exception("Could not reconcile pending undo %s", operation.id)
                return self._mark_ambiguous(
                    operation,
                    "File sudah kembali, tetapi catatan belum bisa diperbarui.",
                )
            return OperationResult(undone, "Catatan diselaraskan dengan file yang sudah dikembalikan.", True)
        return self._mark_ambiguous(
            operation,
            "Kondisi undo ambigu. NEXUS tidak memindahkan, menimpa, atau menghapus file.",
        )

    def _mark_ambiguous(self, operation: FileOperation, message: str) -> OperationResult:
        try:
            recorded = self.repository.mark_recovery_required(operation.id, message, datetime.now())
        except Exception:
            logger.exception("Could not mark operation %s for recovery", operation.id)
            return OperationResult(operation, message, False)
        return OperationResult(recorded, message, False)

    def _fail(self, plan: MovePlan, created: datetime, message: str) -> OperationResult:
        operation = self.repository.add_operation(
            plan.source_path,
            plan.destination_path,
            "move",
            "failed",
            created,
            datetime.now(),
            message,
        )
        logger.warning("Move failed %s -> %s: %s", plan.source_path, plan.destination_path, message)
        return OperationResult(operation, message, False)

    def _fail_pending(self, operation_id: int, message: str) -> OperationResult:
        recorded = self.repository.fail_operation(operation_id, message, datetime.now())
        logger.warning("Pending move %s failed: %s", operation_id, message)
        return OperationResult(recorded, message, False)

    def _abort_undo(self, operation_id: int, created: datetime, message: str) -> OperationResult:
        recorded = self.repository.abort_undo(operation_id, message, created)
        logger.warning("Undo failed for %s: %s", operation_id, message)
        return OperationResult(recorded, message, False)


def safe_move(source: Path, destination: Path, root: Path) -> None:
    """Rename one file inside ``root``. An existing destination raises ``FileExistsError``."""
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(str(destination))
    _assert_parents_safe(root, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _assert_parents_safe(root, destination)
    if not destination.parent.is_dir():
        raise OSError("Folder tujuan tidak tersedia")
    if is_reparse_point(source):
        raise OSError("Sumber adalah symbolic link atau junction")
    os.rename(source, destination)


def _regular_file(path: Path) -> bool:
    """True for a normal file. Links and missing paths are excluded."""
    return path.is_file() and not is_reparse_point(path)


def _path_present(path: Path) -> bool:
    """True when any directory entry occupies the path, including a link."""
    return path.exists() or path.is_symlink()


def _assert_parents_safe(root: Path, destination: Path) -> None:
    current = destination.parent
    while not paths_equal(current, root):
        if current.exists() and not current.is_dir():
            raise OSError("Bagian dari folder tujuan sudah dipakai oleh sebuah file")
        if current.exists() and is_reparse_point(current):
            raise OSError("Folder tujuan melewati symbolic link atau junction")
        if current.parent == current:
            break
        current = current.parent
