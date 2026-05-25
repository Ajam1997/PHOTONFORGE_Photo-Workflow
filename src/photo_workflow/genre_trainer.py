"""Genre trainer — prototype calibration and centroid blending."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import numpy as np

from .genre_router import GENRES

logger = logging.getLogger(__name__)


def compute_alpha(n_corrections: int, decay_rate: float = 0.02) -> float:
    """Compute alpha blend factor as corrections accumulate.

    Alpha decays from 1.0 (trust hardcoded) toward a floor of 0.3.

    Args:
        n_corrections: Number of user corrections for a genre
        decay_rate: Rate of decay per correction (default 0.02)

    Returns:
        Alpha in [0.3, 1.0]
    """
    return max(0.3, 1.0 - decay_rate * n_corrections)


def _load_corpus(
    corpus_path: Path,
    source_folders: list[str] | None = None,
) -> dict[str, list[str]]:
    """Load genre labels from JSONL corpus.

    Implements last-write-wins per filename: if the same filename appears
    multiple times, the last entry wins. Entries with empty genres list
    are skipped.

    Args:
        corpus_path: Path to genre_labels.jsonl
        source_folders: Optional list of source_folder values to include.
                       If None, all entries are included.

    Returns:
        dict mapping filename to list of genres (e.g., {"P001ICE0001.ARW": ["wildlife", "landscape"]})
    """
    result = {}
    if not corpus_path.exists():
        logger.warning("Corpus file not found: %s", corpus_path)
        return result

    try:
        with open(corpus_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                filename = entry.get("filename")
                genres = entry.get("genres", [])
                source_folder = entry.get("source_folder")

                # Skip entries with no genres
                if not genres:
                    continue

                # Filter by source_folder if specified
                if source_folders is not None and source_folder not in source_folders:
                    continue

                # Last-write-wins
                result[filename] = genres
    except Exception as e:
        logger.error("Failed to load corpus: %s", e)
        return {}

    return result


def _load_embeddings(
    photon_db_path: Path,
    filenames: list[str],
) -> dict[str, np.ndarray]:
    """Load CLIP embeddings from photonforge.db per-folder tables.

    Queries all tables in photonforge.db (except system tables) to find
    clip_embedding BLOBs for the requested filenames.

    Args:
        photon_db_path: Path to photonforge.db
        filenames: List of filenames to load embeddings for

    Returns:
        dict mapping filename to np.ndarray (512,) float32 embeddings
    """
    result = {}
    if not photon_db_path.exists():
        logger.warning("Photonforge DB not found: %s", photon_db_path)
        return result

    try:
        conn = sqlite3.connect(str(photon_db_path))
        cursor = conn.cursor()

        # Get all user-defined tables (exclude system tables)
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = [row[0] for row in cursor.fetchall()]

        filename_set = set(filenames)

        for table_name in tables:
            try:
                # Check if table has clip_embedding column
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = {row[1] for row in cursor.fetchall()}
                if "clip_embedding" not in columns or "filename" not in columns:
                    continue

                # Query embeddings for filenames in this table
                placeholders = ",".join("?" * len(filename_set))
                query = f"SELECT filename, clip_embedding FROM {table_name} WHERE filename IN ({placeholders}) AND clip_embedding IS NOT NULL"
                cursor.execute(query, list(filename_set))

                for filename, embedding_bytes in cursor.fetchall():
                    if embedding_bytes:
                        embedding = np.frombuffer(embedding_bytes, dtype=np.float32)
                        result[filename] = embedding
            except Exception as e:
                logger.debug("Failed to query table %s: %s", table_name, e)
                continue

        conn.close()
    except Exception as e:
        logger.error("Failed to load embeddings: %s", e)
        return {}

    return result


def compute_centroids(
    filename_to_genres: dict[str, list[str]],
    filename_to_embedding: dict[str, np.ndarray],
) -> dict[str, list[np.ndarray]]:
    """Group embeddings by genre, handling multi-label assignments.

    For each filename, its embedding is added to ALL of its genres' lists.

    Args:
        filename_to_genres: dict mapping filename to list of genre strings
        filename_to_embedding: dict mapping filename to np.ndarray (512,)

    Returns:
        dict mapping genre to list of embeddings (all L2-normalized)
    """
    genre_embeddings: dict[str, list[np.ndarray]] = {genre: [] for genre in GENRES}

    for filename, genres in filename_to_genres.items():
        embedding = filename_to_embedding.get(filename)
        if embedding is None:
            continue

        # Ensure embedding is L2-normalized
        embedding_norm = np.linalg.norm(embedding)
        if embedding_norm > 0:
            normalized = embedding / embedding_norm
        else:
            normalized = embedding

        # Add to all genres this image belongs to
        for genre in genres:
            if genre in genre_embeddings:
                genre_embeddings[genre].append(normalized)

    return genre_embeddings


def recalibrate_prototypes(
    corpus_path: Path,
    photon_db_path: Path,
    hardcoded_prototypes: np.ndarray,
    source_folders: list[str] | None = None,
    min_samples: int = 10,
) -> dict[str, dict]:
    """Reblend genre prototypes from user corrections.

    Full pipeline:
    1. Load corpus (JSONL) and embeddings (from photonforge.db)
    2. Compute centroids per genre (L2-normalized)
    3. For each genre: blend hardcoded + learned, compute alpha, return metadata

    Args:
        corpus_path: Path to genre_labels.jsonl
        photon_db_path: Path to photonforge.db
        hardcoded_prototypes: np.ndarray (num_genres, 512) float32 hardcoded prototypes
        source_folders: Optional list of source_folder values to include
        min_samples: Minimum embeddings per genre to re-estimate (default 10)

    Returns:
        dict mapping genre to {
            "prototype": np.ndarray (512,) float32,
            "n_corrections": int (number of embeddings used),
            "alpha": float,
            "source": "blended" | "hardcoded"
        }
    """
    # Load corpus and embeddings
    filename_to_genres = _load_corpus(corpus_path, source_folders=source_folders)
    logger.info("Loaded %d unique filenames from corpus", len(filename_to_genres))

    filename_to_embedding = _load_embeddings(photon_db_path, list(filename_to_genres.keys()))
    logger.info("Loaded %d embeddings from photonforge.db", len(filename_to_embedding))

    # Compute centroids per genre
    genre_embeddings = compute_centroids(filename_to_genres, filename_to_embedding)

    result = {}

    # Validate hardcoded prototypes shape
    if hardcoded_prototypes.shape[0] != len(GENRES) or hardcoded_prototypes.shape[1] != 512:
        raise ValueError(
            f"Hardcoded prototypes shape {hardcoded_prototypes.shape} does not match "
            f"expected ({len(GENRES)}, 512). Please rerun provision_scoring_models.py "
            f"with --only clip --force to regenerate genre_prototypes.npy"
        )

    for i, genre in enumerate(GENRES):
        embeddings = genre_embeddings[genre]
        hardcoded = hardcoded_prototypes[i]

        if len(embeddings) < min_samples:
            # Not enough data: use hardcoded with alpha=1.0
            result[genre] = {
                "prototype": hardcoded.copy(),
                "n_corrections": 0,
                "alpha": 1.0,
                "source": "hardcoded",
            }
            logger.info(
                "Genre '%s': %d samples < %d threshold, keeping hardcoded",
                genre,
                len(embeddings),
                min_samples,
            )
        else:
            # Compute learned centroid
            learned_centroid = np.mean(embeddings, axis=0)
            learned_norm = np.linalg.norm(learned_centroid)
            if learned_norm > 0:
                learned_centroid = learned_centroid / learned_norm
            else:
                # Degenerate: all-zero embeddings; fall back to hardcoded
                result[genre] = {
                    "prototype": hardcoded.copy(),
                    "n_corrections": len(embeddings),
                    "alpha": 1.0,
                    "source": "hardcoded",
                }
                logger.info("Genre '%s': learned centroid is zero, keeping hardcoded", genre)
                continue

            # Blend
            alpha = compute_alpha(len(embeddings))
            blended = alpha * hardcoded + (1.0 - alpha) * learned_centroid
            blended_norm = np.linalg.norm(blended)
            if blended_norm > 0:
                blended = blended / blended_norm
            else:
                # Degenerate blend; keep hardcoded
                blended = hardcoded.copy()

            result[genre] = {
                "prototype": blended,
                "n_corrections": len(embeddings),
                "alpha": alpha,
                "source": "blended",
            }
            logger.info(
                "Genre '%s': %d samples, alpha=%.3f, cosine_sim_to_hardcoded=%.3f",
                genre,
                len(embeddings),
                alpha,
                float(np.dot(blended, hardcoded)),
            )

    return result
