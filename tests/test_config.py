"""Settings file and the Phase 1 safety boundary."""

from pathlib import Path

import pytest

from core.config import load_settings
from security import FILE_MOVE_REQUIRES_APPROVAL, FORBIDDEN_ACTIONS, PHASE_NAME, READ_ONLY_SYSTEM_ACCESS


def test_project_settings_match_phase1_defaults() -> None:
    settings = load_settings()
    assert settings.cpu_ram_seconds == 5
    assert settings.process_seconds == 10
    assert settings.disk_seconds == 30
    assert settings.persist_seconds == 30
    assert settings.process_top_n == 10
    assert settings.history_retention_days == 7
    assert settings.drives == ("C:/", "D:/")
    assert settings.thresholds.cpu_warning == 70
    assert settings.thresholds.cpu_critical == 90
    assert settings.thresholds.ram_warning == 70
    assert settings.thresholds.ram_critical == 85
    assert settings.thresholds.disk_free_warning == 20
    assert settings.thresholds.disk_free_critical == 10
    assert settings.refresh_seconds == 5
    assert settings.history_hours == 24
    assert settings.database_path == settings.project_root / "database" / "nexus.db"
    assert settings.organizer_large_file_bytes == 104_857_600
    assert settings.organizer_max_files == 5000
    assert settings.organizer_max_depth == 6
    assert settings.organizer_hash_chunk_bytes == 1_048_576
    assert settings.organizer_batch_size == 80


def test_missing_file_and_invalid_thresholds(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not found"):
        load_settings(tmp_path / "missing.yaml")

    config = tmp_path / "settings.yaml"
    config.write_text(
        """
monitoring:
  intervals:
    cpu_ram_seconds: 5
    process_seconds: 10
    disk_seconds: 30
    persist_seconds: 30
  cpu_sample_interval_seconds: 0.1
  process_top_n: 10
  history_retention_days: 7
  drives: ['C:/']
thresholds:
  cpu:
    warning: 95
    critical: 90
  ram:
    warning: 70
    critical: 85
  disk_free:
    warning: 20
    critical: 10
database:
  path: database/nexus.db
dashboard:
  refresh_seconds: 5
  history_hours: 24
logging:
  level: INFO
  path: logs/nexus.log
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cpu thresholds"):
        load_settings(config)


def test_phase1_does_not_allow_destructive_actions() -> None:
    assert READ_ONLY_SYSTEM_ACCESS is True
    assert "delete_files" in FORBIDDEN_ACTIONS
    assert "kill_processes" in FORBIDDEN_ACTIONS
    assert "run_admin_shell" in FORBIDDEN_ACTIONS


def test_phase2_move_requires_approval_and_cannot_destroy_files() -> None:
    assert PHASE_NAME == "phase2"
    assert FILE_MOVE_REQUIRES_APPROVAL is True
    assert "overwrite_files" in FORBIDDEN_ACTIONS
    assert "rename_files" in FORBIDDEN_ACTIONS
    assert "change_file_content" in FORBIDDEN_ACTIONS
    assert "move_files_without_approval" in FORBIDDEN_ACTIONS
    assert "run_shell" in FORBIDDEN_ACTIONS


def test_file_organizer_settings_default_when_section_is_absent(tmp_path: Path) -> None:
    config = tmp_path / "settings.yaml"
    config.write_text(
        """
monitoring:
  intervals:
    cpu_ram_seconds: 5
    process_seconds: 10
    disk_seconds: 30
    persist_seconds: 30
  cpu_sample_interval_seconds: 0.1
  process_top_n: 10
  history_retention_days: 7
  drives: ['C:/']
thresholds:
  cpu:
    warning: 70
    critical: 90
  ram:
    warning: 70
    critical: 85
  disk_free:
    warning: 20
    critical: 10
database:
  path: database/nexus.db
dashboard:
  refresh_seconds: 5
  history_hours: 24
logging:
  level: INFO
  path: logs/nexus.log
""",
        encoding="utf-8",
    )
    settings = load_settings(config)
    assert settings.organizer_large_file_bytes == 104_857_600
    assert settings.organizer_max_files == 5000
    assert settings.organizer_batch_size == 80
