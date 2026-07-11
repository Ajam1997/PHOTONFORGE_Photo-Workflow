"""Tests for FR-1.6: luminance zone entropy exposure scoring (exposure.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np

from photo_workflow.exposure import score_exposure, NUM_ZONES


def test_num_zones_is_11() -> None:
    """FR-1.6 specifies 11-zone segmentation per CLAUDE.md."""
    assert NUM_ZONES == 11


def test_missing_image_returns_zero() -> None:
    """Unloadable image → score of 0.0."""
    with patch("cv2.imread", return_value=None):
        score = score_exposure(Path("/nonexistent/image.jpg"))
    assert score == 0.0


def test_flat_image_scores_low() -> None:
    """Solid-color image has near-zero entropy → low score."""
    flat = np.full((100, 100, 3), 128, dtype=np.uint8)

    with patch("cv2.imread", return_value=flat):
        score = score_exposure(Path("/fake/flat.jpg"))

    assert score < 0.2


def test_well_exposed_image_scores_high() -> None:
    """Image with values spread across all zones → score near 1.0."""
    # Create a gradient image covering full 0-255 luminance range
    gradient = np.tile(np.linspace(0, 255, 300, dtype=np.uint8), (100, 1))
    bgr = np.stack([gradient, gradient, gradient], axis=-1)

    with patch("cv2.imread", return_value=bgr):
        score = score_exposure(Path("/fake/gradient.jpg"))

    assert score > 0.8


def test_score_is_normalized() -> None:
    """Score must always be in [0.0, 1.0]."""
    random_img = np.random.randint(0, 256, (200, 200, 3), dtype=np.uint8)

    with patch("cv2.imread", return_value=random_img):
        score = score_exposure(Path("/fake/random.jpg"))

    assert 0.0 <= score <= 1.0
