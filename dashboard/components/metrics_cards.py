"""CPU, RAM, and disk cards."""

import streamlit as st

from core.models import CpuMetrics, DiskMetrics, SystemSnapshot, bytes_to_gb, find_disk


def render_metric_cards(snapshot: SystemSnapshot) -> None:
    """Show the four resources Phase 1 monitors."""
    cpu_col, ram_col, disk_c_col, disk_d_col = st.columns(4)
    with cpu_col:
        _render_cpu(snapshot.cpu)
    with ram_col:
        _render_memory(snapshot)
    with disk_c_col:
        _render_disk("Disk C", find_disk(snapshot.disks, "C"))
    with disk_d_col:
        _render_disk("Disk D", find_disk(snapshot.disks, "D"))


def _render_cpu(cpu: CpuMetrics) -> None:
    st.metric("CPU", f"{cpu.percent:.1f}%")
    physical = cpu.physical_count if cpu.physical_count is not None else "?"
    if cpu.frequency_mhz is None:
        frequency = "frekuensi tidak tersedia"
    else:
        frequency = f"{cpu.frequency_mhz:.0f} MHz"
    st.caption(f"{cpu.logical_count} logical / {physical} physical · {frequency}")


def _render_memory(snapshot: SystemSnapshot) -> None:
    memory = snapshot.memory
    st.metric("RAM", f"{memory.percent:.1f}%")
    st.caption(
        f"{bytes_to_gb(memory.used_bytes):.1f} / {bytes_to_gb(memory.total_bytes):.1f} GB"
        f" · tersedia {bytes_to_gb(memory.available_bytes):.1f} GB"
    )


def _render_disk(title: str, metrics: DiskMetrics | None) -> None:
    if metrics is None:
        st.metric(title, "Tidak tersedia")
        st.caption("Drive tidak terdeteksi")
        return
    st.metric(title, f"{metrics.used_percent:.1f}%")
    st.caption(
        f"Terpakai · kosong {metrics.free_percent:.1f}% · "
        f"{bytes_to_gb(metrics.free_bytes):.1f} GB bebas dari "
        f"{bytes_to_gb(metrics.total_bytes):.1f} GB"
    )
