"""Live Windows reads. These tests talk to the real machine."""

from modules.system_monitor.cpu import read_cpu
from modules.system_monitor.disk import read_disks
from modules.system_monitor.memory import read_memory
from modules.system_monitor.processes import read_top_processes


def test_live_readers_on_this_windows_pc() -> None:
    cpu = read_cpu(0.1)
    assert cpu.percent >= 0
    assert cpu.logical_count >= 1

    memory = read_memory()
    assert memory.total_bytes > 0
    assert memory.used_bytes >= 0
    assert memory.available_bytes >= 0
    assert memory.percent >= 0

    disks = read_disks(["C:/", "D:/"])
    assert disks["C:/"] is not None
    assert disks["D:/"] is not None
    assert disks["C:/"].total_bytes > 0
    assert disks["D:/"].total_bytes > 0
    assert 0 <= disks["C:/"].free_percent <= 100

    cache: dict[int, tuple[float, float]] = {}
    first = read_top_processes(5, cache)
    assert 1 <= len(first) <= 5
    assert first[0].memory_bytes >= first[-1].memory_bytes
    assert all(process.cpu_percent is None for process in first)

    second = read_top_processes(5, cache)
    assert 1 <= len(second) <= 5
