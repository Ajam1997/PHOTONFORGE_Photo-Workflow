"""Genre-weighted score fusion — combines sub-scores into master score."""

from __future__ import annotations

import logging

import numpy as np

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

GENRE_WEIGHTS: dict[str, dict[str, float]] = {
    "wildlife": {
        "eye_sharpness": 0.28, "subject_sharpness": 0.12,
        "subject_isolation": 0.10, "composition_rot": 0.10,
        "negative_space": 0.08, "exposure_overall": 0.12,
        "blur_type_penalty": 0.08, "aesthetic_clip": 0.07,
        "behavior_proxy": 0.05,
    },
    "landscape": {
        "zone_entropy": 0.12, "dynamic_range": 0.12,
        "front_to_back_sharp": 0.16, "composition_rot": 0.10,
        "leading_lines": 0.10, "negative_space": 0.08,
        "balance": 0.08, "highlight_clip": 0.10,
        "aesthetic_clip": 0.08, "symmetry": 0.06,
    },
    "portrait": {
        "eye_sharpness": 0.25, "face_exposure": 0.12,
        "subject_isolation": 0.12, "composition_rot": 0.10,
        "negative_space": 0.10, "blur_type_bonus": 0.08,
        "expression_proxy": 0.08, "balance": 0.07,
        "aesthetic_clip": 0.08,
    },
    "street": {
        "subject_sharpness": 0.18, "composition_rot": 0.12,
        "leading_lines": 0.12, "subject_isolation": 0.10,
        "exposure_overall": 0.12, "negative_space": 0.08,
        "motion_tolerance": 0.08, "aesthetic_clip": 0.10,
        "balance": 0.05, "symmetry": 0.05,
    },
    "architecture": {
        "symmetry": 0.18, "leading_lines": 0.16,
        "subject_sharpness": 0.15, "exposure_overall": 0.12,
        "composition_rot": 0.10, "balance": 0.10,
        "negative_space": 0.07, "highlight_clip": 0.07,
        "aesthetic_clip": 0.05,
    },
    "macro": {
        "subject_sharpness": 0.25, "sharpness_contrast": 0.15,
        "negative_space": 0.12, "subject_isolation": 0.12,
        "composition_rot": 0.10, "exposure_overall": 0.08,
        "balance": 0.06, "aesthetic_clip": 0.07,
        "color_contrast": 0.05,
    },
    "event": {
        "eye_sharpness": 0.20, "face_exposure": 0.12,
        "expression_proxy": 0.18, "subject_sharpness": 0.15,
        "composition_rot": 0.10, "exposure_overall": 0.10,
        "aesthetic_clip": 0.08, "balance": 0.07,
    },
    # Waterfall: leading lines (flow), motion tolerance (long-exposure silk),
    # sharp surrounding rock, balanced composition. Sits between landscape
    # and macro in subject-emphasis terms.
    "waterfall": {
        "leading_lines": 0.15, "subject_sharpness": 0.15,
        "composition_rot": 0.12, "motion_tolerance": 0.12,
        "exposure_overall": 0.10, "dynamic_range": 0.10,
        "balance": 0.08, "negative_space": 0.08,
        "aesthetic_clip": 0.08, "highlight_clip": 0.02,
    },
    "general": {
        "subject_sharpness": 0.20, "exposure_overall": 0.18,
        "composition_rot": 0.15, "subject_isolation": 0.12,
        "aesthetic_clip": 0.10, "negative_space": 0.10,
        "balance": 0.08, "symmetry": 0.07,
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
    """Compute the genre-weighted master score via soft blending.

    Blends GENRE_WEIGHTS across all entries in genre.genres,
    weighted by their confidence scores (normalized to sum to 1).
    """
    # Normalize genre confidences so they sum to 1
    total_confidence = sum(conf for _, conf in genre.genres)
    if total_confidence <= 0:
        # Fallback to equal weighting
        normalized_genres = [(g, 1.0 / len(genre.genres)) for g, _ in genre.genres]
    else:
        normalized_genres = [(g, conf / total_confidence) for g, conf in genre.genres]

    effective_weights: dict[str, float] = {}

    # Accumulate weights from all genres in the list
    for genre_name, normalized_conf in normalized_genres:
        if genre_name not in GENRE_WEIGHTS:
            continue
        for key, weight in GENRE_WEIGHTS[genre_name].items():
            effective_weights[key] = effective_weights.get(key, 0.0) + normalized_conf * weight

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
    """Fuse all sub-scores into a genre-weighted master score.

    Args:
        sharpness: Enhanced sharpness analysis results.
        composition: Enhanced composition analysis results.
        exposure: Enhanced exposure analysis results.
        genre: Genre classification result with multi-genre list and distribution.
        aesthetic: CLIP aesthetic head score in [0, 1].

    Returns:
        FusionResult with master score, sub-scores, classification labels, and multi-genre data.
    """
    sub_scores = _build_sub_score_dict(
        sharpness, composition, exposure, aesthetic, faces, image_gray,
    )
    hard_reject, reject_reason = _check_hard_gates(sharpness, faces, image_gray)
    master_score = _compute_master_score(sub_scores, genre)
    star_rating = _score_to_stars(master_score)
    color_label = _score_to_color_label(master_score, hard_reject)

    return FusionResult(
        master_score=round(master_score, 4),
        genre=genre.primary_genre,  # Backward compatibility
        genre_confidence=round(genre.primary_confidence, 4),  # Backward compatibility
        sub_scores=sub_scores,
        hard_reject=hard_reject,
        hard_reject_reason=reject_reason,
        star_rating=star_rating,
        color_label=color_label,
        genres=genre.genres,  # Multi-genre data
        needs_review=genre.needs_review,
    )
