"""Unit tests for FR-1.4: Laplacian variance sharpness scoring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from photo_workflow.sharpness import score_sharpness


def test_sharp_image_scores_high() -> None:
    """High-gradient image (sharp) → score close to 1.0."""
    # Random noise produces very high Tenengrad + SML values → saturates at 1.0
    rng = np.random.default_rng(42)
    sharp_gray = rng.integers(0, 256, (100, 100), dtype=np.uint8)

    with patch("photo_workflow.raw_loader.load_gray", return_value=sharp_gray):
        score = score_sharpness(Path("/fake/sharp.jpg"))

    assert score == 1.0  # Should saturate at max


def test_blurry_image_scores_low() -> None:
    """Low-gradient image (blurry) → score well below 0.5."""
    blurry_gray = np.full((100, 100), 128, dtype=np.uint8)

    with patch("photo_workflow.raw_loader.load_gray", return_value=blurry_gray):
        score = score_sharpness(Path("/fake/blurry.jpg"))

    assert score < 0.1


def test_missing_image_returns_zero() -> None:
    """Unloadable image → score of 0.0."""
    with patch("cv2.imread", return_value=None):
        score = score_sharpness(Path("/nonexistent/image.jpg"))
    assert score == 0.0


def test_score_is_normalized() -> None:
    """Score must always be in [0.0, 1.0]."""
    # Extreme noise should still clamp to [0, 1]
    rng = np.random.default_rng(99)
    extreme_gray = rng.integers(0, 256, (200, 200), dtype=np.uint8)

    with patch("photo_workflow.raw_loader.load_gray", return_value=extreme_gray):
        score = score_sharpness(Path("/fake/extreme.jpg"))

    assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Fixture-backed tests (real synthetic images, no mocks)
# ---------------------------------------------------------------------------

def test_fixture_sharp_scores_high(sharp_image: Path) -> None:
    """Checkerboard PNG (high-frequency) scores > 0.5."""
    score = score_sharpness(sharp_image)
    assert score > 0.5, f"Expected sharp score > 0.5, got {score}"


def test_fixture_blurry_scores_low(blurry_image: Path) -> None:
    """Solid-gray PNG (no edges) scores < 0.05."""
    score = score_sharpness(blurry_image)
    assert score < 0.05, f"Expected blurry score < 0.05, got {score}"


@pytest.mark.slow
def test_batch_memory_under_500mb(sharp_image: Path, tmp_path: Path) -> None:
    """KPM guard: RSS delta for 50-image batch must stay below 500 MB."""
    import shutil
    from memory_profiler import memory_usage  # type: ignore[import-untyped]

    paths = []
    for i in range(50):
        dst = tmp_path / f"img_{i:03d}.png"
        shutil.copy(sharp_image, dst)
        paths.append(dst)

    def run_batch() -> None:
        for p in paths:
            score_sharpness(p)

    mem: list[float] = memory_usage(run_batch, interval=0.05, retval=False)  # type: ignore[assignment]
    peak_delta_mb = max(mem) - min(mem)
    assert peak_delta_mb < 500, f"Batch RSS delta {peak_delta_mb:.1f} MB >= 500 MB"
