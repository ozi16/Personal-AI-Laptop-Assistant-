"""Disk capacity sampling. A missing drive returns None instead of raising."""

import logging

import psutil

from core.models import DiskMetrics

logger = logging.getLogger("nexus.disk")


def read_disks(
    drives: tuple[str, ...] | list[str],
    usage_fn=psutil.disk_usage,
) -> dict[str, DiskMetrics | None]:
    """Read each configured drive. One failure does not cancel the others."""
    return {drive: read_disk(drive, usage_fn) for drive in drives}


def read_disk(drive: str, usage_fn=psutil.disk_usage) -> DiskMetrics | None:
    """Read one drive. ``OSError`` and ``PermissionError`` mean it is unavailable."""
    try:
        usage = usage_fn(drive)
    except (OSError, PermissionError):
        logger.info("Drive %s is not available", drive)
        return None

    total = int(usage.total)
    used = int(usage.used)
    free = int(usage.free)
    free_percent = (free / total) * 100 if total else 0.0
    return DiskMetrics(
        drive=drive,
        total_bytes=total,
        used_bytes=used,
        free_bytes=free,
        free_percent=free_percent,
    )
