"""Top processes by RAM."""

import streamlit as st

from core.models import ProcessInfo


def render_processes(processes: tuple[ProcessInfo, ...]) -> None:
    """Show the processes that currently use the most memory."""
    st.subheader("Proses dengan RAM terbesar")
    if not processes:
        st.info("Tidak ada proses yang bisa dibaca.")
        return

    # Keep each column one type. A mix of numbers and "n/a" makes Streamlit
    # retry Arrow conversion on every refresh.
    rows = [
        {
            "Nama": process.name,
            "PID": process.pid,
            "CPU %": "n/a" if process.cpu_percent is None else f"{process.cpu_percent:.1f}",
            "RAM (MB)": f"{process.memory_bytes / (1024 ** 2):.1f}",
            "RAM %": "n/a" if process.memory_percent is None else f"{process.memory_percent:.1f}",
        }
        for process in processes
    ]
    st.dataframe(rows, hide_index=True, width="stretch")
