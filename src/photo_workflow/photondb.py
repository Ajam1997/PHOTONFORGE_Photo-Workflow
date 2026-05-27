"""SQLite-backed pipeline stage tracker — replaces JSONL manifest."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path


def sanitize_table_name(name: str) -> str:
    """Convert a folder name to a valid SQLite table name."""
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not sanitized:
        return "default"
    return sanitized


def _db_path_from_dest(dest: Path) -> Path:
    """Derive photonforge.db path at the parent of dest (the cartridge root)."""
    return dest.parent / "photonforge.db"


def open_db(dest_path: Path) -> sqlite3.Connection:
    """Open or create photonforge.db at the drive root of dest_path."""
    db_file = _db_path_from_dest(dest_path)
    # Ensure parent directory exists, but don't fail if it's a drive root
    try:
        db_file.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError):
        # Parent is likely a drive root or permission denied; trust sqlite3 can write
        pass
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=DELETE")
    return conn


def ensure_table(conn: sqlite3.Connection, table: str) -> None:
    """Create the per-folder table if it doesn't exist."""
    table = sanitize_table_name(table)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS [{table}] (
            filename       TEXT PRIMARY KEY,
            original_name  TEXT NOT NULL,
            exif_timestamp TEXT,
            session_id     TEXT DEFAULT '',
            is_duplicate   INTEGER DEFAULT 0,
            sharpness      REAL,
            composition    REAL,
            exposure       REAL,
            semantic_name  TEXT DEFAULT '',
            stages         TEXT DEFAULT '',
            error          TEXT DEFAULT '',
            genre          TEXT DEFAULT '',
            genre_confidence REAL DEFAULT 0.0,
            master_score   REAL DEFAULT 0.0,
            sub_scores     TEXT DEFAULT '',
            dhash          TEXT DEFAULT ''
        )
    """)
    conn.commit()

    # Migration: add new columns to existing tables
    try:
        conn.execute(f"ALTER TABLE [{table}] ADD COLUMN genre TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        conn.execute(f"ALTER TABLE [{table}] ADD COLUMN genre_confidence REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(f"ALTER TABLE [{table}] ADD COLUMN master_score REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(f"ALTER TABLE [{table}] ADD COLUMN sub_scores TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(f"ALTER TABLE [{table}] ADD COLUMN dhash TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(f"ALTER TABLE [{table}] ADD COLUMN genres TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(f"ALTER TABLE [{table}] ADD COLUMN primary_genre TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(f"ALTER TABLE [{table}] ADD COLUMN needs_review INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(f"ALTER TABLE [{table}] ADD COLUMN clip_embedding BLOB")
    except sqlite3.OperationalError:
        pass
    conn.commit()


def insert_photo(
    conn: sqlite3.Connection,
    table: str,
    filename: str,
    original_name: str,
    exif_timestamp: str | None,
    *,
    auto_commit: bool = True,
) -> None:
    """Insert a photo row. Ignores if filename already exists."""
    table = sanitize_table_name(table)
    conn.execute(
        f"INSERT OR IGNORE INTO [{table}] (filename, original_name, exif_timestamp) VALUES (?, ?, ?)",
        (filename, original_name, exif_timestamp),
    )
    if auto_commit:
        conn.commit()


def update_stages(
    conn: sqlite3.Connection, table: str, filename: str, stage: str,
    *, auto_commit: bool = True,
) -> None:
    """Append a stage to the stages column if not already present."""
    table = sanitize_table_name(table)
    row = conn.execute(f"SELECT stages FROM [{table}] WHERE filename=?", (filename,)).fetchone()
    if row is None:
        return
    current = row["stages"] or ""
    parts = [s for s in current.split(",") if s]
    if stage not in parts:
        parts.append(stage)
    conn.execute(
        f"UPDATE [{table}] SET stages=? WHERE filename=?",
        (",".join(parts), filename),
    )
    if auto_commit:
        conn.commit()


def get_pending(conn: sqlite3.Connection, table: str, stage: str) -> list[sqlite3.Row]:
    """Return rows that do NOT have the given stage in their stages column."""
    table = sanitize_table_name(table)
    rows = conn.execute(f"SELECT * FROM [{table}]").fetchall()
    return [r for r in rows if stage not in (r["stages"] or "").split(",")]


def update_scores(
    conn: sqlite3.Connection,
    table: str,
    filename: str,
    sharpness: float,
    composition: float,
    exposure: float,
    *,
    auto_commit: bool = True,
) -> None:
    """Write scoring results."""
    table = sanitize_table_name(table)
    conn.execute(
        f"UPDATE [{table}] SET sharpness=?, composition=?, exposure=? WHERE filename=?",
        (sharpness, composition, exposure, filename),
    )
    if auto_commit:
        conn.commit()


def update_semantic(
    conn: sqlite3.Connection, table: str, filename: str, semantic_name: str,
    *, auto_commit: bool = True,
) -> None:
    """Write Florence-2 semantic name."""
    table = sanitize_table_name(table)
    conn.execute(
        f"UPDATE [{table}] SET semantic_name=? WHERE filename=?",
        (semantic_name, filename),
    )
    if auto_commit:
        conn.commit()


def mark_duplicate(
    conn: sqlite3.Connection, table: str, filename: str,
    *, auto_commit: bool = True,
) -> None:
    """Set is_duplicate=1."""
    table = sanitize_table_name(table)
    conn.execute(
        f"UPDATE [{table}] SET is_duplicate=1 WHERE filename=?",
        (filename,),
    )
    if auto_commit:
        conn.commit()


def clear_stage(conn: sqlite3.Connection, table: str, stage: str) -> None:
    """Remove a stage from all rows (for --force mode)."""
    table = sanitize_table_name(table)
    rows = conn.execute(f"SELECT filename, stages FROM [{table}]").fetchall()
    for row in rows:
        parts = [s for s in (row["stages"] or "").split(",") if s and s != stage]
        conn.execute(
            f"UPDATE [{table}] SET stages=? WHERE filename=?",
            (",".join(parts), row["filename"]),
        )
    conn.commit()


def update_genre_scores(
    conn: sqlite3.Connection,
    table: str,
    filename: str,
    genre: str,
    genre_confidence: float,
    master_score: float,
    sub_scores: dict,
    *,
    genres: dict | None = None,
    primary_genre: str | None = None,
    needs_review: bool = False,
    clip_embedding: bytes | None = None,
    auto_commit: bool = True,
) -> None:
    """Write genre-aware scoring results including two-axis genre data.

    Args:
        conn: SQLite connection
        table: Table name
        filename: Filename to update
        genre: Subject (primary genre for backward compatibility)
        genre_confidence: Subject confidence
        master_score: Master score
        sub_scores: Sub-scores dictionary
        genres: Two-axis genre dict {subject, subject_confidence, photo_type, type_confidence}
        primary_genre: Primary genre (alias for genre column)
        needs_review: Whether image needs review (low-confidence fallback)
        clip_embedding: Raw bytes of CLIP embedding (float32 numpy array)
        auto_commit: Whether to auto-commit
    """
    import json
    table = sanitize_table_name(table)
    sub_scores_json = json.dumps(sub_scores) if sub_scores else ""

    genres_json = ""
    if genres:
        genres_json = json.dumps(genres)

    # Use primary_genre if provided, otherwise use genre
    primary_genre_val = primary_genre if primary_genre else genre

    conn.execute(
        f"UPDATE [{table}] SET genre=?, genre_confidence=?, master_score=?, sub_scores=?, "
        f"genres=?, primary_genre=?, needs_review=?, clip_embedding=? WHERE filename=?",
        (
            genre,
            genre_confidence,
            master_score,
            sub_scores_json,
            genres_json,
            primary_genre_val,
            1 if needs_review else 0,
            clip_embedding,
            filename,
        ),
    )
    if auto_commit:
        conn.commit()


def update_dhash(
    conn: sqlite3.Connection, table: str, filename: str, dhash: int,
    *, auto_commit: bool = True,
) -> None:
    """Write cached dHash value."""
    table = sanitize_table_name(table)
    conn.execute(
        f"UPDATE [{table}] SET dhash=? WHERE filename=?",
        (str(dhash), filename),
    )
    if auto_commit:
        conn.commit()


def get_dhashes(conn: sqlite3.Connection, table: str) -> dict[str, int]:
    """Return {filename: dhash_int} for all rows with a cached dHash."""
    table = sanitize_table_name(table)
    rows = conn.execute(f"SELECT filename, dhash FROM [{table}] WHERE dhash IS NOT NULL AND dhash != ''").fetchall()
    result: dict[str, int] = {}
    for row in rows:
        try:
            result[row["filename"]] = int(row["dhash"])
        except (ValueError, TypeError):
            pass
    return result
