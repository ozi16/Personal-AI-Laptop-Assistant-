"""Top processes by RAM. Access-denied and exited processes are skipped."""

import time
from collections.abc import Iterable
from typing import Any, NamedTuple

import psutil

from core.models import ProcessInfo

# Processes can exit or refuse access while we are reading them.
_SKIPPED = (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess)
# cpu_times is intentionally absent. It is read later, and only for the top rows.
_MEMORY_FIELDS = ["pid", "name", "memory_info", "memory_percent"]

# pid -> (monotonic time, total cpu seconds)
CpuCache = dict[int, tuple[float, float]]


class _MemoryRow(NamedTuple):
    proc: Any
    pid: int
    name: str
    memory_bytes: int
    memory_percent: float | None


def read_top_processes(
    top_n: int,
    cpu_cache: CpuCache,
    source: Iterable[Any] | None = None,
    clock=time.monotonic,
) -> list[ProcessInfo]:
    """Return the ``top_n`` processes using the most RAM.

    Every readable process is ranked by memory. ``cpu_times`` is requested
    only for the rows that remain after that cut. CPU percent needs two
    samples of the same PID, so the first time a process stays in the top
    list its CPU value is None.
    """
    if top_n <= 0:
        return []

    processes = psutil.process_iter(_MEMORY_FIELDS) if source is None else source
    ranked = [row for row in (_memory_row(proc) for proc in processes) if row is not None]
    ranked.sort(key=lambda item: item.memory_bytes, reverse=True)
    top = ranked[:top_n]
    top_pids = {row.pid for row in top}

    for pid in list(cpu_cache):
        if pid not in top_pids:
            del cpu_cache[pid]

    return [
        ProcessInfo(
            pid=row.pid,
            name=row.name,
            cpu_percent=_cpu_percent_for(row.proc, row.pid, cpu_cache, clock),
            memory_bytes=row.memory_bytes,
            memory_percent=row.memory_percent,
        )
        for row in top
    ]


def _memory_row(proc: Any) -> _MemoryRow | None:
    """Read identity and RAM. This path does not ask for CPU time."""
    try:
        info = proc.info
    except _SKIPPED:
        return None
    if not isinstance(info, dict):
        return None

    pid = info.get("pid")
    memory_info = info.get("memory_info")
    if pid is None or memory_info is None or not hasattr(memory_info, "rss"):
        return None

    memory_percent = info.get("memory_percent")
    return _MemoryRow(
        proc=proc,
        pid=int(pid),
        name=str(info.get("name") or "unknown"),
        memory_bytes=int(memory_info.rss),
        memory_percent=None if memory_percent is None else float(memory_percent),
    )


def _cpu_percent_for(proc: Any, pid: int, cpu_cache: CpuCache, clock) -> float | None:
    """CPU for one already selected process. A refused or exited process stays in the list."""
    try:
        cpu_times = proc.cpu_times()
    except _SKIPPED:
        return None
    return _cpu_percent(pid, cpu_times, cpu_cache, clock)


def _cpu_percent(pid: int, cpu_times: Any, cpu_cache: CpuCache, clock) -> float | None:
    """Percent of one core since the previous sample. None until a baseline exists."""
    if cpu_times is None or not hasattr(cpu_times, "user"):
        return None
    total = float(cpu_times.user) + float(cpu_times.system)
    now = float(clock())
    previous = cpu_cache.get(pid)
    cpu_cache[pid] = (now, total)
    if previous is None:
        return None
    elapsed = now - previous[0]
    if elapsed <= 0:
        return None
    return max(0.0, ((total - previous[1]) / elapsed) * 100)
