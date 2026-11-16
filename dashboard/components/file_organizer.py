"""File Organizer page. Scanning and hashing run only when a button is pressed."""

from dataclasses import replace
from pathlib import Path

import streamlit as st

from core.config import Settings
from database.repositories.file_repository import FileRepository
from modules.file_manager.classifier import CATEGORIES
from modules.file_manager.duplicate_detector import group_by_recorded_hash
from modules.file_manager.large_file_detector import find_large_files
from modules.file_manager.models import (
    DuplicateGroup,
    DuplicateReport,
    FileOperation,
    MovePlan,
    ScanResult,
    ScannedFile,
)
from modules.file_manager.organizer import build_recommendations, split_plans
from modules.file_manager.path_validator import (
    PathValidationError,
    default_downloads_dir,
    ensure_inside,
    folders_match,
    validate_scan_root,
)
from modules.file_manager.service import (
    apply_moves,
    infer_organizer_root,
    plans_for,
    recover_operations,
    scan_folder,
    store_duplicates,
    undo_move,
)

_SORTS = {
    "Ukuran, terbesar": "size_desc",
    "Ukuran, terkecil": "size_asc",
    "Tanggal, terbaru": "date_desc",
    "Tanggal, terlama": "date_asc",
    "Nama": "name",
}
_STATUS = {
    "pending": "Tertunda",
    "success": "Berhasil",
    "failed": "Gagal",
    "undo_pending": "Undo tertunda",
    "undone": "Diurungkan",
    "recovery_required": "Perlu pemulihan",
}
_UNDO_PAGE_SIZE = 20
_OPERATION = {"move": "Pindah", "undo": "Undo"}
_DISPLAY_LIMIT = 1000


def render_file_organizer(settings: Settings, repository: FileRepository) -> None:
    """Show the latest scan and the actions that require an explicit click."""
    _ensure_state(repository)
    _show_notice()
    if "organizer_folder" not in st.session_state:
        stored_root = st.session_state.get("organizer_root")
        st.session_state["organizer_folder"] = stored_root or str(default_downloads_dir())

    st.caption(
        "Pemindaian membaca metadata. File dipindahkan setelah persetujuan, "
        "tanpa menimpa file yang sudah ada dan tanpa menghapus apa pun."
    )
    folder = st.text_input("Folder sumber", key="organizer_folder")
    active = st.session_state.get("organizer_root")
    if active:
        st.caption(f"Folder aktif: {active}")
        if not folders_match(folder, active):
            st.info("Isi kotak belum menjadi folder aktif. Tekan Pindai folder untuk memakainya.")
    else:
        st.caption("Belum ada folder aktif. Tekan Pindai folder.")

    scan_col, plan_col = st.columns(2)
    with scan_col:
        scan_clicked = st.button("Pindai folder", type="primary", key="organizer_scan")
    with plan_col:
        plan_clicked = st.button("Buat rencana", key="organizer_plan")

    if scan_clicked:
        _run_scan(settings, repository, folder)
    elif plan_clicked:
        _run_plan(folder)

    files: tuple[ScannedFile, ...] = st.session_state["organizer_files"]
    plans: tuple[MovePlan, ...] | None = st.session_state["organizer_plans"]
    _render_overview(settings, files, plans)
    _render_large_files(settings, files)

    section = st.radio(
        "Bagian",
        ["File Explorer", "Duplicate Files", "Organization Preview", "Operation History"],
        horizontal=True,
        key="organizer_section",
    )
    if section == "File Explorer":
        _render_explorer(files)
    elif section == "Duplicate Files":
        _render_duplicates(settings, repository, files)
    elif section == "Organization Preview":
        _render_preview(repository, plans)
    else:
        _render_history(repository)


def _ensure_state(repository: FileRepository) -> None:
    if "organizer_files" in st.session_state:
        return
    files = tuple(repository.list_all())
    root = infer_organizer_root(files)
    st.session_state["organizer_files"] = files
    st.session_state["organizer_plans"] = None
    st.session_state["organizer_root"] = None if root is None else str(root)
    st.session_state["organizer_errors"] = ()
    st.session_state["organizer_truncated"] = False
    st.session_state["organizer_duplicates"] = None


def _show_notice() -> None:
    notice = st.session_state.pop("organizer_notice", None)
    if not notice:
        return
    kind, text = notice
    if kind == "warning":
        st.warning(text)
    elif kind == "error":
        st.error(text)
    else:
        st.success(text)


def _run_scan(settings: Settings, repository: FileRepository, folder: str) -> None:
    progress_bar = st.progress(0.0)
    status = st.empty()

    def on_progress(count: int) -> None:
        status.text(f"Memindai... {count} file")
        progress_bar.progress(min(count / settings.organizer_max_files, 1.0))

    try:
        outcome = scan_folder(
            Path(folder),
            recursive=True,
            max_depth=settings.organizer_max_depth,
            max_files=settings.organizer_max_files,
            repository=repository,
            batch_size=settings.organizer_batch_size,
            progress=on_progress,
        )
    except PathValidationError as exc:
        st.error(str(exc))
        return
    if not outcome.completed:
        message = outcome.errors[0].message if outcome.errors else "Folder tidak bisa dipindai."
        st.error(message)
        return

    state = session_after_scan(outcome)
    if state is None:
        st.error("Folder tidak bisa dipindai.")
        return
    st.session_state.update(state)
    st.session_state["organizer_notice"] = (
        "success",
        f"Pindaian selesai. {len(outcome.files)} file. Folder aktif: {outcome.root}",
    )
    st.rerun()


def _run_plan(folder: str) -> None:
    files: tuple[ScannedFile, ...] = st.session_state["organizer_files"]
    if not files:
        st.info("Belum ada file. Pindai folder terlebih dahulu.")
        return
    try:
        root_text = active_root_for_actions(st.session_state.get("organizer_root"), folder)
        root = validate_scan_root(Path(root_text))
    except PathValidationError as exc:
        st.error(str(exc))
        return
    st.session_state["organizer_plans"] = plans_for(files, root)
    st.session_state["organizer_notice"] = ("success", "Rencana pengorganisasian diperbarui.")
    st.rerun()


def _render_overview(
    settings: Settings,
    files: tuple[ScannedFile, ...],
    plans: tuple[MovePlan, ...] | None,
) -> None:
    st.subheader("Overview")
    duplicate_count = _duplicate_count(files)
    large_files = find_large_files(files, threshold_bytes=settings.organizer_large_file_bytes)
    categories = {item.category for item in files if item.category}
    total_bytes = sum(item.file_size for item in files)

    columns = st.columns(5)
    columns[0].metric("Total file", len(files))
    columns[1].metric("Penyimpanan", _format_size(total_bytes))
    columns[2].metric("Kategori", len(categories))
    columns[3].metric("Kelompok duplikat", "—" if duplicate_count is None else duplicate_count)
    columns[4].metric("File besar", len(large_files))

    if st.session_state.get("organizer_truncated"):
        st.warning(f"Pindaian berhenti pada batas {settings.organizer_max_files} file.")
    errors = st.session_state.get("organizer_errors") or ()
    if errors:
        with st.expander(f"{len(errors)} item tidak bisa dibaca"):
            for error in errors:
                st.write(f"{error.path}: {error.message}")

    st.subheader("Rekomendasi")
    for tip in build_recommendations(files, plans, duplicate_count, len(large_files)):
        st.write(f"- {tip}")


def _render_large_files(settings: Settings, files: tuple[ScannedFile, ...]) -> None:
    threshold = settings.organizer_large_file_bytes
    large_files = find_large_files(files, threshold_bytes=threshold)
    st.subheader("File besar")
    st.caption(f"Ambang {_format_size(threshold)}. File ini hanya dilaporkan.")
    if not large_files:
        st.info("Tidak ada file pada atau di atas ambang.")
        return
    shown = large_files[:20]
    if len(large_files) > len(shown):
        st.caption(f"Menampilkan {len(shown)} file terbesar dari {len(large_files)}.")
    st.dataframe(_file_rows(shown), hide_index=True, width="stretch")


def _render_explorer(files: tuple[ScannedFile, ...]) -> None:
    if not files:
        st.info("Belum ada hasil pindaian.")
        return
    search_col, category_col, sort_col = st.columns(3)
    with search_col:
        query = st.text_input("Cari", key="organizer_search")
    with category_col:
        category = st.selectbox("Kategori", ["Semua", *CATEGORIES], key="organizer_category")
    with sort_col:
        sort_label = st.selectbox("Urutkan", list(_SORTS), key="organizer_sort")

    selected = _filter_files(files, category, query, _SORTS[sort_label])
    st.caption(f"{len(selected)} file")
    if len(selected) > _DISPLAY_LIMIT:
        st.caption(f"Menampilkan {_DISPLAY_LIMIT} file pertama. Persempit pencarian untuk melihat sisanya.")
        selected = selected[:_DISPLAY_LIMIT]
    if not selected:
        st.info("Tidak ada file yang cocok.")
        return
    st.dataframe(_file_rows(selected), hide_index=True, width="stretch")


def _render_duplicates(
    settings: Settings,
    repository: FileRepository,
    files: tuple[ScannedFile, ...],
) -> None:
    st.caption("Hash dihitung hanya untuk file yang ukurannya sama, dan hanya ketika tombol ini ditekan.")
    detect = st.button(
        "Deteksi duplikat",
        key="organizer_detect",
        disabled=not files,
    )
    if detect:
        _run_duplicate_check(settings, repository, files)
        return

    report: DuplicateReport | None = st.session_state.get("organizer_duplicates")
    if report is not None:
        _show_duplicate_report(report.groups, report.errors)
        return
    stored = group_by_recorded_hash(files)
    if stored is None:
        st.info("Deteksi duplikat belum dijalankan.")
        return
    st.caption("Menampilkan hash yang sudah tersimpan. Tekan deteksi untuk menghitung ulang.")
    _show_duplicate_report(stored, ())


def _run_duplicate_check(
    settings: Settings,
    repository: FileRepository,
    files: tuple[ScannedFile, ...],
) -> None:
    progress_bar = st.progress(0.0)
    status = st.empty()

    def on_progress(done: int, total: int) -> None:
        status.text(f"Menghitung hash {done} dari {total}")
        if total:
            progress_bar.progress(done / total)

    report = store_duplicates(
        files,
        repository,
        chunk_size=settings.organizer_hash_chunk_bytes,
        batch_size=settings.organizer_batch_size,
        progress=on_progress,
    )
    saved = dict(report.hashes)
    st.session_state["organizer_files"] = tuple(
        replace(item, sha256=saved.get(str(item.file_path), item.sha256))
        for item in files
    )
    st.session_state["organizer_duplicates"] = report
    if report.hashes:
        text = f"Deteksi selesai. {len(report.groups)} kelompok duplikat."
    else:
        text = "Deteksi selesai. Tidak ada file dengan ukuran yang sama, jadi tidak ada hash yang dihitung."
    st.session_state["organizer_notice"] = ("success", text)
    st.rerun()


def _show_duplicate_report(groups: tuple[DuplicateGroup, ...], errors) -> None:
    if errors:
        st.warning(f"{len(errors)} file tidak bisa di-hash.")
    if not groups:
        st.info("Tidak ada file dengan hash yang sama.")
        return
    st.caption("Kelompok di bawah ini punya isi yang sama. NEXUS tidak menghapus duplikat.")
    for index, group in enumerate(groups, start=1):
        st.markdown(f"**Kelompok {index}** · {_format_size(group.file_size)} · `{group.sha256[:12]}`")
        st.dataframe(
            [
                {"File": item.file_name, "Lokasi": str(item.file_path), "Ukuran": _format_size(item.file_size)}
                for item in group.files
            ],
            hide_index=True,
            width="stretch",
        )


def _render_preview(repository: FileRepository, plans: tuple[MovePlan, ...] | None) -> None:
    active = st.session_state.get("organizer_root") or "belum ada"
    st.caption(f"Folder aktif: {active}")
    if plans is None:
        st.info("Buat rencana untuk melihat tujuan file. Rencana ini belum memindahkan apa pun.")
        return
    movable, conflicts, organized = split_plans(plans)
    if organized:
        st.caption(f"{len(organized)} file sudah berada di folder yang sesuai.")
    st.subheader("Siap dipindahkan")
    if not movable:
        st.info("Tidak ada file yang menunggu persetujuan.")
    else:
        st.dataframe(_plan_rows(movable), hide_index=True, width="stretch")
        approved = st.checkbox(
            f"Saya meninjau rencana ini dan menyetujui pemindahan di dalam folder aktif: {active}.",
            key="organizer_approve",
        )
        if st.button("Pindahkan file", key="organizer_move", disabled=not approved):
            _run_move(repository, movable)

    st.subheader("Konflik")
    if not conflicts:
        st.caption("Tidak ada konflik.")
        return
    st.warning(
        "File bentrok dilewati. NEXUS tidak menimpa, tidak mengganti nama, dan tidak menghapus file."
    )
    st.dataframe(_plan_rows(conflicts), hide_index=True, width="stretch")


def _run_move(repository: FileRepository, movable: tuple[MovePlan, ...]) -> None:
    root_text = st.session_state.get("organizer_root")
    if not root_text:
        st.error("Pindai folder terlebih dahulu.")
        return
    try:
        root = validate_scan_root(Path(root_text))
        for plan in movable:
            ensure_inside(root, plan.source_path)
        results = apply_moves(movable, root, repository, approved=True)
    except PermissionError as exc:
        st.error(str(exc))
        return
    except PathValidationError as exc:
        st.error(str(exc))
        return
    files = tuple(repository.list_all())
    st.session_state["organizer_files"] = files
    st.session_state["organizer_plans"] = plans_for(files, root)
    st.session_state["organizer_duplicates"] = None
    ok = sum(1 for item in results if item.ok)
    failed = [item for item in results if not item.ok]
    text = f"{ok} file dipindahkan."
    if failed:
        text = f"{text} {len(failed)} gagal. {failed[0].message}"
    st.session_state["organizer_notice"] = ("warning" if failed else "success", text)
    st.rerun()


def _render_history(repository: FileRepository) -> None:
    operations = repository.list_operations(limit=100)
    open_operations = repository.list_open_operations()
    if open_operations:
        st.warning(f"{len(open_operations)} operasi belum selesai. Periksa pemulihan sebelum mengulang pemindahan.")
    if st.button("Periksa operasi tertunda", key="organizer_recover"):
        _run_recover(repository)
    if not operations:
        st.info("Belum ada operasi.")
        return
    st.caption("Riwayat menampilkan 100 operasi terbaru. Pilihan Undo mencari seluruh pemindahan yang berhasil.")
    st.dataframe(history_rows(operations), hide_index=True, width="stretch")
    _render_undo_picker(repository)


def _render_undo_picker(repository: FileRepository) -> None:
    search = st.text_input("Cari undo", key="organizer_undo_search")
    page = _undo_page(search)
    undoable, total = repository.list_undoable_moves(
        search=search,
        limit=_UNDO_PAGE_SIZE,
        offset=page * _UNDO_PAGE_SIZE,
    )
    if total == 0:
        st.caption("Tidak ada pemindahan yang bisa diurungkan.")
        return
    st.caption(f"{total} pemindahan berhasil. Halaman {page + 1}.")
    labels = {
        f"#{item.id} · {Path(item.source_path).name}": item.id
        for item in undoable
    }
    choice = st.selectbox("Operasi yang diurungkan", list(labels), key="organizer_undo_choice")
    previous, following = st.columns(2)
    if page > 0 and previous.button("Sebelumnya", key="organizer_undo_prev"):
        st.session_state["organizer_undo_page"] = page - 1
        st.session_state.pop("organizer_undo_choice", None)
        st.rerun()
    if (page + 1) * _UNDO_PAGE_SIZE < total and following.button("Berikutnya", key="organizer_undo_next"):
        st.session_state["organizer_undo_page"] = page + 1
        st.session_state.pop("organizer_undo_choice", None)
        st.rerun()
    confirmed = st.checkbox(
        "Kembalikan file ini ke lokasi asal jika lokasi itu kosong.",
        key="organizer_undo_confirm",
    )
    if st.button("Undo", key="organizer_undo", disabled=not confirmed):
        _run_undo(repository, labels[choice])


def _undo_page(search: str) -> int:
    if st.session_state.get("organizer_undo_query") != search:
        st.session_state["organizer_undo_query"] = search
        st.session_state["organizer_undo_page"] = 0
        st.session_state.pop("organizer_undo_choice", None)
    return int(st.session_state.get("organizer_undo_page", 0))


def _run_recover(repository: FileRepository) -> None:
    root_text = st.session_state.get("organizer_root")
    if not root_text:
        st.error("Pindai folder aktif terlebih dahulu. Pemulihan tidak memindahkan file.")
        return
    try:
        results = recover_operations(Path(root_text), repository)
    except PathValidationError as exc:
        st.error(str(exc))
        return
    if not results:
        st.session_state["organizer_notice"] = ("success", "Tidak ada operasi tertunda.")
    else:
        text = " ".join(item.message for item in results if item.message)
        kind = "warning" if any(item.operation and item.operation.status == "recovery_required" for item in results) else "success"
        st.session_state["organizer_notice"] = (kind, text or "Pemeriksaan selesai.")
    st.rerun()


def _run_undo(repository: FileRepository, operation_id: int) -> None:
    root_text = st.session_state.get("organizer_root")
    if not root_text:
        st.error("Pindai folder aktif terlebih dahulu.")
        return
    try:
        result = undo_move(operation_id, Path(root_text), repository)
    except ValueError as exc:
        st.error(str(exc))
        return
    except PathValidationError as exc:
        st.error(str(exc))
        return
    files = tuple(repository.list_all())
    st.session_state["organizer_files"] = files
    root = st.session_state.get("organizer_root")
    if root and files:
        try:
            st.session_state["organizer_plans"] = plans_for(files, Path(root))
        except PathValidationError:
            st.session_state["organizer_plans"] = None
    st.session_state["organizer_duplicates"] = None
    st.session_state["organizer_notice"] = ("success" if result.ok else "warning", result.message)
    st.rerun()


def active_root_for_actions(scanned_root: str | None, typed_folder: str) -> str:
    """Return the last successful scan. ``typed_folder`` applies only on the next scan."""
    del typed_folder
    if not scanned_root:
        raise PathValidationError("Pindai folder terlebih dahulu.")
    return scanned_root


def session_after_scan(outcome: ScanResult) -> dict[str, object] | None:
    """Replace the active folder and discard the previous plan after a completed scan."""
    if not outcome.completed:
        return None
    root = Path(outcome.root)
    return {
        "organizer_files": outcome.files,
        "organizer_root": outcome.root,
        "organizer_errors": outcome.errors,
        "organizer_truncated": outcome.truncated,
        "organizer_duplicates": None,
        "organizer_plans": plans_for(outcome.files, root),
    }


def history_rows(operations: list[FileOperation]) -> list[dict[str, str]]:
    """Rows for the history table, including the stored failure reason."""
    return [
        {
            "ID": str(item.id),
            "Jenis": _OPERATION.get(item.operation_type, item.operation_type),
            "Status": _STATUS.get(item.status, item.status),
            "Pesan": item.error_message or "",
            "Dari": item.source_path,
            "Ke": item.destination_path,
            "Dibuat": item.created_at,
            "Selesai": item.completed_at or "",
        }
        for item in operations
    ]


def _duplicate_count(files: tuple[ScannedFile, ...]) -> int | None:
    report: DuplicateReport | None = st.session_state.get("organizer_duplicates")
    if report is not None:
        return len(report.groups)
    stored = group_by_recorded_hash(files)
    if stored is None:
        return None
    return len(stored)


def _filter_files(files: tuple[ScannedFile, ...], category: str, query: str, sort_key: str) -> list[ScannedFile]:
    needle = query.casefold().strip()
    selected = []
    for item in files:
        if category != "Semua" and item.category != category:
            continue
        haystack = f"{item.file_name} {item.file_path}".casefold()
        if needle and needle not in haystack:
            continue
        selected.append(item)
    selected.sort(key=_sort_value(sort_key))
    return selected


def _sort_value(sort_key: str):
    def key(item: ScannedFile):
        name = item.file_name.casefold()
        if sort_key == "size_asc":
            return (item.file_size, name)
        if sort_key == "date_desc":
            return (-item.modified_at.timestamp(), name)
        if sort_key == "date_asc":
            return (item.modified_at.timestamp(), name)
        if sort_key == "name":
            return (name,)
        return (-item.file_size, name)

    return key


def _file_rows(files) -> list[dict[str, str]]:
    return [
        {
            "Nama": item.file_name,
            "Kategori": item.category,
            "Ekstensi": item.extension or "—",
            "Ukuran": _format_size(item.file_size),
            "Diubah": item.modified_at.strftime("%Y-%m-%d %H:%M"),
            "Lokasi": str(item.file_path),
        }
        for item in files
    ]


def _plan_rows(plans: tuple[MovePlan, ...]) -> list[dict[str, str]]:
    return [
        {
            "File": plan.file_name,
            "Kategori": plan.category,
            "Ukuran": _format_size(plan.file_size),
            "Dari": str(plan.source_path),
            "Ke": str(plan.destination_path),
            "Konflik": plan.conflict_reason,
        }
        for plan in plans
    ]


def _format_size(size: int) -> str:
    """Format a byte count for the dashboard."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
