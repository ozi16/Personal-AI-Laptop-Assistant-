"""Phase 2 tables sit beside the Phase 1 metrics tables."""

from datetime import datetime

from core.models import (
    CpuMetrics,
    DiskMetrics,
    HealthLevel,
    HealthReport,
    MemoryMetrics,
    ProcessInfo,
    SystemSnapshot,
)
from database.connection import sqlite_connection
from database.repositories.file_repository import FileRepository
from database.repositories.metrics_repository import MetricsRepository
from modules.file_manager.service import scan_folder


def test_new_tables_keep_phase1_metrics(tmp_path) -> None:
    database = tmp_path / "nexus.db"
    metrics = MetricsRepository(database)
    metrics.save_snapshot(_snapshot(datetime(2026, 11, 16, 8, 0, 0)))
    FileRepository(database)

    history = metrics.get_system_history(datetime(2026, 1, 1))
    assert [row.timestamp for row in history] == ["2026-11-16T08:00:00"]
    assert history[0].cpu_percent == 80

    with sqlite_connection(database) as connection:
        system_columns = [row[1] for row in connection.execute("PRAGMA table_info(system_metrics)")]
        process_columns = [row[1] for row in connection.execute("PRAGMA table_info(process_metrics)")]
        file_columns = [row[1] for row in connection.execute("PRAGMA table_info(scanned_files)")]
        operation_columns = [row[1] for row in connection.execute("PRAGMA table_info(file_operations)")]
    assert "cpu_percent" in system_columns
    assert "pid" in process_columns
    assert "sha256" in file_columns
    assert "operation_type" in operation_columns


def test_scan_stores_metadata_without_a_hash_and_a_failed_scan_keeps_it(tmp_path, monkeypatch) -> None:
    def explode(*_args, **_kwargs):
        raise AssertionError("scan hashed a file")

    monkeypatch.setattr("modules.file_manager.duplicate_detector.hash_file", explode)
    root = tmp_path / "Downloads"
    root.mkdir()
    (root / "notes.txt").write_text("hello", encoding="utf-8")
    repository = FileRepository(tmp_path / "nexus.db")

    outcome = scan_folder(
        root,
        recursive=True,
        max_depth=2,
        max_files=10,
        repository=repository,
        batch_size=10,
    )
    stored = repository.list_all()

    assert outcome.completed is True
    assert stored[0].category == "Documents"
    assert stored[0].sha256 is None
    assert stored[0].file_name == "notes.txt"

    failed = scan_folder(
        tmp_path / "missing",
        recursive=True,
        max_depth=2,
        max_files=10,
        repository=repository,
        batch_size=10,
    )
    assert failed.completed is False
    assert len(repository.list_all()) == 1


def _snapshot(when: datetime) -> SystemSnapshot:
    return SystemSnapshot(
        timestamp=when,
        cpu=CpuMetrics(80, 8, 4, 2100),
        memory=MemoryMetrics(100, 80, 20, 80),
        disks={"C:/": DiskMetrics("C:/", 1000, 900, 100, 10), "D:/": None},
        processes=(ProcessInfo(1, "editor", 1.0, 4096, 2.0),),
        health=HealthReport(HealthLevel.NORMAL, (), ("baik",)),
    )
