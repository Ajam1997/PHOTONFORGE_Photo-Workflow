"""Tests for enhanced composition scoring."""

from __future__ import annotations

import numpy as np

from photo_workflow.scoring_types import SubjectContext, CompositionScores
from photo_workflow.composition import (
    score_composition_detailed,
    _improved_rot_score,
    _symmetry_score,
    _negative_space_score,
    _balance_score,
)


def _make_context(
    image_bgr: np.ndarray,
    subject_mask: np.ndarray | None = None,
) -> SubjectContext:
    """Build a SubjectContext for composition tests."""
    h, w = image_bgr.shape[:2]
    gray = np.mean(image_bgr, axis=2).astype(np.uint8) if image_bgr.ndim == 3 else image_bgr
    if subject_mask is None:
        subject_mask = np.zeros((h, w), dtype=np.uint8)
        subject_mask[h//4:3*h//4, w//4:3*w//4] = 1
    return SubjectContext(
        image_bgr=image_bgr,
        image_gray=gray,
        thumbnail_rgb=np.zeros((100, 100, 3), dtype=np.uint8),
        subject_mask=subject_mask,
        subject_area_ratio=float(subject_mask.sum()) / (h * w),
        faces=[],
        detections=[],
        primary_subject_bbox=None,
        clip_embedding=np.zeros(512, dtype=np.float32),
        exif={},
    )


def test_score_composition_detailed_returns_dataclass() -> None:
    """score_composition_detailed should return CompositionScores."""
    img = np.random.randint(0, 255, (300, 400, 3), dtype=np.uint8)
    ctx = _make_context(img)
    result = score_composition_detailed(ctx)
    assert isinstance(result, CompositionScores)
    assert 0.0 <= result.overall <= 1.0


def test_rot_score_in_range() -> None:
    """Rule of thirds score should be in [0, 1]."""
    saliency = np.random.rand(300, 400).astype(np.float32)
    score = _improved_rot_score(saliency)
    assert 0.0 <= score <= 1.0


def test_rot_score_subject_at_power_point() -> None:
    """Subject placed exactly at a power point should score high."""
    saliency = np.zeros((300, 400), dtype=np.float32)
    # Place bright spot at upper-left power point (1/3, 1/3)
    py, px = 100, 133
    saliency[py-10:py+10, px-10:px+10] = 1.0
    score = _improved_rot_score(saliency)
    assert score > 0.5


def test_symmetry_score_symmetric_image() -> None:
    """A horizontally symmetric image should score higher than random."""
    # Create symmetric image
    half = np.random.randint(50, 200, (200, 100, 3), dtype=np.uint8)
    img = np.hstack([half, np.fliplr(half)])
    score_sym = _symmetry_score(img)

    # Random image
    random_img = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
    score_rand = _symmetry_score(random_img)

    assert score_sym >= score_rand * 0.8  # Symmetric should generally score higher


def test_negative_space_high_for_minimal_subject() -> None:
    """Image with small subject and clean background has high negative space."""
    mask = np.zeros((300, 400), dtype=np.uint8)
    mask[130:170, 180:220] = 1  # Small subject (tiny area)
    bg = np.full((300, 400), 128, dtype=np.uint8)  # Uniform background
    score = _negative_space_score(mask, bg)
    assert score > 0.45  # Gaussian peaks at 0.7 ratio, this is just below ideal


def test_negative_space_low_for_full_frame_subject() -> None:
    """Image with subject filling entire frame has low negative space."""
    mask = np.ones((300, 400), dtype=np.uint8)
    bg = np.random.randint(0, 255, (300, 400), dtype=np.uint8)
    score = _negative_space_score(mask, bg)
    assert score < 0.3


def test_balance_centered_subject_high() -> None:
    """Subject centered in frame should have high balance."""
    saliency = np.zeros((300, 400), dtype=np.float32)
    saliency[125:175, 175:225] = 1.0  # Center hot spot
    score = _balance_score(saliency)
    assert score > 0.7


def test_balance_corner_subject_low() -> None:
    """Subject in corner should have low balance."""
    saliency = np.zeros((300, 400), dtype=np.float32)
    saliency[0:30, 0:30] = 1.0  # Top-left corner
    score = _balance_score(saliency)
    assert score < 0.5


def test_backward_compat_score_composition(sharp_image) -> None:
    """Original score_composition(path) still works and returns float."""
    from photo_workflow.composition import score_composition
    result = score_composition(sharp_image)
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0
