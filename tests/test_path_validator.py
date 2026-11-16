"""Path rules: no whole drives, no Windows folders, no path escape."""

import os
from pathlib import Path

import pytest

from modules.file_manager.path_validator import (
    PathValidationError,
    is_inside,
    resolve_inside,
    validate_filename,
    validate_scan_root,
)


def test_drive_root_and_windows_directory_are_rejected() -> None:
    with pytest.raises(PathValidationError):
        validate_scan_root(Path("C:/"))
    with pytest.raises(PathValidationError):
        validate_scan_root(Path(os.environ["SystemRoot"]))


def test_path_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    with pytest.raises(PathValidationError):
        resolve_inside(root, outside)
    with pytest.raises(PathValidationError):
        resolve_inside(root, root / ".." / outside.name)
    assert outside.read_text(encoding="utf-8") == "x"


def test_child_path_is_inside_and_reserved_names_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    child = root / "report.pdf"
    child.write_bytes(b"%PDF")

    resolved = resolve_inside(root, child)
    assert is_inside(root.resolve(), resolved)
    assert resolved == child.resolve()
    with pytest.raises(PathValidationError):
        validate_filename("CON.txt")
    with pytest.raises(PathValidationError):
        validate_filename("..\\secret.txt")
    with pytest.raises(PathValidationError):
        validate_filename("notes.txt ")
