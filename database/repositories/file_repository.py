"""Store scanned files and file operations. Hashes are written only when supplied."""

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from database.connection import initialize_schema, sqlite_connection
from modules.file_manager.models import FileOperation, ScannedFile

_INSERT_FILE = """
INSERT INTO scanned_files (
    file_path, file_name, extension, category, file_size, modified_at, sha256, scanned_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

_OPERATION_COLUMNS = """
id, source_path, destination_path, operation_type, status, created_at, completed_at, error_message
"""

_INSERT_OPERATION = """
INSERT INTO file_operations (
    source_path, destination_path, operation_type, status, created_at, completed_at, error_message
) VALUES (?, ?, ?, ?, ?, ?, ?)
"""

# 8 columns x 80 rows = 640 bound values, under SQLite's default limit of 999.
MAX_STATEMENT_ROWS = 80

_SORTS = {
    "size_desc": "file_size DESC, file_name COLLATE NOCASE ASC",
    "size_asc": "file_size ASC, file_name COLLATE NOCASE ASC",
    "date_desc": "modified_at DESC, file_name COLLATE NOCASE ASC",
    "date_asc": "modified_at ASC, file_name COLLATE NOCASE ASC",
    "name_asc": "file_name COLLATE NOCASE ASC",
}


class FileRepository:
    """SQLite storage for the latest scan and the move history."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        initialize_schema(db_path)

    def replace_scan(self, files: Sequence[ScannedFile], batch_size: int = 80) -> None:
        """Replace the stored scan. ``sha256`` is saved only when a file already has one."""
        rows = [_file_row(item) for item in files]
        with sqlite_connection(self.db_path) as connection:
            connection.execute("DELETE FROM scanned_files")
            for batch in _batches(rows, batch_size):
                connection.executemany(_INSERT_FILE, batch)

    def update_hashes(self, hashes: Sequence[tuple[str, str]], batch_size: int = 80) -> None:
        """Store hashes for the paths that were read. Other rows stay empty."""
        if not hashes:
            return
        with sqlite_connection(self.db_path) as connection:
            for batch in _batches(list(hashes), batch_size):
                connection.executemany(
                    "UPDATE scanned_files SET sha256 = ? WHERE file_path = ?",
                    [(digest, path) for path, digest in batch],
                )

    def list_files(
        self,
        *,
        category: str = "",
        search: str = "",
        sort: str = "size_desc",
        limit: int = 5000,
    ) -> list[ScannedFile]:
        """Return stored metadata. This does not walk the disk or hash files."""
        order = _SORTS.get(sort, _SORTS["size_desc"])
        clauses = ["1 = 1"]
        parameters: list[object] = []
        if category:
            clauses.append("category = ?")
            parameters.append(category)
        if search:
            clauses.append("file_name LIKE ? ESCAPE '\\'")
            parameters.append(_like(search))
        parameters.append(max(1, limit))
        query = f"""
            SELECT file_path, file_name, extension, category, file_size,
                   modified_at, sha256, scanned_at
            FROM scanned_files
            WHERE {' AND '.join(clauses)}
            ORDER BY {order}
            LIMIT ?
        """
        with sqlite_connection(self.db_path) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_file_from_row(row) for row in rows]

    def list_all(self) -> list[ScannedFile]:
        """Return every stored file, ordered by name."""
        return self.list_files(sort="name_asc", limit=100_000)

    def relocate_file(self, source: Path, destination: Path) -> None:
        """Point the stored scan at a file that was moved. The hash is kept."""
        with sqlite_connection(self.db_path) as connection:
            connection.execute(
                """
                UPDATE scanned_files
                SET file_path = ?, file_name = ?
                WHERE file_path = ?
                """,
                (str(destination), destination.name, str(source)),
            )

    def add_operation(
        self,
        source: Path | str,
        destination: Path | str,
        operation_type: str,
        status: str,
        created_at: datetime,
        completed_at: datetime | None,
        error_message: str | None = None,
    ) -> FileOperation:
        """Insert one move or undo row and return it."""
        created = _stamp(created_at)
        completed = None if completed_at is None else _stamp(completed_at)
        with sqlite_connection(self.db_path) as connection:
            cursor = connection.execute(
                _INSERT_OPERATION,
                (
                    str(source),
                    str(destination),
                    operation_type,
                    status,
                    created,
                    completed,
                    error_message,
                ),
            )
            operation_id = int(cursor.lastrowid)
        return self._require_operation(operation_id)

    def complete_move(
        self,
        operation_id: int,
        source: Path,
        destination: Path,
        completed_at: datetime,
    ) -> FileOperation:
        """Mark a pending move successful and point the scan at the new path."""
        completed = _stamp(completed_at)
        with sqlite_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE file_operations
                SET status = 'success', completed_at = ?, error_message = NULL
                WHERE id = ? AND operation_type = 'move' AND status = 'pending'
                """,
                (completed, operation_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Operasi pending tidak bisa diselesaikan")
            connection.execute(
                """
                UPDATE scanned_files
                SET file_path = ?, file_name = ?
                WHERE file_path = ?
                """,
                (str(destination), destination.name, str(source)),
            )
        return self._require_operation(operation_id)

    def fail_operation(
        self,
        operation_id: int,
        message: str,
        completed_at: datetime,
    ) -> FileOperation:
        """Mark a pending move as failed. The file is not touched here."""
        with sqlite_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE file_operations
                SET status = 'failed', completed_at = ?, error_message = ?
                WHERE id = ? AND operation_type = 'move' AND status = 'pending'
                """,
                (_stamp(completed_at), message, operation_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Operasi pending tidak bisa ditandai gagal")
        return self._require_operation(operation_id)

    def begin_undo(self, operation_id: int) -> FileOperation:
        """Commit undo_pending before the file is returned."""
        with sqlite_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE file_operations
                SET status = 'undo_pending', error_message = NULL
                WHERE id = ? AND operation_type = 'move' AND status = 'success'
                """,
                (operation_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("Undo hanya untuk pemindahan yang berhasil.")
        return self._require_operation(operation_id)

    def abort_undo(
        self,
        operation_id: int,
        message: str,
        created_at: datetime,
    ) -> FileOperation:
        """Restore a move to success and store a failed undo. No file is moved."""
        created = _stamp(created_at)
        completed = _stamp(datetime.now())
        with sqlite_connection(self.db_path) as connection:
            original = connection.execute(
                f"SELECT {_OPERATION_COLUMNS} FROM file_operations WHERE id = ?",
                (operation_id,),
            ).fetchone()
            cursor = connection.execute(
                """
                UPDATE file_operations
                SET status = 'success', error_message = NULL
                WHERE id = ? AND operation_type = 'move' AND status = 'undo_pending'
                """,
                (operation_id,),
            )
            if original is None or cursor.rowcount != 1:
                raise ValueError("Undo tertunda tidak bisa dibatalkan")
            inserted = connection.execute(
                _INSERT_OPERATION,
                (
                    original["destination_path"],
                    original["source_path"],
                    "undo",
                    "failed",
                    created,
                    completed,
                    message,
                ),
            )
            undo_id = int(inserted.lastrowid)
        return self._require_operation(undo_id)

    def restore_successful_move(self, operation_id: int) -> FileOperation:
        """Return an interrupted undo to success when the file never moved back."""
        with sqlite_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE file_operations
                SET status = 'success', error_message = NULL
                WHERE id = ? AND operation_type = 'move' AND status = 'undo_pending'
                """,
                (operation_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("Undo tertunda tidak bisa dipulihkan")
        return self._require_operation(operation_id)

    def mark_recovery_required(
        self,
        operation_id: int,
        message: str,
        completed_at: datetime,
    ) -> FileOperation:
        """Record that a person must decide. This does not change any file."""
        with sqlite_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE file_operations
                SET status = 'recovery_required', completed_at = ?, error_message = ?
                WHERE id = ? AND status IN ('pending', 'undo_pending')
                """,
                (_stamp(completed_at), message, operation_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Operasi tidak bisa ditandai untuk pemulihan")
        return self._require_operation(operation_id)

    def complete_undo(
        self,
        operation_id: int,
        source: Path,
        destination: Path,
        created_at: datetime,
    ) -> FileOperation:
        """Mark an undo_pending move as undone and update the scan in one transaction."""
        completed_at = datetime.now()
        created = _stamp(created_at)
        completed = _stamp(completed_at)
        with sqlite_connection(self.db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE file_operations
                SET status = 'undone', completed_at = ?, error_message = NULL
                WHERE id = ? AND status = 'undo_pending' AND operation_type = 'move'
                """,
                (completed, operation_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Operasi tidak bisa diurungkan")
            inserted = connection.execute(
                _INSERT_OPERATION,
                (str(source), str(destination), "undo", "success", created, completed, None),
            )
            connection.execute(
                """
                UPDATE scanned_files
                SET file_path = ?, file_name = ?
                WHERE file_path = ?
                """,
                (str(destination), destination.name, str(source)),
            )
            undo_id = int(inserted.lastrowid)
        return self._require_operation(undo_id)

    def get_operation(self, operation_id: int) -> FileOperation | None:
        """Return one operation, or None when the id is missing."""
        with sqlite_connection(self.db_path) as connection:
            row = connection.execute(
                f"SELECT {_OPERATION_COLUMNS} FROM file_operations WHERE id = ?",
                (operation_id,),
            ).fetchone()
        if row is None:
            return None
        return _operation_from_row(row)

    def list_operations(self, limit: int = 100) -> list[FileOperation]:
        """Return the newest operations first. This list is for display only."""
        with sqlite_connection(self.db_path) as connection:
            rows = connection.execute(
                f"""
                SELECT {_OPERATION_COLUMNS}
                FROM file_operations
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
        return [_operation_from_row(row) for row in rows]

    def list_open_operations(self) -> list[FileOperation]:
        """Return moves whose file action and database row may still disagree."""
        with sqlite_connection(self.db_path) as connection:
            rows = connection.execute(
                f"""
                SELECT {_OPERATION_COLUMNS}
                FROM file_operations
                WHERE operation_type = 'move' AND status IN ('pending', 'undo_pending')
                ORDER BY id ASC
                """
            ).fetchall()
        return [_operation_from_row(row) for row in rows]

    def list_undoable_moves(
        self,
        *,
        search: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[FileOperation], int]:
        """Return successful moves, independent of the history display limit."""
        clauses = ["operation_type = 'move'", "status = 'success'"]
        parameters: list[object] = []
        if search:
            clauses.append("(source_path LIKE ? ESCAPE '\\' OR destination_path LIKE ? ESCAPE '\\')")
            pattern = _like(search)
            parameters.extend((pattern, pattern))
        where = " AND ".join(clauses)
        with sqlite_connection(self.db_path) as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM file_operations WHERE {where}",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT {_OPERATION_COLUMNS}
                FROM file_operations
                WHERE {where}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, max(1, limit), max(0, offset)],
            ).fetchall()
        return [_operation_from_row(row) for row in rows], total

    def _require_operation(self, operation_id: int) -> FileOperation:
        operation = self.get_operation(operation_id)
        if operation is None:
            raise ValueError("Operasi tidak ditemukan.")
        return operation


def _stamp(value: datetime) -> str:
    """ISO-8601 without fractions so text comparison matches time order."""
    return value.replace(microsecond=0).isoformat(timespec="seconds")


def _file_row(item: ScannedFile) -> tuple:
    scanned_at = item.scanned_at or datetime.now()
    return (
        str(item.file_path),
        item.file_name,
        item.extension,
        item.category,
        int(item.file_size),
        _stamp(item.modified_at),
        item.sha256,
        _stamp(scanned_at),
    )


def _file_from_row(row) -> ScannedFile:
    return ScannedFile(
        file_path=Path(row["file_path"]),
        file_name=row["file_name"],
        extension=row["extension"],
        category=row["category"],
        file_size=int(row["file_size"]),
        modified_at=datetime.fromisoformat(row["modified_at"]),
        sha256=row["sha256"],
        scanned_at=datetime.fromisoformat(row["scanned_at"]),
    )


def _operation_from_row(row) -> FileOperation:
    return FileOperation(
        id=int(row["id"]),
        source_path=row["source_path"],
        destination_path=row["destination_path"],
        operation_type=row["operation_type"],
        status=row["status"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        error_message=row["error_message"],
    )


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _batches(items: Sequence, batch_size: int):
    """Yield slices small enough for SQLite's variable limit."""
    size = max(1, min(int(batch_size), MAX_STATEMENT_ROWS))
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
