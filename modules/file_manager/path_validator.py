"""Decide which folders NEXUS may scan or use as a move destination."""

import os
import stat
from pathlib import Path

_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
})


class PathValidationError(ValueError):
    """The path is outside the folder NEXUS is allowed to touch."""


def default_downloads_dir() -> Path:
    """The user's Downloads folder. Scanning starts here unless another folder is chosen."""
    return Path.home() / "Downloads"


def blocked_system_roots() -> tuple[Path, ...]:
    """Windows and program directories that NEXUS must not scan."""
    names: list[str] = []
    for key in ("SystemRoot", "WINDIR"):
        value = os.environ.get(key)
        if value:
            names.append(value)
    names.extend((
        r"C:\Windows",
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        r"C:\ProgramData",
    ))
    unique: list[Path] = []
    seen: set[str] = set()
    for name in names:
        key = os.path.normcase(str(Path(name)))
        if key in seen:
            continue
        seen.add(key)
        unique.append(Path(name))
    return tuple(unique)


def is_reparse_point(path: Path) -> bool:
    """True for a symbolic link or junction. A missing path is not a link."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & _REPARSE)


def is_drive_root(path: Path) -> bool:
    """True when the path is a whole drive such as ``C:\\``."""
    raw = str(path).replace("/", "\\").rstrip("\\")
    if len(raw) == 2 and raw[1] == ":":
        return True
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return os.path.normcase(str(resolved)) == os.path.normcase(str(Path(resolved.anchor)))


def is_blocked_system_path(path: Path) -> bool:
    """True when the path is a Windows or program directory, or lives inside one."""
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return _matches_blocked(resolved) or _matches_blocked(path)


def paths_equal(left: Path, right: Path) -> bool:
    """Compare two paths the way the Windows filesystem does."""
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(
        os.path.normpath(str(right))
    )


def folders_match(left: str | Path, right: str | Path) -> bool:
    """True when two folder texts resolve to the same directory."""
    try:
        return paths_equal(Path(left).resolve(), Path(right).resolve())
    except OSError:
        return paths_equal(Path(left), Path(right))


def is_inside(root: Path, candidate: Path) -> bool:
    """True when ``candidate`` is ``root`` or a path under it."""
    root_key = os.path.normcase(os.path.normpath(str(root)))
    candidate_key = os.path.normcase(os.path.normpath(str(candidate)))
    return candidate_key == root_key or candidate_key.startswith(root_key + os.sep)


def validate_filename(name: str) -> str:
    """Reject a name that would escape the folder or hit a reserved Windows name."""
    if name in {"", ".", ".."} or "/" in name or "\\" in name or "\x00" in name:
        raise PathValidationError("Nama file tidak valid")
    if name.rstrip(" .") != name:
        raise PathValidationError("Nama file yang berakhiran spasi atau titik tidak dipindahkan")
    stem = name.split(".", 1)[0].upper()
    if stem in _RESERVED_NAMES:
        raise PathValidationError("Nama file dicadangkan oleh Windows")
    return name


def validate_scan_root(path: Path) -> Path:
    """Return the resolved directory when it is safe to scan."""
    candidate = Path(path)
    raw = str(candidate).replace("/", "\\").rstrip("\\")
    if len(raw) == 2 and raw[1] == ":":
        raise PathValidationError("NEXUS tidak memindai seluruh drive")
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate

    try:
        candidate.lstat()
    except FileNotFoundError:
        raise
    except PermissionError:
        raise

    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise PathValidationError("Folder sumber tidak bisa dibuka") from exc

    if is_drive_root(resolved):
        raise PathValidationError("NEXUS tidak memindai seluruh drive")
    if is_blocked_system_path(resolved):
        raise PathValidationError("NEXUS tidak mengakses folder Windows atau sistem")
    try:
        is_directory = resolved.is_dir()
    except PermissionError:
        raise
    except OSError as exc:
        raise PathValidationError("Folder sumber tidak bisa dibuka") from exc
    if not is_directory:
        raise PathValidationError("Folder sumber harus berupa direktori")
    return resolved


def ensure_inside(root: Path, candidate: Path) -> Path:
    """Resolve ``candidate`` and require it to stay inside an already validated root."""
    target = Path(candidate)
    if not target.is_absolute():
        target = root / target
    if is_reparse_point(target):
        raise PathValidationError("Symbolic link atau junction tidak dipindahkan")
    _reject_nested_reparse(root, target)
    try:
        resolved = target.resolve()
    except OSError as exc:
        raise PathValidationError("Lokasi tidak bisa dibuka") from exc
    if is_drive_root(resolved) or is_blocked_system_path(resolved):
        raise PathValidationError("Lokasi berada di folder sistem")
    if not is_inside(root, resolved):
        raise PathValidationError("Lokasi berada di luar folder yang diizinkan")
    return resolved


def resolve_inside(root: Path, candidate: Path) -> Path:
    """Validate ``root``, then require ``candidate`` to stay inside it."""
    return ensure_inside(validate_scan_root(root), candidate)


def infer_scan_root(paths: list[Path]) -> Path | None:
    """Return the folder that contains every file. A drive root is rejected."""
    if not paths:
        return None
    try:
        common = Path(os.path.commonpath([str(path.parent) for path in paths]))
    except ValueError:
        return None
    try:
        return validate_scan_root(common)
    except (OSError, PathValidationError):
        return None


def _matches_blocked(path: Path) -> bool:
    candidate = os.path.normcase(os.path.normpath(str(path)))
    for blocked in blocked_system_roots():
        root = os.path.normcase(os.path.normpath(str(blocked)))
        if candidate == root or candidate.startswith(root + os.sep):
            return True
    return False


def _reject_nested_reparse(root: Path, candidate: Path) -> None:
    """Reject a junction under the source. The source folder itself may be a junction."""
    current = candidate
    while not paths_equal(current, root):
        if current.exists() and is_reparse_point(current):
            raise PathValidationError("Jalur melewati symbolic link atau junction")
        parent = current.parent
        if parent == current:
            return
        current = parent
