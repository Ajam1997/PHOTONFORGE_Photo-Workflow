"""Tests for photondb — SQLite-backed pipeline stage tracker (single-table schema)."""

from __future__ import annotations

from pathlib import Path

import pytest

from photo_workflow.photondb import (
    open_db,
    ensure_table,
    insert_photo,
    update_stages,
    get_pending,
    update_scores,
    update_semantic,
    mark_duplicate,
    sanitize_table_name,
    update_genre_scores,
)


@pytest.fixture(autouse=True)
def cleanup_db(tmp_path: Path) -> None:
    """Clean up database file before each test to ensure isolation."""
    db_file = tmp_path.parent / "photonforge.db"
    # Clean up before test (in case it was left from a previous run)
    # Ignore errors in case the file is still open
    try:
        if db_file.exists():
            db_file.unlink()
    except (OSError, PermissionError):
        pass
    yield
    # Clean up after test to avoid interference with next test
    try:
        if db_file.exists():
            db_file.unlink()
    except (OSError, PermissionError):
        pass


def test_sanitize_table_name_alpha():
    assert sanitize_table_name("ICELAND") == "ICELAND"


def test_sanitize_table_name_strips_special():
    assert sanitize_table_name("My Trip!") == "My_Trip_"


def test_sanitize_table_name_preserves_underscores():
    assert sanitize_table_name("WEDDING_2026") == "WEDDING_2026"


def test_sanitize_table_name_short_pads():
    assert sanitize_table_name("") == "default"


def test_open_db_creates_file(tmp_path: Path):
    dest = tmp_path / "ICELAND"
    dest.mkdir()
    conn = open_db(dest)
    assert (tmp_path / "photonforge.db").exists()
    conn.close()


def test_open_db_windows_drive_root(tmp_path: Path):
    """open_db resolves to drive root on Windows-like paths."""
    conn = open_db(tmp_path / "subdir")
    conn.close()


def test_ensure_schema_creates_photos_and_embeddings(tmp_path: Path):
    conn = open_db(tmp_path)
    ensure_table(conn, "ICELAND")
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert "photos" in names
    assert "embeddings" in names
    conn.close()


def test_ensure_table_idempotent(tmp_path: Path):
    conn = open_db(tmp_path)
    ensure_table(conn, "ICELAND")
    ensure_table(conn, "ICELAND")
    conn.close()


def test_insert_and_retrieve(tmp_path: Path):
    conn = open_db(tmp_path)
    ensure_table(conn, "ICELAND")
    insert_photo(conn, "ICELAND", "P003ICE0000001.ARW", "DSC03056.ARW", "2026-05-10T14:32:01")
    rows = conn.execute(
        "SELECT filename, original_name FROM photos WHERE folder='ICELAND'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "P003ICE0000001.ARW"
    assert rows[0][1] == "DSC03056.ARW"
    conn.close()


def test_rows_are_scoped_by_folder(tmp_path: Path):
    """Two folders share one table but stay isolated by the folder column."""
    conn = open_db(tmp_path)
    ensure_table(conn, "ICELAND")
    insert_photo(conn, "ICELAND", "a.jpg", "a.jpg", None)
    insert_photo(conn, "UTAH", "a.jpg", "a.jpg", None)  # same filename, other folder
    total = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    assert total == 2
    iceland = conn.execute("SELECT COUNT(*) FROM photos WHERE folder='ICELAND'").fetchone()[0]
    assert iceland == 1
    conn.close()


def test_insert_duplicate_ignored(tmp_path: Path):
    conn = open_db(tmp_path)
    ensure_table(conn, "ICELAND")
    insert_photo(conn, "ICELAND", "P003ICE0000001.ARW", "DSC03056.ARW", "2026-05-10T14:32:01")
    insert_photo(conn, "ICELAND", "P003ICE0000001.ARW", "DSC03056.ARW", "2026-05-10T14:32:01")
    rows = conn.execute("SELECT COUNT(*) FROM photos WHERE folder='ICELAND'").fetchone()
    assert rows[0] == 1
    conn.close()


def test_update_stages(tmp_path: Path):
    conn = open_db(tmp_path)
    ensure_table(conn, "T")
    insert_photo(conn, "T", "a.jpg", "a.jpg", None)
    update_stages(conn, "T", "a.jpg", "scan")
    update_stages(conn, "T", "a.jpg", "dedup")
    row = conn.execute(
        "SELECT stages FROM photos WHERE folder='T' AND filename='a.jpg'"
    ).fetchone()
    assert row[0] == "scan,dedup"
    conn.close()


def test_update_stages_no_duplicate(tmp_path: Path):
    conn = open_db(tmp_path)
    ensure_table(conn, "T")
    insert_photo(conn, "T", "a.jpg", "a.jpg", None)
    update_stages(conn, "T", "a.jpg", "scan")
    update_stages(conn, "T", "a.jpg", "scan")
    row = conn.execute(
        "SELECT stages FROM photos WHERE folder='T' AND filename='a.jpg'"
    ).fetchone()
    assert row[0] == "scan"
    conn.close()


def test_get_pending(tmp_path: Path):
    conn = open_db(tmp_path)
    ensure_table(conn, "T")
    insert_photo(conn, "T", "a.jpg", "a.jpg", None)
    insert_photo(conn, "T", "b.jpg", "b.jpg", None)
    update_stages(conn, "T", "a.jpg", "scan")
    update_stages(conn, "T", "a.jpg", "dedup")
    update_stages(conn, "T", "b.jpg", "scan")
    pending = get_pending(conn, "T", "dedup")
    assert len(pending) == 1
    assert pending[0]["filename"] == "b.jpg"
    conn.close()


def test_update_scores(tmp_path: Path):
    conn = open_db(tmp_path)
    ensure_table(conn, "T")
    insert_photo(conn, "T", "a.jpg", "a.jpg", None)
    update_scores(conn, "T", "a.jpg", 0.85, 0.72, 0.91)
    row = conn.execute(
        "SELECT sharpness, composition, exposure FROM photos WHERE folder='T' AND filename='a.jpg'"
    ).fetchone()
    assert tuple(row) == (0.85, 0.72, 0.91)
    conn.close()


def test_update_semantic(tmp_path: Path):
    conn = open_db(tmp_path)
    ensure_table(conn, "T")
    insert_photo(conn, "T", "a.jpg", "a.jpg", None)
    update_semantic(conn, "T", "a.jpg", "golden-sunset-beach")
    row = conn.execute(
        "SELECT semantic_name FROM photos WHERE folder='T' AND filename='a.jpg'"
    ).fetchone()
    assert row[0] == "golden-sunset-beach"
    conn.close()


def test_mark_duplicate(tmp_path: Path):
    conn = open_db(tmp_path)
    ensure_table(conn, "T")
    insert_photo(conn, "T", "a.jpg", "a.jpg", None)
    mark_duplicate(conn, "T", "a.jpg")
    row = conn.execute(
        "SELECT is_duplicate FROM photos WHERE folder='T' AND filename='a.jpg'"
    ).fetchone()
    assert row[0] == 1
    conn.close()


def test_update_genre_scores_with_multi_genre(tmp_path: Path):
    """update_genre_scores stores two-axis genre dict (and no legacy genre column)."""
    conn = open_db(tmp_path)
    ensure_table(conn, "T")
    insert_photo(conn, "T", "a.jpg", "a.jpg", None)

    genres = {
        "subject": "wildlife",
        "subject_confidence": 0.87,
        "photo_type": "landscape",
        "type_confidence": 0.65,
    }
    update_genre_scores(
        conn, "T", "a.jpg",
        genre="wildlife",
        genre_confidence=0.87,
        master_score=0.75,
        sub_scores={"eye_sharpness": 0.9, "subject_sharpness": 0.85},
        genres=genres,
        primary_genre="wildlife",
        needs_review=False,
        clip_embedding=b"fake_embedding_bytes",
    )

    row = conn.execute(
        "SELECT primary_genre, genres, needs_review, clip_embedding "
        "FROM photos WHERE folder='T' AND filename='a.jpg'"
    ).fetchone()

    assert row["primary_genre"] == "wildlife"
    assert row["needs_review"] == 0
    assert row["clip_embedding"] == b"fake_embedding_bytes"
    import json
    genres_parsed = json.loads(row["genres"])
    assert genres_parsed["subject"] == "wildlife"
    assert genres_parsed["subject_confidence"] == 0.87
    assert genres_parsed["photo_type"] == "landscape"
    assert genres_parsed["type_confidence"] == 0.65

    conn.close()


def test_photos_schema_has_expected_columns(tmp_path: Path):
    """The photos table carries the analysis columns; legacy `genre` is gone."""
    conn = open_db(tmp_path)
    ensure_table(conn, "T")
    col_names = {col[1] for col in conn.execute("PRAGMA table_info(photos)")}
    assert {"folder", "filename", "genres", "primary_genre", "needs_review",
            "clip_embedding"} <= col_names
    assert "genre" not in col_names  # legacy singular column dropped
    # idempotent
    ensure_table(conn, "T")
    col_names2 = {col[1] for col in conn.execute("PRAGMA table_info(photos)")}
    assert col_names2 == col_names
    conn.close()
