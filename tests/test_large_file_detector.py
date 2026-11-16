"""Large-file reporting sorts by size and leaves every file in place."""

from pathlib import Path

from modules.file_manager.large_file_detector import find_large_files
from modules.file_manager.scanner import scan_directory


def test_large_files_are_sorted_and_not_deleted(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    (root / "small.txt").write_bytes(b"x" * 5)
    (root / "bigger.bin").write_bytes(b"x" * 30)
    (root / "biggest.bin").write_bytes(b"x" * 50)
    files = scan_directory(root, recursive=True, max_depth=1, max_files=10).files

    found = find_large_files(files, threshold_bytes=20)

    assert [item.file_name for item in found] == ["biggest.bin", "bigger.bin"]
    assert (root / "small.txt").read_bytes() == b"x" * 5
    assert (root / "biggest.bin").stat().st_size == 50


def test_default_threshold_is_100_mb() -> None:
    from modules.file_manager.large_file_detector import DEFAULT_LARGE_FILE_BYTES

    assert DEFAULT_LARGE_FILE_BYTES == 100 * 1024 * 1024
