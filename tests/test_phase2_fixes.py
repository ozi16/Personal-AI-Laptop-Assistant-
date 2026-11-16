"""Post-audit checks. Every file and database lives under tmp_path."""

import os
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from dashboard.components.file_organizer import (
    active_root_for_actions,
    history_rows,
    session_after_scan,
)
from database.connection import sqlite_connection
from database.repositories.file_repository import FileRepository
from modules.file_manager.models import MovePlan
from modules.file_manager.operation_manager import OperationManager
from modules.file_manager.organizer import plan_organization
from modules.file_manager.path_validator import PathValidationError
from modules.file_manager.scanner import scan_directory
from modules.file_manager.service import scan_folder

_LEGACY_SCHEMA = """
CREATE TABLE system_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    cpu_percent REAL NOT NULL,
    cpu_count_logical INTEGER,
    cpu_count_physical INTEGER,
    cpu_freq_mhz REAL,
    ram_total_bytes INTEGER NOT NULL,
    ram_used_bytes INTEGER NOT NULL,
    ram_available_bytes INTEGER NOT NULL,
    ram_percent REAL NOT NULL,
    disk_c_total_bytes INTEGER,
    disk_c_used_bytes INTEGER,
    disk_c_free_bytes INTEGER,
    disk_c_free_percent REAL,
    disk_d_total_bytes INTEGER,
    disk_d_used_bytes INTEGER,
    disk_d_free_bytes INTEGER,
    disk_d_free_percent REAL,
    health_status TEXT NOT NULL
);
CREATE TABLE process_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    pid INTEGER NOT NULL,
    name TEXT NOT NULL,
    cpu_percent REAL,
    memory_bytes INTEGER NOT NULL,
    memory_percent REAL
);
CREATE TABLE file_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    destination_path TEXT NOT NULL,
    operation_type TEXT NOT NULL CHECK (operation_type IN ('move', 'undo')),
    status TEXT NOT NULL CHECK (status IN ('success', 'failed', 'undone')),
    created_at TEXT NOT NULL,
    completed_at TEXT
);
"""


def _manager(tmp_path: Path, root: Path) -> tuple[OperationManager, FileRepository]:
    repository = FileRepository(tmp_path / "nexus.db")
    return OperationManager(repository, root), repository


def _movable(root: Path):
    return [
        plan
        for plan in plan_organization(
            scan_directory(root, recursive=True, max_depth=4, max_files=20).files,
            root,
        )
        if not plan.conflict and not plan.already_organized
    ]


def test_unapproved_move_writes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    source = root / "report.pdf"
    source.write_bytes(b"%PDF")
    manager, repository = _manager(tmp_path, root)

    with pytest.raises(PermissionError):
        manager.execute(_movable(root), approved=False)

    assert source.read_bytes() == b"%PDF"
    assert repository.list_operations() == []


def test_database_failure_after_rename_stays_pending_and_can_be_reconciled(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    source = root / "report.pdf"
    source.write_bytes(b"%PDF")
    manager, repository = _manager(tmp_path, root)
    real_complete = repository.complete_move

    def fail_complete(*_args, **_kwargs):
        raise sqlite3.OperationalError("simulated failure")

    monkeypatch.setattr(repository, "complete_move", fail_complete)
    results = manager.execute(_movable(root), approved=True)
    destination = root / "Documents" / "PDF" / "report.pdf"

    assert results[0].ok is False
    assert results[0].operation is not None
    assert results[0].operation.status == "pending"
    assert not source.exists()
    assert destination.read_bytes() == b"%PDF"

    monkeypatch.setattr(repository, "complete_move", real_complete)
    monkeypatch.setattr(
        "modules.file_manager.operation_manager.os.rename",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("recovery renamed a file")),
    )
    recovered = manager.recover()

    assert recovered[0].operation is not None
    assert recovered[0].operation.status == "success"
    assert destination.read_bytes() == b"%PDF"
    assert repository.list_open_operations() == []


def test_interrupted_pending_move_is_marked_failed_without_touching_the_file(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    source = root / "report.pdf"
    destination = root / "Documents" / "PDF" / "report.pdf"
    source.write_bytes(b"%PDF")
    manager, repository = _manager(tmp_path, root)
    repository.add_operation(source, destination, "move", "pending", datetime.now(), None)
    monkeypatch.setattr(
        "modules.file_manager.operation_manager.os.rename",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("recovery renamed a file")),
    )

    recovered = manager.recover()

    assert recovered[0].operation is not None
    assert recovered[0].operation.status == "failed"
    assert "terputus" in (recovered[0].operation.error_message or "")
    assert source.read_bytes() == b"%PDF"
    assert not destination.exists()


def test_database_failure_after_undo_stays_undo_pending(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    source = root / "report.pdf"
    source.write_bytes(b"%PDF")
    repository = FileRepository(tmp_path / "nexus.db")
    scan_folder(root, recursive=True, max_depth=3, max_files=10, repository=repository, batch_size=10)
    manager = OperationManager(repository, root)
    moved = manager.execute(_movable(root), approved=True)
    real_complete = repository.complete_undo

    def fail_complete(*_args, **_kwargs):
        raise sqlite3.OperationalError("simulated failure")

    monkeypatch.setattr(repository, "complete_undo", fail_complete)
    result = manager.undo(moved[0].operation.id)
    destination = root / "Documents" / "PDF" / "report.pdf"

    assert result.ok is False
    assert result.operation is not None
    assert result.operation.status == "undo_pending"
    assert source.read_bytes() == b"%PDF"
    assert not destination.exists()

    monkeypatch.setattr(repository, "complete_undo", real_complete)
    monkeypatch.setattr(
        "modules.file_manager.operation_manager.os.rename",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("recovery renamed a file")),
    )
    recovered = manager.recover()

    assert repository.get_operation(moved[0].operation.id).status == "undone"
    assert recovered[0].operation is not None
    assert recovered[0].operation.operation_type == "undo"
    assert source.read_bytes() == b"%PDF"
    assert repository.list_all()[0].file_path == source.resolve()


def test_undo_pending_before_the_file_returns_becomes_success_again(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    source = root / "report.pdf"
    source.write_bytes(b"%PDF")
    manager, repository = _manager(tmp_path, root)
    moved = manager.execute(_movable(root), approved=True)
    repository.begin_undo(moved[0].operation.id)
    destination = root / "Documents" / "PDF" / "report.pdf"
    monkeypatch.setattr(
        "modules.file_manager.operation_manager.os.rename",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("recovery renamed a file")),
    )

    recovered = manager.recover()

    assert recovered[0].operation.status == "success"
    assert destination.read_bytes() == b"%PDF"
    assert not source.exists()


def test_ambiguous_pending_move_does_not_delete_either_file(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    source = root / "report.pdf"
    destination = root / "Documents" / "PDF" / "report.pdf"
    destination.parent.mkdir(parents=True)
    source.write_bytes(b"source")
    destination.write_bytes(b"destination")
    manager, repository = _manager(tmp_path, root)
    repository.add_operation(source.resolve(), destination.resolve(), "move", "pending", datetime.now(), None)
    monkeypatch.setattr(
        "modules.file_manager.operation_manager.os.rename",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("recovery renamed a file")),
    )

    recovered = manager.recover()

    assert recovered[0].operation.status == "recovery_required"
    assert source.read_bytes() == b"source"
    assert destination.read_bytes() == b"destination"


def test_a_file_blocking_the_category_folder_is_left_in_place(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    source = root / "report.pdf"
    blocker = root / "Documents"
    source.write_bytes(b"%PDF")
    blocker.write_bytes(b"blocker")
    manager, repository = _manager(tmp_path, root)
    plans = plan_organization(
        scan_directory(root, recursive=True, max_depth=2, max_files=10).files,
        root,
    )
    pdf = next(plan for plan in plans if plan.file_name == "report.pdf")

    assert pdf.conflict
    results = manager.execute([pdf], approved=True)
    forged = MovePlan(
        source_path=source,
        destination_path=root / "Documents" / "PDF" / "report.pdf",
        category="Documents",
        file_name=source.name,
        file_size=4,
        conflict=False,
        conflict_reason="",
        already_organized=False,
    )
    forged_result = manager.execute([forged], approved=True)

    assert results[0].operation.status == "failed"
    assert forged_result[0].operation.status == "failed"
    assert "folder tujuan" in (forged_result[0].operation.error_message or "").lower() or (
        "dipakai" in (forged_result[0].operation.error_message or "").lower()
    )
    assert blocker.read_bytes() == b"blocker"
    assert source.read_bytes() == b"%PDF"


def test_trailing_space_name_is_not_moved_onto_the_plain_file(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    plain = root / "notes.txt"
    plain.write_bytes(b"plain")
    spaced = _create_trailing_space_file(root)
    if spaced is None:
        pytest.skip("filesystem does not keep a trailing space in the file name")

    manager, _repository = _manager(tmp_path, root)
    plans = plan_organization(
        scan_directory(root, recursive=True, max_depth=2, max_files=10).files,
        root,
    )
    movable = [plan for plan in plans if not plan.conflict and not plan.already_organized]
    manager.execute(movable, approved=True)

    if plain.exists():
        assert plain.read_bytes() == b"plain"
    else:
        assert (root / "Documents" / "TXT" / "notes.txt").read_bytes() == b"plain"
    assert _read_exact_name(root, "notes.txt ") == b"spaced"


def test_active_folder_changes_only_after_a_completed_scan(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "report.pdf").write_bytes(b"one")
    (second / "notes.txt").write_bytes(b"two")
    repository = FileRepository(tmp_path / "nexus.db")
    arguments = {"recursive": True, "max_depth": 2, "max_files": 10, "repository": repository, "batch_size": 10}

    first_scan = scan_folder(first, **arguments)
    first_state = session_after_scan(first_scan)
    assert first_state is not None
    active = active_root_for_actions(str(first_state["organizer_root"]), str(second))
    assert active == first_state["organizer_root"]
    assert str(second.resolve()) not in active
    assert all(
        str(plan.destination_path).startswith(active)
        for plan in first_state["organizer_plans"]
    )

    missing = session_after_scan(scan_folder(tmp_path / "missing", **arguments))
    assert missing is None

    second_scan = scan_folder(second, **arguments)
    second_state = session_after_scan(second_scan)
    assert second_state is not None
    assert second_state["organizer_root"] != first_state["organizer_root"]
    assert all(
        str(plan.destination_path).startswith(str(second_state["organizer_root"]))
        for plan in second_state["organizer_plans"]
    )


def test_successful_moves_beyond_the_history_page_remain_undoable(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    repository = FileRepository(tmp_path / "nexus.db")
    now = datetime(2026, 11, 16, 12, 0, 0)
    for index in range(105):
        repository.add_operation(
            root / f"file-{index}.txt",
            root / "Documents" / f"file-{index}.txt",
            "move",
            "success",
            now,
            now,
        )
    for status in ("pending", "failed", "undo_pending", "undone", "recovery_required"):
        repository.add_operation(root / f"{status}.txt", root / f"{status}-dest.txt", "move", status, now, now)

    shown = repository.list_operations(limit=100)
    undoable, total = repository.list_undoable_moves(limit=20, offset=100)
    found, found_total = repository.list_undoable_moves(search="file-0.txt", limit=20, offset=0)

    assert total == 105
    assert len(undoable) == 5
    assert {item.id for item in undoable} == {1, 2, 3, 4, 5}
    assert all(item.status == "success" for item in undoable)
    assert 1 not in {item.id for item in shown}
    assert found_total == 1
    assert found[0].status == "success"
    assert all(item.status == "success" for item in undoable)


def test_failure_message_is_stored_and_shown_in_history(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    source = root / "notes.txt"
    destination = root / "Documents" / "TXT" / "notes.txt"
    destination.parent.mkdir(parents=True)
    source.write_text("new", encoding="utf-8")
    destination.write_text("old", encoding="utf-8")
    manager, repository = _manager(tmp_path, root)
    conflicts = [
        plan
        for plan in plan_organization(
            scan_directory(root, recursive=True, max_depth=4, max_files=10).files,
            root,
        )
        if plan.file_name == "notes.txt" and plan.conflict and plan.source_path == source.resolve()
    ]

    results = manager.execute(conflicts, approved=True)
    stored = repository.get_operation(results[0].operation.id)
    rows = history_rows([stored])

    assert stored.status == "failed"
    assert stored.error_message
    assert "sudah ada" in stored.error_message
    assert rows[0]["Status"] == "Gagal"
    assert rows[0]["Pesan"] == stored.error_message
    assert source.read_text(encoding="utf-8") == "new"
    assert destination.read_text(encoding="utf-8") == "old"


def test_legacy_database_gains_statuses_without_losing_history(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    with sqlite_connection(database) as connection:
        connection.executescript(_LEGACY_SCHEMA)
        connection.execute(
            """
            INSERT INTO system_metrics (
                timestamp, cpu_percent, ram_total_bytes, ram_used_bytes,
                ram_available_bytes, ram_percent, health_status
            ) VALUES ('2026-11-16T08:00:00', 10, 100, 40, 60, 40, 'normal')
            """
        )
        connection.execute(
            """
            INSERT INTO process_metrics (
                timestamp, pid, name, cpu_percent, memory_bytes, memory_percent
            ) VALUES ('2026-11-16T08:00:00', 4, 'keep', 1, 10, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO file_operations (
                source_path, destination_path, operation_type, status, created_at, completed_at
            ) VALUES ('C:/temp/a.txt', 'C:/temp/Documents/a.txt', 'move', 'success',
                      '2026-11-16T08:00:00', '2026-11-16T08:01:00')
            """
        )

    repository = FileRepository(database)
    kept = repository.get_operation(1)
    added = repository.add_operation(
        "C:/temp/b.txt",
        "C:/temp/Documents/b.txt",
        "move",
        "pending",
        datetime(2026, 11, 16, 9, 0, 0),
        None,
        None,
    )
    with sqlite_connection(database) as connection:
        definition = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'file_operations'"
        ).fetchone()["sql"]
        metrics = connection.execute("SELECT COUNT(*) FROM system_metrics").fetchone()[0]
        processes = connection.execute("SELECT COUNT(*) FROM process_metrics").fetchone()[0]
        names = [row[1] for row in connection.execute("PRAGMA table_info(system_metrics)")]

    assert kept is not None
    assert kept.status == "success"
    assert kept.error_message is None
    assert added.id == 2
    assert added.status == "pending"
    assert "pending" in definition
    assert "error_message" in definition
    assert metrics == 1
    assert processes == 1
    assert "cpu_percent" in names


def test_typing_a_new_folder_without_a_scan_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(PathValidationError):
        active_root_for_actions(None, str(tmp_path))


def _create_trailing_space_file(directory: Path) -> Path | None:
    name = "notes.txt "
    extended = "\\\\?\\" + str(directory.resolve()) + "\\" + name
    try:
        handle = os.open(extended, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return None
    try:
        os.write(handle, b"spaced")
    finally:
        os.close(handle)
    for entry in os.scandir(directory):
        if entry.name == name:
            return Path(entry.path)
    return None


def _read_exact_name(directory: Path, name: str) -> bytes:
    for entry in os.scandir(directory):
        if entry.name == name:
            extended = "\\\\?\\" + str(directory.resolve()) + "\\" + entry.name
            with open(extended, "rb") as handle:
                return handle.read()
    raise AssertionError(f"{name!r} is missing")
