"""Genre trainer — two-axis prototype calibration and centroid blending."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import numpy as np

from .genre_router import ALL_LABELS, SUBJECTS, PHOTO_TYPES

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

    Implements last-write-wins per filename. Handles both old format
    ({"genres": ["wildlife"]}) and new format ({"subject": "wildlife"}).

    Returns:
        dict mapping filename to list of genre labels (each label is a
        subject or photo_type string). GENRES = SUBJECTS + PHOTO_TYPES.
    """
    subjects_set = set(SUBJECTS)
    types_set = set(PHOTO_TYPES)

    result: dict[str, list[str]] = {}
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
                source_folder = entry.get("source_folder")

                if source_folders is not None and source_folder not in source_folders:
                    continue

                # New two-axis format
                if "subject" in entry:
                    labels = [entry["subject"]]
                    if "photo_type" in entry and entry["photo_type"] != "general":
                        labels.append(entry["photo_type"])
                    result[filename] = labels
                    continue

                # Old flat format: classify each label as subject or type
                genres = entry.get("genres", [])
                if not genres:
                    continue
                labels = []
                for g in genres:
                    if g in subjects_set or g in types_set:
                        labels.append(g)
                if labels:
                    result[filename] = labels
    except Exception as e:
        logger.error("Failed to load corpus: %s", e)
        return {}

    return result


def _load_embeddings(
    photon_db_path: Path,
    filenames: list[str],
) -> dict[str, np.ndarray]:
    """Load CLIP embeddings from photonforge.db for the requested filenames.

    Reads from both the ``photos`` analysis table (clip_embedding column) and the
    ``embeddings`` cache (training corpora: CURATED/WEB). Falls back to scanning
    any legacy per-folder tables so a not-yet-migrated DB still works.

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
        filename_set = set(filenames)
        placeholders = ",".join("?" * len(filename_set))

        # Preferred sources (single-table schema). Fall back to legacy per-folder
        # tables only if neither exists yet.
        sources = ["photos", "embeddings"]
        existing = {
            row[0] for row in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if not ({"photos", "embeddings"} & existing):
            sources = [t for t in existing]

        for table_name in sources:
            try:
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = {row[1] for row in cursor.fetchall()}
                if "clip_embedding" not in columns or "filename" not in columns:
                    continue
                query = (
                    f"SELECT filename, clip_embedding FROM {table_name} "
                    f"WHERE filename IN ({placeholders}) AND clip_embedding IS NOT NULL"
                )
                for filename, embedding_bytes in cursor.execute(query, list(filename_set)):
                    if embedding_bytes and filename not in result:
                        result[filename] = np.frombuffer(embedding_bytes, dtype=np.float32)
            except Exception as e:
                logger.debug("Failed to query table %s: %s", table_name, e)
                continue

        conn.close()
    except Exception as e:
        logger.error("Failed to load embeddings: %s", e)
        return {}

    return result


def _load_secondary_feedback(
    secondary_feedback_path: Path,
) -> dict[str, list[str]]:
    """Load added_secondary events from secondary_feedback.jsonl.

    Each entry is one user-confirmed secondary genre for a filename.
    Only "added_secondary" events are used (positive signal only).

    Returns:
        dict mapping filename to list of genres the user added as secondary
    """
    result: dict[str, list[str]] = {}
    if not secondary_feedback_path.exists():
        return result

    try:
        with open(secondary_feedback_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("event") != "added_secondary":
                    continue
                filename = entry.get("filename")
                genre = entry.get("genre")
                if filename and genre:
                    result.setdefault(filename, []).append(genre)
    except Exception as e:
        logger.error("Failed to load secondary feedback: %s", e)
        return {}

    return result


def compute_centroids(
    filename_to_genres: dict[str, list[str]],
    filename_to_embedding: dict[str, np.ndarray],
) -> dict[str, list[np.ndarray]]:
    """Group embeddings by label for prototype calibration.

    Each image trains every label in its list — typically one subject and
    optionally one photo type.

    Returns:
        dict mapping label (from GENRES = SUBJECTS + PHOTO_TYPES) to
        list of L2-normalized embeddings.
    """
    genre_embeddings: dict[str, list[np.ndarray]] = {label: [] for label in ALL_LABELS}

    for filename, labels in filename_to_genres.items():
        if not labels:
            continue
        embedding = filename_to_embedding.get(filename)
        if embedding is None:
            continue

        embedding_norm = np.linalg.norm(embedding)
        if embedding_norm > 0:
            normalized = embedding / embedding_norm
        else:
            normalized = embedding

        for label in labels:
            if label in genre_embeddings:
                genre_embeddings[label].append(normalized)

    return genre_embeddings


def recalibrate_prototypes(
    corpus_path: Path,
    photon_db_path: Path,
    hardcoded_prototypes: np.ndarray,
    source_folders: list[str] | None = None,
    min_samples: int = 10,
    secondary_feedback_path: Path | None = None,
) -> dict[str, dict]:
    """Reblend genre prototypes from user corrections.

    Full pipeline:
    1. Load corpus (JSONL) and embeddings (from photonforge.db)
    2. Compute centroids per genre (L2-normalized)
    3. Merge added_secondary events from secondary_feedback.jsonl (if provided)
    4. For each genre: blend hardcoded + learned, compute alpha, return metadata

    Args:
        corpus_path: Path to genre_labels.jsonl
        photon_db_path: Path to photonforge.db
        hardcoded_prototypes: np.ndarray (num_genres, 512) float32 hardcoded prototypes
        source_folders: Optional list of source_folder values to include
        min_samples: Minimum embeddings per genre to re-estimate (default 10)
        secondary_feedback_path: Optional path to secondary_feedback.jsonl; when
            provided, user-confirmed secondary genres augment prototype centroids.

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

    # Collect all filenames we need embeddings for (primary corpus + secondary feedback)
    all_filenames = set(filename_to_genres.keys())
    secondary_feedback: dict[str, list[str]] = {}
    if secondary_feedback_path is not None:
        secondary_feedback = _load_secondary_feedback(secondary_feedback_path)
        all_filenames.update(secondary_feedback.keys())
        logger.info(
            "Loaded secondary feedback: %d filenames with added secondary genres",
            len(secondary_feedback),
        )

    filename_to_embedding = _load_embeddings(photon_db_path, list(all_filenames))
    logger.info("Loaded %d embeddings from photonforge.db", len(filename_to_embedding))

    # Compute centroids per genre from primary corpus
    genre_embeddings = compute_centroids(filename_to_genres, filename_to_embedding)

    # Augment with secondary feedback (user-confirmed secondary genres)
    for filename, genres in secondary_feedback.items():
        embedding = filename_to_embedding.get(filename)
        if embedding is None:
            continue
        norm = np.linalg.norm(embedding)
        normalized = embedding / norm if norm > 0 else embedding
        for genre in genres:
            if genre in genre_embeddings:
                genre_embeddings[genre].append(normalized)
    if secondary_feedback:
        total_augmented = sum(len(g) for g in secondary_feedback.values())
        logger.info("Augmented centroids with %d secondary feedback samples", total_augmented)

    result = {}

    expected_rows = len(SUBJECTS) + len(PHOTO_TYPES)
    if hardcoded_prototypes.shape[0] != expected_rows or hardcoded_prototypes.shape[1] != 512:
        raise ValueError(
            f"Hardcoded prototypes shape {hardcoded_prototypes.shape} does not match "
            f"expected ({expected_rows}, 512). Please rerun provision_scoring_models.py "
            f"with --only clip --force to regenerate genre_prototypes.npy"
        )

    # Build index mapping: label -> row in prototype file.
    # "general" appears in both halves; average the two hardcoded vectors.
    label_to_hardcoded: dict[str, np.ndarray] = {}
    for i, subj in enumerate(SUBJECTS):
        label_to_hardcoded[subj] = hardcoded_prototypes[i]
    n_subj = len(SUBJECTS)
    for i, ptype in enumerate(PHOTO_TYPES):
        if ptype in label_to_hardcoded:
            # Average subject and type versions (only "general")
            label_to_hardcoded[ptype] = (
                label_to_hardcoded[ptype] + hardcoded_prototypes[n_subj + i]
            ) / 2.0
            norm = np.linalg.norm(label_to_hardcoded[ptype])
            if norm > 0:
                label_to_hardcoded[ptype] = label_to_hardcoded[ptype] / norm
        else:
            label_to_hardcoded[ptype] = hardcoded_prototypes[n_subj + i]

    for label in ALL_LABELS:
        embeddings = genre_embeddings[label]
        hardcoded = label_to_hardcoded[label]

        if len(embeddings) < min_samples:
            result[label] = {
                "prototype": hardcoded.copy(),
                "n_corrections": len(embeddings),
                "alpha": 1.0,
                "source": "hardcoded",
            }
            logger.info(
                "'%s': %d samples < %d threshold, keeping hardcoded",
                label, len(embeddings), min_samples,
            )
        else:
            learned_centroid = np.mean(embeddings, axis=0)
            learned_norm = np.linalg.norm(learned_centroid)
            if learned_norm > 0:
                learned_centroid = learned_centroid / learned_norm
            else:
                result[label] = {
                    "prototype": hardcoded.copy(),
                    "n_corrections": len(embeddings),
                    "alpha": 1.0,
                    "source": "hardcoded",
                }
                logger.info("'%s': learned centroid is zero, keeping hardcoded", label)
                continue

            alpha = compute_alpha(len(embeddings))
            blended = alpha * hardcoded + (1.0 - alpha) * learned_centroid
            blended_norm = np.linalg.norm(blended)
            if blended_norm > 0:
                blended = blended / blended_norm
            else:
                blended = hardcoded.copy()

            result[label] = {
                "prototype": blended,
                "n_corrections": len(embeddings),
                "alpha": alpha,
                "source": "blended",
            }
            logger.info(
                "'%s': %d samples, alpha=%.3f, cosine_sim=%.3f",
                label, len(embeddings), alpha,
                float(np.dot(blended, hardcoded)),
            )

    return result
