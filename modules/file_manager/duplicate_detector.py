"""Find files with identical contents. Same names are not enough to match."""

import hashlib
import os
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path

from modules.file_manager.models import DuplicateGroup, DuplicateReport, ScanError, ScannedFile

DEFAULT_CHUNK_BYTES = 1024 * 1024
HashProgress = Callable[[int, int], None]


def hash_file(path: Path, chunk_size: int = DEFAULT_CHUNK_BYTES) -> str:
    """SHA-256 of ``path``, read in chunks so a large file is not loaded whole."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def find_duplicate_groups(
    files: Sequence[ScannedFile],
    *,
    chunk_size: int = DEFAULT_CHUNK_BYTES,
    progress: HashProgress | None = None,
) -> DuplicateReport:
    """Hash only files that share a size. Unique sizes are not read."""
    by_size: dict[int, list[ScannedFile]] = defaultdict(list)
    for item in files:
        by_size[item.file_size].append(item)

    candidates = [
        item
        for group in by_size.values()
        if len(group) > 1
        for item in group
    ]
    total = len(candidates)
    hashes: list[tuple[str, str]] = []
    errors: list[ScanError] = []
    by_hash: dict[str, list[ScannedFile]] = defaultdict(list)

    for index, item in enumerate(candidates, start=1):
        try:
            digest = hash_file(item.file_path, chunk_size)
        except PermissionError:
            errors.append(ScanError(str(item.file_path), "Tidak ada izin untuk membaca file"))
        except FileNotFoundError:
            errors.append(ScanError(str(item.file_path), "File tidak ditemukan"))
        except OSError:
            errors.append(ScanError(str(item.file_path), "File tidak bisa dibaca"))
        else:
            hashes.append((str(item.file_path), digest))
            by_hash[digest].append(item)
        if progress is not None:
            progress(index, total)

    groups: list[DuplicateGroup] = []
    for digest, items in by_hash.items():
        if len(items) < 2:
            continue
        ordered = tuple(sorted(items, key=lambda entry: os.path.normcase(str(entry.file_path))))
        groups.append(DuplicateGroup(digest, ordered[0].file_size, ordered))
    groups.sort(key=lambda group: (-group.file_size, group.sha256))
    return DuplicateReport(tuple(groups), tuple(hashes), tuple(errors))


def group_by_recorded_hash(
    files: Sequence[ScannedFile],
) -> tuple[DuplicateGroup, ...] | None:
    """Group hashes that are already stored. This does not read file contents."""
    hashed = [item for item in files if item.sha256]
    if not hashed:
        return None
    buckets: dict[str, list[ScannedFile]] = defaultdict(list)
    for item in hashed:
        if item.sha256 is not None:
            buckets[item.sha256].append(item)
    groups: list[DuplicateGroup] = []
    for digest, items in buckets.items():
        if len(items) < 2:
            continue
        ordered = tuple(sorted(items, key=lambda entry: os.path.normcase(str(entry.file_path))))
        groups.append(DuplicateGroup(digest, ordered[0].file_size, ordered))
    groups.sort(key=lambda group: (-group.file_size, group.sha256))
    return tuple(groups)
