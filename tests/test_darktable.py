"""Unit tests for FR-1.8: Darktable SQLite + XMP sync."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from photo_workflow.darktable_bridge import sync_to_darktable, _write_xmp, validate_xmp
from photo_workflow.pipeline import PhotoRecord

_FIXTURE_DB = Path(__file__).parent / "fixtures" / "library.db"


def _make_db(path: Path) -> None:
    """Create a minimal Darktable-compatible SQLite DB at path."""
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS images (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                folder   TEXT NOT NULL DEFAULT '',
                flags    INTEGER DEFAULT 0,
                caption  TEXT DEFAULT '',
                UNIQUE(filename, folder)
            );
            CREATE TABLE IF NOT EXISTS tags (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT UNIQUE,
                synonyms TEXT DEFAULT '',
                flags    INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS tagged_images (
                imgid  INTEGER,
                tagid  INTEGER,
                UNIQUE(imgid, tagid)
            );
        """)


def _make_record(tmp_path: Path, name: str = "test", duplicate: bool = False) -> PhotoRecord:
    img_path = tmp_path / f"{name}.jpg"
    img_path.touch()
    rec = PhotoRecord(path=img_path)
    rec.session_id = "session_0001"
    rec.is_duplicate = duplicate
    rec.sharpness_score = 0.85
    rec.composition_score = 0.72
    rec.exposure_score = 0.91
    rec.semantic_name = "golden_hour_landscape"
    return rec


# ---------------------------------------------------------------------------
# XMP tests
# ---------------------------------------------------------------------------

def test_xmp_written_for_non_duplicate(tmp_path: Path) -> None:
    """XMP sidecar is created for non-duplicate records."""
    rec = _make_record(tmp_path)
    _write_xmp(rec)
    xmp_path = rec.path.with_suffix(".xmp")
    assert xmp_path.exists()
    content = xmp_path.read_text()
    assert "0.85" in content
    assert "golden_hour_landscape" in content


def test_xmp_not_written_for_duplicate(tmp_path: Path) -> None:
    """Duplicate records are skipped — no XMP written."""
    rec = _make_record(tmp_path, duplicate=True)
    sync_to_darktable([rec], db_path=tmp_path / "nonexistent.db")
    xmp_path = rec.path.with_suffix(".xmp")
    assert not xmp_path.exists()


def test_validate_xmp_passes_for_valid_sidecar(tmp_path: Path) -> None:
    """XMP written by _write_xmp passes schema validation."""
    rec = _make_record(tmp_path)
    _write_xmp(rec)
    assert validate_xmp(rec.path.with_suffix(".xmp")) is True


def test_validate_xmp_fails_for_malformed(tmp_path: Path) -> None:
    """Non-XMP file fails validation gracefully."""
    bad_xmp = tmp_path / "bad.xmp"
    bad_xmp.write_text("<not-valid-xmp>garbage</not-valid-xmp>", encoding="utf-8")
    assert validate_xmp(bad_xmp) is False


# ---------------------------------------------------------------------------
# DB tests
# ---------------------------------------------------------------------------

def test_db_upsert(tmp_path: Path) -> None:
    """Non-duplicate records are upserted with star rating and caption."""
    db_path = tmp_path / "library.db"
    _make_db(db_path)

    rec = _make_record(tmp_path)
    sync_to_darktable([rec], db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT filename, flags, caption FROM images").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == rec.path.name
    assert rows[0][2] == "golden_hour_landscape"
    assert 0 <= rows[0][1] <= 7  # star rating 0–5 stored in low 3 bits


def test_db_upsert_idempotent(tmp_path: Path) -> None:
    """Running sync twice produces exactly one row (no duplicates in DB)."""
    db_path = tmp_path / "library.db"
    _make_db(db_path)

    rec = _make_record(tmp_path)
    sync_to_darktable([rec], db_path=db_path)
    sync_to_darktable([rec], db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    assert count == 1


def test_db_tag_written(tmp_path: Path) -> None:
    """Session tag is written to tags + tagged_images tables."""
    db_path = tmp_path / "library.db"
    _make_db(db_path)

    rec = _make_record(tmp_path)
    sync_to_darktable([rec], db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        tag = conn.execute(
            "SELECT name FROM tags WHERE name = ?", ("session:session_0001",)
        ).fetchone()
        linked = conn.execute("SELECT COUNT(*) FROM tagged_images").fetchone()[0]
    assert tag is not None
    assert linked == 1


def test_missing_db_does_not_raise(tmp_path: Path) -> None:
    """Missing Darktable DB logs a warning but does not raise."""
    rec = _make_record(tmp_path)
    sync_to_darktable([rec], db_path=tmp_path / "nonexistent.db")
    assert rec.path.with_suffix(".xmp").exists()


# ---------------------------------------------------------------------------
# Fixture DB schema validation (zero-corruption acceptance criterion)
# ---------------------------------------------------------------------------

def test_fixture_db_schema_validates(tmp_path: Path) -> None:
    """Fixture library.db has the required tables; sync succeeds without corruption."""
    assert _FIXTURE_DB.exists(), f"Fixture DB missing: {_FIXTURE_DB}"

    db_path = tmp_path / "library.db"
    shutil.copy(_FIXTURE_DB, db_path)

    rec = _make_record(tmp_path)
    sync_to_darktable([rec], db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        rows = conn.execute("SELECT filename FROM images").fetchall()

    assert {"images", "tags", "tagged_images"}.issubset(tables)
    assert len(rows) >= 1

    # Original fixture must still be readable (zero-corruption check)
    with sqlite3.connect(_FIXTURE_DB) as orig:
        orig.execute("SELECT COUNT(*) FROM images").fetchone()
