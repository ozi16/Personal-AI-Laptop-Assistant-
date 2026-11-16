"""CPU sampling."""

import psutil

from core.models import CpuMetrics


def read_cpu(sample_interval: float) -> CpuMetrics:
    """Return current CPU load, core counts, and frequency when Windows provides it.

    ``sample_interval`` blocks briefly. psutil needs that gap; without it the
    first non-blocking call always returns 0.0.
    """
    percent = float(psutil.cpu_percent(interval=sample_interval))
    frequency = _frequency_mhz()
    physical = psutil.cpu_count(logical=False)
    logical = psutil.cpu_count(logical=True) or 0
    return CpuMetrics(
        percent=percent,
        logical_count=logical,
        physical_count=physical,
        frequency_mhz=frequency,
    )


def _frequency_mhz() -> float | None:
    try:
        freq = psutil.cpu_freq()
    except (OSError, RuntimeError, AttributeError):
        return None
    if freq is None:
        return None
    return float(freq.current)
