"""Collector intervals: read often enough, write to SQLite less often."""

from datetime import datetime, timedelta

from core.config import Settings
from core.models import CpuMetrics, DiskMetrics, MemoryMetrics, ProcessInfo, Thresholds
from database.repositories.metrics_repository import MetricsRepository
from modules.system_monitor.collector import SystemCollector


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _settings(tmp_path) -> Settings:
    return Settings(
        project_root=tmp_path,
        cpu_ram_seconds=5,
        process_seconds=10,
        disk_seconds=30,
        persist_seconds=30,
        cpu_sample_interval_seconds=0.1,
        process_top_n=10,
        history_retention_days=7,
        drives=("C:/", "D:/"),
        thresholds=Thresholds(70, 90, 70, 85, 20, 10),
        database_path=tmp_path / "nexus.db",
        refresh_seconds=5,
        history_hours=24,
        log_level="INFO",
        log_path=tmp_path / "nexus.log",
    )


def test_readers_and_database_follow_their_own_intervals(tmp_path) -> None:
    calls = {"cpu": 0, "ram": 0, "disk": 0, "process": 0}
    clock = Clock()
    wall = {"value": datetime(2026, 11, 16, 12, 0, 0)}

    def cpu_reader(interval: float) -> CpuMetrics:
        assert interval == 0.1
        calls["cpu"] += 1
        return CpuMetrics(15, 8, 4, None)

    def memory_reader() -> MemoryMetrics:
        calls["ram"] += 1
        return MemoryMetrics(1000, 400, 600, 40)

    def disk_reader(drives) -> dict[str, DiskMetrics | None]:
        calls["disk"] += 1
        assert tuple(drives) == ("C:/", "D:/")
        return {"C:/": DiskMetrics("C:/", 1000, 400, 600, 60), "D:/": None}

    def process_reader(top_n: int, cache) -> list[ProcessInfo]:
        calls["process"] += 1
        assert top_n == 10
        assert isinstance(cache, dict)
        return [ProcessInfo(9, "editor", None, 2048, 2.5)]

    repository = MetricsRepository(_settings(tmp_path).database_path)
    collector = SystemCollector(
        _settings(tmp_path),
        repository,
        cpu_reader=cpu_reader,
        memory_reader=memory_reader,
        disk_reader=disk_reader,
        process_reader=process_reader,
        clock=clock,
        now=lambda: wall["value"],
    )

    def stored() -> int:
        return len(repository.get_system_history(datetime(2026, 1, 1)))

    first = collector.get_snapshot()
    assert calls == {"cpu": 1, "ram": 1, "disk": 1, "process": 1}
    assert stored() == 1
    assert collector.saved_sample_count == 1
    assert first.disks["D:/"] is None
    history = repository.get_system_history(datetime(2026, 1, 1))
    assert history[0].disk_c_free_percent == 60
    assert history[0].disk_d_free_percent is None
    assert history[0].health_status == "normal"
    assert repository.get_latest_processes()[0].name == "editor"

    collector.get_snapshot()
    assert calls == {"cpu": 1, "ram": 1, "disk": 1, "process": 1}
    assert stored() == 1
    assert collector.saved_sample_count == 1

    clock.advance(5)
    wall["value"] += timedelta(seconds=5)
    collector.get_snapshot()
    assert calls == {"cpu": 2, "ram": 2, "disk": 1, "process": 1}
    assert stored() == 1

    clock.advance(5)
    wall["value"] += timedelta(seconds=5)
    collector.get_snapshot()
    assert calls["process"] == 2
    assert calls["disk"] == 1
    assert calls["cpu"] == 3
    assert stored() == 1

    clock.advance(20)
    wall["value"] += timedelta(seconds=20)
    collector.get_snapshot()
    assert calls == {"cpu": 4, "ram": 4, "disk": 2, "process": 3}
    assert stored() == 2
    assert collector.saved_sample_count == 2
