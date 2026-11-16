"""Report the largest files. This module never deletes or changes them."""

from collections.abc import Sequence

from modules.file_manager.models import ScannedFile

DEFAULT_LARGE_FILE_BYTES = 100 * 1024 * 1024


def find_large_files(
    files: Sequence[ScannedFile],
    *,
    threshold_bytes: int = DEFAULT_LARGE_FILE_BYTES,
) -> list[ScannedFile]:
    """Return files at or above ``threshold_bytes``, largest first."""
    if threshold_bytes < 0:
        raise ValueError("threshold_bytes must be zero or greater")
    selected = [item for item in files if item.file_size >= threshold_bytes]
    selected.sort(key=lambda item: (-item.file_size, item.file_name.casefold()))
    return selected
