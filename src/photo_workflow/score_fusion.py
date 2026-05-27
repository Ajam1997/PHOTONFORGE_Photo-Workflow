"""Two-axis genre-weighted score fusion — combines sub-scores into master score.

The master score blends weights from two independent axes:
  Subject (what's in the photo) — controls sharpness emphasis, eye/face priority
  Photo Type (composition style) — controls composition, exposure, aesthetic weights

Each axis contributes 50% of the effective weight profile.
"""

from __future__ import annotations

import logging

import numpy as np

from .genre_router import SUBJECTS, PHOTO_TYPES
from .scoring_types import (
    CompositionScores,
    ExposureScores,
    FaceDetection,
    FusionResult,
    GenreResult,
    SharpnessScores,
)

logger = logging.getLogger(__name__)

# Darktable color label constants
_DT_RED = 0
_DT_YELLOW = 1
_DT_GREEN = 2
_DT_BLUE = 3
_DT_PURPLE = 4
_DT_NONE = -1

SUBJECT_WEIGHTS: dict[str, dict[str, float]] = {
    "person": {
        "eye_sharpness": 0.25, "subject_sharpness": 0.15,
        "face_exposure": 0.15, "expression_proxy": 0.15,
        "exposure_overall": 0.10, "aesthetic_clip": 0.10,
        "blur_type_penalty": 0.05, "behavior_proxy": 0.05,
    },
    "people": {
        "eye_sharpness": 0.20, "expression_proxy": 0.18,
        "subject_sharpness": 0.15, "face_exposure": 0.12,
        "exposure_overall": 0.10, "aesthetic_clip": 0.10,
        "blur_type_penalty": 0.05, "behavior_proxy": 0.10,
    },
    "child": {
        "eye_sharpness": 0.22, "expression_proxy": 0.20,
        "subject_sharpness": 0.15, "face_exposure": 0.13,
        "exposure_overall": 0.10, "aesthetic_clip": 0.10,
        "blur_type_penalty": 0.05, "behavior_proxy": 0.05,
    },
    "wildlife": {
        "eye_sharpness": 0.28, "subject_sharpness": 0.15,
        "subject_isolation": 0.12, "exposure_overall": 0.10,
        "blur_type_penalty": 0.10, "aesthetic_clip": 0.10,
        "behavior_proxy": 0.15,
    },
    "pet": {
        "eye_sharpness": 0.28, "subject_sharpness": 0.18,
        "subject_isolation": 0.14, "exposure_overall": 0.10,
        "aesthetic_clip": 0.10, "blur_type_penalty": 0.05,
        "behavior_proxy": 0.15,
    },
    "plant": {
        "subject_sharpness": 0.25, "subject_isolation": 0.20,
        "aesthetic_clip": 0.15, "color_contrast": 0.15,
        "exposure_overall": 0.10, "blur_type_penalty": 0.05,
        "blur_type_bonus": 0.10,
    },
    "landscape": {
        "subject_sharpness": 0.20, "exposure_overall": 0.20,
        "aesthetic_clip": 0.20, "dynamic_range": 0.15,
        "highlight_clip": 0.10, "blur_type_penalty": 0.05,
        "color_contrast": 0.10,
    },
    "seascape": {
        "subject_sharpness": 0.20, "exposure_overall": 0.20,
        "aesthetic_clip": 0.20, "highlight_clip": 0.10,
        "dynamic_range": 0.15, "blur_type_penalty": 0.05,
        "color_contrast": 0.10,
    },
    "cityscape": {
        "subject_sharpness": 0.20, "exposure_overall": 0.20,
        "aesthetic_clip": 0.15, "leading_lines": 0.15,
        "highlight_clip": 0.10, "blur_type_penalty": 0.05,
        "symmetry": 0.15,
    },
    "building": {
        "subject_sharpness": 0.25, "exposure_overall": 0.20,
        "aesthetic_clip": 0.15, "highlight_clip": 0.10,
        "leading_lines": 0.10, "symmetry": 0.10,
        "blur_type_penalty": 0.10,
    },
    "vehicle": {
        "subject_sharpness": 0.30, "subject_isolation": 0.15,
        "exposure_overall": 0.15, "motion_tolerance": 0.15,
        "aesthetic_clip": 0.10, "highlight_clip": 0.05,
        "blur_type_penalty": 0.10,
    },
    "food": {
        "subject_sharpness": 0.25, "aesthetic_clip": 0.20,
        "color_contrast": 0.15, "exposure_overall": 0.15,
        "subject_isolation": 0.10, "blur_type_bonus": 0.10,
        "highlight_clip": 0.05,
    },
    "object": {
        "subject_sharpness": 0.25, "aesthetic_clip": 0.20,
        "exposure_overall": 0.15, "subject_isolation": 0.15,
        "color_contrast": 0.10, "blur_type_penalty": 0.05,
        "highlight_clip": 0.10,
    },
    "text": {
        "subject_sharpness": 0.35, "exposure_overall": 0.25,
        "highlight_clip": 0.10, "color_contrast": 0.10,
        "aesthetic_clip": 0.10, "blur_type_penalty": 0.10,
    },
    "night-sky": {
        "exposure_overall": 0.25, "dynamic_range": 0.20,
        "aesthetic_clip": 0.20, "subject_sharpness": 0.15,
        "highlight_clip": 0.10, "color_contrast": 0.10,
    },
    "abstract": {
        "aesthetic_clip": 0.30, "color_contrast": 0.20,
        "subject_sharpness": 0.15, "exposure_overall": 0.15,
        "blur_type_bonus": 0.10, "negative_space": 0.10,
    },
}

TYPE_WEIGHTS: dict[str, dict[str, float]] = {
    "portrait": {
        "composition_rot": 0.15, "negative_space": 0.15,
        "subject_isolation": 0.15, "blur_type_bonus": 0.15,
        "balance": 0.10, "aesthetic_clip": 0.15,
        "face_exposure": 0.15,
    },
    "candid": {
        "composition_rot": 0.15, "exposure_overall": 0.15,
        "aesthetic_clip": 0.15, "expression_proxy": 0.15,
        "balance": 0.10, "motion_tolerance": 0.10,
        "negative_space": 0.10, "face_exposure": 0.10,
    },
    "landscape": {
        "zone_entropy": 0.15, "dynamic_range": 0.15,
        "front_to_back_sharp": 0.15, "composition_rot": 0.10,
        "leading_lines": 0.10, "negative_space": 0.10,
        "balance": 0.10, "highlight_clip": 0.10,
        "symmetry": 0.05,
    },
    "street": {
        "composition_rot": 0.15, "leading_lines": 0.15,
        "negative_space": 0.10, "motion_tolerance": 0.10,
        "balance": 0.10, "aesthetic_clip": 0.15,
        "symmetry": 0.10, "exposure_overall": 0.15,
    },
    "wildlife": {
        "composition_rot": 0.15, "subject_isolation": 0.15,
        "aesthetic_clip": 0.15, "balance": 0.10,
        "negative_space": 0.15, "exposure_overall": 0.10,
        "blur_type_penalty": 0.10, "behavior_proxy": 0.10,
    },
    "macro": {
        "sharpness_contrast": 0.20, "negative_space": 0.15,
        "subject_isolation": 0.15, "composition_rot": 0.15,
        "balance": 0.10, "aesthetic_clip": 0.10,
        "color_contrast": 0.10, "exposure_overall": 0.05,
    },
    "architecture": {
        "symmetry": 0.20, "leading_lines": 0.20,
        "composition_rot": 0.15, "balance": 0.15,
        "negative_space": 0.10, "highlight_clip": 0.10,
        "aesthetic_clip": 0.10,
    },
    "action": {
        "motion_tolerance": 0.20, "composition_rot": 0.15,
        "exposure_overall": 0.15, "aesthetic_clip": 0.15,
        "subject_isolation": 0.10, "blur_type_penalty": 0.15,
        "balance": 0.10,
    },
    "aerial": {
        "composition_rot": 0.20, "balance": 0.18,
        "aesthetic_clip": 0.15, "symmetry": 0.15,
        "negative_space": 0.12, "exposure_overall": 0.10,
        "color_contrast": 0.10,
    },
    "long-exposure": {
        "motion_tolerance": 0.20, "composition_rot": 0.18,
        "dynamic_range": 0.15, "aesthetic_clip": 0.12,
        "balance": 0.10, "negative_space": 0.10,
        "highlight_clip": 0.10, "leading_lines": 0.05,
    },
    "still-life": {
        "aesthetic_clip": 0.22, "composition_rot": 0.18,
        "subject_isolation": 0.15, "balance": 0.15,
        "color_contrast": 0.10, "exposure_overall": 0.10,
        "negative_space": 0.10,
    },
    "documentary": {
        "expression_proxy": 0.20, "composition_rot": 0.15,
        "exposure_overall": 0.15, "aesthetic_clip": 0.15,
        "balance": 0.10, "face_exposure": 0.15,
        "negative_space": 0.10,
    },
}


_EYE_ROI_RADIUS = 10
_OPEN_EYE_VARIANCE_THRESHOLD = 400.0


def estimate_eye_openness(face: FaceDetection, image_gray: np.ndarray) -> float:
    """Estimate whether a face's eyes are open using local intensity variance.

    Open eyes contain iris/pupil/sclera contrast (high variance).
    Closed eyes show uniform eyelid skin (low variance).
    """
    h, w = image_gray.shape[:2]
    variances: list[float] = []

    for key in ("left_eye", "right_eye"):
        pt = face.landmarks.get(key)
        if pt is None:
            continue
        cx, cy = pt
        y0 = max(0, cy - _EYE_ROI_RADIUS)
        y1 = min(h, cy + _EYE_ROI_RADIUS)
        x0 = max(0, cx - _EYE_ROI_RADIUS)
        x1 = min(w, cx + _EYE_ROI_RADIUS)
        if y1 <= y0 or x1 <= x0:
            continue
        roi = image_gray[y0:y1, x0:x1].astype(np.float64)
        variances.append(float(np.var(roi)))

    if not variances:
        return 0.5

    per_eye = [min(v / _OPEN_EYE_VARIANCE_THRESHOLD, 1.0) for v in variances]
    return float(sum(per_eye) / len(per_eye))


def _build_sub_score_dict(
    sharpness: SharpnessScores,
    composition: CompositionScores,
    exposure: ExposureScores,
    aesthetic: float,
    faces: list[FaceDetection] | None = None,
    image_gray: np.ndarray | None = None,
) -> dict[str, float]:
    """Map module outputs to the flat sub-score dictionary used by weight profiles."""
    scores: dict[str, float] = {
        "eye_sharpness": sharpness.eye_region,
        "subject_sharpness": sharpness.subject,
        "sharpness_contrast": min(sharpness.sharpness_contrast / 5.0, 1.0),
        "composition_rot": composition.rule_of_thirds,
        "symmetry": composition.symmetry,
        "leading_lines": composition.leading_lines,
        "negative_space": composition.negative_space,
        "subject_isolation": composition.subject_isolation,
        "balance": composition.balance,
        "zone_entropy": exposure.zone_entropy,
        "dynamic_range": exposure.dynamic_range,
        "exposure_overall": exposure.overall,
        "aesthetic_clip": aesthetic,
    }

    # Face exposure (use neutral 0.5 if no face)
    scores["face_exposure"] = exposure.face_exposure if exposure.face_exposure >= 0 else 0.5

    # Derived scores
    scores["front_to_back_sharp"] = min(sharpness.subject, sharpness.background)
    scores["blur_type_penalty"] = 0.0 if sharpness.blur_type in ("motion_global", "misfocused") else 1.0
    if sharpness.blur_type == "bokeh":
        scores["blur_type_bonus"] = 1.0
    elif sharpness.blur_type == "sharp":
        scores["blur_type_bonus"] = 0.5
    else:
        scores["blur_type_bonus"] = 0.0
    scores["motion_tolerance"] = 0.0 if sharpness.blur_type == "motion_global" else 1.0
    scores["highlight_clip"] = 1.0 - exposure.clipping_highlights
    if faces and image_gray is not None:
        openness_scores = [estimate_eye_openness(f, image_gray) for f in faces]
        scores["expression_proxy"] = max(openness_scores)
    else:
        scores["expression_proxy"] = 0.5
    scores["behavior_proxy"] = 1.0 if sharpness.blur_type == "motion_subject" else 0.5
    scores["color_contrast"] = composition.subject_isolation

    return scores


def _compute_master_score(
    sub_scores: dict[str, float],
    genre: GenreResult,
) -> float:
    """Compute the two-axis weighted master score.

    Each axis (subject, photo_type) contributes 50% of the effective weight
    profile.  The final score is the weighted sum of sub-scores.
    """
    subj = genre.subject if genre.subject in SUBJECT_WEIGHTS else SUBJECTS[0]
    ptype = genre.photo_type if genre.photo_type in TYPE_WEIGHTS else PHOTO_TYPES[0]

    effective_weights: dict[str, float] = {}

    for key, weight in SUBJECT_WEIGHTS[subj].items():
        effective_weights[key] = effective_weights.get(key, 0.0) + 0.5 * weight

    for key, weight in TYPE_WEIGHTS[ptype].items():
        effective_weights[key] = effective_weights.get(key, 0.0) + 0.5 * weight

    master = 0.0
    for key, weight in effective_weights.items():
        if key in sub_scores:
            master += weight * sub_scores[key]

    return max(0.0, min(1.0, master))


_EYES_CLOSED_THRESHOLD = 0.15


def _check_hard_gates(
    sharpness: SharpnessScores,
    faces: list[FaceDetection] | None = None,
    image_gray: np.ndarray | None = None,
) -> tuple[bool, str]:
    """Check hard rejection gates."""
    if sharpness.blur_type == "motion_global" and sharpness.subject < 0.2:
        return True, "motion_global_blur"
    if sharpness.blur_type == "misfocused" and sharpness.eye_region < 0.15:
        return True, "misfocused"
    if faces and image_gray is not None:
        if all(
            estimate_eye_openness(f, image_gray) < _EYES_CLOSED_THRESHOLD
            for f in faces
        ):
            return True, "all_eyes_closed"
    return False, ""


def _score_to_stars(master_score: float) -> int:
    """Map master score [0, 1] to star rating [1, 5]."""
    return max(1, min(5, round(master_score * 5)))


def _score_to_color_label(master_score: float, hard_reject: bool) -> int:
    """Map master score to Darktable color label.

    RED is reserved for duplicates (handled elsewhere).
    Hard rejects get the Darktable reject flag, not a color label.
    """
    if hard_reject:
        return _DT_NONE  # Reject flag is separate
    if master_score < 0.3:
        return _DT_YELLOW
    if master_score < 0.5:
        return _DT_NONE
    if master_score < 0.75:
        return _DT_GREEN
    return _DT_BLUE


def fuse_scores(
    sharpness: SharpnessScores,
    composition: CompositionScores,
    exposure: ExposureScores,
    genre: GenreResult,
    aesthetic: float,
    faces: list[FaceDetection] | None = None,
    image_gray: np.ndarray | None = None,
) -> FusionResult:
    """Fuse all sub-scores into a two-axis genre-weighted master score."""
    sub_scores = _build_sub_score_dict(
        sharpness, composition, exposure, aesthetic, faces, image_gray,
    )
    hard_reject, reject_reason = _check_hard_gates(sharpness, faces, image_gray)
    master_score = _compute_master_score(sub_scores, genre)
    star_rating = _score_to_stars(master_score)
    color_label = _score_to_color_label(master_score, hard_reject)

    return FusionResult(
        master_score=round(master_score, 4),
        subject=genre.subject,
        subject_confidence=round(genre.subject_confidence, 4),
        photo_type=genre.photo_type,
        type_confidence=round(genre.type_confidence, 4),
        sub_scores=sub_scores,
        hard_reject=hard_reject,
        hard_reject_reason=reject_reason,
        star_rating=star_rating,
        color_label=color_label,
        needs_review=genre.needs_review,
    )
