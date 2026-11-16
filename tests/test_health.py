"""Health threshold boundaries."""

from core.models import (
    ComponentHealth,
    CpuMetrics,
    DiskMetrics,
    HealthLevel,
    HealthReport,
    MemoryMetrics,
    ProcessInfo,
    SystemSnapshot,
    Thresholds,
)
from datetime import datetime

import pytest

from main import format_snapshot
from modules.system_monitor.health import analyze

THRESHOLDS = Thresholds(
    cpu_warning=70,
    cpu_critical=90,
    ram_warning=70,
    ram_critical=85,
    disk_free_warning=20,
    disk_free_critical=10,
)


def _cpu(percent: float) -> CpuMetrics:
    return CpuMetrics(percent=percent, logical_count=8, physical_count=4, frequency_mhz=2400)


def _memory(percent: float) -> MemoryMetrics:
    return MemoryMetrics(total_bytes=100, used_bytes=40, available_bytes=60, percent=percent)


def _disk(free_percent: float, drive: str = "C:/") -> DiskMetrics:
    return DiskMetrics(
        drive=drive,
        total_bytes=1000,
        used_bytes=1000 - int(free_percent * 10),
        free_bytes=int(free_percent * 10),
        free_percent=free_percent,
    )


def _status(report: HealthReport, name: str) -> HealthLevel:
    return next(component.status for component in report.components if component.name == name)


@pytest.mark.parametrize(
    ("percent", "expected"),
    [
        (69.9, HealthLevel.NORMAL),
        (70, HealthLevel.WARNING),
        (89.9, HealthLevel.WARNING),
        (90, HealthLevel.CRITICAL),
    ],
)
def test_cpu_boundaries(percent: float, expected: HealthLevel) -> None:
    report = analyze(_cpu(percent), _memory(10), {"C:/": _disk(50)}, THRESHOLDS)
    assert _status(report, "CPU") is expected


@pytest.mark.parametrize(
    ("percent", "expected"),
    [
        (69.9, HealthLevel.NORMAL),
        (70, HealthLevel.WARNING),
        (84.9, HealthLevel.WARNING),
        (85, HealthLevel.CRITICAL),
    ],
)
def test_ram_boundaries(percent: float, expected: HealthLevel) -> None:
    report = analyze(_cpu(10), _memory(percent), {"C:/": _disk(50)}, THRESHOLDS)
    assert _status(report, "RAM") is expected


@pytest.mark.parametrize(
    ("free_percent", "expected"),
    [
        (20.1, HealthLevel.NORMAL),
        (20, HealthLevel.WARNING),
        (10, HealthLevel.WARNING),
        (9.9, HealthLevel.CRITICAL),
    ],
)
def test_disk_free_boundaries(free_percent: float, expected: HealthLevel) -> None:
    report = analyze(_cpu(10), _memory(10), {"C:/": _disk(free_percent)}, THRESHOLDS)
    assert _status(report, "Disk C") is expected


def test_overall_status_uses_the_worst_component_and_skips_missing_drives() -> None:
    report = analyze(
        _cpu(10),
        _memory(90),
        {"C:/": _disk(50), "D:/": None},
        THRESHOLDS,
    )
    assert report.status is HealthLevel.CRITICAL
    assert [component.name for component in report.components] == ["CPU", "RAM", "Disk C"]
    assert any("RAM kritis" in item for item in report.recommendations)


def test_windows_drive_letter_and_critical_disk_recommendation() -> None:
    report = analyze(_cpu(1), _memory(1), {"D:\\": _disk(5, "D:\\")}, THRESHOLDS)
    assert _status(report, "Disk D") is HealthLevel.CRITICAL
    assert any("Disk D sangat penuh" in item for item in report.recommendations)
    assert any("tidak menghapus file" in item for item in report.recommendations)


def test_normal_snapshot_still_marks_recommendations_as_rules() -> None:
    report = analyze(_cpu(5), _memory(5), {"C:/": _disk(40)}, THRESHOLDS)
    assert report.status is HealthLevel.NORMAL
    assert any("batas normal" in item for item in report.recommendations)
    assert report.recommendations[-1].endswith("bukan model AI.")


def test_terminal_report_lists_health_processes_and_missing_drive() -> None:
    snapshot = SystemSnapshot(
        timestamp=datetime(2026, 11, 16, 21, 0, 0),
        cpu=_cpu(12),
        memory=_memory(40),
        disks={"C:/": _disk(8), "D:/": None},
        processes=(ProcessInfo(pid=4, name="chrome", cpu_percent=None, memory_bytes=50_000_000, memory_percent=12),),
        health=HealthReport(
            status=HealthLevel.CRITICAL,
            components=(
                ComponentHealth("CPU", HealthLevel.NORMAL, 12, "12.0% terpakai"),
                ComponentHealth("Disk C", HealthLevel.CRITICAL, 8, "8.0% kosong"),
            ),
            recommendations=("Disk C sangat penuh.", "Rekomendasi ini dihasilkan oleh aturan lokal, bukan model AI."),
        ),
    )
    text = format_snapshot(snapshot)
    assert "CPU: 12.0%" in text
    assert "Disk D: tidak tersedia" in text
    assert "Kesehatan: Kritis" in text
    assert "chrome" in text
    assert "n/a" in text
