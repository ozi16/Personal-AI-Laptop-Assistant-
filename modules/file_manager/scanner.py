"""Read file metadata inside one folder. File contents are not opened."""

import logging
import os
import stat
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from modules.file_manager.classifier import file_extension
from modules.file_manager.models import ScanError, ScanResult, ScannedFile
from modules.file_manager.path_validator import is_inside, validate_scan_root

logger = logging.getLogger("nexus.file_manager")

_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
ProgressCallback = Callable[[int], None]


def scan_directory(
    root: Path,
    *,
    recursive: bool = True,
    max_depth: int = 6,
    max_files: int = 5000,
    progress: ProgressCallback | None = None,
) -> ScanResult:
    """Scan ``root`` without following a symbolic link or junction.

    A missing root or a root that cannot be opened returns a result with
    ``completed=False``. A Windows system directory raises ``PathValidationError``
    before any file is listed. ``max_depth`` counts the source folder as zero.
    """
    if max_depth < 0:
        raise ValueError("max_depth must be zero or greater")
    if max_files < 1:
        raise ValueError("max_files must be positive")

    try:
        allowed = validate_scan_root(root)
    except FileNotFoundError:
        return _incomplete(root, "Folder tidak ditemukan")
    except PermissionError:
        return _incomplete(root, "Tidak ada izin untuk membuka folder")

    files: list[ScannedFile] = []
    errors: list[ScanError] = []
    truncated = False
    depth_limit = max_depth if recursive else 0
    stack: list[tuple[Path, int]] = [(allowed, 0)]
    seen = {os.path.normcase(str(allowed))}

    while stack:
        current, depth = stack.pop()
        try:
            entries = _list_directory(current)
        except PermissionError:
            errors.append(ScanError(str(current), "Tidak ada izin untuk membaca folder"))
            continue
        except FileNotFoundError:
            errors.append(ScanError(str(current), "Folder tidak ditemukan"))
            continue
        except OSError as exc:
            logger.warning("Cannot read %s: %s", current, exc)
            errors.append(ScanError(str(current), "Folder tidak bisa dibaca"))
            continue

        for entry in entries:
            if len(files) >= max_files:
                truncated = True
                stack.clear()
                break
            _consume_entry(
                entry,
                allowed=allowed,
                depth=depth,
                depth_limit=depth_limit,
                files=files,
                errors=errors,
                stack=stack,
                seen=seen,
            )
            if progress is not None and files and len(files) % 25 == 0:
                progress(len(files))

    if progress is not None:
        progress(len(files))

    files.sort(key=lambda item: os.path.normcase(str(item.file_path)))
    logger.info("Scanned %s files in %s", len(files), allowed)
    return ScanResult(str(allowed), tuple(files), tuple(errors), truncated, True)


def _incomplete(root: Path, message: str) -> ScanResult:
    return ScanResult(str(root), (), (ScanError(str(root), message),), False, False)


def _list_directory(path: Path) -> list[os.DirEntry]:
    iterator = os.scandir(path)
    try:
        return list(iterator)
    finally:
        close = getattr(iterator, "close", None)
        if close is not None:
            close()


def _consume_entry(
    entry: os.DirEntry,
    *,
    allowed: Path,
    depth: int,
    depth_limit: int,
    files: list[ScannedFile],
    errors: list[ScanError],
    stack: list[tuple[Path, int]],
    seen: set[str],
) -> None:
    try:
        if entry.is_symlink():
            return
        info = entry.stat(follow_symlinks=False)
    except PermissionError:
        errors.append(ScanError(entry.path, "Tidak ada izin untuk membaca file"))
        return
    except FileNotFoundError:
        errors.append(ScanError(entry.path, "File tidak ditemukan"))
        return
    except OSError as exc:
        logger.warning("Cannot stat %s: %s", entry.path, exc)
        errors.append(ScanError(entry.path, "File tidak bisa dibaca"))
        return

    attributes = getattr(info, "st_file_attributes", 0)
    if attributes & _REPARSE:
        return

    path = Path(entry.path)
    try:
        resolved = path.resolve()
    except OSError as exc:
        logger.warning("Cannot resolve %s: %s", path, exc)
        errors.append(ScanError(str(path), "File tidak bisa dibaca"))
        return
    if not is_inside(allowed, resolved):
        errors.append(ScanError(str(path), "File berada di luar folder sumber"))
        return

    if stat.S_ISDIR(info.st_mode):
        identity = os.path.normcase(str(resolved))
        if depth < depth_limit and identity not in seen:
            seen.add(identity)
            stack.append((resolved, depth + 1))
        return
    if not stat.S_ISREG(info.st_mode):
        return

    modified = datetime.fromtimestamp(info.st_mtime).replace(microsecond=0)
    files.append(
        ScannedFile(
            file_path=resolved,
            file_name=resolved.name,
            extension=file_extension(resolved),
            file_size=int(info.st_size),
            modified_at=modified,
        )
    )
