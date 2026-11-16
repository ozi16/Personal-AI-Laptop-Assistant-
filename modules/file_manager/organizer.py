"""Build a move plan. Planning does not create folders or move files."""

import os
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from modules.file_manager.classifier import (
    CATEGORIES,
    FORMAT_SUBFOLDERS,
    OTHERS,
    classify_file,
    file_extension,
)
from modules.file_manager.models import MovePlan, ScannedFile
from modules.file_manager.path_validator import (
    PathValidationError,
    ensure_inside,
    is_reparse_point,
    paths_equal,
    validate_filename,
    validate_scan_root,
)


def destination_for(root: Path, file_path: Path) -> tuple[str, Path]:
    """Return the category and destination. ``root`` must already be validated.

    A document such as ``report.pdf`` becomes ``Documents/PDF/report.pdf``.
    An archive stays in one folder: ``Archives/archive.zip``.
    """
    name = validate_filename(Path(file_path).name)
    category = classify_file(file_path)
    if category not in CATEGORIES:
        category = OTHERS
    extension = file_extension(file_path)
    if category in FORMAT_SUBFOLDERS and extension.isalnum():
        return category, root / category / extension.upper() / name
    return category, root / category / name


def build_destination(root: Path, file_path: Path) -> tuple[str, Path]:
    """Validate ``root``, then build the destination path."""
    return destination_for(validate_scan_root(root), file_path)


def plan_organization(files: Sequence[ScannedFile], root: Path) -> tuple[MovePlan, ...]:
    """Describe where each file would move. The filesystem is only read."""
    allowed = validate_scan_root(root)
    ready: list[MovePlan] = []
    pending: list[MovePlan] = []
    ordered = sorted(files, key=lambda item: os.path.normcase(str(item.file_path)))
    for item in ordered:
        plan = _prepare(item, allowed)
        if plan.already_organized or plan.conflict:
            ready.append(plan)
        else:
            pending.append(plan)

    counts = Counter(_key(plan.destination_path) for plan in pending)
    finished = list(ready)
    for plan in pending:
        reason = _block_reason(allowed, plan.source_path, plan.destination_path)
        if not reason and counts[_key(plan.destination_path)] > 1:
            reason = "Lebih dari satu file menuju lokasi yang sama"
        if reason:
            finished.append(
                MovePlan(
                    source_path=plan.source_path,
                    destination_path=plan.destination_path,
                    category=plan.category,
                    file_name=plan.file_name,
                    file_size=plan.file_size,
                    conflict=True,
                    conflict_reason=reason,
                    already_organized=False,
                )
            )
        else:
            finished.append(plan)
    finished.sort(key=lambda plan: os.path.normcase(str(plan.source_path)))
    return tuple(finished)


def destination_block_reason(root: Path, source: Path, destination: Path) -> str:
    """Return why a move must stop, or an empty string when the path is free."""
    return _block_reason(root, source, destination)


def split_plans(
    plans: Sequence[MovePlan],
) -> tuple[tuple[MovePlan, ...], tuple[MovePlan, ...], tuple[MovePlan, ...]]:
    """Split a plan into movable files, conflicts, and files already in place."""
    movable: list[MovePlan] = []
    conflicts: list[MovePlan] = []
    organized: list[MovePlan] = []
    for plan in plans:
        if plan.already_organized:
            organized.append(plan)
        elif plan.conflict:
            conflicts.append(plan)
        else:
            movable.append(plan)
    return tuple(movable), tuple(conflicts), tuple(organized)


def build_recommendations(
    files: Sequence[ScannedFile],
    plans: Sequence[MovePlan] | None,
    duplicate_groups: int | None,
    large_file_count: int,
) -> list[str]:
    """Rule-based organization advice. This does not call a language model."""
    if not files:
        return ["Pindai folder Downloads untuk melihat file. NEXUS tidak memindai seluruh drive."]

    tips: list[str] = []
    if plans is None:
        tips.append(
            "Buat rencana pengorganisasian untuk meninjau tujuan setiap file. "
            "Pemindaian tidak memindahkan apa pun."
        )
    else:
        movable, conflicts, organized = split_plans(plans)
        if movable:
            tips.append(f"{len(movable)} file dapat dikelompokkan ke folder kategori setelah Anda menyetujui.")
        else:
            tips.append("Tidak ada file yang menunggu dipindahkan.")
        if conflicts:
            tips.append(f"{len(conflicts)} file bentrok dan akan dilewati. File yang sudah ada tidak ditimpa.")
        if organized:
            tips.append(f"{len(organized)} file sudah berada di folder yang sesuai.")
    if duplicate_groups is None:
        tips.append("Deteksi duplikat belum dijalankan. Hash hanya dihitung ketika Anda memintanya.")
    elif duplicate_groups:
        tips.append(
            f"Ada {duplicate_groups} kelompok file dengan isi yang sama. "
            "NEXUS tidak menghapus duplikat."
        )
    if large_file_count:
        tips.append(f"{large_file_count} file berada pada atau di atas ambang ukuran dan hanya dilaporkan.")
    others = sum(1 for item in files if item.category == OTHERS)
    if others:
        tips.append(f"{others} file tidak punya kategori yang dikenali dan masuk ke folder Others.")
    return tips


def _prepare(item: ScannedFile, root: Path) -> MovePlan:
    try:
        source = ensure_inside(root, item.file_path)
    except (OSError, PathValidationError) as exc:
        return _conflict(item.file_path, item, str(exc) or "File sumber tidak bisa dipakai")
    if not source.is_file() or is_reparse_point(source):
        return _conflict(source, item, "File sumber tidak ditemukan")
    try:
        category, destination = destination_for(root, source)
        destination = ensure_inside(root, destination)
    except (OSError, PathValidationError) as exc:
        return _conflict(source, item, str(exc) or "Tujuan tidak valid")
    if paths_equal(source, destination):
        return MovePlan(
            source_path=source,
            destination_path=destination,
            category=category,
            file_name=source.name,
            file_size=item.file_size,
            conflict=False,
            conflict_reason="",
            already_organized=True,
        )
    return MovePlan(
        source_path=source,
        destination_path=destination,
        category=category,
        file_name=source.name,
        file_size=item.file_size,
        conflict=False,
        conflict_reason="",
        already_organized=False,
    )


def _conflict(source: Path, item: ScannedFile, reason: str) -> MovePlan:
    return MovePlan(
        source_path=source,
        destination_path=source,
        category=item.category or OTHERS,
        file_name=item.file_name,
        file_size=item.file_size,
        conflict=True,
        conflict_reason=reason,
        already_organized=False,
    )


def _block_reason(root: Path, source: Path, destination: Path) -> str:
    if (destination.exists() or destination.is_symlink()) and not paths_equal(source, destination):
        return "File tujuan sudah ada"
    current = destination.parent
    while not paths_equal(current, root):
        if current.exists() and not current.is_dir():
            return "Bagian dari folder tujuan sudah dipakai oleh sebuah file"
        if current.exists() and is_reparse_point(current):
            return "Folder tujuan melewati symbolic link atau junction"
        if current.parent == current:
            break
        current = current.parent
    return ""


def _key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))
