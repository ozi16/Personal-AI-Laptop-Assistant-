"""File scanner: metadata only, with depth, permission, and link limits."""

import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from modules.file_manager.models import ScannedFile
from modules.file_manager.path_validator import PathValidationError
from modules.file_manager.scanner import scan_directory


def test_scan_reads_metadata_without_changing_the_file(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    target = root / "notes.PDF"
    payload = b"hello"
    target.write_bytes(payload)
    before = target.stat().st_mtime_ns

    result = scan_directory(root, recursive=True, max_depth=2, max_files=10)

    assert result.completed is True
    assert result.truncated is False
    assert len(result.files) == 1
    found = result.files[0]
    assert found.file_name == "notes.PDF"
    assert found.extension == "pdf"
    assert found.file_size == len(payload)
    assert found.file_path == target.resolve()
    assert found.file_path.is_absolute()
    assert isinstance(found.modified_at, datetime)
    assert target.read_bytes() == payload
    assert target.stat().st_mtime_ns == before


def test_recursive_depth_limit(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    (root / "level1" / "level2").mkdir(parents=True)
    (root / "a.txt").write_text("a", encoding="utf-8")
    (root / "level1" / "b.txt").write_text("b", encoding="utf-8")
    (root / "level1" / "level2" / "c.txt").write_text("c", encoding="utf-8")

    top = scan_directory(root, recursive=False, max_depth=5, max_files=10)
    one_level = scan_directory(root, recursive=True, max_depth=1, max_files=10)
    two_levels = scan_directory(root, recursive=True, max_depth=2, max_files=10)

    assert _names(top.files) == ["a.txt"]
    assert _names(one_level.files) == ["a.txt", "b.txt"]
    assert _names(two_levels.files) == ["a.txt", "b.txt", "c.txt"]


def test_max_files_stops_and_marks_the_scan_truncated(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    for index in range(4):
        (root / f"file-{index}.txt").write_text("x", encoding="utf-8")

    result = scan_directory(root, recursive=True, max_depth=1, max_files=2)

    assert result.truncated is True
    assert len(result.files) == 2
    assert len(list(root.iterdir())) == 4


def test_missing_root_is_reported(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    result = scan_directory(missing, recursive=True, max_depth=1, max_files=10)
    assert result.completed is False
    assert result.files == ()
    assert result.errors
    assert "tidak ditemukan" in result.errors[0].message.lower()


def test_file_not_found_on_one_entry_keeps_the_rest(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    keep = root / "keep.txt"
    keep.write_text("keep", encoding="utf-8")
    gone = root / "gone.txt"

    def fake_scandir(path):
        if Path(path) == root:
            return [_Entry(gone, error=FileNotFoundError("gone")), _Entry(keep)]
        raise AssertionError(path)

    monkeypatch.setattr("modules.file_manager.scanner.os.scandir", fake_scandir)
    result = scan_directory(root, recursive=True, max_depth=1, max_files=10)

    assert _names(result.files) == ["keep.txt"]
    assert any(error.path.endswith("gone.txt") for error in result.errors)


def test_permission_error_on_a_subdirectory_is_reported(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "Downloads"
    locked = root / "locked"
    locked.mkdir(parents=True)
    (root / "visible.txt").write_text("ok", encoding="utf-8")
    real_scandir = os.scandir

    def guarded(path):
        if Path(path) == locked:
            raise PermissionError("denied")
        return real_scandir(path)

    monkeypatch.setattr("modules.file_manager.scanner.os.scandir", guarded)
    result = scan_directory(root, recursive=True, max_depth=2, max_files=10)

    assert _names(result.files) == ["visible.txt"]
    assert any("izin" in error.message.lower() for error in result.errors)


def test_system_directory_is_rejected_before_listing(monkeypatch) -> None:
    def fail(_path):
        raise AssertionError("system directory was listed")

    monkeypatch.setattr("modules.file_manager.scanner.os.scandir", fail)
    with pytest.raises(PathValidationError):
        scan_directory(Path(os.environ["SystemRoot"]), recursive=True, max_depth=1, max_files=10)


def test_symlink_entry_is_skipped_without_a_privilege(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    keep = root / "keep.txt"
    keep.write_text("keep", encoding="utf-8")

    class _Link(_Entry):
        def is_symlink(self) -> bool:
            return True

    def fake_scandir(path):
        if Path(path) == root:
            return [_Link(root / "secret.txt"), _Entry(keep)]
        raise AssertionError(path)

    monkeypatch.setattr("modules.file_manager.scanner.os.scandir", fake_scandir)
    result = scan_directory(root, recursive=True, max_depth=1, max_files=10)

    assert _names(result.files) == ["keep.txt"]
    assert result.errors == ()
    assert keep.read_text(encoding="utf-8") == "keep"


def test_symlink_outside_the_folder_is_not_followed(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    (root / "keep.txt").write_text("keep", encoding="utf-8")
    link = root / "secret.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink is not permitted")

    result = scan_directory(root, recursive=True, max_depth=2, max_files=10)

    assert _names(result.files) == ["keep.txt"]
    assert outside.read_text(encoding="utf-8") == "secret"


def test_junction_outside_the_folder_is_not_followed(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (root / "keep.txt").write_text("keep", encoding="utf-8")
    link = root / "linked"
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip("junction is not available")

    result = scan_directory(root, recursive=True, max_depth=3, max_files=20)

    assert _names(result.files) == ["keep.txt"]
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "secret"


def _names(files: tuple[ScannedFile, ...] | list[ScannedFile]) -> list[str]:
    return [item.file_name for item in files]


class _Entry:
    def __init__(self, path: Path, *, error: OSError | None = None):
        self.path = str(path)
        self.name = path.name
        self._error = error

    def is_symlink(self) -> bool:
        return False

    def stat(self, follow_symlinks: bool = True):
        if self._error is not None:
            raise self._error
        return Path(self.path).stat()
