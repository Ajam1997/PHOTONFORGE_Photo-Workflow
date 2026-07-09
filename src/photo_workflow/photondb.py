"""SQLite-backed pipeline stage tracker — replaces JSONL manifest.

Schema (single-table, since 2026-06): all analysis rows live in one ``photos``
table keyed by ``(folder, filename)``; ``folder`` is the ingest folder/session
that was previously a table name. A separate ``embeddings`` table caches CLIP
vectors for training corpora (the old CURATED/WEB tables). The public functions
still take a ``table`` argument — it is the folder value — so callers are
unchanged from the table-per-folder era.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path


def sanitize_table_name(name: str) -> str:
    """Normalize a folder name to a stable key (kept for backward compatibility).

    Historically this produced a SQLite table name; now it just yields the
    ``folder`` column value, but the same normalization is preserved so existing
    rows keep matching.
    """
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


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the single-table schema (photos + embeddings). Idempotent."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS photos (
            folder           TEXT NOT NULL,
            filename         TEXT NOT NULL,
            original_name    TEXT NOT NULL,
            exif_timestamp   TEXT,
            session_id       TEXT DEFAULT '',
            is_duplicate     INTEGER DEFAULT 0,
            sharpness        REAL,
            composition      REAL,
            exposure         REAL,
            semantic_name    TEXT DEFAULT '',
            stages           TEXT DEFAULT '',
            error            TEXT DEFAULT '',
            genre_confidence REAL DEFAULT 0.0,
            master_score     REAL DEFAULT 0.0,
            sub_scores       TEXT DEFAULT '',
            dhash            TEXT DEFAULT '',
            genres           TEXT DEFAULT '',
            primary_genre    TEXT DEFAULT '',
            needs_review     INTEGER DEFAULT 0,
            clip_embedding   BLOB,
            PRIMARY KEY (folder, filename)
        );
        CREATE INDEX IF NOT EXISTS idx_photos_folder ON photos(folder);

        -- CLIP embedding cache for training corpora (was the CURATED/WEB tables).
        -- `source` groups vectors (e.g. 'CURATED', 'WEB'); `ref` is the master
        -- RAW path or source URL the vector came from.
        CREATE TABLE IF NOT EXISTS embeddings (
            source         TEXT NOT NULL,
            filename       TEXT NOT NULL,
            clip_embedding BLOB NOT NULL,
            ref            TEXT DEFAULT '',
            PRIMARY KEY (source, filename)
        );
        """
    )
    conn.commit()


def ensure_table(conn: sqlite3.Connection, table: str | None = None) -> None:
    """Backward-compatible alias for :func:`ensure_schema`.

    The ``table`` argument is ignored — the schema is global now — but the
    signature is preserved so existing per-folder callers keep working.
    """
    ensure_schema(conn)


def insert_photo(
    conn: sqlite3.Connection,
    table: str,
    filename: str,
    original_name: str,
    exif_timestamp: str | None,
    *,
    auto_commit: bool = True,
) -> None:
    """Insert a photo row. Ignores if (folder, filename) already exists."""
    folder = sanitize_table_name(table)
    conn.execute(
        "INSERT OR IGNORE INTO photos (folder, filename, original_name, exif_timestamp) "
        "VALUES (?, ?, ?, ?)",
        (folder, filename, original_name, exif_timestamp),
    )
    if auto_commit:
        conn.commit()


def update_stages(
    conn: sqlite3.Connection, table: str, filename: str, stage: str,
    *, auto_commit: bool = True,
) -> None:
    """Append a stage to the stages column if not already present."""
    folder = sanitize_table_name(table)
    row = conn.execute(
        "SELECT stages FROM photos WHERE folder=? AND filename=?", (folder, filename)
    ).fetchone()
    if row is None:
        return
    current = row["stages"] or ""
    parts = [s for s in current.split(",") if s]
    if stage not in parts:
        parts.append(stage)
    conn.execute(
        "UPDATE photos SET stages=? WHERE folder=? AND filename=?",
        (",".join(parts), folder, filename),
    )
    if auto_commit:
        conn.commit()


def get_pending(conn: sqlite3.Connection, table: str, stage: str) -> list[sqlite3.Row]:
    """Return rows in this folder that do NOT have the given stage."""
    folder = sanitize_table_name(table)
    rows = conn.execute("SELECT * FROM photos WHERE folder=?", (folder,)).fetchall()
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
    folder = sanitize_table_name(table)
    conn.execute(
        "UPDATE photos SET sharpness=?, composition=?, exposure=? WHERE folder=? AND filename=?",
        (sharpness, composition, exposure, folder, filename),
    )
    if auto_commit:
        conn.commit()


def update_semantic(
    conn: sqlite3.Connection, table: str, filename: str, semantic_name: str,
    *, auto_commit: bool = True,
) -> None:
    """Write Florence-2 semantic name."""
    folder = sanitize_table_name(table)
    conn.execute(
        "UPDATE photos SET semantic_name=? WHERE folder=? AND filename=?",
        (semantic_name, folder, filename),
    )
    if auto_commit:
        conn.commit()


def clear_stage(conn: sqlite3.Connection, table: str, stage: str) -> None:
    """Remove a stage from all rows in this folder (for --force mode)."""
    folder = sanitize_table_name(table)
    rows = conn.execute(
        "SELECT filename, stages FROM photos WHERE folder=?", (folder,)
    ).fetchall()
    for row in rows:
        parts = [s for s in (row["stages"] or "").split(",") if s and s != stage]
        conn.execute(
            "UPDATE photos SET stages=? WHERE folder=? AND filename=?",
            (",".join(parts), folder, row["filename"]),
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

    The ``genre`` argument is the subject; it is stored only as ``primary_genre``
    (the redundant singular ``genre`` column was removed in the schema cleanup).
    """
    import json
    folder = sanitize_table_name(table)
    sub_scores_json = json.dumps(sub_scores) if sub_scores else ""
    genres_json = json.dumps(genres) if genres else ""
    primary_genre_val = primary_genre if primary_genre else genre

    conn.execute(
        "UPDATE photos SET genre_confidence=?, master_score=?, sub_scores=?, "
        "genres=?, primary_genre=?, needs_review=?, clip_embedding=? "
        "WHERE folder=? AND filename=?",
        (
            genre_confidence,
            master_score,
            sub_scores_json,
            genres_json,
            primary_genre_val,
            1 if needs_review else 0,
            clip_embedding,
            folder,
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
    folder = sanitize_table_name(table)
    conn.execute(
        "UPDATE photos SET dhash=? WHERE folder=? AND filename=?",
        (str(dhash), folder, filename),
    )
    if auto_commit:
        conn.commit()


def get_dhashes(conn: sqlite3.Connection, table: str) -> dict[str, int]:
    """Return {filename: dhash_int} for all rows in this folder with a cached dHash."""
    folder = sanitize_table_name(table)
    rows = conn.execute(
        "SELECT filename, dhash FROM photos WHERE folder=? AND dhash IS NOT NULL AND dhash != ''",
        (folder,),
    ).fetchall()
    result: dict[str, int] = {}
    for row in rows:
        try:
            result[row["filename"]] = int(row["dhash"])
        except (ValueError, TypeError):
            pass
    return result
