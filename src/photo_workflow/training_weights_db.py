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
    """Create the training tables if they don't exist.

    genre_prototypes, genre_adapter_linear, aesthetic_weights. Idempotent.
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

    -- Learned linear genre classifier (one row per axis: 'subject' / 'type').
    -- logits = clip_embedding @ weight.T + bias  ->  softmax over `classes`.
    CREATE TABLE IF NOT EXISTS genre_adapter_linear (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version INTEGER NOT NULL,
        axis TEXT NOT NULL,
        classes TEXT NOT NULL,
        weight BLOB NOT NULL,
        bias BLOB NOT NULL,
        dim INTEGER NOT NULL,
        n_samples INTEGER,
        cv_accuracy REAL,
        created_at TEXT DEFAULT (datetime('now')),
        is_active INTEGER DEFAULT 1,
        UNIQUE(version, axis)
    );

    -- Per-genre aesthetic scoring weights. One row per (axis, label); `weights`
    -- is a JSON map {sub_score_key: weight} the score fuser applies to combine
    -- sub-scores into the master score. axis is 'subject' or 'type'; the fuser
    -- blends the two axes' active profiles. Tunable / learnable; falls back to
    -- the hardcoded score_fusion defaults when absent.
    CREATE TABLE IF NOT EXISTS aesthetic_weights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version INTEGER NOT NULL,
        axis TEXT NOT NULL,
        label TEXT NOT NULL,
        weights TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        is_active INTEGER DEFAULT 1,
        UNIQUE(version, axis, label)
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


def upsert_linear_adapter(
    conn: sqlite3.Connection,
    version: int,
    axis: str,
    classes: list[str],
    weight: np.ndarray,
    bias: np.ndarray,
    n_samples: int,
    cv_accuracy: float,
) -> None:
    """Store a learned linear classifier head for one axis ('subject'/'type')."""
    import json

    conn.execute("UPDATE genre_adapter_linear SET is_active=0 WHERE axis=? AND is_active=1", (axis,))
    conn.execute(
        """
        INSERT INTO genre_adapter_linear
            (version, axis, classes, weight, bias, dim, n_samples, cv_accuracy, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            version, axis, json.dumps(list(classes)),
            np.asarray(weight, dtype=np.float32).tobytes(),
            np.asarray(bias, dtype=np.float32).tobytes(),
            int(weight.shape[1]), int(n_samples), float(cv_accuracy),
        ),
    )
    conn.commit()


def get_active_linear_adapter(conn: sqlite3.Connection) -> dict[str, dict]:
    """Retrieve the active linear adapter heads keyed by axis.

    Returns {axis: {"classes": list[str], "weight": (n,dim) f32, "bias": (n,) f32,
                    "version": int}} — empty dict if none stored.
    """
    import json

    try:
        rows = conn.execute(
            "SELECT axis, classes, weight, bias, dim, version "
            "FROM genre_adapter_linear WHERE is_active=1"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    out: dict[str, dict] = {}
    for row in rows:
        dim = row["dim"]
        w = np.frombuffer(row["weight"], dtype=np.float32).reshape(-1, dim)
        b = np.frombuffer(row["bias"], dtype=np.float32)
        out[row["axis"]] = {
            "classes": json.loads(row["classes"]),
            "weight": w,
            "bias": b,
            "version": row["version"],
        }
    return out


def next_aesthetic_weights_version(conn: sqlite3.Connection) -> int:
    """Next version number for the aesthetic_weights table (highest + 1, or 1)."""
    try:
        row = conn.execute("SELECT MAX(version) AS v FROM aesthetic_weights").fetchone()
    except sqlite3.OperationalError:
        return 1
    if row and row["v"] is not None:
        return row["v"] + 1
    return 1


def upsert_aesthetic_weights(
    conn: sqlite3.Connection,
    version: int,
    axis: str,
    label: str,
    weights: dict[str, float],
) -> None:
    """Insert a per-genre aesthetic weight profile, deactivating the prior active one.

    Args:
        axis: 'subject' or 'type'.
        label: genre label (e.g. 'portrait', 'landscape').
        weights: {sub_score_key: weight}.
    """
    import json

    conn.execute(
        "UPDATE aesthetic_weights SET is_active=0 WHERE axis=? AND label=? AND is_active=1",
        (axis, label),
    )
    conn.execute(
        "INSERT INTO aesthetic_weights (version, axis, label, weights, is_active) "
        "VALUES (?, ?, ?, ?, 1)",
        (version, axis, label, json.dumps({k: float(v) for k, v in weights.items()})),
    )
    conn.commit()


def get_active_aesthetic_weights(conn: sqlite3.Connection) -> dict[str, dict[str, dict[str, float]]]:
    """Retrieve active aesthetic weight profiles, grouped by axis.

    Returns {'subject': {label: {key: weight}}, 'type': {label: {key: weight}}}.
    Empty dict if the table is absent or unpopulated.
    """
    import json

    try:
        rows = conn.execute(
            "SELECT axis, label, weights FROM aesthetic_weights WHERE is_active=1"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    out: dict[str, dict[str, dict[str, float]]] = {}
    for row in rows:
        out.setdefault(row["axis"], {})[row["label"]] = json.loads(row["weights"])
    return out


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
