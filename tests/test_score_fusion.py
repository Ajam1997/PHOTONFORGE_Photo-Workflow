"""Tests for genre-weighted score fusion."""

from __future__ import annotations

from photo_workflow.scoring_types import (
    SharpnessScores,
    CompositionScores,
    ExposureScores,
    GenreResult,
    FusionResult,
)
from photo_workflow.score_fusion import fuse_scores, GENRE_WEIGHTS


def _make_sharpness(**kwargs) -> SharpnessScores:
    defaults = dict(subject=0.7, eye_region=0.8, background=0.3,
                    sharpness_contrast=2.3, blur_type="bokeh", overall=0.7)
    defaults.update(kwargs)
    return SharpnessScores(**defaults)


def _make_composition(**kwargs) -> CompositionScores:
    defaults = dict(rule_of_thirds=0.6, symmetry=0.4, leading_lines=0.3,
                    negative_space=0.65, subject_isolation=0.7, balance=0.6, overall=0.55)
    defaults.update(kwargs)
    return CompositionScores(**defaults)


def _make_exposure(**kwargs) -> ExposureScores:
    defaults = dict(zone_entropy=0.8, zone_diversity=8, clipping_shadows=0.01,
                    clipping_highlights=0.02, dynamic_range=0.85, midtone_density=0.4,
                    face_exposure=-1.0, style="normal", style_confidence=0.0, overall=0.75)
    defaults.update(kwargs)
    return ExposureScores(**defaults)


def _make_genre(genre: str = "wildlife", confidence: float = 0.85) -> GenreResult:
    dist = {g: 0.02 for g in GENRE_WEIGHTS}
    dist[genre] = confidence
    # Normalize
    total = sum(dist.values())
    dist = {g: v / total for g, v in dist.items()}
    return GenreResult(genre=genre, confidence=dist[genre], distribution=dist)


def test_fuse_scores_returns_fusion_result() -> None:
    """fuse_scores should return a FusionResult."""
    result = fuse_scores(
        sharpness=_make_sharpness(),
        composition=_make_composition(),
        exposure=_make_exposure(),
        genre=_make_genre(),
        aesthetic=0.65,
    )
    assert isinstance(result, FusionResult)
    assert 0.0 <= result.master_score <= 1.0
    assert result.genre == "wildlife"
    assert result.star_rating in range(1, 6)


def test_genre_weights_all_sum_to_one() -> None:
    """Every genre weight profile should sum to 1.0."""
    for genre, weights in GENRE_WEIGHTS.items():
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01, f"{genre} weights sum to {total}"


def test_high_scores_produce_high_master() -> None:
    """All-high sub-scores should produce a high master score."""
    result = fuse_scores(
        sharpness=_make_sharpness(subject=0.95, eye_region=0.95, background=0.3, overall=0.9),
        composition=_make_composition(rule_of_thirds=0.9, subject_isolation=0.9, overall=0.85),
        exposure=_make_exposure(zone_entropy=0.9, dynamic_range=0.95, overall=0.9),
        genre=_make_genre("wildlife"),
        aesthetic=0.9,
    )
    assert result.master_score > 0.7
    assert result.star_rating >= 4


def test_low_scores_produce_low_master() -> None:
    """All-low sub-scores should produce a low master score."""
    result = fuse_scores(
        sharpness=_make_sharpness(subject=0.1, eye_region=0.1, background=0.1, overall=0.1),
        composition=_make_composition(rule_of_thirds=0.1, subject_isolation=0.1, overall=0.1),
        exposure=_make_exposure(zone_entropy=0.2, dynamic_range=0.2, overall=0.2),
        genre=_make_genre("wildlife"),
        aesthetic=0.2,
    )
    assert result.master_score < 0.3
    assert result.star_rating <= 2


def test_hard_reject_motion_global() -> None:
    """motion_global with low subject sharpness should hard reject."""
    result = fuse_scores(
        sharpness=_make_sharpness(subject=0.1, eye_region=0.1, blur_type="motion_global"),
        composition=_make_composition(),
        exposure=_make_exposure(),
        genre=_make_genre("wildlife"),
        aesthetic=0.7,
    )
    assert result.hard_reject is True
    assert "motion_global" in result.hard_reject_reason


def test_hard_reject_misfocused() -> None:
    """Misfocused with very low eye sharpness should hard reject."""
    result = fuse_scores(
        sharpness=_make_sharpness(eye_region=0.1, blur_type="misfocused"),
        composition=_make_composition(),
        exposure=_make_exposure(),
        genre=_make_genre("portrait"),
        aesthetic=0.7,
    )
    assert result.hard_reject is True
    assert "misfocused" in result.hard_reject_reason


def test_no_hard_reject_for_bokeh() -> None:
    """Bokeh should NOT trigger hard reject."""
    result = fuse_scores(
        sharpness=_make_sharpness(subject=0.8, blur_type="bokeh"),
        composition=_make_composition(),
        exposure=_make_exposure(),
        genre=_make_genre("portrait"),
        aesthetic=0.7,
    )
    assert result.hard_reject is False


def test_color_label_mapping() -> None:
    """Color labels should map correctly from master score."""
    # Excellent
    result = fuse_scores(
        sharpness=_make_sharpness(subject=0.95, eye_region=0.95, overall=0.9),
        composition=_make_composition(overall=0.85),
        exposure=_make_exposure(overall=0.9),
        genre=_make_genre("wildlife"),
        aesthetic=0.9,
    )
    assert result.color_label == 3  # BLUE (excellent)

    # Weak - all low scores
    result2 = fuse_scores(
        sharpness=_make_sharpness(subject=0.1, eye_region=0.1, background=0.1, overall=0.1),
        composition=_make_composition(rule_of_thirds=0.1, symmetry=0.1, leading_lines=0.1,
                                     negative_space=0.1, subject_isolation=0.1, balance=0.1, overall=0.1),
        exposure=_make_exposure(zone_entropy=0.1, dynamic_range=0.1, overall=0.1),
        genre=_make_genre("wildlife"),
        aesthetic=0.1,
    )
    assert result2.color_label == 1  # YELLOW (weak)


def test_soft_genre_blending() -> None:
    """Mixed genre probabilities should blend weights, not hard-switch."""
    # 50% wildlife, 50% portrait
    dist = {g: 0.0 for g in GENRE_WEIGHTS}
    dist["wildlife"] = 0.5
    dist["portrait"] = 0.5
    genre = GenreResult(genre="wildlife", confidence=0.5, distribution=dist)

    result = fuse_scores(
        sharpness=_make_sharpness(),
        composition=_make_composition(),
        exposure=_make_exposure(),
        genre=genre,
        aesthetic=0.6,
    )
    # Should still produce a valid result
    assert 0.0 <= result.master_score <= 1.0
