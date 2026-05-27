"""Database operations for photonforge.db and Darktable library.db.

All mutations run inside transactions. On filesystem failure, callers
should rollback via the returned connection.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path


def sanitize_table_name(name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return sanitized or "default"


# -- Column schema (mirrors photondb.ensure_table) --

_COLUMNS = [
    ("filename", "TEXT PRIMARY KEY"),
    ("original_name", "TEXT NOT NULL"),
    ("exif_timestamp", "TEXT"),
    ("session_id", "TEXT DEFAULT ''"),
    ("is_duplicate", "INTEGER DEFAULT 0"),
    ("sharpness", "REAL"),
    ("composition", "REAL"),
    ("exposure", "REAL"),
    ("semantic_name", "TEXT DEFAULT ''"),
    ("stages", "TEXT DEFAULT ''"),
    ("error", "TEXT DEFAULT ''"),
    ("genre", "TEXT DEFAULT ''"),
    ("genre_confidence", "REAL DEFAULT 0.0"),
    ("master_score", "REAL DEFAULT 0.0"),
    ("sub_scores", "TEXT DEFAULT ''"),
    ("dhash", "TEXT DEFAULT ''"),
    ("genres", "TEXT DEFAULT ''"),
    ("primary_genre", "TEXT DEFAULT ''"),
    ("needs_review", "INTEGER DEFAULT 0"),
    ("clip_embedding", "BLOB"),
]

_COLUMN_NAMES = [c[0] for c in _COLUMNS]


def _create_table_sql(table: str) -> str:
    cols = ", ".join(f"{name} {typedef}" for name, typedef in _COLUMNS)
    return f"CREATE TABLE IF NOT EXISTS [{table}] ({cols})"


# -- Connection helpers --


def open_photondb(cartridge_root: Path) -> sqlite3.Connection:
    db_path = cartridge_root / "photonforge.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA foreign_keys=ON")
    # Migrate existing tables to ensure all columns are present
    _migrate_all_tables(conn)
    return conn


def _migrate_all_tables(conn: sqlite3.Connection) -> None:
    """Add missing columns to all existing tables (safe to call repeatedly)."""
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    # Columns that may be missing from older tables, with their defaults
    migrations = [
        ("session_id", "TEXT DEFAULT ''"),
        ("genre", "TEXT DEFAULT ''"),
        ("genre_confidence", "REAL DEFAULT 0.0"),
        ("master_score", "REAL DEFAULT 0.0"),
        ("sub_scores", "TEXT DEFAULT ''"),
        ("dhash", "TEXT DEFAULT ''"),
        ("genres", "TEXT DEFAULT ''"),
        ("primary_genre", "TEXT DEFAULT ''"),
        ("needs_review", "INTEGER DEFAULT 0"),
        ("clip_embedding", "BLOB"),
    ]
    for table in tables:
        for col_name, col_def in migrations:
            try:
                conn.execute(f"ALTER TABLE [{table}] ADD COLUMN {col_name} {col_def}")
            except sqlite3.OperationalError:
                pass  # Column already exists
    conn.commit()


def open_darktable_db(cartridge_root: Path) -> sqlite3.Connection:
    db_path = cartridge_root / "darktable" / "library.db"
    if not db_path.exists():
        raise FileNotFoundError(f"Darktable library.db not found: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    data_db = cartridge_root / "darktable" / "data.db"
    if data_db.exists():
        conn.execute("ATTACH DATABASE ? AS data", (str(data_db),))
    return conn


# -- Table discovery --


def list_tables(conn: sqlite3.Connection) -> list[str]:
    """Return all user-created table names in photonforge.db."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [r["name"] for r in rows]


@dataclass
class TableInfo:
    name: str
    photo_count: int
    has_scored: int
    has_named: int


def get_table_info(conn: sqlite3.Connection, table: str) -> TableInfo:
    safe = sanitize_table_name(table)
    total = conn.execute(f"SELECT COUNT(*) as c FROM [{safe}]").fetchone()["c"]
    scored = conn.execute(
        f"SELECT COUNT(*) as c FROM [{safe}] WHERE stages LIKE '%score%'"
    ).fetchone()["c"]
    named = conn.execute(
        f"SELECT COUNT(*) as c FROM [{safe}] WHERE stages LIKE '%name%'"
    ).fetchone()["c"]
    return TableInfo(name=table, photo_count=total, has_scored=scored, has_named=named)


# -- Table creation --


def create_table(conn: sqlite3.Connection, folder_name: str) -> str:
    """Create a new folder-table. Returns the sanitized table name."""
    safe = sanitize_table_name(folder_name)
    conn.execute(_create_table_sql(safe))
    conn.commit()
    return safe


# -- Row operations --


def get_all_rows(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    safe = sanitize_table_name(table)
    return conn.execute(f"SELECT * FROM [{safe}]").fetchall()


def get_row(conn: sqlite3.Connection, table: str, filename: str) -> sqlite3.Row | None:
    safe = sanitize_table_name(table)
    return conn.execute(
        f"SELECT * FROM [{safe}] WHERE filename=?", (filename,)
    ).fetchone()


def move_row(
    conn: sqlite3.Connection,
    src_table: str,
    dst_table: str,
    filename: str,
) -> None:
    """Move a photo row between tables in a single transaction.

    The destination table must already exist.
    """
    src = sanitize_table_name(src_table)
    dst = sanitize_table_name(dst_table)
    row = conn.execute(f"SELECT * FROM [{src}] WHERE filename=?", (filename,)).fetchone()
    if row is None:
        raise ValueError(f"Photo {filename} not found in table {src}")

    placeholders = ", ".join("?" for _ in _COLUMN_NAMES)
    col_list = ", ".join(_COLUMN_NAMES)
    values = [row[c] for c in _COLUMN_NAMES]

    conn.execute("BEGIN")
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO [{dst}] ({col_list}) VALUES ({placeholders})",
            values,
        )
        conn.execute(f"DELETE FROM [{src}] WHERE filename=?", (filename,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def copy_row(
    conn: sqlite3.Connection,
    src_table: str,
    dst_table: str,
    filename: str,
) -> None:
    """Copy a photo row to another table (for test datasets)."""
    src = sanitize_table_name(src_table)
    dst = sanitize_table_name(dst_table)
    row = conn.execute(f"SELECT * FROM [{src}] WHERE filename=?", (filename,)).fetchone()
    if row is None:
        raise ValueError(f"Photo {filename} not found in table {src}")

    placeholders = ", ".join("?" for _ in _COLUMN_NAMES)
    col_list = ", ".join(_COLUMN_NAMES)
    values = [row[c] for c in _COLUMN_NAMES]
    conn.execute(
        f"INSERT OR IGNORE INTO [{dst}] ({col_list}) VALUES ({placeholders})",
        values,
    )
    conn.commit()


def delete_table(conn: sqlite3.Connection, table: str) -> None:
    safe = sanitize_table_name(table)
    conn.execute(f"DROP TABLE IF EXISTS [{safe}]")
    conn.commit()


# -- Darktable folder updates --


def update_darktable_folder(
    dt_conn: sqlite3.Connection,
    filename: str,
    new_folder: str,
) -> None:
    """Update the folder field for an image in Darktable's library.db."""
    dt_conn.execute(
        "UPDATE images SET folder=? WHERE filename=?",
        (new_folder, filename),
    )
    dt_conn.commit()


def darktable_image_exists(dt_conn: sqlite3.Connection, filename: str) -> bool:
    row = dt_conn.execute(
        "SELECT id FROM images WHERE filename=?", (filename,)
    ).fetchone()
    return row is not None
