"""SQLite history: insert, read, and retention."""

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
from database.repositories.metrics_repository import MetricsRepository


def _snapshot(when: datetime, pid: int, name: str) -> SystemSnapshot:
    return SystemSnapshot(
        timestamp=when,
        cpu=CpuMetrics(80, 8, 4, 2100),
        memory=MemoryMetrics(100, 80, 20, 80),
        disks={
            "C:/": DiskMetrics("C:/", 1000, 900, 100, 10),
            "D:/": None,
        },
        processes=(ProcessInfo(pid, name, 1.5, 4096, 3.0),),
        health=HealthReport(HealthLevel.WARNING, (), ("cek",)),
    )


def test_saves_history_and_prunes_old_rows(tmp_path) -> None:
    repository = MetricsRepository(tmp_path / "nexus.db")
    assert repository.get_system_history(datetime(2026, 1, 1)) == []
    assert repository.get_latest_processes() == []

    repository.save_snapshot(_snapshot(datetime(2026, 11, 1, 8, 0, 0), pid=1, name="old"))
    repository.save_snapshot(_snapshot(datetime(2026, 11, 16, 8, 0, 0), pid=2, name="new"))

    history = repository.get_system_history(datetime(2026, 11, 1))
    assert [row.timestamp for row in history] == [
        "2026-11-01T08:00:00",
        "2026-11-16T08:00:00",
    ]
    assert history[0].cpu_percent == 80
    assert history[0].ram_percent == 80
    assert history[0].disk_c_free_percent == 10
    assert history[0].disk_d_free_percent is None
    assert history[0].health_status == "warning"
    assert repository.get_latest_processes()[0].name == "new"

    deleted = repository.prune(datetime(2026, 11, 10))
    assert deleted == 2
    remaining = repository.get_system_history(datetime(2026, 1, 1))
    assert [row.timestamp for row in remaining] == ["2026-11-16T08:00:00"]
    assert repository.get_latest_processes()[0].pid == 2
