"""Disk reads must survive a drive Windows cannot open."""

from types import SimpleNamespace

from modules.system_monitor.disk import read_disks


def test_one_unavailable_drive_does_not_drop_the_other() -> None:
    def usage(drive: str):
        if drive == "Z:/":
            raise OSError("not ready")
        if drive == "D:/":
            raise PermissionError("denied")
        return SimpleNamespace(total=1000, used=400, free=600)

    result = read_disks(["C:/", "D:/", "Z:/"], usage_fn=usage)

    assert result["D:/"] is None
    assert result["Z:/"] is None
    assert result["C:/"] is not None
    assert result["C:/"].free_percent == 60
    assert result["C:/"].used_percent == 40


def test_empty_drive_reports_zero_percent() -> None:
    result = read_disks(
        ["C:/"],
        usage_fn=lambda _drive: SimpleNamespace(total=0, used=0, free=0),
    )
    assert result["C:/"] is not None
    assert result["C:/"].free_percent == 0
    assert result["C:/"].used_percent == 0
