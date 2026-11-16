"""Approved moves, conflicts, and undo. Every fixture stays in tmp_path."""

from pathlib import Path

import pytest

from database.repositories.file_repository import FileRepository
from modules.file_manager.models import MovePlan
from modules.file_manager.operation_manager import OperationManager
from modules.file_manager.organizer import plan_organization
from modules.file_manager.scanner import scan_directory
from modules.file_manager.service import scan_folder


def _manager(tmp_path: Path, root: Path) -> tuple[OperationManager, FileRepository]:
    repository = FileRepository(tmp_path / "nexus.db")
    return OperationManager(repository, root), repository


def _plans(root: Path):
    return plan_organization(
        scan_directory(root, recursive=True, max_depth=5, max_files=50).files,
        root,
    )


def test_preview_does_not_move_and_approval_is_required(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    source = root / "report.pdf"
    source.write_bytes(b"%PDF")
    manager, _repository = _manager(tmp_path, root)

    preview = manager.preview(
        scan_directory(root, recursive=True, max_depth=2, max_files=10).files
    )
    assert not (root / "Documents").exists()
    assert source.read_bytes() == b"%PDF"

    with pytest.raises(PermissionError):
        manager.execute(preview, approved=False)
    assert source.read_bytes() == b"%PDF"
    assert not (root / "Documents").exists()


def test_approved_move_then_undo_restores_the_file(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    source = root / "report.pdf"
    source.write_bytes(b"%PDF")
    manager, repository = _manager(tmp_path, root)
    movable = [plan for plan in _plans(root) if not plan.conflict and not plan.already_organized]

    results = manager.execute(movable, approved=True)
    destination = root / "Documents" / "PDF" / "report.pdf"

    assert results[0].ok is True
    assert not source.exists()
    assert destination.read_bytes() == b"%PDF"
    assert repository.get_operation(results[0].operation.id).status == "success"

    undone = manager.undo(results[0].operation.id)
    assert undone.ok is True
    assert source.read_bytes() == b"%PDF"
    assert not destination.exists()
    assert repository.get_operation(results[0].operation.id).status == "undone"
    with pytest.raises(ValueError):
        manager.undo(results[0].operation.id)


def test_destination_conflict_does_not_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    source = root / "notes.txt"
    source.write_text("new", encoding="utf-8")
    destination = root / "Documents" / "TXT" / "notes.txt"
    destination.parent.mkdir(parents=True)
    destination.write_text("old", encoding="utf-8")
    manager, repository = _manager(tmp_path, root)
    conflicts = [plan for plan in _plans(root) if plan.file_name == "notes.txt" and plan.conflict]

    results = manager.execute(conflicts, approved=True)

    assert results[0].ok is False
    assert source.read_text(encoding="utf-8") == "new"
    assert destination.read_text(encoding="utf-8") == "old"
    assert repository.get_operation(results[0].operation.id).status == "failed"


def test_missing_source_is_a_failed_move(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    source = root / "report.pdf"
    source.write_bytes(b"%PDF")
    manager, repository = _manager(tmp_path, root)
    plans = [plan for plan in _plans(root) if not plan.conflict and not plan.already_organized]
    source.unlink()

    results = manager.execute(plans, approved=True)

    assert results[0].ok is False
    assert not source.exists()
    assert not (root / "Documents" / "PDF" / "report.pdf").exists()
    assert repository.get_operation(results[0].operation.id).status == "failed"


def test_permission_error_keeps_the_source(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    source = root / "report.pdf"
    source.write_bytes(b"%PDF")
    manager, repository = _manager(tmp_path, root)
    plans = [plan for plan in _plans(root) if not plan.conflict and not plan.already_organized]

    def deny(_source, _destination):
        raise PermissionError("denied")

    monkeypatch.setattr("modules.file_manager.operation_manager.os.rename", deny)
    results = manager.execute(plans, approved=True)

    assert results[0].ok is False
    assert source.read_bytes() == b"%PDF"
    assert repository.get_operation(results[0].operation.id).status == "failed"


def test_undo_conflict_keeps_both_files(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    source = root / "report.pdf"
    source.write_bytes(b"%PDF")
    manager, repository = _manager(tmp_path, root)
    plans = [plan for plan in _plans(root) if not plan.conflict and not plan.already_organized]
    moved = manager.execute(plans, approved=True)
    destination = root / "Documents" / "PDF" / "report.pdf"
    source.write_bytes(b"occupant")

    result = manager.undo(moved[0].operation.id)

    assert result.ok is False
    assert source.read_bytes() == b"occupant"
    assert destination.read_bytes() == b"%PDF"
    assert repository.get_operation(moved[0].operation.id).status == "success"
    assert result.operation is not None
    assert result.operation.status == "failed"
    assert result.operation.operation_type == "undo"


def test_successful_move_updates_the_stored_scan_path(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    (root / "report.pdf").write_bytes(b"%PDF")
    repository = FileRepository(tmp_path / "nexus.db")
    scan_folder(
        root,
        recursive=True,
        max_depth=3,
        max_files=10,
        repository=repository,
        batch_size=10,
    )
    manager = OperationManager(repository, root)
    plans = [plan for plan in _plans(root) if not plan.conflict and not plan.already_organized]

    moved = manager.execute(plans, approved=True)
    destination = (root / "Documents" / "PDF" / "report.pdf").resolve()
    assert moved[0].ok is True
    assert repository.list_all()[0].file_path == destination

    manager.undo(moved[0].operation.id)
    assert repository.list_all()[0].file_path == (root / "report.pdf").resolve()
    assert (root / "report.pdf").read_bytes() == b"%PDF"


def test_plan_pointing_outside_the_folder_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    source = root / "report.pdf"
    source.write_bytes(b"%PDF")
    outside = tmp_path / "outside" / "report.pdf"
    manager, _repository = _manager(tmp_path, root)
    plan = MovePlan(
        source_path=source,
        destination_path=outside,
        category="Documents",
        file_name=source.name,
        file_size=source.stat().st_size,
        conflict=False,
        conflict_reason="",
        already_organized=False,
    )

    results = manager.execute([plan], approved=True)

    assert results[0].ok is False
    assert source.read_bytes() == b"%PDF"
    assert not outside.exists()
