"""Records shared by the file organizer. These objects do not touch disk."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class ScannedFile:
    """Metadata for one file. ``sha256`` stays empty until a duplicate check."""

    file_path: Path
    file_name: str
    extension: str
    file_size: int
    modified_at: datetime
    category: str = ""
    sha256: str | None = None
    scanned_at: datetime | None = None


@dataclass(frozen=True)
class ScanError:
    """A file or folder the scanner could not read."""

    path: str
    message: str


@dataclass(frozen=True)
class ScanResult:
    """One requested scan. ``completed`` is false when the root could not be opened."""

    root: str
    files: tuple[ScannedFile, ...]
    errors: tuple[ScanError, ...]
    truncated: bool
    completed: bool


@dataclass(frozen=True)
class MovePlan:
    """A proposed move. Creating a plan does not move the file."""

    source_path: Path
    destination_path: Path
    category: str
    file_name: str
    file_size: int
    conflict: bool
    conflict_reason: str
    already_organized: bool


@dataclass(frozen=True)
class DuplicateGroup:
    """Files whose contents hashed to the same SHA-256."""

    sha256: str
    file_size: int
    files: tuple[ScannedFile, ...]


@dataclass(frozen=True)
class DuplicateReport:
    """Groups plus the hashes that were actually computed."""

    groups: tuple[DuplicateGroup, ...]
    hashes: tuple[tuple[str, str], ...]
    errors: tuple[ScanError, ...]


@dataclass(frozen=True)
class FileOperation:
    """One row from file_operations."""

    id: int
    source_path: str
    destination_path: str
    operation_type: str
    status: str
    created_at: str
    completed_at: str | None
    error_message: str | None = None


@dataclass(frozen=True)
class OperationResult:
    """The outcome of one move or undo, including a message for the dashboard."""

    operation: FileOperation | None
    message: str
    ok: bool
