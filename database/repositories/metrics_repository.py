"""Store and read system_metrics and process_metrics."""

from datetime import datetime
from pathlib import Path

from core.models import (
    DiskMetrics,
    ProcessInfo,
    SystemMetricRecord,
    SystemSnapshot,
    find_disk,
)
from database.connection import initialize_schema, sqlite_connection

_INSERT_SYSTEM = """
INSERT INTO system_metrics (
    timestamp,
    cpu_percent,
    cpu_count_logical,
    cpu_count_physical,
    cpu_freq_mhz,
    ram_total_bytes,
    ram_used_bytes,
    ram_available_bytes,
    ram_percent,
    disk_c_total_bytes,
    disk_c_used_bytes,
    disk_c_free_bytes,
    disk_c_free_percent,
    disk_d_total_bytes,
    disk_d_used_bytes,
    disk_d_free_bytes,
    disk_d_free_percent,
    health_status
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_PROCESS = """
INSERT INTO process_metrics (
    timestamp, pid, name, cpu_percent, memory_bytes, memory_percent
) VALUES (?, ?, ?, ?, ?, ?)
"""


class MetricsRepository:
    """SQLite history for Phase 1. The schema is created on first use."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_schema()

    def save_snapshot(self, snapshot: SystemSnapshot) -> None:
        """Write one system row and the top processes that belong to the same timestamp."""
        stamp = _stamp(snapshot.timestamp)
        disk_c = _disk_values(find_disk(snapshot.disks, "C"))
        disk_d = _disk_values(find_disk(snapshot.disks, "D"))
        with sqlite_connection(self.db_path) as connection:
            connection.execute(
                _INSERT_SYSTEM,
                (
                    stamp,
                    snapshot.cpu.percent,
                    snapshot.cpu.logical_count,
                    snapshot.cpu.physical_count,
                    snapshot.cpu.frequency_mhz,
                    snapshot.memory.total_bytes,
                    snapshot.memory.used_bytes,
                    snapshot.memory.available_bytes,
                    snapshot.memory.percent,
                    *disk_c,
                    *disk_d,
                    snapshot.health.status.value,
                ),
            )
            connection.executemany(
                _INSERT_PROCESS,
                [
                    (
                        stamp,
                        process.pid,
                        process.name,
                        process.cpu_percent,
                        process.memory_bytes,
                        process.memory_percent,
                    )
                    for process in snapshot.processes
                ],
            )

    def get_system_history(self, since: datetime) -> list[SystemMetricRecord]:
        """Return system rows at or after ``since``, oldest first."""
        with sqlite_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT timestamp, cpu_percent, ram_percent,
                       disk_c_free_percent, disk_d_free_percent, health_status
                FROM system_metrics
                WHERE timestamp >= ?
                ORDER BY timestamp ASC
                """,
                (_stamp(since),),
            ).fetchall()
        return [
            SystemMetricRecord(
                timestamp=row["timestamp"],
                cpu_percent=row["cpu_percent"],
                ram_percent=row["ram_percent"],
                disk_c_free_percent=row["disk_c_free_percent"],
                disk_d_free_percent=row["disk_d_free_percent"],
                health_status=row["health_status"],
            )
            for row in rows
        ]

    def get_latest_processes(self) -> list[ProcessInfo]:
        """Return the process rows stored with the newest timestamp."""
        with sqlite_connection(self.db_path) as connection:
            latest = connection.execute(
                "SELECT timestamp FROM process_metrics ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            if latest is None:
                return []
            rows = connection.execute(
                """
                SELECT pid, name, cpu_percent, memory_bytes, memory_percent
                FROM process_metrics
                WHERE timestamp = ?
                ORDER BY memory_bytes DESC
                """,
                (latest["timestamp"],),
            ).fetchall()
        return [
            ProcessInfo(
                pid=row["pid"],
                name=row["name"],
                cpu_percent=row["cpu_percent"],
                memory_bytes=row["memory_bytes"],
                memory_percent=row["memory_percent"],
            )
            for row in rows
        ]

    def prune(self, older_than: datetime) -> int:
        """Delete history older than ``older_than``. Returns the number of deleted rows."""
        cutoff = _stamp(older_than)
        with sqlite_connection(self.db_path) as connection:
            system_deleted = connection.execute(
                "DELETE FROM system_metrics WHERE timestamp < ?",
                (cutoff,),
            ).rowcount
            process_deleted = connection.execute(
                "DELETE FROM process_metrics WHERE timestamp < ?",
                (cutoff,),
            ).rowcount
        return system_deleted + process_deleted

    def _init_schema(self) -> None:
        initialize_schema(self.db_path)


def _stamp(value: datetime) -> str:
    """ISO-8601 without fractions so text comparison matches time order."""
    return value.replace(microsecond=0).isoformat(timespec="seconds")


def _disk_values(metrics: DiskMetrics | None) -> tuple:
    if metrics is None:
        return (None, None, None, None)
    return (
        metrics.total_bytes,
        metrics.used_bytes,
        metrics.free_bytes,
        metrics.free_percent,
    )
