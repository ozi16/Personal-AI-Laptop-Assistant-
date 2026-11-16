"""Decide when to sample and when to write history.

Streamlit reruns the script often. This object remembers the last sample so a
rerun before the interval does not call psutil or insert another database row.
"""

import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

import psutil

from core.config import Settings
from core.models import CpuMetrics, DiskMetrics, MemoryMetrics, ProcessInfo, SystemSnapshot
from database.repositories.metrics_repository import MetricsRepository
from modules.system_monitor.cpu import read_cpu
from modules.system_monitor.disk import read_disks
from modules.system_monitor.health import analyze
from modules.system_monitor.memory import read_memory
from modules.system_monitor.processes import CpuCache, read_top_processes

logger = logging.getLogger("nexus.collector")


class SystemCollector:
    """In-memory sampler with separate intervals for reading and storing."""

    def __init__(
        self,
        settings: Settings,
        repository: MetricsRepository,
        *,
        cpu_reader: Callable[[float], CpuMetrics] = read_cpu,
        memory_reader: Callable[[], MemoryMetrics] = read_memory,
        disk_reader: Callable[[Sequence[str]], dict[str, DiskMetrics | None]] = read_disks,
        process_reader: Callable[[int, CpuCache], list[ProcessInfo]] = read_top_processes,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._cpu_reader = cpu_reader
        self._memory_reader = memory_reader
        self._disk_reader = disk_reader
        self._process_reader = process_reader
        self._clock = clock
        self._now = now
        self._lock = threading.Lock()
        self._cpu_cache: CpuCache = {}
        self._cpu: CpuMetrics | None = None
        self._memory: MemoryMetrics | None = None
        self._disks: dict[str, DiskMetrics | None] | None = None
        self._processes: tuple[ProcessInfo, ...] | None = None
        self._last_cpu_ram_at: float | None = None
        self._last_disk_at: float | None = None
        self._last_process_at: float | None = None
        self._last_persist_at: float | None = None
        self._saved_sample_count = 0

    def get_snapshot(self) -> SystemSnapshot:
        """Return a fresh or cached snapshot and persist it only on the storage interval."""
        with self._lock:
            wall = self._now()
            now = self._clock()

            if self._due(self._last_cpu_ram_at, self._settings.cpu_ram_seconds, now):
                self._cpu = self._sample(
                    "CPU",
                    self._cpu,
                    lambda: self._cpu_reader(self._settings.cpu_sample_interval_seconds),
                )
                self._memory = self._sample("RAM", self._memory, self._memory_reader)
                self._last_cpu_ram_at = self._clock()

            if self._due(self._last_disk_at, self._settings.disk_seconds, now):
                self._disks = self._sample(
                    "disk",
                    self._disks,
                    lambda: self._disk_reader(self._settings.drives),
                )
                self._last_disk_at = self._clock()

            if self._due(self._last_process_at, self._settings.process_seconds, now):
                previous = None if self._processes is None else list(self._processes)
                sampled = self._sample(
                    "process",
                    previous,
                    lambda: self._process_reader(
                        self._settings.process_top_n,
                        self._cpu_cache,
                    ),
                )
                self._processes = tuple(sampled)
                self._last_process_at = self._clock()

            if self._cpu is None or self._memory is None or self._disks is None or self._processes is None:
                raise RuntimeError("System snapshot is incomplete")

            snapshot = SystemSnapshot(
                timestamp=wall,
                cpu=self._cpu,
                memory=self._memory,
                disks=self._disks,
                processes=self._processes,
                health=analyze(self._cpu, self._memory, self._disks, self._settings.thresholds),
            )
            self._persist(snapshot, wall)
            return snapshot

    def _persist(self, snapshot: SystemSnapshot, wall: datetime) -> None:
        now = self._clock()
        if not self._due(self._last_persist_at, self._settings.persist_seconds, now):
            return
        try:
            self._repository.save_snapshot(snapshot)
            self._saved_sample_count += 1
            cutoff = wall - timedelta(days=self._settings.history_retention_days)
            self._repository.prune(cutoff)
        except sqlite3.Error:
            logger.exception("Could not store system metrics")
        # A failed write waits for the next interval instead of retrying on every rerun.
        self._last_persist_at = self._clock()

    def _sample(self, label: str, previous, reader):
        try:
            return reader()
        except psutil.Error:
            logger.exception("%s sample failed", label)
            if previous is None:
                raise
            return previous

    @property
    def saved_sample_count(self) -> int:
        """How many snapshots this collector has stored. The chart uses it as a change token."""
        return self._saved_sample_count

    @staticmethod
    def _due(last: float | None, interval: float, now: float) -> bool:
        return last is None or (now - last) >= interval
