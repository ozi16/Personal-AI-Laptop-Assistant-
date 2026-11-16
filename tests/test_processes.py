"""Process sampling skips processes that disappear or refuse access."""

from types import SimpleNamespace

import psutil

from modules.system_monitor.processes import read_top_processes


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeProc:
    def __init__(
        self,
        pid: int = 1,
        name: str = "app",
        rss: int = 100,
        user: float = 0.0,
        system: float = 0.0,
        error: Exception | None = None,
        memory_percent: float | None = 1.0,
    ) -> None:
        self.pid = pid
        self.name = name
        self.rss = rss
        self.user = user
        self.system = system
        self.error = error
        self.memory_percent = memory_percent
        self.cpu_error: Exception | None = None
        self.cpu_reads = 0

    @property
    def info(self) -> dict:
        if self.error is not None:
            raise self.error
        return {
            "pid": self.pid,
            "name": self.name,
            "memory_info": SimpleNamespace(rss=self.rss),
            "memory_percent": self.memory_percent,
        }

    def cpu_times(self) -> SimpleNamespace:
        self.cpu_reads += 1
        if self.cpu_error is not None:
            raise self.cpu_error
        return SimpleNamespace(user=self.user, system=self.system)


def test_skips_access_denied_and_exited_processes() -> None:
    denied = FakeProc(pid=1, error=psutil.AccessDenied(pid=1))
    exited = FakeProc(pid=2, error=psutil.NoSuchProcess(pid=2))
    zombie = FakeProc(pid=4, error=psutil.ZombieProcess(pid=4))
    keeper = FakeProc(pid=3, name="keeper", rss=500)
    result = read_top_processes(10, {}, source=[denied, exited, zombie, keeper], clock=lambda: 1.0)
    assert [item.pid for item in result] == [3]
    assert result[0].cpu_percent is None
    assert denied.cpu_reads == 0
    assert exited.cpu_reads == 0
    assert zombie.cpu_reads == 0
    assert keeper.cpu_reads == 1


def test_cpu_times_are_read_only_for_the_top_processes() -> None:
    small = FakeProc(pid=1, name="small", rss=10, user=1.0, system=1.0)
    big = FakeProc(pid=2, name="big", rss=50, user=1.0, system=1.0)
    cache: dict[int, tuple[float, float]] = {}

    read_top_processes(1, cache, source=[small, big], clock=lambda: 1.0)

    assert big.cpu_reads == 1
    assert small.cpu_reads == 0
    assert set(cache) == {2}


def test_cpu_times_denied_keeps_the_memory_row() -> None:
    locked = FakeProc(pid=4, name="locked", rss=100)
    locked.cpu_error = psutil.AccessDenied(pid=4)
    result = read_top_processes(5, {}, source=[locked], clock=lambda: 1.0)
    assert [item.pid for item in result] == [4]
    assert result[0].cpu_percent is None
    assert result[0].memory_bytes == 100


def test_returns_the_largest_memory_users_only() -> None:
    source = [
        FakeProc(pid=1, name="small", rss=10),
        FakeProc(pid=2, name="big", rss=50),
        FakeProc(pid=3, name="mid", rss=30),
    ]
    result = read_top_processes(2, {}, source=source, clock=lambda: 1.0)
    assert [item.name for item in result] == ["big", "mid"]


def test_cpu_is_missing_until_a_second_sample_exists() -> None:
    clock = Clock()
    cache: dict[int, tuple[float, float]] = {}
    proc = FakeProc(pid=7, name="app", rss=100, user=1.0, system=1.0)

    first = read_top_processes(5, cache, source=[proc], clock=clock)
    assert first[0].cpu_percent is None
    assert 7 in cache

    clock.advance(2)
    proc.user = 2.0
    proc.system = 2.0
    second = read_top_processes(5, cache, source=[proc], clock=clock)
    assert second[0].cpu_percent == 100

    read_top_processes(5, cache, source=[], clock=clock)
    assert cache == {}
