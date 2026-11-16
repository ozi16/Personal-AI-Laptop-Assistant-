"""Shared data structures for Phase 1 monitoring."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class HealthLevel(str, Enum):
    """Rule-based status. The string value is what SQLite stores."""

    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"


SEVERITY: dict[HealthLevel, int] = {
    HealthLevel.NORMAL: 0,
    HealthLevel.WARNING: 1,
    HealthLevel.CRITICAL: 2,
}


@dataclass(frozen=True)
class Thresholds:
    """Configurable health boundaries loaded from settings.yaml."""

    cpu_warning: float
    cpu_critical: float
    ram_warning: float
    ram_critical: float
    disk_free_warning: float
    disk_free_critical: float


@dataclass(frozen=True)
class CpuMetrics:
    """One CPU sample."""

    percent: float
    logical_count: int
    physical_count: int | None
    frequency_mhz: float | None


@dataclass(frozen=True)
class MemoryMetrics:
    """One RAM sample. Byte fields are what the database stores."""

    total_bytes: int
    used_bytes: int
    available_bytes: int
    percent: float


@dataclass(frozen=True)
class DiskMetrics:
    """Capacity of one drive. free_percent is free bytes / total bytes."""

    drive: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    free_percent: float

    @property
    def used_percent(self) -> float:
        """Share of the drive that is already used."""
        if self.total_bytes <= 0:
            return 0.0
        return (self.used_bytes / self.total_bytes) * 100


@dataclass(frozen=True)
class ProcessInfo:
    """One process row, ranked later by memory_bytes."""

    pid: int
    name: str
    cpu_percent: float | None
    memory_bytes: int
    memory_percent: float | None


@dataclass(frozen=True)
class ComponentHealth:
    """Health of a single resource such as CPU or Disk C."""

    name: str
    status: HealthLevel
    value: float
    detail: str


@dataclass(frozen=True)
class HealthReport:
    """Overall status is the worst component status."""

    status: HealthLevel
    components: tuple[ComponentHealth, ...]
    recommendations: tuple[str, ...]


@dataclass(frozen=True)
class SystemSnapshot:
    """Everything the dashboard and the database need from one cycle."""

    timestamp: datetime
    cpu: CpuMetrics
    memory: MemoryMetrics
    disks: dict[str, DiskMetrics | None]
    processes: tuple[ProcessInfo, ...]
    health: HealthReport


@dataclass(frozen=True)
class SystemMetricRecord:
    """One stored system row, used by the history chart."""

    timestamp: str
    cpu_percent: float
    ram_percent: float
    disk_c_free_percent: float | None
    disk_d_free_percent: float | None
    health_status: str


def bytes_to_gb(value: int) -> float:
    """Convert a byte count to gibibytes for display."""
    return value / (1024 ** 3)


def drive_letter(drive: str) -> str:
    """Return the Windows drive letter from a path such as ``C:/`` or ``D:\\``."""
    head = drive.replace("\\", "/").split("/")[0]
    if len(head) >= 2 and head[1] == ":":
        return head[0].upper()
    return head[:1].upper()


def find_disk(
    disks: dict[str, DiskMetrics | None],
    letter: str,
) -> DiskMetrics | None:
    """Find a drive sample by letter. Missing drives stay None."""
    target = letter.upper()
    for drive, metrics in disks.items():
        if drive_letter(drive) == target:
            return metrics
    return None
