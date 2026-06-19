"""Tests for training_weights_db — SQLite schema and accessors."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from photo_workflow.training_weights_db import (
    open_training_db,
    ensure_schema,
    next_version,
    upsert_prototype,
    get_active_prototypes,
    rollback_to_version,
    next_aesthetic_weights_version,
    upsert_aesthetic_weights,
    get_active_aesthetic_weights,
)


def test_aesthetic_weights_roundtrip(training_db):
    """Stored profiles come back grouped by axis, latest version active."""
    v = next_aesthetic_weights_version(training_db)
    assert v == 1
    upsert_aesthetic_weights(training_db, v, "subject", "wildlife",
                             {"subject_sharpness": 0.6, "exposure_overall": 0.4})
    upsert_aesthetic_weights(training_db, v, "type", "candid", {"subject_sharpness": 1.0})
    got = get_active_aesthetic_weights(training_db)
    assert got["subject"]["wildlife"] == {"subject_sharpness": 0.6, "exposure_overall": 0.4}
    assert got["type"]["candid"] == {"subject_sharpness": 1.0}


def test_aesthetic_weights_upsert_deactivates_prior(training_db):
    """A second upsert for the same (axis,label) replaces the active row."""
    upsert_aesthetic_weights(training_db, 1, "type", "candid", {"a": 1.0})
    v2 = next_aesthetic_weights_version(training_db)
    upsert_aesthetic_weights(training_db, v2, "type", "candid", {"b": 1.0})
    got = get_active_aesthetic_weights(training_db)
    assert got["type"]["candid"] == {"b": 1.0}


def test_aesthetic_weights_empty_when_unpopulated(training_db):
    assert get_active_aesthetic_weights(training_db) == {}


@pytest.fixture
def training_db(tmp_path: Path):
    """Create a test training_weights.db and ensure schema."""
    db_path = tmp_path / "training_weights.db"
    conn = open_training_db(db_path)
    ensure_schema(conn)
    yield conn
    conn.close()


def test_open_training_db_creates_file(tmp_path: Path):
    """open_training_db should create the database file."""
    db_path = tmp_path / "test.db"
    conn = open_training_db(db_path)
    assert db_path.exists()
    conn.close()


def test_ensure_schema_creates_tables(training_db):
    """ensure_schema creates the live training tables (dead ones were removed)."""
    cursor = training_db.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row[0] for row in cursor.fetchall()}
    assert {"genre_prototypes", "genre_adapter_linear", "aesthetic_weights"} <= tables
    # Dead tables removed in the schema cleanup.
    assert "genre_adapter" not in tables  # old ONNX adapter
    assert "genre_corrections" not in tables
    assert "custom_genres" not in tables


def test_ensure_schema_idempotent(training_db):
    """ensure_schema should be idempotent."""
    # Call twice; should not raise
    ensure_schema(training_db)
    ensure_schema(training_db)


def test_next_version_empty_db(training_db):
    """next_version should return 1 for an empty database."""
    assert next_version(training_db) == 1


def test_next_version_with_existing(training_db):
    """next_version should return max + 1."""
    proto_bytes = np.random.randn(512).astype(np.float32).tobytes()
    upsert_prototype(training_db, 1, "wildlife", proto_bytes, 0, 1.0)
    upsert_prototype(training_db, 2, "landscape", proto_bytes, 0, 1.0)
    assert next_version(training_db) == 3


def test_upsert_prototype_new(training_db):
    """upsert_prototype should insert a new prototype."""
    proto = np.random.randn(512).astype(np.float32)
    proto_bytes = proto.tobytes()
    upsert_prototype(training_db, 1, "wildlife", proto_bytes, 5, 0.75)

    cursor = training_db.cursor()
    cursor.execute(
        "SELECT version, genre, n_corrections, alpha, is_active FROM genre_prototypes WHERE genre='wildlife'"
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == 1  # version
    assert row[1] == "wildlife"  # genre
    assert row[2] == 5  # n_corrections
    assert row[3] == 0.75  # alpha
    assert row[4] == 1  # is_active


def test_upsert_prototype_deactivates_previous(training_db):
    """upsert_prototype should deactivate previous active version for a genre."""
    proto_bytes = np.random.randn(512).astype(np.float32).tobytes()

    # Insert v1
    upsert_prototype(training_db, 1, "wildlife", proto_bytes, 0, 1.0)
    cursor = training_db.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM genre_prototypes WHERE genre='wildlife' AND is_active=1"
    )
    assert cursor.fetchone()[0] == 1

    # Insert v2 (should deactivate v1)
    upsert_prototype(training_db, 2, "wildlife", proto_bytes, 10, 0.8)
    cursor.execute(
        "SELECT COUNT(*) FROM genre_prototypes WHERE genre='wildlife' AND is_active=1"
    )
    assert cursor.fetchone()[0] == 1
    cursor.execute(
        "SELECT COUNT(*) FROM genre_prototypes WHERE genre='wildlife' AND is_active=0"
    )
    assert cursor.fetchone()[0] == 1


def test_get_active_prototypes_empty(training_db):
    """get_active_prototypes should return empty dict for empty database."""
    result = get_active_prototypes(training_db)
    assert result == {}


def test_get_active_prototypes_round_trip(training_db):
    """get_active_prototypes should return the prototypes that were inserted."""
    proto_wildlife = np.random.randn(512).astype(np.float32)
    proto_landscape = np.random.randn(512).astype(np.float32)

    upsert_prototype(training_db, 1, "wildlife", proto_wildlife.tobytes(), 5, 0.75)
    upsert_prototype(training_db, 1, "landscape", proto_landscape.tobytes(), 3, 0.85)

    result = get_active_prototypes(training_db)
    assert "wildlife" in result
    assert "landscape" in result
    assert result["wildlife"]["version"] == 1
    assert result["wildlife"]["n_corrections"] == 5
    assert result["wildlife"]["alpha"] == 0.75
    assert np.allclose(result["wildlife"]["prototype"], proto_wildlife)
    assert np.allclose(result["landscape"]["prototype"], proto_landscape)


def test_get_active_prototypes_only_active(training_db):
    """get_active_prototypes should only return is_active=1 rows."""
    proto_bytes = np.random.randn(512).astype(np.float32).tobytes()

    # Insert v1, then v2 (deactivates v1)
    upsert_prototype(training_db, 1, "wildlife", proto_bytes, 0, 1.0)
    upsert_prototype(training_db, 2, "wildlife", proto_bytes, 10, 0.8)

    result = get_active_prototypes(training_db)
    # Should only have v2
    assert len(result) == 1
    assert result["wildlife"]["version"] == 2


def test_rollback_to_version(training_db):
    """rollback_to_version should reactivate a previous version."""
    proto_bytes = np.random.randn(512).astype(np.float32).tobytes()

    # Insert v1, v2, v3
    for version in [1, 2, 3]:
        upsert_prototype(training_db, version, "wildlife", proto_bytes, version * 10, 1.0 - version * 0.1)

    # v3 should be active now
    result = get_active_prototypes(training_db)
    assert result["wildlife"]["version"] == 3

    # Rollback to v2
    rollback_to_version(training_db, 2)
    result = get_active_prototypes(training_db)
    assert result["wildlife"]["version"] == 2

    # Verify v3 is now inactive
    cursor = training_db.cursor()
    cursor.execute("SELECT is_active FROM genre_prototypes WHERE version=3")
    assert cursor.fetchone()[0] == 0


def test_rollback_to_version_deactivates_later(training_db):
    """rollback_to_version should deactivate all versions after the target."""
    proto_bytes = np.random.randn(512).astype(np.float32).tobytes()

    # Insert v1 and v2 for two genres
    for genre in ["wildlife", "landscape"]:
        upsert_prototype(training_db, 1, genre, proto_bytes, 0, 1.0)
        upsert_prototype(training_db, 2, genre, proto_bytes, 10, 0.8)

    # Rollback to v1
    rollback_to_version(training_db, 1)

    cursor = training_db.cursor()
    # All v1 rows should be active
    cursor.execute("SELECT COUNT(*) FROM genre_prototypes WHERE version=1 AND is_active=1")
    assert cursor.fetchone()[0] == 2
    # All v2 rows should be inactive
    cursor.execute("SELECT COUNT(*) FROM genre_prototypes WHERE version=2 AND is_active=0")
    assert cursor.fetchone()[0] == 2
