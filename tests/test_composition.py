"""Tests for FR-1.5: rule-of-thirds + saliency composition scoring (composition.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np

from photo_workflow.composition import score_composition, _improved_rot_score


def test_missing_image_returns_zero() -> None:
    """Unloadable image → score of 0.0."""
    with patch("cv2.imread", return_value=None):
        score = score_composition(Path("/nonexistent/image.jpg"))
    assert score == 0.0


def test_score_is_normalized() -> None:
    """Score must be in [0.0, 1.0]."""
    fake_img = np.zeros((100, 100, 3), dtype=np.uint8)
    fake_saliency = np.ones((100, 100), dtype=np.float32) * 0.5

    with patch("cv2.imread", return_value=fake_img), \
         patch("photo_workflow.composition._compute_saliency", return_value=fake_saliency):
        score = score_composition(Path("/fake/image.jpg"))

    assert 0.0 <= score <= 1.0


def test_saliency_failure_returns_valid_score() -> None:
    """If saliency computation raises, score uses fallback (empty saliency)."""
    fake_img = np.zeros((100, 100, 3), dtype=np.uint8)

    with patch("cv2.imread", return_value=fake_img), \
         patch("photo_workflow.composition._compute_saliency", side_effect=RuntimeError("fail")):
        score = score_composition(Path("/fake/image.jpg"))

    # Should return a valid score in [0,1], not crash
    assert 0.0 <= score <= 1.0


def test_uniform_saliency_returns_nonzero() -> None:
    """Uniform saliency map gives a deterministic non-zero score."""
    fake_img = np.zeros((300, 300, 3), dtype=np.uint8)
    # All saliency equal → power points have same density as everywhere else
    fake_saliency = np.ones((300, 300), dtype=np.float32)

    with patch("cv2.imread", return_value=fake_img), \
         patch("photo_workflow.composition._compute_saliency", return_value=fake_saliency):
        score = score_composition(Path("/fake/image.jpg"))

    assert score > 0.0


def test_rule_of_thirds_score_range() -> None:
    """_improved_rot_score always returns a value in [0.0, 1.0]."""
    for _ in range(10):
        saliency_map = np.random.rand(200, 300).astype(np.float32)
        score = _improved_rot_score(saliency_map)
        assert 0.0 <= score <= 1.0
