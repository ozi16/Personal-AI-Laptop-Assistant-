"""Rule-based health checks. Thresholds come from configuration, not from this file."""

from core.models import (
    ComponentHealth,
    CpuMetrics,
    DiskMetrics,
    HealthLevel,
    HealthReport,
    MemoryMetrics,
    SEVERITY,
    Thresholds,
    drive_letter,
)


def analyze(
    cpu: CpuMetrics,
    memory: MemoryMetrics,
    disks: dict[str, DiskMetrics | None],
    thresholds: Thresholds,
) -> HealthReport:
    """Score the snapshot and build short local recommendations.

    Recommendations are rules, not an LLM. The dashboard says so explicitly.
    """
    components = [
        ComponentHealth(
            name="CPU",
            status=_usage_level(cpu.percent, thresholds.cpu_warning, thresholds.cpu_critical),
            value=cpu.percent,
            detail=f"{cpu.percent:.1f}% terpakai",
        ),
        ComponentHealth(
            name="RAM",
            status=_usage_level(memory.percent, thresholds.ram_warning, thresholds.ram_critical),
            value=memory.percent,
            detail=f"{memory.percent:.1f}% terpakai",
        ),
    ]

    for drive, metrics in disks.items():
        if metrics is None:
            continue
        status = _free_level(
            metrics.free_percent,
            thresholds.disk_free_warning,
            thresholds.disk_free_critical,
        )
        components.append(
            ComponentHealth(
                name=f"Disk {drive_letter(drive)}",
                status=status,
                value=metrics.free_percent,
                detail=f"{metrics.free_percent:.1f}% kosong",
            )
        )

    overall = max(components, key=lambda item: SEVERITY[item.status]).status
    return HealthReport(
        status=overall,
        components=tuple(components),
        recommendations=_recommendations(components),
    )


def _usage_level(percent: float, warning: float, critical: float) -> HealthLevel:
    """CPU and RAM: higher usage is worse. The critical bound is inclusive."""
    if percent >= critical:
        return HealthLevel.CRITICAL
    if percent >= warning:
        return HealthLevel.WARNING
    return HealthLevel.NORMAL


def _free_level(free_percent: float, warning: float, critical: float) -> HealthLevel:
    """Free disk: lower free space is worse. Exactly ``warning`` percent is still a warning."""
    if free_percent < critical:
        return HealthLevel.CRITICAL
    if free_percent <= warning:
        return HealthLevel.WARNING
    return HealthLevel.NORMAL


def _recommendations(components: list[ComponentHealth]) -> tuple[str, ...]:
    messages = [_advice(component) for component in components if component.status is not HealthLevel.NORMAL]
    if not messages:
        messages.append("Semua metrik dalam batas normal.")
    messages.append("Rekomendasi ini dihasilkan oleh aturan lokal, bukan model AI.")
    return tuple(messages)


def _advice(component: ComponentHealth) -> str:
    if component.name == "CPU" and component.status is HealthLevel.CRITICAL:
        return "CPU kritis. Kurangi beban sebelum membuka pekerjaan baru."
    if component.name == "CPU":
        return "CPU cukup tinggi. Tutup tab atau aplikasi yang tidak sedang dipakai."
    if component.name == "RAM" and component.status is HealthLevel.CRITICAL:
        return (
            "RAM kritis. Tutup aplikasi yang memakai memori paling besar di daftar proses."
        )
    if component.name == "RAM":
        return "RAM mulai penuh. Menutup tab browser biasanya memberi efek paling besar."
    if component.status is HealthLevel.CRITICAL:
        return (
            f"{component.name} sangat penuh. NEXUS tidak menghapus file. "
            "Pembersihan aman ada di fase berikutnya."
        )
    return f"{component.name} mulai penuh. Hindari menyimpan data baru di drive ini."
