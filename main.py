"""Print one system snapshot. This does not keep a background loop running."""

import logging

from core.config import load_settings
from core.logging_setup import configure_logging
from core.models import DiskMetrics, HealthLevel, SystemSnapshot, bytes_to_gb, find_disk
from database.repositories.metrics_repository import MetricsRepository
from modules.system_monitor.collector import SystemCollector

logger = logging.getLogger("nexus")

_LABELS = {
    HealthLevel.NORMAL: "Normal",
    HealthLevel.WARNING: "Peringatan",
    HealthLevel.CRITICAL: "Kritis",
}


def main() -> int:
    """Collect one sample, store it, and print a readable summary."""
    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"Konfigurasi tidak valid: {exc}")
        return 1

    configure_logging(settings)
    logger.info("NEXUS Phase 1 snapshot started")
    repository = MetricsRepository(settings.database_path)
    collector = SystemCollector(settings, repository)
    snapshot = collector.get_snapshot()
    print(format_snapshot(snapshot))
    return 0


def format_snapshot(snapshot: SystemSnapshot) -> str:
    """Turn a snapshot into plain text for the terminal."""
    lines = [
        "NEXUS Phase 1 — System Monitoring",
        f"Waktu: {snapshot.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        _cpu_line(snapshot),
        _memory_line(snapshot),
        _disk_line("Disk C", find_disk(snapshot.disks, "C")),
        _disk_line("Disk D", find_disk(snapshot.disks, "D")),
        "",
        f"Kesehatan: {_LABELS[snapshot.health.status]}",
    ]
    for component in snapshot.health.components:
        lines.append(f"  {component.name}: {_LABELS[component.status]} ({component.detail})")

    lines.extend(["", "Proses dengan RAM terbesar:"])
    if not snapshot.processes:
        lines.append("  Tidak ada proses yang bisa dibaca.")
    for process in snapshot.processes:
        cpu = "n/a" if process.cpu_percent is None else f"{process.cpu_percent:.1f}%"
        memory_mb = process.memory_bytes / (1024 ** 2)
        lines.append(f"  {process.name} (PID {process.pid}) CPU {cpu} RAM {memory_mb:.1f} MB")

    lines.extend(["", "Rekomendasi:"])
    lines.extend(f"  - {item}" for item in snapshot.health.recommendations)
    return "\n".join(lines)


def _cpu_line(snapshot: SystemSnapshot) -> str:
    cpu = snapshot.cpu
    physical = cpu.physical_count if cpu.physical_count is not None else "?"
    frequency = "tidak tersedia" if cpu.frequency_mhz is None else f"{cpu.frequency_mhz:.0f} MHz"
    return (
        f"CPU: {cpu.percent:.1f}% · {cpu.logical_count} logical / {physical} physical"
        f" · {frequency}"
    )


def _memory_line(snapshot: SystemSnapshot) -> str:
    memory = snapshot.memory
    return (
        f"RAM: {memory.percent:.1f}% · {bytes_to_gb(memory.used_bytes):.1f} / "
        f"{bytes_to_gb(memory.total_bytes):.1f} GB · tersedia "
        f"{bytes_to_gb(memory.available_bytes):.1f} GB"
    )


def _disk_line(title: str, metrics: DiskMetrics | None) -> str:
    if metrics is None:
        return f"{title}: tidak tersedia"
    return (
        f"{title}: {metrics.used_percent:.1f}% terpakai · {metrics.free_percent:.1f}% kosong · "
        f"{bytes_to_gb(metrics.free_bytes):.1f} GB bebas dari {bytes_to_gb(metrics.total_bytes):.1f} GB"
    )


if __name__ == "__main__":
    raise SystemExit(main())
