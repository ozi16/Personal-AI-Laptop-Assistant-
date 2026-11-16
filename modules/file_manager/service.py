"""Connect a requested scan or move to SQLite. Nothing here runs on a timer."""

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from database.repositories.file_repository import FileRepository
from modules.file_manager.classifier import classify_file
from modules.file_manager.duplicate_detector import find_duplicate_groups
from modules.file_manager.models import DuplicateReport, MovePlan, OperationResult, ScanResult, ScannedFile
from modules.file_manager.operation_manager import OperationManager
from modules.file_manager.organizer import plan_organization
from modules.file_manager.path_validator import infer_scan_root
from modules.file_manager.scanner import scan_directory

ScanProgress = Callable[[int], None]
HashProgress = Callable[[int, int], None]


def scan_folder(
    root: Path,
    *,
    recursive: bool,
    max_depth: int,
    max_files: int,
    repository: FileRepository,
    batch_size: int,
    progress: ScanProgress | None = None,
) -> ScanResult:
    """Scan metadata, classify it, and store it. File contents are not hashed."""
    result = scan_directory(
        root,
        recursive=recursive,
        max_depth=max_depth,
        max_files=max_files,
        progress=progress,
    )
    if not result.completed:
        return result
    scanned_at = datetime.now().replace(microsecond=0)
    files = tuple(
        replace(
            item,
            category=classify_file(item.file_path),
            scanned_at=scanned_at,
        )
        for item in result.files
    )
    repository.replace_scan(files, batch_size=batch_size)
    return ScanResult(result.root, files, result.errors, result.truncated, True)


def store_duplicates(
    files: Sequence[ScannedFile],
    repository: FileRepository,
    *,
    chunk_size: int,
    batch_size: int,
    progress: HashProgress | None = None,
) -> DuplicateReport:
    """Hash same-sized files and save those hashes. Unique sizes are not read."""
    report = find_duplicate_groups(files, chunk_size=chunk_size, progress=progress)
    repository.update_hashes(report.hashes, batch_size=batch_size)
    return report


def apply_moves(
    plans: Sequence[MovePlan],
    root: Path,
    repository: FileRepository,
    *,
    approved: bool,
) -> tuple[OperationResult, ...]:
    """Move files only when ``approved`` is true."""
    return OperationManager(repository, root).execute(plans, approved=approved)


def undo_move(
    operation_id: int,
    root: Path,
    repository: FileRepository,
) -> OperationResult:
    """Undo one successful move inside ``root``."""
    return OperationManager(repository, root).undo(operation_id)


def recover_operations(
    root: Path,
    repository: FileRepository,
) -> tuple[OperationResult, ...]:
    """Reconcile unfinished rows. This does not move or delete files."""
    return OperationManager(repository, root).recover()


def infer_organizer_root(files: Sequence[ScannedFile]) -> Path | None:
    """Recover the folder used by a stored scan, when every file shares one."""
    return infer_scan_root([item.file_path for item in files])


def plans_for(files: Sequence[ScannedFile], root: Path) -> tuple[MovePlan, ...]:
    """Build a preview for files that are already in memory."""
    return plan_organization(files, root)
