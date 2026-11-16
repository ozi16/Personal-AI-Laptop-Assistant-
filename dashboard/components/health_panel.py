"""Health status and the rule-based recommendation box."""

import streamlit as st

from core.models import HealthLevel, HealthReport

_LABELS = {
    HealthLevel.NORMAL: "Normal",
    HealthLevel.WARNING: "Peringatan",
    HealthLevel.CRITICAL: "Kritis",
}
_COLORS = {
    HealthLevel.NORMAL: "green",
    HealthLevel.WARNING: "orange",
    HealthLevel.CRITICAL: "red",
}


def render_health(report: HealthReport) -> None:
    """Show the worst status and the reason for each resource."""
    st.subheader("Status kesehatan")
    color = _COLORS[report.status]
    label = _LABELS[report.status]
    st.markdown(f"Keseluruhan: :{color}[**{label}**]")
    for component in report.components:
        component_color = _COLORS[component.status]
        component_label = _LABELS[component.status]
        st.markdown(
            f"{component.name}: :{component_color}[{component_label}] · {component.detail}"
        )


def render_recommendations(report: HealthReport) -> None:
    """Placeholder for Phase 4. Phase 1 only shows local rules."""
    st.subheader("Rekomendasi")
    st.caption("Berbasis aturan lokal. Mesin AI ditambahkan pada Phase 4.")
    for recommendation in report.recommendations:
        st.write(f"- {recommendation}")
