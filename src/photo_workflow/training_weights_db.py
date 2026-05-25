"""Training weights database — stores genre prototypes, corrections, and adapters."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np


def open_training_db(path: Path) -> sqlite3.Connection:
    """Open or create a training weights database.

    Args:
        path: Path to the training_weights.db file.

    Returns:
        An open sqlite3.Connection with row factory set to sqlite3.Row.
    """
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create all four training tables if they don't exist.

    Idempotent: safe to call multiple times.
    """
    conn.executescript(
        """
    CREATE TABLE IF NOT EXISTS genre_prototypes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version INTEGER NOT NULL,
        genre TEXT NOT NULL,
        prototype BLOB NOT NULL,
        n_corrections INTEGER DEFAULT 0,
        alpha REAL DEFAULT 1.0,
        created_at TEXT DEFAULT (datetime('now')),
        is_active INTEGER DEFAULT 1,
        UNIQUE(version, genre)
    );

    CREATE TABLE IF NOT EXISTS genre_corrections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        image_path TEXT NOT NULL,
        clip_embedding BLOB NOT NULL,
        aux_features BLOB,
        original_genres TEXT NOT NULL,
        corrected_genres TEXT NOT NULL,
        correction_source TEXT DEFAULT 'darktable',
        corrected_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS genre_adapter (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version INTEGER NOT NULL,
        model_onnx BLOB NOT NULL,
        n_training_samples INTEGER,
        f1_score REAL,
        created_at TEXT DEFAULT (datetime('now')),
        is_active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS custom_genres (
        name TEXT PRIMARY KEY,
        first_seen_at TEXT DEFAULT (datetime('now')),
        n_examples INTEGER DEFAULT 0,
        promoted INTEGER DEFAULT 0
    );
    """
    )
    conn.commit()


def next_version(conn: sqlite3.Connection) -> int:
    """Get the next version number for prototypes.

    Returns the highest existing version + 1, or 1 if no versions exist yet.
    """
    cursor = conn.execute("SELECT MAX(version) as max_version FROM genre_prototypes")
    row = cursor.fetchone()
    if row and row["max_version"] is not None:
        return row["max_version"] + 1
    return 1


def upsert_prototype(
    conn: sqlite3.Connection,
    version: int,
    genre: str,
    prototype_bytes: bytes,
    n_corrections: int,
    alpha: float,
) -> None:
    """Insert or update a genre prototype.

    Marks any previous active row for this genre as inactive (is_active=0),
    then inserts the new row with is_active=1.

    Args:
        conn: sqlite3.Connection to training_weights.db
        version: Version number (should be next_version() result)
        genre: Genre name (e.g., 'wildlife')
        prototype_bytes: Raw float32 numpy array bytes (512 dims)
        n_corrections: Number of corrections used in blending
        alpha: Blend factor (1.0=hardcoded, 0.3=mostly learned)
    """
    # Deactivate any previous active prototype for this genre
    conn.execute(
        "UPDATE genre_prototypes SET is_active=0 WHERE genre=? AND is_active=1",
        (genre,),
    )
    # Insert the new active prototype
    conn.execute(
        """
        INSERT INTO genre_prototypes (version, genre, prototype, n_corrections, alpha, is_active)
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        (version, genre, prototype_bytes, n_corrections, alpha),
    )
    conn.commit()


def get_active_prototypes(conn: sqlite3.Connection) -> dict[str, dict]:
    """Retrieve all active genre prototypes.

    Returns:
        dict mapping genre name to {
            "prototype": np.ndarray (512,) float32,
            "version": int,
            "n_corrections": int,
            "alpha": float
        }
    """
    cursor = conn.execute(
        """
        SELECT genre, prototype, version, n_corrections, alpha
        FROM genre_prototypes
        WHERE is_active=1
        ORDER BY genre
        """
    )
    result = {}
    for row in cursor.fetchall():
        genre = row["genre"]
        prototype_array = np.frombuffer(row["prototype"], dtype=np.float32)
        result[genre] = {
            "prototype": prototype_array,
            "version": row["version"],
            "n_corrections": row["n_corrections"],
            "alpha": row["alpha"],
        }
    return result


def rollback_to_version(conn: sqlite3.Connection, version: int) -> None:
    """Rollback to a specific version.

    Sets is_active=1 for the specified version and is_active=0 for any later versions.

    Args:
        conn: sqlite3.Connection to training_weights.db
        version: Version number to revert to
    """
    conn.execute(
        "UPDATE genre_prototypes SET is_active=1 WHERE version=?",
        (version,),
    )
    conn.execute(
        "UPDATE genre_prototypes SET is_active=0 WHERE version>?",
        (version,),
    )
    conn.commit()
