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
    "waterfall",
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
    # Waterfall: wide-to-mid focal lengths, narrow apertures (f/8-f/16),
    # shutter is bimodal (long-exposure silk OR fast-freeze droplets) so
    # std is wide; low ISO typical of tripod/landscape shooting.
    "waterfall": {
        "focal_length": (3.2, 0.7),
        "aperture": (2.3, 0.4),
        "shutter": (-2.0, 2.5),
        "iso": (4.6, 0.6),
    },
    "general": {
        "focal_length": (3.8, 1.5),
        "aperture": (1.5, 1.0),
        "shutter": (-5.0, 2.0),
        "iso": (5.5, 1.5),
    },
}

# Confidence threshold below which we fall back to "general"
_CONFIDENCE_THRESHOLD = 0.15  # Floor for top-3 genres

# Per-genre Gaussian priors for subject context (face_count, subject_area_ratio, primary class)
_SUBJECT_CONTEXT_PRIORS = {
    "wildlife": {
        "face_count": (0.0, 0.5),       # No faces
        "subject_area_ratio": (0.2, 0.15),  # Medium subject size
        "primary_class": {"bird": 1.5, "elephant": 1.5, "giraffe": 1.5},  # Multipliers
    },
    "landscape": {
        "face_count": (0.0, 0.5),       # No faces
        "subject_area_ratio": (0.1, 0.1),   # Small subject
        "primary_class": {},             # Indifferent to class
    },
    "portrait": {
        "face_count": (1.0, 0.3),       # One face
        "subject_area_ratio": (0.2, 0.1),   # Focused face
        "primary_class": {"person": 2.0},   # Person preferred
    },
    "street": {
        "face_count": (0.5, 0.4),       # Few faces
        "subject_area_ratio": (0.15, 0.1),  # Mixed subject size
        "primary_class": {"person": 1.3},
    },
    "architecture": {
        "face_count": (0.0, 0.5),       # No faces
        "subject_area_ratio": (0.25, 0.15), # Medium-large
        "primary_class": {},             # Indifferent
    },
    "macro": {
        "face_count": (0.0, 0.5),       # No faces
        "subject_area_ratio": (0.4, 0.15),  # Large subject zoom
        "primary_class": {"insect": 1.5, "flower": 1.5},
    },
    "event": {
        "face_count": (3.0, 1.0),       # Multiple faces
        "subject_area_ratio": (0.2, 0.15),  # Varied
        "primary_class": {"person": 1.5},
    },
    "waterfall": {
        "face_count": (0.0, 0.5),       # No faces
        "subject_area_ratio": (0.3, 0.2),   # Waterfall fills mid-to-large frame
        "primary_class": {},             # YOLO COCO has no waterfall class
    },
    "general": {
        "face_count": (0.5, 1.0),       # Uniform (any)
        "subject_area_ratio": (0.2, 0.2),   # Uniform
        "primary_class": {},             # Indifferent
    },
}

# Per-genre sharpness profile (subject/background contrast preference)
_SHARPNESS_PROFILE_PRIORS = {
    "wildlife": (2.5, 1.0),   # High contrast preferred
    "landscape": (1.0, 0.5),  # Uniform sharpness
    "portrait": (3.0, 1.2),   # High contrast (bokeh)
    "street": (1.5, 0.8),     # Moderate contrast
    "architecture": (1.0, 0.5),  # Uniform
    "macro": (3.5, 1.2),      # Very high contrast
    "event": (1.5, 0.8),      # Moderate contrast
    "waterfall": (1.3, 0.7),  # Mostly uniform; rocks sharp, water motion-blurred
    "general": (1.5, 1.0),    # Moderate baseline
}


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


def _compute_subject_context_likelihood(ctx: SubjectContext) -> dict[str, float]:
    """Compute per-genre likelihood from subject context.

    Uses face_count, subject_area_ratio, and primary detection class.
    Returns dict of genre -> unnormalized probability.
    """
    face_count = len(ctx.faces)
    area_ratio = ctx.subject_area_ratio

    # Determine primary detection class
    primary_class = ""
    if ctx.detections:
        largest = max(ctx.detections, key=lambda d: d.bbox[2] * d.bbox[3])
        primary_class = largest.class_name

    evidence = {g: 1.0 for g in GENRES}

    for genre in GENRES:
        priors = _SUBJECT_CONTEXT_PRIORS.get(genre, {})

        # Face count Gaussian likelihood
        face_mean, face_std = priors.get("face_count", (0.0, 1.0))
        face_diff = face_count - face_mean
        face_likelihood = math.exp(-0.5 * (face_diff / max(face_std, 0.1)) ** 2)
        evidence[genre] *= face_likelihood

        # Subject area ratio Gaussian likelihood
        area_mean, area_std = priors.get("subject_area_ratio", (0.2, 0.2))
        area_diff = area_ratio - area_mean
        area_likelihood = math.exp(-0.5 * (area_diff / max(area_std, 0.1)) ** 2)
        evidence[genre] *= area_likelihood

        # Primary class bonus (if applicable)
        if primary_class:
            class_bonus = priors.get("primary_class", {}).get(primary_class, 1.0)
            evidence[genre] *= class_bonus

    # Normalize
    total = sum(evidence.values())
    if total > 0:
        return {g: evidence[g] / total for g in GENRES}
    return {g: 1.0 / len(GENRES) for g in GENRES}


def _compute_sharpness_profile_likelihood(sharpness_contrast: float) -> dict[str, float]:
    """Compute per-genre likelihood from sharpness contrast.

    Higher contrast (subject sharp, background blurred) favors portrait/macro.
    Uniform sharpness favors landscape/architecture.
    Returns dict of genre -> unnormalized probability.
    """
    evidence = {g: 1.0 for g in GENRES}

    for genre in GENRES:
        mean, std = _SHARPNESS_PROFILE_PRIORS.get(genre, (1.5, 1.0))
        diff = sharpness_contrast - mean
        likelihood = math.exp(-0.5 * (diff / max(std, 0.1)) ** 2)
        evidence[genre] = likelihood

    # Normalize
    total = sum(evidence.values())
    if total > 0:
        return {g: evidence[g] / total for g in GENRES}
    return {g: 1.0 / len(GENRES) for g in GENRES}


def route_genre(
    ctx: SubjectContext,
    genre_prototypes: np.ndarray | None = None,
) -> GenreResult:
    """Classify image genre using 5-signal Bayesian product-of-experts.

    Fuses: CLIP similarity, EXIF prior, YOLO object evidence,
    subject context (faces/area/class), and sharpness profile.

    Returns top-3 genres above 0.15 floor, or [("general", 1.0)] with needs_review=True
    if nothing clears the threshold.

    Args:
        ctx: SubjectContext with CLIP embedding, detections, EXIF, and sharpness_contrast.
        genre_prototypes: Precomputed genre prototype embeddings, shape (8, 512).
                          If None, CLIP evidence is uniform.

    Returns:
        GenreResult with top-3 genres, full distribution, and needs_review flag.
    """
    # Evidence source 1: CLIP
    clip_probs = _compute_clip_similarity(ctx.clip_embedding, genre_prototypes)

    # Evidence source 2: EXIF prior
    exif_probs = _compute_exif_prior(ctx.exif)

    # Evidence source 3: YOLO
    image_area = ctx.image_bgr.shape[0] * ctx.image_bgr.shape[1]
    yolo_probs = _compute_yolo_evidence(ctx.detections, image_area)

    # Evidence source 4: Subject context (faces, area, class)
    subject_probs = _compute_subject_context_likelihood(ctx)

    # Evidence source 5: Sharpness profile
    sharpness_probs = _compute_sharpness_profile_likelihood(ctx.sharpness_contrast)

    # Bayesian product-of-experts fusion (5 signals)
    fused = {}
    for g in GENRES:
        fused[g] = (
            clip_probs[g] *
            exif_probs[g] *
            yolo_probs[g] *
            subject_probs[g] *
            sharpness_probs[g]
        )

    # Normalize
    total = sum(fused.values())
    if total > 0:
        distribution = {g: fused[g] / total for g in GENRES}
    else:
        distribution = {g: 1.0 / len(GENRES) for g in GENRES}

    # Extract top-3 above confidence floor (0.15)
    sorted_genres = sorted(distribution.items(), key=lambda x: x[1], reverse=True)
    top_3 = [(g, conf) for g, conf in sorted_genres if conf >= _CONFIDENCE_THRESHOLD]

    # If no genre clears the floor, return general with needs_review=True
    needs_review = False
    if not top_3:
        top_3 = [("general", 1.0)]
        needs_review = True

    return GenreResult(
        genres=top_3,
        distribution=distribution,
        needs_review=needs_review,
    )
