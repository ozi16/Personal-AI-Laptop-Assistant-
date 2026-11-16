"""Load config/settings.yaml into a typed Settings object."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from core.models import Thresholds

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Paths are absolute and resolved from the project root."""

    project_root: Path
    cpu_ram_seconds: float
    process_seconds: float
    disk_seconds: float
    persist_seconds: float
    cpu_sample_interval_seconds: float
    process_top_n: int
    history_retention_days: int
    drives: tuple[str, ...]
    thresholds: Thresholds
    database_path: Path
    refresh_seconds: float
    history_hours: int
    log_level: str
    log_path: Path
    organizer_large_file_bytes: int = 104_857_600
    organizer_max_files: int = 5_000
    organizer_max_depth: int = 6
    organizer_hash_chunk_bytes: int = 1_048_576
    organizer_batch_size: int = 80


def load_settings(path: Path | None = None) -> Settings:
    """Read YAML settings and reject values that would break the monitor."""
    config_path = path or (PROJECT_ROOT / "config" / "settings.yaml")
    if not config_path.is_file():
        raise ValueError(f"Settings file not found: {config_path}")

    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"Settings file must be a mapping: {config_path}")

    monitoring = _mapping(raw, "monitoring")
    intervals = _mapping(monitoring, "intervals")
    thresholds_raw = _mapping(raw, "thresholds")
    cpu_raw = _mapping(thresholds_raw, "cpu")
    ram_raw = _mapping(thresholds_raw, "ram")
    disk_raw = _mapping(thresholds_raw, "disk_free")
    database = _mapping(raw, "database")
    dashboard = _mapping(raw, "dashboard")
    logging_raw = _mapping(raw, "logging")
    organizer_raw = _optional_mapping(raw, "file_organizer")

    thresholds = Thresholds(
        cpu_warning=_number(cpu_raw, "warning"),
        cpu_critical=_number(cpu_raw, "critical"),
        ram_warning=_number(ram_raw, "warning"),
        ram_critical=_number(ram_raw, "critical"),
        disk_free_warning=_number(disk_raw, "warning"),
        disk_free_critical=_number(disk_raw, "critical"),
    )
    _validate_thresholds(thresholds)

    drives = tuple(str(drive) for drive in _sequence(monitoring, "drives"))
    if not drives:
        raise ValueError("monitoring.drives must list at least one drive")

    settings = Settings(
        project_root=PROJECT_ROOT,
        cpu_ram_seconds=_positive(intervals, "cpu_ram_seconds"),
        process_seconds=_positive(intervals, "process_seconds"),
        disk_seconds=_positive(intervals, "disk_seconds"),
        persist_seconds=_positive(intervals, "persist_seconds"),
        cpu_sample_interval_seconds=_positive(monitoring, "cpu_sample_interval_seconds"),
        process_top_n=_positive_int(monitoring, "process_top_n"),
        history_retention_days=_positive_int(monitoring, "history_retention_days"),
        drives=drives,
        thresholds=thresholds,
        database_path=_resolve(PROJECT_ROOT, str(_required(database, "path"))),
        refresh_seconds=_positive(dashboard, "refresh_seconds"),
        history_hours=_positive_int(dashboard, "history_hours"),
        log_level=str(_required(logging_raw, "level")).upper(),
        log_path=_resolve(PROJECT_ROOT, str(_required(logging_raw, "path"))),
        organizer_large_file_bytes=_int_or(organizer_raw, "large_file_bytes", 104_857_600),
        organizer_max_files=_int_or(organizer_raw, "max_files", 5_000),
        organizer_max_depth=_int_or(organizer_raw, "max_depth", 6),
        organizer_hash_chunk_bytes=_int_or(organizer_raw, "hash_chunk_bytes", 1_048_576),
        organizer_batch_size=_int_or(organizer_raw, "batch_size", 80),
    )
    if settings.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError(f"Unsupported logging.level: {settings.log_level}")
    return settings


def _validate_thresholds(thresholds: Thresholds) -> None:
    """CPU and RAM get worse as they rise. Free disk gets worse as it falls."""
    _validate_rising("cpu", thresholds.cpu_warning, thresholds.cpu_critical)
    _validate_rising("ram", thresholds.ram_warning, thresholds.ram_critical)
    if not (0 <= thresholds.disk_free_critical < thresholds.disk_free_warning <= 100):
        raise ValueError(
            "disk_free thresholds must satisfy 0 <= critical < warning <= 100"
        )


def _validate_rising(name: str, warning: float, critical: float) -> None:
    if not (0 <= warning < critical <= 100):
        raise ValueError(f"{name} thresholds must satisfy 0 <= warning < critical <= 100")


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return path


def _required(mapping: dict, key: str) -> object:
    if key not in mapping:
        raise ValueError(f"Missing config key: {key}")
    return mapping[key]


def _optional_mapping(parent: dict, key: str) -> dict:
    if key not in parent or parent[key] is None:
        return {}
    value = parent[key]
    if not isinstance(value, dict):
        raise ValueError(f"Config key '{key}' must be a mapping")
    return value


def _mapping(parent: dict, key: str) -> dict:
    value = _required(parent, key)
    if not isinstance(value, dict):
        raise ValueError(f"Config key '{key}' must be a mapping")
    return value


def _sequence(parent: dict, key: str) -> list:
    value = _required(parent, key)
    if not isinstance(value, list):
        raise ValueError(f"Config key '{key}' must be a list")
    return value


def _number(parent: dict, key: str) -> float:
    value = _required(parent, key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Config key '{key}' must be a number")
    return float(value)


def _positive(parent: dict, key: str) -> float:
    value = _number(parent, key)
    if value <= 0:
        raise ValueError(f"Config key '{key}' must be greater than 0")
    return value


def _int_or(parent: dict, key: str, default: int) -> int:
    if key not in parent:
        return default
    return _positive_int(parent, key)


def _positive_int(parent: dict, key: str) -> int:
    value = _required(parent, key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"Config key '{key}' must be a positive integer")
    return value
