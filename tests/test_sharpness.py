"""Unit tests for FR-1.4: Laplacian variance sharpness scoring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from photo_workflow.sharpness import score_sharpness, BLUR_THRESHOLD


def test_sharp_image_scores_high() -> None:
    """High-variance image (sharp) → score close to 1.0."""
    # Simulate a high-variance Laplacian (sharp image)
    fake_lap = np.random.randn(100, 100) * 50.0  # variance ~2500

    with patch("cv2.imread", return_value=np.zeros((100, 100), dtype=np.uint8)), \
         patch("cv2.Laplacian", return_value=fake_lap):
        score = score_sharpness(Path("/fake/sharp.jpg"))

    assert score == 1.0  # Should saturate at max


def test_blurry_image_scores_low() -> None:
    """Low-variance image (blurry) → score well below 0.5."""
    fake_lap = np.ones((100, 100)) * 0.1  # variance near 0

    with patch("cv2.imread", return_value=np.zeros((100, 100), dtype=np.uint8)), \
         patch("cv2.Laplacian", return_value=fake_lap):
        score = score_sharpness(Path("/fake/blurry.jpg"))

    assert score < 0.1


def test_missing_image_returns_zero() -> None:
    """Unloadable image → score of 0.0."""
    with patch("cv2.imread", return_value=None):
        score = score_sharpness(Path("/nonexistent/image.jpg"))
    assert score == 0.0


def test_score_is_normalized() -> None:
    """Score must always be in [0.0, 1.0]."""
    fake_lap = np.random.randn(200, 200) * 1000.0  # extreme variance

    with patch("cv2.imread", return_value=np.zeros((200, 200), dtype=np.uint8)), \
         patch("cv2.Laplacian", return_value=fake_lap):
        score = score_sharpness(Path("/fake/extreme.jpg"))

    assert 0.0 <= score <= 1.0
