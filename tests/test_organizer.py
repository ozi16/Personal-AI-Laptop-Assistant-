"""Organization plans describe a move and do not perform it."""

from pathlib import Path

import pytest

from modules.file_manager.organizer import build_destination, plan_organization
from modules.file_manager.path_validator import PathValidationError
from modules.file_manager.scanner import scan_directory


def test_plan_builds_category_paths_without_moving(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    (root / "report.pdf").write_bytes(b"%PDF")
    (root / "archive.zip").write_bytes(b"PK")
    (root / "README").write_bytes(b"plain")
    (root / "file.unknownext").write_bytes(b"mystery")
    (root / "main.py").write_bytes(b"print(1)")
    before = {
        path.name: path.read_bytes()
        for path in root.iterdir()
    }

    plans = plan_organization(
        scan_directory(root, recursive=True, max_depth=2, max_files=20).files,
        root,
    )
    by_name = {plan.file_name: plan for plan in plans}

    assert by_name["report.pdf"].destination_path == root.resolve() / "Documents" / "PDF" / "report.pdf"
    assert by_name["report.pdf"].category == "Documents"
    assert by_name["archive.zip"].destination_path == root.resolve() / "Archives" / "archive.zip"
    assert by_name["README"].destination_path == root.resolve() / "Others" / "README"
    assert by_name["file.unknownext"].destination_path == root.resolve() / "Others" / "file.unknownext"
    assert by_name["main.py"].destination_path == root.resolve() / "Development" / "PY" / "main.py"
    assert all(not plan.conflict for plan in plans)
    assert not (root / "Documents").exists()
    assert {path.name: path.read_bytes() for path in root.iterdir()} == before


def test_same_destination_name_is_a_conflict_for_both_files(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir()
    (root / "a" / "report.pdf").write_bytes(b"aaa")
    (root / "b" / "report.pdf").write_bytes(b"bbb")

    plans = plan_organization(
        scan_directory(root, recursive=True, max_depth=2, max_files=20).files,
        root,
    )

    assert len(plans) == 2
    assert all(plan.conflict for plan in plans)
    assert all("lokasi yang sama" in plan.conflict_reason for plan in plans)
    assert (root / "a" / "report.pdf").read_bytes() == b"aaa"
    assert (root / "b" / "report.pdf").read_bytes() == b"bbb"
    assert not (root / "Documents").exists()


def test_existing_destination_and_file_parent_are_conflicts(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    (root / "notes.txt").write_text("new", encoding="utf-8")
    occupied = root / "Documents" / "TXT"
    occupied.mkdir(parents=True)
    (occupied / "notes.txt").write_text("old", encoding="utf-8")

    blocked = root / "blocked.pdf"
    blocked.write_bytes(b"%PDF")
    (root / "DocumentsFile").write_text("not-used", encoding="utf-8")

    plans = plan_organization(
        scan_directory(root, recursive=True, max_depth=3, max_files=20).files,
        root,
    )
    notes = next(plan for plan in plans if plan.file_name == "notes.txt" and plan.source_path == (root / "notes.txt").resolve())
    assert notes.conflict
    assert "sudah ada" in notes.conflict_reason
    assert (occupied / "notes.txt").read_text(encoding="utf-8") == "old"
    assert (root / "notes.txt").read_text(encoding="utf-8") == "new"


def test_file_already_in_place_is_not_a_move(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    ready = root / "Documents" / "PDF" / "report.pdf"
    ready.parent.mkdir(parents=True)
    ready.write_bytes(b"%PDF")

    plans = plan_organization(
        scan_directory(root, recursive=True, max_depth=4, max_files=20).files,
        root,
    )

    assert len(plans) == 1
    assert plans[0].already_organized is True
    assert plans[0].conflict is False
    assert ready.read_bytes() == b"%PDF"


def test_reserved_destination_name_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    with pytest.raises(PathValidationError):
        build_destination(root, root / "CON.txt")
