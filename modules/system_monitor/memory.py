"""RAM sampling."""

import psutil

from core.models import MemoryMetrics


def read_memory() -> MemoryMetrics:
    """Return total, used, available RAM and the usage percentage."""
    memory = psutil.virtual_memory()
    return MemoryMetrics(
        total_bytes=int(memory.total),
        used_bytes=int(memory.used),
        available_bytes=int(memory.available),
        percent=float(memory.percent),
    )
