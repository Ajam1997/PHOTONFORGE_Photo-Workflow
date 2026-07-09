"""Genre router — two-axis CLIP + EXIF + YOLO Bayesian fusion.

Classifies each image along two orthogonal axes:
  Subject (what): 16 classes describing primary image content
  Photo Type (how): 11 classes describing photographic approach/technique
"""

from __future__ import annotations

import logging
import math

import numpy as np

from .scoring_types import GenreResult, ObjectDetection, SubjectContext

logger = logging.getLogger(__name__)

SUBJECTS = [
    "people",
    "pet",
    "wildlife",
    "plant",
    "landscape",
    "seascape",
    "sky",
    "cityscape",
    "building",
    "vehicle",
    "food",
    "object",
    "abstract",
    "monument",
    "waterfall",
]

PHOTO_TYPES = [
    "portrait",
    "candid",
    "scenic",
    "street",
    "macro",
    "architecture",
    "action",
    "aerial",
    "motion-blur",
    "still-life",
    "documentary",
]

# All unique labels from both axes. Used for training DB keys and backward compat.
ALL_LABELS = list(dict.fromkeys(SUBJECTS + PHOTO_TYPES))

# Backward compatibility alias

# Animal COCO class IDs: bird=14, cat=15, dog=16, horse=17, sheep=18, cow=19,
# elephant=20, bear=21, zebra=22, giraffe=23
_ANIMAL_CLASS_IDS = {14, 15, 16, 17, 18, 19, 20, 21, 22, 23}

# ---------------------------------------------------------------------------
# EXIF priors — split by axis
# ---------------------------------------------------------------------------

_SUBJECT_EXIF_PRIORS = {
    "people": {
        "focal_length": (3.9, 0.7), "aperture": (0.9, 0.6),
        "shutter": (-6.0, 0.9), "iso": (5.6, 0.8),
    },
    "pet": {
        "focal_length": (4.5, 0.8), "aperture": (0.8, 0.5),
        "shutter": (-6.5, 1.0), "iso": (6.0, 0.8),
    },
    "wildlife": {
        "focal_length": (5.7, 0.8), "aperture": (1.2, 0.5),
        "shutter": (-7.0, 1.0), "iso": (6.4, 0.8),
    },
    "plant": {
        "focal_length": (4.2, 0.8), "aperture": (1.2, 0.6),
        "shutter": (-5.5, 1.0), "iso": (5.5, 0.8),
    },
    "landscape": {
        "focal_length": (3.0, 0.8), "aperture": (2.2, 0.3),
        "shutter": (-3.0, 2.0), "iso": (4.6, 0.5),
    },
    "seascape": {
        "focal_length": (3.0, 0.8), "aperture": (2.2, 0.3),
        "shutter": (-3.0, 2.0), "iso": (4.6, 0.5),
    },
    # sky spans daytime cloud/sunset (fast, low ISO) through astro
    # (long shutter, high ISO); wide stds keep the prior weak.
    "sky": {
        "focal_length": (3.0, 1.0), "aperture": (1.3, 1.0),
        "shutter": (-3.0, 3.0), "iso": (6.0, 1.6),
    },
    "cityscape": {
        "focal_length": (3.5, 0.7), "aperture": (1.8, 0.4),
        "shutter": (-4.0, 2.0), "iso": (5.2, 0.7),
    },
    "building": {
        "focal_length": (3.0, 0.6), "aperture": (2.1, 0.3),
        "shutter": (-2.0, 2.0), "iso": (4.6, 0.5),
    },
    "vehicle": {
        "focal_length": (3.8, 0.7), "aperture": (1.5, 0.5),
        "shutter": (-6.0, 1.5), "iso": (5.5, 0.8),
    },
    "food": {
        "focal_length": (4.0, 0.6), "aperture": (1.2, 0.6),
        "shutter": (-5.5, 1.0), "iso": (4.6, 0.8),
    },
    "object": {
        "focal_length": (4.0, 0.7), "aperture": (1.8, 0.6),
        "shutter": (-5.0, 1.0), "iso": (5.0, 0.8),
    },
    "abstract": {
        "focal_length": (3.8, 1.0), "aperture": (1.5, 1.0),
        "shutter": (-5.0, 2.0), "iso": (5.5, 1.0),
    },
    # monument ~ building (mid focal, stopped-down, daylight)
    "monument": {
        "focal_length": (3.2, 0.7), "aperture": (2.0, 0.4),
        "shutter": (-3.0, 2.0), "iso": (4.8, 0.6),
    },
    # waterfall ~ landscape/seascape, often motion-blur (slow shutter)
    "waterfall": {
        "focal_length": (3.2, 0.8), "aperture": (2.2, 0.4),
        "shutter": (-3.5, 2.5), "iso": (4.6, 0.7),
    },
}

_TYPE_EXIF_PRIORS = {
    "portrait": {
        "focal_length": (4.2, 0.4), "aperture": (0.5, 0.5),
        "shutter": (-5.5, 0.8), "iso": (5.5, 0.8),
    },
    "candid": {
        "focal_length": (3.5, 0.6), "aperture": (1.2, 0.5),
        "shutter": (-5.5, 0.8), "iso": (5.8, 0.8),
    },
    "scenic": {
        "focal_length": (3.0, 0.6), "aperture": (2.2, 0.3),
        "shutter": (-3.0, 2.0), "iso": (4.6, 0.5),
    },
    "street": {
        "focal_length": (3.5, 0.5), "aperture": (1.4, 0.5),
        "shutter": (-6.0, 0.8), "iso": (6.2, 0.8),
    },
    "macro": {
        "focal_length": (4.3, 0.3), "aperture": (2.1, 0.3),
        "shutter": (-5.0, 0.8), "iso": (5.5, 0.8),
    },
    "architecture": {
        "focal_length": (3.0, 0.6), "aperture": (2.1, 0.3),
        "shutter": (-2.0, 2.0), "iso": (4.6, 0.5),
    },
    "action": {
        "focal_length": (4.8, 0.5), "aperture": (1.0, 0.5),
        "shutter": (-7.5, 0.8), "iso": (6.4, 0.8),
    },
    "aerial": {
        "focal_length": (3.2, 0.6), "aperture": (1.0, 0.5),
        "shutter": (-6.5, 0.8), "iso": (5.5, 0.8),
    },
    "motion-blur": {
        "focal_length": (3.5, 0.8), "aperture": (2.3, 0.4),
        "shutter": (1.5, 2.0), "iso": (4.0, 0.6),
    },
    "still-life": {
        "focal_length": (4.0, 0.6), "aperture": (1.8, 0.5),
        "shutter": (-4.5, 0.8), "iso": (4.6, 0.6),
    },
    "documentary": {
        "focal_length": (3.5, 0.6), "aperture": (1.2, 0.5),
        "shutter": (-5.0, 0.8), "iso": (6.0, 0.8),
    },
}

# An axis is "needs review" when its top-1 and top-2 probabilities differ by less
# than this margin (genuine ambiguity). Calibrated to the learned adapter's softmax
# spread: ~24% of a hard real folder (ICELAND) is flagged at 0.02, vs ~100% under
# the old absolute-confidence threshold.
_REVIEW_MARGIN = 0.02


def _top2_margin(dist: dict[str, float]) -> float:
    """Gap between the top-1 and top-2 probabilities of an axis distribution."""
    if len(dist) < 2:
        return 1.0
    top2 = sorted(dist.values(), reverse=True)[:2]
    return top2[0] - top2[1]

# ---------------------------------------------------------------------------
# Subject context priors — split by axis
# ---------------------------------------------------------------------------

_SUBJECT_CONTEXT_PRIORS = {
    "people": {
        "face_count": (1.5, 1.5),
        "subject_area_ratio": (0.18, 0.12),
        "primary_class": {"person": 2.2},
    },
    "wildlife": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.2, 0.15),
        "primary_class": {"bird": 1.5, "bear": 1.5, "elephant": 1.5, "giraffe": 1.5},
    },
    "pet": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.25, 0.15),
        "primary_class": {"cat": 3.0, "dog": 3.0},
    },
    "plant": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.3, 0.2),
        "primary_class": {"potted plant": 1.5},
    },
    "landscape": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.1, 0.1),
        "primary_class": {},
    },
    "seascape": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.1, 0.1),
        "primary_class": {"boat": 1.5},
    },
    "sky": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.1, 0.1),
        "primary_class": {},
    },
    "cityscape": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.1, 0.1),
        "primary_class": {},
    },
    "building": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.25, 0.15),
        "primary_class": {},
    },
    "vehicle": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.3, 0.2),
        "primary_class": {"car": 2.5, "truck": 2.5, "bus": 2.5, "motorcycle": 2.5},
    },
    "food": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.3, 0.2),
        "primary_class": {"bowl": 1.5, "cup": 1.5, "dining table": 1.5},
    },
    "object": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.3, 0.2),
        "primary_class": {},
    },
    "abstract": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.3, 0.2),
        "primary_class": {},
    },
    "monument": {
        "face_count": (0.0, 0.6),
        "subject_area_ratio": (0.3, 0.18),
        "primary_class": {"clock": 1.3},
    },
    "waterfall": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.25, 0.18),
        "primary_class": {},
    },
}

_TYPE_CONTEXT_PRIORS = {
    "portrait": {
        "face_count": (1.0, 0.3),
        "subject_area_ratio": (0.2, 0.1),
        "primary_class": {"person": 2.0},
    },
    "candid": {
        "face_count": (1.0, 0.5),
        "subject_area_ratio": (0.15, 0.1),
        "primary_class": {"person": 1.5},
    },
    "scenic": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.1, 0.1),
        "primary_class": {},
    },
    "street": {
        "face_count": (0.5, 0.4),
        "subject_area_ratio": (0.15, 0.1),
        "primary_class": {"person": 1.3},
    },
    "macro": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.4, 0.15),
        "primary_class": {},
    },
    "architecture": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.25, 0.15),
        "primary_class": {},
    },
    "action": {
        "face_count": (0.5, 0.5),
        "subject_area_ratio": (0.15, 0.1),
        "primary_class": {"person": 1.5, "sports ball": 1.3},
    },
    "aerial": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.1, 0.1),
        "primary_class": {},
    },
    "motion-blur": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.15, 0.15),
        "primary_class": {},
    },
    "still-life": {
        "face_count": (0.0, 0.5),
        "subject_area_ratio": (0.3, 0.2),
        "primary_class": {},
    },
    "documentary": {
        "face_count": (2.0, 1.0),
        "subject_area_ratio": (0.2, 0.15),
        "primary_class": {"person": 1.5},
    },
}

# ---------------------------------------------------------------------------
# Sharpness profile priors — split by axis
# ---------------------------------------------------------------------------

_SUBJECT_SHARPNESS_PRIORS = {
    "people": (1.8, 0.9),
    "pet": (2.5, 1.0),
    "wildlife": (2.5, 1.0),
    "plant": (2.0, 1.0),
    "landscape": (1.0, 0.5),
    "seascape": (1.0, 0.6),
    "sky": (0.8, 0.7),
    "cityscape": (1.0, 0.5),
    "building": (1.0, 0.5),
    "vehicle": (1.5, 0.8),
    "food": (2.0, 0.8),
    "object": (2.0, 0.8),
    "abstract": (1.5, 1.5),
    "monument": (1.2, 0.6),
    "waterfall": (1.0, 0.7),
}

_TYPE_SHARPNESS_PRIORS = {
    "portrait": (3.0, 1.2),
    "candid": (1.5, 0.8),
    "scenic": (1.0, 0.5),
    "street": (1.5, 0.8),
    "macro": (2.5, 1.0),
    "architecture": (1.0, 0.5),
    "action": (1.5, 1.0),
    "aerial": (1.0, 0.5),
    "motion-blur": (0.8, 0.5),
    "still-life": (2.0, 0.8),
    "documentary": (1.5, 0.8),
}


def _compute_exif_prior_axis(
    exif: dict,
    axis_labels: list[str],
    axis_priors: dict[str, dict[str, tuple[float, float]]],
) -> dict[str, float]:
    """Compute per-label log-Gaussian likelihood from EXIF metadata for one axis."""
    result = {g: 0.0 for g in axis_labels}

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

        for label in axis_labels:
            mean, std = axis_priors[label][prior_key]
            log_prob = -0.5 * ((log_val - mean) / std) ** 2
            result[label] += log_prob

    if not any_field_present:
        return {g: 1.0 / len(axis_labels) for g in axis_labels}

    max_val = max(result.values())
    exp_vals = {g: math.exp(result[g] - max_val) for g in axis_labels}
    total = sum(exp_vals.values())
    return {g: exp_vals[g] / total for g in axis_labels}


def _compute_yolo_evidence_subject(detections: list[ObjectDetection], image_area: int) -> dict[str, float]:
    """Compute subject-axis evidence from YOLO detections."""
    evidence = {g: 1.0 for g in SUBJECTS}

    if not detections or image_area == 0:
        total = sum(evidence.values())
        return {g: evidence[g] / total for g in SUBJECTS}

    has_animal = False
    has_person = False
    person_count = 0
    has_food = False

    for det in detections:
        det_area = det.bbox[2] * det.bbox[3]
        area_ratio = det_area / image_area

        if det.class_id in _ANIMAL_CLASS_IDS and area_ratio > 0.05:
            has_animal = True
            evidence["wildlife"] *= 3.0
            if det.class_id == 15:  # cat
                evidence["pet"] *= 4.0
            elif det.class_id == 16:  # dog
                evidence["pet"] *= 4.0

        if det.class_name in ("car", "truck", "bus", "motorcycle") and area_ratio > 0.05:
            evidence["vehicle"] *= 3.5

        if det.class_name == "person":
            has_person = True
            person_count += 1

        # Food detection (COCO classes 45-55)
        if det.class_id in (45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55):
            has_food = True
            evidence["food"] *= 3.0

    # Person presence logic (people is a single subject regardless of count)
    if person_count >= 1:
        evidence["people"] *= 2.5

    # Suppress incompatible labels
    if has_person:
        evidence["pet"] *= 0.3
        evidence["landscape"] *= 0.2

    if has_food:
        evidence["people"] *= 0.1

    if not has_animal and not has_person and not has_food:
        evidence["people"] *= 0.2
        evidence["pet"] *= 0.2

    total = sum(evidence.values())
    return {g: evidence[g] / total for g in SUBJECTS}


def _compute_yolo_evidence_type(
    detections: list[ObjectDetection],
    image_area: int,
) -> dict[str, float]:
    """Compute photo-type-axis evidence from YOLO detections."""
    evidence = {g: 1.0 for g in PHOTO_TYPES}

    if not detections or image_area == 0:
        total = sum(evidence.values())
        return {g: evidence[g] / total for g in PHOTO_TYPES}

    has_person = False
    largest_person_ratio = 0.0
    person_count = 0
    has_animal = False
    has_food = False

    for det in detections:
        det_area = det.bbox[2] * det.bbox[3]
        area_ratio = det_area / image_area

        if det.class_id in _ANIMAL_CLASS_IDS and area_ratio > 0.05:
            has_animal = True

        if det.class_name == "person":
            person_count += 1
            largest_person_ratio = max(largest_person_ratio, area_ratio)
            has_person = True

        # Action cues: sports ball (class 32), tennis racket (38), etc
        if det.class_id in (32, 38, 39, 41):  # sports ball, sports equipment classes
            evidence["action"] *= 2.0

        # Food detection
        if det.class_id in (45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55):
            has_food = True
            evidence["still-life"] *= 1.5

    if has_person:
        if largest_person_ratio > 0.15:
            evidence["portrait"] *= 2.5
            evidence["documentary"] *= 1.5
        if person_count >= 3:
            evidence["documentary"] *= 2.0
            evidence["street"] *= 1.5
        elif person_count == 1 or person_count == 2:
            if largest_person_ratio < 0.15:
                evidence["candid"] *= 2.0
                evidence["street"] *= 1.5
        if person_count >= 2 and largest_person_ratio < 0.3:
            evidence["candid"] *= 1.5

    if not has_person and not has_animal and not has_food:
        evidence["scenic"] *= 1.5
        evidence["architecture"] *= 1.5

    total = sum(evidence.values())
    return {g: evidence[g] / total for g in PHOTO_TYPES}


def _compute_clip_similarity_axis(
    clip_embedding: np.ndarray,
    prototypes: np.ndarray | None,
    axis_labels: list[str],
) -> dict[str, float]:
    """Compute axis probabilities from CLIP cosine similarity.

    prototypes: shape (len(axis_labels), 512).
    """
    if prototypes is None or np.allclose(clip_embedding, 0.0):
        return {g: 1.0 / len(axis_labels) for g in axis_labels}

    similarities = prototypes @ clip_embedding
    temperature = 0.35
    exp_sim = np.exp((similarities - similarities.max()) / temperature)
    probs = exp_sim / exp_sim.sum()

    return {axis_labels[i]: float(probs[i]) for i in range(len(axis_labels))}


# Cap on the squared z-score inside Gaussian-likelihood experts. Without it, an
# out-of-range feature value (e.g. a sharpness_contrast far from every prior mean)
# makes exp(-0.5*z**2) underflow to exactly 0 for all-but-one label, turning a soft
# prior into a one-hot veto that overrides CLIP in the product-of-experts fusion.
# Capping z**2 keeps each expert a bounded nudge (min factor exp(-_GAUSSIAN_Z2_CAP/2)).
_GAUSSIAN_Z2_CAP = 4.0

# Per-expert fusion weights in signal order [CLIP, EXIF, YOLO, context, sharpness].
# CLIP is the trained prototype signal and is weighted to dominate; the heuristic
# experts contribute as gentle nudges so a single miscalibrated one cannot hijack
# the result on out-of-distribution images.
_FUSION_WEIGHTS = [4.0, 1.0, 1.0, 1.0, 1.0]

# Each expert is blended this far toward uniform before fusion, bounding how hard
# any single expert can veto a label it assigns near-zero probability.
_EXPERT_SMOOTHING = 0.20


def _capped_gauss(diff: float, std: float) -> float:
    """Gaussian likelihood factor with the squared z-score capped (never 0)."""
    z2 = (diff / max(std, 0.1)) ** 2
    return math.exp(-0.5 * min(z2, _GAUSSIAN_Z2_CAP))


def _compute_context_likelihood_axis(
    ctx: SubjectContext,
    axis_labels: list[str],
    axis_priors: dict[str, dict],
) -> dict[str, float]:
    """Compute per-label likelihood from subject context for one axis."""
    face_count = len(ctx.faces)
    area_ratio = ctx.subject_area_ratio

    primary_class = ""
    if ctx.detections:
        largest = max(ctx.detections, key=lambda d: d.bbox[2] * d.bbox[3])
        primary_class = largest.class_name

    evidence = {g: 1.0 for g in axis_labels}

    for label in axis_labels:
        priors = axis_priors.get(label, {})

        face_mean, face_std = priors.get("face_count", (0.0, 1.0))
        evidence[label] *= _capped_gauss(face_count - face_mean, face_std)

        area_mean, area_std = priors.get("subject_area_ratio", (0.2, 0.2))
        evidence[label] *= _capped_gauss(area_ratio - area_mean, area_std)

        if primary_class:
            class_bonus = priors.get("primary_class", {}).get(primary_class, 1.0)
            evidence[label] *= class_bonus

    total = sum(evidence.values())
    if total > 0:
        return {g: evidence[g] / total for g in axis_labels}
    return {g: 1.0 / len(axis_labels) for g in axis_labels}


def _compute_sharpness_likelihood_axis(
    sharpness_contrast: float,
    axis_labels: list[str],
    axis_priors: dict[str, tuple[float, float]],
) -> dict[str, float]:
    """Compute per-label likelihood from sharpness contrast for one axis."""
    evidence = {g: 1.0 for g in axis_labels}

    for label in axis_labels:
        mean, std = axis_priors.get(label, (1.5, 1.0))
        evidence[label] = _capped_gauss(sharpness_contrast - mean, std)

    total = sum(evidence.values())
    if total > 0:
        return {g: evidence[g] / total for g in axis_labels}
    return {g: 1.0 / len(axis_labels) for g in axis_labels}


def _fuse_axis(
    signals: list[dict[str, float]],
    axis_labels: list[str],
    weights: list[float] | None = None,
) -> dict[str, float]:
    """Weighted product-of-experts fusion (log-space) for one axis.

    CLIP is the trained, reliable signal; the EXIF/YOLO/context/sharpness experts
    are weak heuristics that are noisy on out-of-distribution images. ``weights``
    lets the caller make CLIP dominant so a single miscalibrated heuristic can
    nudge but not override it. A small floor keeps log() finite.
    """
    n = len(axis_labels)
    if weights is None:
        weights = [1.0] * len(signals)
    uniform = 1.0 / n
    logp = {g: 0.0 for g in axis_labels}
    for sig, w in zip(signals, weights):
        # Smooth each expert toward uniform so a label it (wrongly) assigns ~0 to
        # cannot be vetoed — every expert becomes a bounded nudge, not a gate.
        for g in axis_labels:
            p = (1.0 - _EXPERT_SMOOTHING) * sig.get(g, uniform) + _EXPERT_SMOOTHING * uniform
            logp[g] += w * math.log(p)

    hi = max(logp.values())
    exp = {g: math.exp(logp[g] - hi) for g in axis_labels}
    total = sum(exp.values())
    if total > 0:
        return {g: exp[g] / total for g in axis_labels}
    return {g: uniform for g in axis_labels}


# ---------------------------------------------------------------------------
# EXIF motion-blur gate
# ---------------------------------------------------------------------------
# Folding all EXIF/YOLO/face aux features into the learned CLIP head was measured
# to be net-negative: on the 271-image corpus it dropped subject CV accuracy
# 0.882->0.768 and type 0.786->0.694, degrading nearly every class (the all-zero
# aux block on EXIF-less web images becomes a spurious source-of-image leak).
# The ONE genuine aux signal is the shutter speed for the motion-blur TYPE,
# which is near-deterministic. We apply just that, as a narrow high-precision
# post-classification gate. Measured on the corpus: shutter >= 0.5s predicts
# motion-blur with precision 0.94 / recall 0.83 (a single false positive, a
# tripod macro). See .claude/phase2_measure.py for the full ablation.
_MOTION_BLUR_SHUTTER_S = 0.5    # exposure time (s) at/above which the gate fires
_MOTION_BLUR_GATE_CONF = 0.80   # confidence assigned to motion-blur when it fires
                                # (conservative vs the measured 0.94 precision)


def _apply_motion_blur_gate(
    type_dist: dict[str, float],
    exif: dict | None,
) -> dict[str, float]:
    """Reassign the type distribution toward motion-blur on a slow shutter.

    Fires only when EXIF carries an exposure time >= ``_MOTION_BLUR_SHUTTER_S``.
    Raises motion-blur to ``_MOTION_BLUR_GATE_CONF`` (never lowers it) and
    rescales the remaining mass across the other types, preserving their relative
    order. A no-op when EXIF is absent or the shutter is fast.
    """
    shutter = (exif or {}).get("shutter")
    if not shutter or shutter < _MOTION_BLUR_SHUTTER_S:
        return type_dist
    current = type_dist.get("motion-blur", 0.0)
    if current >= _MOTION_BLUR_GATE_CONF:
        return type_dist
    remaining = 1.0 - _MOTION_BLUR_GATE_CONF
    others_total = sum(v for k, v in type_dist.items() if k != "motion-blur")
    out = {}
    for k, v in type_dist.items():
        if k == "motion-blur":
            out[k] = _MOTION_BLUR_GATE_CONF
        elif others_total > 0:
            out[k] = v / others_total * remaining
        else:
            out[k] = remaining / max(len(type_dist) - 1, 1)
    return out


def route_genre(
    ctx: SubjectContext,
    genre_prototypes: np.ndarray | None = None,
    adapter: dict | None = None,
) -> GenreResult:
    """Classify image along two orthogonal axes: Subject and Photo Type.

    Each axis runs independent product-of-experts fusion across CLIP, EXIF,
    YOLO, subject context, and sharpness signals.

    Args:
        ctx: SubjectContext with CLIP embedding, detections, EXIF, sharpness_contrast.
        genre_prototypes: Precomputed prototype embeddings with shape
            (len(SUBJECTS) + len(PHOTO_TYPES), 512).  First len(SUBJECTS)
            rows are subject prototypes, remaining are type prototypes.
            If None, CLIP evidence is uniform on both axes.

    Returns:
        GenreResult with subject, photo_type, confidences, distributions,
        and needs_review flag.
    """
    clip = ctx.clip_embedding
    have_clip = clip is not None and not np.allclose(clip, 0.0)
    use_adapter = (
        adapter is not None
        and adapter.get("subject") and adapter.get("type")
        and have_clip
    )

    if use_adapter:
        # Learned linear classifier on the CLIP embedding (replaces product-of-experts).
        from .genre_adapter import predict_axis

        subj_dist = predict_axis(clip, adapter["subject"], SUBJECTS)
        type_dist = predict_axis(clip, adapter["type"], PHOTO_TYPES)
    else:
        # Fallback: product-of-experts over CLIP prototypes + heuristic priors.
        subject_protos = None
        type_protos = None
        if genre_prototypes is not None:
            n_subjects = len(SUBJECTS)
            if genre_prototypes.shape[0] >= n_subjects + len(PHOTO_TYPES):
                subject_protos = genre_prototypes[:n_subjects]
                type_protos = genre_prototypes[n_subjects:]
            else:
                logger.warning(
                    "genre_prototypes shape %s does not match expected (%d, 512); "
                    "using uniform CLIP priors",
                    genre_prototypes.shape,
                    len(SUBJECTS) + len(PHOTO_TYPES),
                )

        image_area = ctx.image_bgr.shape[0] * ctx.image_bgr.shape[1]

        # --- Subject axis signals --------------------------------------------
        subj_clip  = _compute_clip_similarity_axis(clip, subject_protos, SUBJECTS)
        subj_exif  = _compute_exif_prior_axis(ctx.exif, SUBJECTS, _SUBJECT_EXIF_PRIORS)
        subj_yolo  = _compute_yolo_evidence_subject(ctx.detections, image_area)
        subj_ctx   = _compute_context_likelihood_axis(ctx, SUBJECTS, _SUBJECT_CONTEXT_PRIORS)
        subj_sharp = _compute_sharpness_likelihood_axis(ctx.sharpness_contrast, SUBJECTS, _SUBJECT_SHARPNESS_PRIORS)

        subj_dist = _fuse_axis([subj_clip, subj_exif, subj_yolo, subj_ctx, subj_sharp], SUBJECTS,
                               weights=_FUSION_WEIGHTS)

        # --- Type axis signals -----------------------------------------------
        type_clip  = _compute_clip_similarity_axis(clip, type_protos, PHOTO_TYPES)
        type_exif  = _compute_exif_prior_axis(ctx.exif, PHOTO_TYPES, _TYPE_EXIF_PRIORS)
        type_yolo  = _compute_yolo_evidence_type(ctx.detections, image_area)
        type_ctx   = _compute_context_likelihood_axis(ctx, PHOTO_TYPES, _TYPE_CONTEXT_PRIORS)
        type_sharp = _compute_sharpness_likelihood_axis(ctx.sharpness_contrast, PHOTO_TYPES, _TYPE_SHARPNESS_PRIORS)

        type_dist = _fuse_axis([type_clip, type_exif, type_yolo, type_ctx, type_sharp], PHOTO_TYPES,
                               weights=_FUSION_WEIGHTS)

    # --- EXIF motion-blur gate (high-precision aux signal) -----------------
    type_dist = _apply_motion_blur_gate(type_dist, ctx.exif)

    # --- Pick winners --------------------------------------------------------
    subject = max(subj_dist, key=subj_dist.__getitem__)
    subject_conf = subj_dist[subject]
    photo_type = max(type_dist, key=type_dist.__getitem__)
    type_conf = type_dist[photo_type]

    # needs_review flags genuine ambiguity, not low absolute confidence. The
    # learned adapter spreads calibrated probability over 15 subjects / 11 types,
    # so a confident top pick is often only ~0.25-0.35 — an absolute threshold
    # (the old 0.45) flagged ~everything. Instead flag when the top-1 and top-2 on
    # either axis are nearly tied (small margin), which is scale-invariant and
    # works for both the adapter and the peaked PoE-fallback distributions.
    subj_margin = _top2_margin(subj_dist)
    type_margin = _top2_margin(type_dist)
    needs_review = subj_margin < _REVIEW_MARGIN or type_margin < _REVIEW_MARGIN

    return GenreResult(
        subject=subject,
        subject_confidence=round(subject_conf, 4),
        photo_type=photo_type,
        type_confidence=round(type_conf, 4),
        subject_distribution=subj_dist,
        type_distribution=type_dist,
        needs_review=needs_review,
    )
