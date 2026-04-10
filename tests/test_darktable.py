"""Unit tests for FR-1.8: Darktable SQLite + XMP sync."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from photo_workflow.darktable_bridge import sync_to_darktable, _write_xmp
from photo_workflow.pipeline import PhotoRecord


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


def test_db_upsert(tmp_path: Path) -> None:
    """Non-duplicate records are upserted into an existing SQLite DB."""
    db_path = tmp_path / "library.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE images (filename TEXT, folder TEXT, flags INTEGER, "
            "UNIQUE(filename, folder))"
        )

    rec = _make_record(tmp_path)
    sync_to_darktable([rec], db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT filename FROM images").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == rec.path.name


def test_missing_db_does_not_raise(tmp_path: Path) -> None:
    """Missing Darktable DB logs a warning but does not raise."""
    rec = _make_record(tmp_path)
    sync_to_darktable([rec], db_path=tmp_path / "nonexistent.db")
    # XMP should still be written
    assert rec.path.with_suffix(".xmp").exists()
