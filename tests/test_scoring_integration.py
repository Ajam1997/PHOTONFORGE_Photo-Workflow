# tests/test_scoring_integration.py
"""Integration tests for the full genre-aware scoring flow."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from photo_workflow.scoring_types import FusionResult
from photo_workflow.subject_context import ModelSessions, build_subject_context
from photo_workflow.genre_router import route_genre
from photo_workflow.sharpness import score_sharpness_detailed
from photo_workflow.composition import score_composition_detailed
from photo_workflow.exposure import score_exposure_detailed
from photo_workflow.score_fusion import fuse_scores


@pytest.fixture
def sharp_color_image(tmp_path: Path) -> Path:
    """Create a sharp color image with high-frequency edges throughout.

    Uses seeded random noise rather than a 1-pixel checkerboard because
    the perfect alternating pattern produces zero Sobel response (the 3×3
    kernel neighbourhood cancels symmetrically).  Random noise has strong
    gradients everywhere → high Tenengrad and SML scores.
    """
    rng = np.random.default_rng(42)
    arr = rng.integers(0, 256, (400, 600, 3), dtype=np.uint8)
    p = tmp_path / "sharp_color.png"
    Image.fromarray(arr).save(p)
    return p


@pytest.fixture
def blurry_color_image(tmp_path: Path) -> Path:
    """Create a uniformly blurry image."""
    arr = np.full((400, 600, 3), 128, dtype=np.uint8)
    # Add very slight noise (still effectively blurry)
    noise = np.random.randint(-3, 4, arr.shape, dtype=np.int16)
    arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    p = tmp_path / "blurry_color.png"
    Image.fromarray(arr).save(p)
    return p


@pytest.mark.integration
def test_full_scoring_flow_no_models(sharp_color_image: Path, tmp_path: Path) -> None:
    """Full scoring flow should work without any ML models (graceful degradation)."""
    model_sessions = ModelSessions(tmp_path / "empty_models")
    ctx = build_subject_context(sharp_color_image, model_sessions)

    genre_result = route_genre(ctx)
    sharp = score_sharpness_detailed(ctx)
    comp = score_composition_detailed(ctx)
    expo = score_exposure_detailed(ctx)

    result = fuse_scores(sharp, comp, expo, genre_result, aesthetic=0.5)

    assert isinstance(result, FusionResult)
    assert 0.0 <= result.master_score <= 1.0
    assert result.genre in ("general", "landscape", "architecture", "wildlife",
                             "portrait", "street", "macro", "event")
    assert result.star_rating in range(1, 6)
    assert not result.hard_reject


@pytest.mark.integration
def test_sharp_scores_higher_than_blurry(
    sharp_color_image: Path, blurry_color_image: Path, tmp_path: Path
) -> None:
    """A sharp image should score higher than a blurry one."""
    model_sessions = ModelSessions(tmp_path / "empty_models")

    ctx_sharp = build_subject_context(sharp_color_image, model_sessions)
    genre_sharp = route_genre(ctx_sharp)
    s_sharp = score_sharpness_detailed(ctx_sharp)
    c_sharp = score_composition_detailed(ctx_sharp)
    e_sharp = score_exposure_detailed(ctx_sharp)
    result_sharp = fuse_scores(s_sharp, c_sharp, e_sharp, genre_sharp, 0.5)

    ctx_blurry = build_subject_context(blurry_color_image, model_sessions)
    genre_blurry = route_genre(ctx_blurry)
    s_blurry = score_sharpness_detailed(ctx_blurry)
    c_blurry = score_composition_detailed(ctx_blurry)
    e_blurry = score_exposure_detailed(ctx_blurry)
    result_blurry = fuse_scores(s_blurry, c_blurry, e_blurry, genre_blurry, 0.5)

    assert result_sharp.master_score > result_blurry.master_score


@pytest.mark.integration
def test_sub_scores_all_populated(sharp_color_image: Path, tmp_path: Path) -> None:
    """All expected sub-score keys should be present in the result."""
    model_sessions = ModelSessions(tmp_path / "empty_models")
    ctx = build_subject_context(sharp_color_image, model_sessions)
    genre = route_genre(ctx)
    sharp = score_sharpness_detailed(ctx)
    comp = score_composition_detailed(ctx)
    expo = score_exposure_detailed(ctx)
    result = fuse_scores(sharp, comp, expo, genre, 0.5)

    expected_keys = {
        "eye_sharpness", "subject_sharpness", "sharpness_contrast",
        "composition_rot", "symmetry", "leading_lines", "negative_space",
        "subject_isolation", "balance", "zone_entropy", "dynamic_range",
        "exposure_overall", "face_exposure", "aesthetic_clip",
        "front_to_back_sharp", "blur_type_penalty", "blur_type_bonus",
        "motion_tolerance", "highlight_clip", "expression_proxy",
        "behavior_proxy", "color_contrast",
    }
    assert expected_keys.issubset(set(result.sub_scores.keys()))
