"""Open short-lived SQLite connections. Each call owns its own connection."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


@contextmanager
def sqlite_connection(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a connection that commits on success and always closes."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_schema(db_path: Path) -> None:
    """Create missing tables. Existing Phase 1 rows are left in place."""
    schema = _SCHEMA_PATH.read_text(encoding="utf-8")
    with sqlite_connection(db_path) as connection:
        connection.executescript(schema)
        _migrate_file_operations(connection)


def _migrate_file_operations(connection: sqlite3.Connection) -> None:
    """Add Phase 2 operation statuses without dropping existing history.

    ``CREATE TABLE IF NOT EXISTS`` cannot change a check constraint or add a
    column on a database created before ``error_message`` existed. Rows are
    copied, then the old table is replaced. ``system_metrics`` and
    ``process_metrics`` are not rewritten.
    """
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'file_operations'"
    ).fetchone()
    if row is None:
        return
    columns = [info[1] for info in connection.execute("PRAGMA table_info(file_operations)")]
    create_sql = row["sql"] or ""
    if "pending" in create_sql and "error_message" in columns:
        return

    error_select = "error_message" if "error_message" in columns else "NULL"
    connection.execute("DROP TABLE IF EXISTS file_operations_next")
    connection.execute(
        """
        CREATE TABLE file_operations_next (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL,
            destination_path TEXT NOT NULL,
            operation_type TEXT NOT NULL CHECK (operation_type IN ('move', 'undo')),
            status TEXT NOT NULL CHECK (status IN (
                'pending', 'success', 'failed', 'undo_pending', 'undone', 'recovery_required'
            )),
            created_at TEXT NOT NULL,
            completed_at TEXT,
            error_message TEXT
        )
        """
    )
    connection.execute(
        f"""
        INSERT INTO file_operations_next (
            id, source_path, destination_path, operation_type,
            status, created_at, completed_at, error_message
        )
        SELECT id, source_path, destination_path, operation_type,
               status, created_at, completed_at, {error_select}
        FROM file_operations
        """
    )
    connection.execute("DROP TABLE file_operations")
    connection.execute("ALTER TABLE file_operations_next RENAME TO file_operations")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_file_operations_status ON file_operations (status)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_file_operations_created_at ON file_operations (created_at)"
    )
    max_id = connection.execute("SELECT MAX(id) FROM file_operations").fetchone()[0]
    sequence = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'"
    ).fetchone()
    if sequence is not None:
        connection.execute(
            "DELETE FROM sqlite_sequence WHERE name IN ('file_operations', 'file_operations_next')"
        )
        if max_id:
            connection.execute(
                "INSERT INTO sqlite_sequence (name, seq) VALUES ('file_operations', ?)",
                (max_id,),
            )
