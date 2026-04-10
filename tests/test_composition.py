"""Tests for FR-1.5: rule-of-thirds + saliency composition scoring (composition.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from photo_workflow.composition import score_composition


def test_missing_image_returns_zero() -> None:
    """Unloadable image → score of 0.0."""
    with patch("cv2.imread", return_value=None):
        score = score_composition(Path("/nonexistent/image.jpg"))
    assert score == 0.0


def test_score_is_normalized() -> None:
    """Score must be in [0.0, 1.0]."""
    fake_img = np.zeros((100, 100, 3), dtype=np.uint8)
    fake_saliency = np.ones((100, 100), dtype=np.float32) * 0.5

    saliency_obj = MagicMock()
    saliency_obj.computeSaliency.return_value = (True, fake_saliency)

    with patch("cv2.imread", return_value=fake_img), \
         patch("cv2.saliency.StaticSaliencySpectralResidual_create", return_value=saliency_obj):
        score = score_composition(Path("/fake/image.jpg"))

    assert 0.0 <= score <= 1.0


def test_saliency_failure_returns_zero() -> None:
    """If saliency computation fails, score is 0.0."""
    fake_img = np.zeros((100, 100, 3), dtype=np.uint8)

    saliency_obj = MagicMock()
    saliency_obj.computeSaliency.return_value = (False, None)

    with patch("cv2.imread", return_value=fake_img), \
         patch("cv2.saliency.StaticSaliencySpectralResidual_create", return_value=saliency_obj):
        score = score_composition(Path("/fake/image.jpg"))

    assert score == 0.0


def test_uniform_saliency_returns_nonzero() -> None:
    """Uniform saliency map gives a deterministic non-zero score."""
    fake_img = np.zeros((300, 300, 3), dtype=np.uint8)
    # All saliency equal → power points have same density as everywhere else
    fake_saliency = np.ones((300, 300), dtype=np.float32)

    saliency_obj = MagicMock()
    saliency_obj.computeSaliency.return_value = (True, fake_saliency)

    with patch("cv2.imread", return_value=fake_img), \
         patch("cv2.saliency.StaticSaliencySpectralResidual_create", return_value=saliency_obj):
        score = score_composition(Path("/fake/image.jpg"))

    assert score > 0.0
