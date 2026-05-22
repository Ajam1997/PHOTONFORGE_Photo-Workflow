"""Genre router — CLIP + EXIF + YOLO Bayesian fusion for genre classification."""

from __future__ import annotations

import logging
import math

import numpy as np

from .scoring_types import GenreResult, ObjectDetection, SubjectContext

logger = logging.getLogger(__name__)

GENRES = [
    "wildlife",
    "landscape",
    "portrait",
    "street",
    "architecture",
    "macro",
    "event",
    "general",
]

# Animal COCO class IDs: bird=14, cat=15, dog=16, horse=17, sheep=18, cow=19,
# elephant=20, bear=21, zebra=22, giraffe=23
_ANIMAL_CLASS_IDS = {14, 15, 16, 17, 18, 19, 20, 21, 22, 23}

# EXIF priors: (mean, std) for log(value) per genre
# Format: {genre: {"focal_length": (mean_log, std_log), ...}}
_EXIF_PRIORS = {
    "wildlife": {
        "focal_length": (5.7, 0.8),
        "aperture": (1.2, 0.5),
        "shutter": (-7.0, 1.0),
        "iso": (6.4, 0.8),
    },
    "landscape": {
        "focal_length": (3.0, 0.6),
        "aperture": (2.2, 0.3),
        "shutter": (-3.0, 2.0),
        "iso": (4.6, 0.5),
    },
    "portrait": {
        "focal_length": (4.2, 0.4),
        "aperture": (0.5, 0.5),
        "shutter": (-5.5, 0.8),
        "iso": (5.5, 0.8),
    },
    "street": {
        "focal_length": (3.5, 0.4),
        "aperture": (1.4, 0.5),
        "shutter": (-6.0, 0.8),
        "iso": (6.2, 0.8),
    },
    "architecture": {
        "focal_length": (3.0, 0.6),
        "aperture": (2.1, 0.3),
        "shutter": (-2.0, 2.0),
        "iso": (4.6, 0.5),
    },
    "macro": {
        "focal_length": (4.3, 0.3),
        "aperture": (2.1, 0.3),
        "shutter": (-5.0, 0.8),
        "iso": (5.5, 0.8),
    },
    "event": {
        "focal_length": (3.8, 0.5),
        "aperture": (1.2, 0.4),
        "shutter": (-5.5, 0.8),
        "iso": (6.0, 0.8),
    },
    "general": {
        "focal_length": (3.8, 1.5),
        "aperture": (1.5, 1.0),
        "shutter": (-5.0, 2.0),
        "iso": (5.5, 1.5),
    },
}

# Confidence threshold below which we fall back to "general"
_CONFIDENCE_THRESHOLD = 0.3


def _compute_exif_prior(exif: dict) -> dict[str, float]:
    """Compute per-genre log-Gaussian likelihood from EXIF metadata.

    Returns a dict of genre -> unnormalized probability.
    Missing fields contribute uniform (1.0) across all genres.
    """
    result = {g: 0.0 for g in GENRES}  # Log-space accumulator

    fields = [
        ("focal_length", "focal_length"),
        ("aperture", "aperture"),
        ("shutter", "shutter"),
        ("iso", "iso"),
    ]

    any_field_present = False
    for exif_key, prior_key in fields:
        value = exif.get(exif_key)
        if value is None or value <= 0:
            continue
        any_field_present = True
        log_val = math.log(value + 1e-10)

        for genre in GENRES:
            mean, std = _EXIF_PRIORS[genre][prior_key]
            # Log-Gaussian: log P(x|genre) = -0.5 * ((log_val - mean) / std)^2
            log_prob = -0.5 * ((log_val - mean) / std) ** 2
            result[genre] += log_prob

    if not any_field_present:
        # Uniform prior
        return {g: 1.0 / len(GENRES) for g in GENRES}

    # Convert from log-space to probability (softmax-style)
    max_val = max(result.values())
    exp_vals = {g: math.exp(result[g] - max_val) for g in GENRES}
    total = sum(exp_vals.values())
    return {g: exp_vals[g] / total for g in GENRES}


def _compute_yolo_evidence(detections: list[ObjectDetection], image_area: int) -> dict[str, float]:
    """Compute genre evidence from YOLO detections.

    Returns dict of genre -> unnormalized probability.
    """
    evidence = {g: 1.0 for g in GENRES}  # Start uniform

    if not detections or image_area == 0:
        # Uniform
        total = sum(evidence.values())
        return {g: evidence[g] / total for g in GENRES}

    has_animal = False
    has_person = False
    largest_person_ratio = 0.0
    person_count = 0

    for det in detections:
        det_area = det.bbox[2] * det.bbox[3]
        area_ratio = det_area / image_area

        if det.class_id in _ANIMAL_CLASS_IDS and area_ratio > 0.05:
            has_animal = True
            evidence["wildlife"] *= 3.0

        if det.class_name == "person":
            person_count += 1
            largest_person_ratio = max(largest_person_ratio, area_ratio)
            has_person = True

    # Person logic
    if has_person:
        if largest_person_ratio > 0.15:
            evidence["portrait"] *= 2.5
            evidence["event"] *= 1.5
        if person_count >= 3:
            evidence["event"] *= 2.0
            evidence["street"] *= 1.5
        elif person_count == 1 and largest_person_ratio < 0.05:
            evidence["street"] *= 1.5
            evidence["landscape"] *= 1.2

    # No living subjects
    if not has_animal and not has_person:
        evidence["landscape"] *= 1.5
        evidence["architecture"] *= 1.5
        evidence["macro"] *= 1.3

    # Normalize
    total = sum(evidence.values())
    return {g: evidence[g] / total for g in GENRES}


def _compute_clip_similarity(
    clip_embedding: np.ndarray,
    genre_prototypes: np.ndarray | None,
) -> dict[str, float]:
    """Compute genre probabilities from CLIP cosine similarity.

    genre_prototypes: shape (num_genres, 512) — precomputed text embeddings.
    Returns softmax over cosine similarities.
    """
    if genre_prototypes is None or np.allclose(clip_embedding, 0.0):
        # No CLIP signal — uniform
        return {g: 1.0 / len(GENRES) for g in GENRES}

    # Cosine similarity (embedding is already L2-normalized)
    similarities = genre_prototypes @ clip_embedding  # (num_genres,)

    # Temperature-scaled softmax
    temperature = 0.1
    exp_sim = np.exp((similarities - similarities.max()) / temperature)
    probs = exp_sim / exp_sim.sum()

    return {GENRES[i]: float(probs[i]) for i in range(len(GENRES))}


def route_genre(
    ctx: SubjectContext,
    genre_prototypes: np.ndarray | None = None,
) -> GenreResult:
    """Classify image genre using Bayesian product-of-experts.

    Fuses CLIP similarity, EXIF prior, and YOLO object evidence.
    Falls back to "general" when confidence is below threshold.

    Args:
        ctx: SubjectContext with CLIP embedding, detections, and EXIF.
        genre_prototypes: Precomputed genre prototype embeddings, shape (8, 512).
                          If None, CLIP evidence is uniform.

    Returns:
        GenreResult with top genre, confidence, and full distribution.
    """
    # Evidence source 1: CLIP
    clip_probs = _compute_clip_similarity(ctx.clip_embedding, genre_prototypes)

    # Evidence source 2: EXIF prior
    exif_probs = _compute_exif_prior(ctx.exif)

    # Evidence source 3: YOLO
    image_area = ctx.image_bgr.shape[0] * ctx.image_bgr.shape[1]
    yolo_probs = _compute_yolo_evidence(ctx.detections, image_area)

    # Bayesian product-of-experts fusion
    fused = {}
    for g in GENRES:
        fused[g] = clip_probs[g] * exif_probs[g] * yolo_probs[g]

    # Normalize
    total = sum(fused.values())
    if total > 0:
        distribution = {g: fused[g] / total for g in GENRES}
    else:
        distribution = {g: 1.0 / len(GENRES) for g in GENRES}

    # Find top genre
    top_genre = max(distribution, key=lambda g: distribution[g])
    confidence = distribution[top_genre]

    # Fallback to general if confidence is too low
    if confidence < _CONFIDENCE_THRESHOLD:
        top_genre = "general"
        confidence = distribution["general"]

    return GenreResult(
        genre=top_genre,
        confidence=confidence,
        distribution=distribution,
    )
