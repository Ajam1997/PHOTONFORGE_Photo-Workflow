"""Tests for genre_trainer — prototype blending and calibration."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from photo_workflow.genre_trainer import (
    compute_alpha,
    _load_corpus,
    _load_embeddings,
    compute_centroids,
    recalibrate_prototypes,
)
from photo_workflow.genre_router import GENRES


def test_compute_alpha_at_zero():
    """compute_alpha at 0 corrections should return 1.0."""
    assert compute_alpha(0) == 1.0


def test_compute_alpha_at_15():
    """compute_alpha at 15 corrections should decay to 0.7."""
    alpha = compute_alpha(15)
    assert alpha == 0.7


def test_compute_alpha_at_35():
    """compute_alpha at 35+ should floor at 0.3."""
    assert compute_alpha(35) == 0.3
    assert compute_alpha(100) == 0.3


def test_compute_alpha_decay_rate():
    """compute_alpha should respect custom decay_rate."""
    alpha_default = compute_alpha(10)
    alpha_slow = compute_alpha(10, decay_rate=0.01)
    assert alpha_slow > alpha_default  # Slower decay = higher alpha


def test_load_corpus_empty(tmp_path: Path):
    """_load_corpus with missing file should return empty dict."""
    corpus_path = tmp_path / "nonexistent.jsonl"
    result = _load_corpus(corpus_path)
    assert result == {}


def test_load_corpus_basic(tmp_path: Path):
    """_load_corpus should parse JSONL and return dict."""
    corpus_path = tmp_path / "genres.jsonl"
    corpus_path.write_text(
        '{"filename": "A.ARW", "genres": ["wildlife"], "source_folder": "TEST_1", "needs_review": false, "labeled_at": "2026-05-25T00:00:00+00:00", "labeler": "alex"}\n'
        '{"filename": "B.ARW", "genres": ["landscape", "wildlife"], "source_folder": "TEST_1", "needs_review": false, "labeled_at": "2026-05-25T00:00:00+00:00", "labeler": "alex"}\n'
    )
    result = _load_corpus(corpus_path)
    assert result == {
        "A.ARW": ["wildlife"],
        "B.ARW": ["landscape", "wildlife"],
    }


def test_load_corpus_last_write_wins(tmp_path: Path):
    """_load_corpus should use last entry for duplicate filenames."""
    corpus_path = tmp_path / "genres.jsonl"
    corpus_path.write_text(
        '{"filename": "A.ARW", "genres": ["wildlife"], "source_folder": "TEST_1", "needs_review": false, "labeled_at": "2026-05-25T00:00:00+00:00", "labeler": "alex"}\n'
        '{"filename": "A.ARW", "genres": ["landscape"], "source_folder": "TEST_1", "needs_review": false, "labeled_at": "2026-05-25T00:01:00+00:00", "labeler": "alex"}\n'
    )
    result = _load_corpus(corpus_path)
    assert result["A.ARW"] == ["landscape"]


def test_load_corpus_skips_empty_genres(tmp_path: Path):
    """_load_corpus should skip entries with empty genres list."""
    corpus_path = tmp_path / "genres.jsonl"
    corpus_path.write_text(
        '{"filename": "A.ARW", "genres": ["wildlife"], "source_folder": "TEST_1", "needs_review": false, "labeled_at": "2026-05-25T00:00:00+00:00", "labeler": "alex"}\n'
        '{"filename": "B.ARW", "genres": [], "source_folder": "TEST_1", "needs_review": true, "labeled_at": "2026-05-25T00:00:00+00:00", "labeler": "alex"}\n'
    )
    result = _load_corpus(corpus_path)
    assert "A.ARW" in result
    assert "B.ARW" not in result


def test_load_corpus_source_folder_filter(tmp_path: Path):
    """_load_corpus should filter by source_folder when specified."""
    corpus_path = tmp_path / "genres.jsonl"
    corpus_path.write_text(
        '{"filename": "A.ARW", "genres": ["wildlife"], "source_folder": "TEST_1", "needs_review": false, "labeled_at": "2026-05-25T00:00:00+00:00", "labeler": "alex"}\n'
        '{"filename": "B.ARW", "genres": ["landscape"], "source_folder": "TEST_2", "needs_review": false, "labeled_at": "2026-05-25T00:00:00+00:00", "labeler": "alex"}\n'
    )
    result = _load_corpus(corpus_path, source_folders=["TEST_1"])
    assert "A.ARW" in result
    assert "B.ARW" not in result


def test_load_embeddings_missing_db(tmp_path: Path):
    """_load_embeddings with missing DB should return empty dict."""
    db_path = tmp_path / "nonexistent.db"
    result = _load_embeddings(db_path, ["A.ARW", "B.ARW"])
    assert result == {}


def test_load_embeddings_from_photon_db(tmp_path: Path):
    """_load_embeddings should query clip_embedding from per-folder tables."""
    db_path = tmp_path / "photonforge.db"
    conn = sqlite3.connect(str(db_path))

    # Create a TEST_1 table with clip_embedding column
    conn.execute("""
        CREATE TABLE TEST_1 (
            filename TEXT PRIMARY KEY,
            clip_embedding BLOB
        )
    """)

    # Insert embeddings
    emb_a = np.random.randn(512).astype(np.float32)
    conn.execute("INSERT INTO TEST_1 VALUES (?, ?)", ("A.ARW", emb_a.tobytes()))
    conn.execute("INSERT INTO TEST_1 VALUES (?, ?)", ("B.ARW", None))  # NULL embedding
    conn.commit()
    conn.close()

    result = _load_embeddings(db_path, ["A.ARW", "B.ARW"])
    assert "A.ARW" in result
    assert np.allclose(result["A.ARW"], emb_a)
    assert "B.ARW" not in result  # NULL is skipped


def test_compute_centroids_single_label(tmp_path: Path):
    """compute_centroids should group embeddings by single-label genre."""
    emb1 = np.random.randn(512).astype(np.float32)
    emb2 = np.random.randn(512).astype(np.float32)
    emb1_norm = emb1 / np.linalg.norm(emb1)
    emb2_norm = emb2 / np.linalg.norm(emb2)

    filename_to_genres = {
        "A.ARW": ["wildlife"],
        "B.ARW": ["wildlife"],
    }
    filename_to_embedding = {
        "A.ARW": emb1_norm,
        "B.ARW": emb2_norm,
    }

    result = compute_centroids(filename_to_genres, filename_to_embedding)
    assert len(result["wildlife"]) == 2
    assert len(result["landscape"]) == 0


def test_compute_centroids_multi_label(tmp_path: Path):
    """compute_centroids should add multi-label embeddings to all genres."""
    emb = np.random.randn(512).astype(np.float32)
    emb_norm = emb / np.linalg.norm(emb)

    filename_to_genres = {
        "A.ARW": ["wildlife", "landscape"],
    }
    filename_to_embedding = {
        "A.ARW": emb_norm,
    }

    result = compute_centroids(filename_to_genres, filename_to_embedding)
    assert len(result["wildlife"]) == 1
    assert len(result["landscape"]) == 1
    assert np.allclose(result["wildlife"][0], emb_norm)
    assert np.allclose(result["landscape"][0], emb_norm)


def test_compute_centroids_missing_embeddings(tmp_path: Path):
    """compute_centroids should skip files with missing embeddings."""
    emb = np.random.randn(512).astype(np.float32)
    emb_norm = emb / np.linalg.norm(emb)

    filename_to_genres = {
        "A.ARW": ["wildlife"],
        "B.ARW": ["landscape"],  # No embedding
    }
    filename_to_embedding = {
        "A.ARW": emb_norm,
    }

    result = compute_centroids(filename_to_genres, filename_to_embedding)
    assert len(result["wildlife"]) == 1
    assert len(result["landscape"]) == 0


def test_recalibrate_prototypes_small_n(tmp_path: Path):
    """recalibrate_prototypes with n < min_samples should keep hardcoded."""
    corpus_path = tmp_path / "genres.jsonl"
    corpus_path.write_text(
        '{"filename": "A.ARW", "genres": ["wildlife"], "source_folder": "TEST_1", "needs_review": false, "labeled_at": "2026-05-25T00:00:00+00:00", "labeler": "alex"}\n'
    )

    # Create a minimal photon_db
    db_path = tmp_path / "photonforge.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE TEST_1 (filename TEXT PRIMARY KEY, clip_embedding BLOB)")
    emb = np.random.randn(512).astype(np.float32)
    emb_norm = emb / np.linalg.norm(emb)
    conn.execute("INSERT INTO TEST_1 VALUES (?, ?)", ("A.ARW", emb_norm.tobytes()))
    conn.commit()
    conn.close()

    # Hardcoded prototypes
    hardcoded = np.random.randn(len(GENRES), 512).astype(np.float32)
    for i in range(len(GENRES)):
        hardcoded[i] /= np.linalg.norm(hardcoded[i])

    result = recalibrate_prototypes(
        corpus_path, db_path, hardcoded, min_samples=10
    )

    # Wildlife has 1 sample < 10, so should keep hardcoded
    assert result["wildlife"]["source"] == "hardcoded"
    assert result["wildlife"]["alpha"] == 1.0
    assert np.allclose(result["wildlife"]["prototype"], hardcoded[GENRES.index("wildlife")])


def test_recalibrate_prototypes_large_n(tmp_path: Path):
    """recalibrate_prototypes with n >= min_samples should blend."""
    # Create corpus with 15 wildlife samples
    corpus_path = tmp_path / "genres.jsonl"
    lines = []
    for i in range(15):
        filename = f"P{i:06d}.ARW"
        lines.append(
            f'{{"filename": "{filename}", "genres": ["wildlife"], "source_folder": "TEST_1", "needs_review": false, "labeled_at": "2026-05-25T00:00:00+00:00", "labeler": "alex"}}'
        )
    corpus_path.write_text("\n".join(lines))

    # Create photon_db with embeddings
    db_path = tmp_path / "photonforge.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE TEST_1 (filename TEXT PRIMARY KEY, clip_embedding BLOB)")

    # Create 15 distinct embeddings clustered around a learned centroid
    learned_centroid = np.random.randn(512).astype(np.float32)
    learned_centroid /= np.linalg.norm(learned_centroid)

    for i in range(15):
        filename = f"P{i:06d}.ARW"
        # Perturbed version of learned centroid
        emb = learned_centroid + 0.1 * np.random.randn(512).astype(np.float32)
        emb /= np.linalg.norm(emb)
        conn.execute("INSERT INTO TEST_1 VALUES (?, ?)", (filename, emb.tobytes()))
    conn.commit()
    conn.close()

    # Hardcoded prototypes (orthogonal to learned)
    hardcoded = np.random.randn(len(GENRES), 512).astype(np.float32)
    for i in range(len(GENRES)):
        hardcoded[i] /= np.linalg.norm(hardcoded[i])

    result = recalibrate_prototypes(
        corpus_path, db_path, hardcoded, min_samples=10
    )

    # Wildlife has 15 samples >= 10, so should blend
    assert result["wildlife"]["source"] == "blended"
    assert result["wildlife"]["n_corrections"] == 15
    assert 0.3 <= result["wildlife"]["alpha"] < 1.0
    # Blended prototype should be L2-normalized
    assert np.isclose(np.linalg.norm(result["wildlife"]["prototype"]), 1.0)


def test_recalibrate_prototypes_shape_validation(tmp_path: Path):
    """recalibrate_prototypes should raise on wrong hardcoded shape."""
    corpus_path = tmp_path / "genres.jsonl"
    corpus_path.write_text(
        '{"filename": "A.ARW", "genres": ["wildlife"], "source_folder": "TEST_1", "needs_review": false, "labeled_at": "2026-05-25T00:00:00+00:00", "labeler": "alex"}\n'
    )

    db_path = tmp_path / "photonforge.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE TEST_1 (filename TEXT PRIMARY KEY, clip_embedding BLOB)")
    conn.close()

    # Wrong shape: 9x512 instead of 10x512
    hardcoded_wrong = np.random.randn(9, 512).astype(np.float32)

    with pytest.raises(ValueError, match="does not match expected"):
        recalibrate_prototypes(corpus_path, db_path, hardcoded_wrong)


def test_recalibrate_prototypes_cosine_similarity(tmp_path: Path):
    """recalibrate_prototypes should compute reasonable cosine similarity."""
    # Create corpus with 12 wildlife samples
    corpus_path = tmp_path / "genres.jsonl"
    lines = []
    for i in range(12):
        filename = f"P{i:06d}.ARW"
        lines.append(
            f'{{"filename": "{filename}", "genres": ["wildlife"], "source_folder": "TEST_1", "needs_review": false, "labeled_at": "2026-05-25T00:00:00+00:00", "labeler": "alex"}}'
        )
    corpus_path.write_text("\n".join(lines))

    # Create photon_db
    db_path = tmp_path / "photonforge.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE TEST_1 (filename TEXT PRIMARY KEY, clip_embedding BLOB)")

    # Embeddings similar to hardcoded
    learned_centroid = np.random.randn(512).astype(np.float32)
    learned_centroid /= np.linalg.norm(learned_centroid)

    for i in range(12):
        filename = f"P{i:06d}.ARW"
        emb = learned_centroid + 0.05 * np.random.randn(512).astype(np.float32)
        emb /= np.linalg.norm(emb)
        conn.execute("INSERT INTO TEST_1 VALUES (?, ?)", (filename, emb.tobytes()))
    conn.commit()
    conn.close()

    # Hardcoded similar to learned
    hardcoded = np.random.randn(len(GENRES), 512).astype(np.float32)
    hardcoded[GENRES.index("wildlife")] = learned_centroid.copy()
    for i in range(len(GENRES)):
        hardcoded[i] /= np.linalg.norm(hardcoded[i])

    result = recalibrate_prototypes(
        corpus_path, db_path, hardcoded, min_samples=10
    )

    # Blended should have high cosine sim with hardcoded (since learned ≈ hardcoded)
    wildlife_idx = GENRES.index("wildlife")
    cosine_sim = np.dot(result["wildlife"]["prototype"], hardcoded[wildlife_idx])
    assert cosine_sim > 0.8  # Should be high similarity
