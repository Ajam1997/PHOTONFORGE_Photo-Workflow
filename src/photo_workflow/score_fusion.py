"""Genre-weighted score fusion — combines sub-scores into master score."""

from __future__ import annotations

import logging

from .scoring_types import (
    CompositionScores,
    ExposureScores,
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
    "general": {
        "subject_sharpness": 0.20, "exposure_overall": 0.18,
        "composition_rot": 0.15, "subject_isolation": 0.12,
        "aesthetic_clip": 0.10, "negative_space": 0.10,
        "balance": 0.08, "symmetry": 0.07,
    },
}


def _build_sub_score_dict(
    sharpness: SharpnessScores,
    composition: CompositionScores,
    exposure: ExposureScores,
    aesthetic: float,
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
    scores["expression_proxy"] = 0.7 if exposure.face_exposure >= 0 else 0.5
    scores["behavior_proxy"] = 1.0 if sharpness.blur_type == "motion_subject" else 0.5
    scores["color_contrast"] = composition.subject_isolation

    return scores


def _compute_master_score(
    sub_scores: dict[str, float],
    genre: GenreResult,
) -> float:
    """Compute the genre-weighted master score via soft blending."""
    effective_weights: dict[str, float] = {}

    for genre_name, prob in genre.distribution.items():
        if genre_name not in GENRE_WEIGHTS:
            continue
        for key, weight in GENRE_WEIGHTS[genre_name].items():
            effective_weights[key] = effective_weights.get(key, 0.0) + prob * weight

    master = 0.0
    for key, weight in effective_weights.items():
        if key in sub_scores:
            master += weight * sub_scores[key]

    return max(0.0, min(1.0, master))


def _check_hard_gates(sharpness: SharpnessScores) -> tuple[bool, str]:
    """Check hard rejection gates."""
    if sharpness.blur_type == "motion_global" and sharpness.subject < 0.2:
        return True, "motion_global_blur"
    if sharpness.blur_type == "misfocused" and sharpness.eye_region < 0.15:
        return True, "misfocused"
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
) -> FusionResult:
    """Fuse all sub-scores into a genre-weighted master score.

    Args:
        sharpness: Enhanced sharpness analysis results.
        composition: Enhanced composition analysis results.
        exposure: Enhanced exposure analysis results.
        genre: Genre classification result with probability distribution.
        aesthetic: CLIP aesthetic head score in [0, 1].

    Returns:
        FusionResult with master score, sub-scores, and classification labels.
    """
    sub_scores = _build_sub_score_dict(sharpness, composition, exposure, aesthetic)
    hard_reject, reject_reason = _check_hard_gates(sharpness)
    master_score = _compute_master_score(sub_scores, genre)
    star_rating = _score_to_stars(master_score)
    color_label = _score_to_color_label(master_score, hard_reject)

    return FusionResult(
        master_score=round(master_score, 4),
        genre=genre.genre,
        genre_confidence=round(genre.confidence, 4),
        sub_scores=sub_scores,
        hard_reject=hard_reject,
        hard_reject_reason=reject_reason,
        star_rating=star_rating,
        color_label=color_label,
    )
