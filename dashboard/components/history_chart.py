"""Historical CPU, RAM, and free-disk chart."""

import streamlit as st

from core.models import SystemMetricRecord


def render_history(records: list[SystemMetricRecord]) -> None:
    """Plot stored percentages. Disk series are free space, not used space."""
    st.subheader("Histori penggunaan resource")
    st.caption(
        "CPU dan RAM adalah persen terpakai. Garis disk adalah persen ruang kosong. "
        "Titik baru disimpan sekitar setiap 30 detik."
    )
    if not records:
        st.info("Belum ada histori. Data pertama muncul setelah satu siklus penyimpanan.")
        return

    rows: list[dict[str, object]] = []
    for record in records:
        rows.append({"Waktu": record.timestamp, "Metrik": "CPU %", "Persen": record.cpu_percent})
        rows.append({"Waktu": record.timestamp, "Metrik": "RAM %", "Persen": record.ram_percent})
        if record.disk_c_free_percent is not None:
            rows.append(
                {"Waktu": record.timestamp, "Metrik": "Free C %", "Persen": record.disk_c_free_percent}
            )
        if record.disk_d_free_percent is not None:
            rows.append(
                {"Waktu": record.timestamp, "Metrik": "Free D %", "Persen": record.disk_d_free_percent}
            )

    st.vega_lite_chart(
        rows,
        {
            "height": 280,
            "mark": {"type": "line"},
            "encoding": {
                "x": {"field": "Waktu", "type": "temporal", "title": "Waktu"},
                "y": {
                    "field": "Persen",
                    "type": "quantitative",
                    "title": "Persen",
                    "scale": {"domain": [0, 100]},
                },
                "color": {"field": "Metrik", "type": "nominal", "title": "Metrik"},
            },
        },
        width="stretch",
    )
