"""NEXUS dashboard.

Run with: streamlit run dashboard/app.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from core.config import Settings, load_settings
from core.logging_setup import configure_logging
from core.models import SystemMetricRecord
from dashboard.components.file_organizer import render_file_organizer
from dashboard.components.health_panel import render_health, render_recommendations
from dashboard.components.history_chart import render_history
from dashboard.components.metrics_cards import render_metric_cards
from dashboard.components.process_table import render_processes
from database.repositories.file_repository import FileRepository
from database.repositories.metrics_repository import MetricsRepository
from modules.system_monitor.collector import SystemCollector

# This must be the first Streamlit call. Decorators below also talk to Streamlit.
st.set_page_config(page_title="NEXUS", layout="wide")

_REFRESH_SECONDS = load_settings().refresh_seconds


class HistoryCache:
    """Keep the last chart rows until the collector stores a new SQLite sample."""

    def __init__(self) -> None:
        self._token = -1
        self._records: list[SystemMetricRecord] = []

    def records(
        self,
        collector: SystemCollector,
        repository: MetricsRepository,
        since: datetime,
    ) -> list[SystemMetricRecord]:
        """Query history only after a new row is stored."""
        token = collector.saved_sample_count
        if token != self._token:
            self._records = repository.get_system_history(since)
            self._token = token
        return self._records


@st.cache_resource
def get_services() -> tuple[Settings, SystemCollector, MetricsRepository, HistoryCache, FileRepository]:
    """One collector per Streamlit process so reruns share the sampling clock."""
    settings = load_settings()
    configure_logging(settings)
    repository = MetricsRepository(settings.database_path)
    file_repository = FileRepository(settings.database_path)
    collector = SystemCollector(settings, repository)
    return settings, collector, repository, HistoryCache(), file_repository


@st.fragment(run_every=timedelta(seconds=_REFRESH_SECONDS))
def live_view() -> None:
    """Refresh the figures without resampling faster than the configured intervals."""
    settings, collector, repository, history, _file_repository = get_services()
    snapshot = collector.get_snapshot()
    render_metric_cards(snapshot)
    health_col, recommendation_col = st.columns(2)
    with health_col:
        render_health(snapshot.health)
    with recommendation_col:
        render_recommendations(snapshot.health)
    render_processes(snapshot.processes)
    since = datetime.now() - timedelta(hours=settings.history_hours)
    render_history(history.records(collector, repository, since))


def _render_sidebar(settings: Settings, page: str) -> None:
    st.header("NEXUS")
    if page == "System Monitoring":
        st.write("Phase 1 membaca kondisi laptop dan menulis database sendiri.")
        st.write(f"CPU dan RAM: setiap {settings.cpu_ram_seconds:g} detik")
        st.write(f"Proses: setiap {settings.process_seconds:g} detik")
        st.write(f"Disk: setiap {settings.disk_seconds:g} detik")
        st.write(f"Simpan histori: setiap {settings.persist_seconds:g} detik")
        st.write(f"Retensi: {settings.history_retention_days} hari")
    else:
        megabytes = settings.organizer_large_file_bytes / (1024 * 1024)
        st.write("Phase 2 memindai folder yang Anda pilih. Standarnya adalah Downloads.")
        st.write("Pemindaian dan hash berjalan ketika tombolnya ditekan.")
        st.write("File dipindahkan setelah persetujuan, tanpa menimpa dan tanpa menghapus.")
        st.write(f"File besar: {megabytes:g} MB atau lebih")
        st.write(f"Batas pindaian: {settings.organizer_max_files} file")
        st.write(f"Kedalaman folder: {settings.organizer_max_depth}")
    st.caption("Ubah config/settings.yaml, lalu jalankan ulang Streamlit.")


def main() -> None:
    """Page shell. Monitoring keeps its own refresh. The organizer does not."""
    settings, _, _, _, file_repository = get_services()
    st.title("NEXUS")
    with st.sidebar:
        page = st.radio(
            "Halaman",
            ["System Monitoring", "File Organizer"],
            key="nexus_page",
        )
        _render_sidebar(settings, page)
    if page == "System Monitoring":
        st.caption("Personal AI Laptop Assistant · Phase 1 System Monitoring")
        live_view()
    else:
        st.caption("Personal AI Laptop Assistant · Phase 2 Smart File Organizer")
        render_file_organizer(settings, file_repository)


if __name__ == "__main__":
    main()
