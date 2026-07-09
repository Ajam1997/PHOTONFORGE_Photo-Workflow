"""Tests for enhanced subject-aware sharpness scoring."""

from __future__ import annotations

import numpy as np

from photo_workflow.scoring_types import SubjectContext, SharpnessScores
from photo_workflow.sharpness import score_sharpness_detailed, _tenengrad, _sml, _classify_blur


def _make_context(
    image_gray: np.ndarray,
    subject_mask: np.ndarray | None = None,
) -> SubjectContext:
    """Helper to build a SubjectContext with a grayscale image."""
    h, w = image_gray.shape
    if subject_mask is None:
        # Default: center 50% is subject
        subject_mask = np.zeros((h, w), dtype=np.uint8)
        sh, sw = h // 4, w // 4
        subject_mask[sh:3*sh, sw:3*sw] = 1
    bgr = np.stack([image_gray] * 3, axis=-1)
    return SubjectContext(
        image_bgr=bgr,
        image_gray=image_gray,
        thumbnail_rgb=np.zeros((100, 100, 3), dtype=np.uint8),
        subject_mask=subject_mask,
        subject_area_ratio=float(subject_mask.sum()) / (h * w),
        faces=[],
        detections=[],
        primary_subject_bbox=None,
        clip_embedding=np.zeros(512, dtype=np.float32),
        exif={},
    )


def test_tenengrad_sharp_image_high() -> None:
    """High-frequency pattern with gradients should have high Tenengrad."""
    # Create a pattern with actual gradients (diagonal stripes)
    arr = np.zeros((256, 256), dtype=np.uint8)
    for i in range(256):
        arr[i, :] = (i % 20) * 12  # Repeating gradient pattern
    score = _tenengrad(arr)
    assert score > 100.0


def test_tenengrad_uniform_image_low() -> None:
    """Solid gray image should have near-zero Tenengrad."""
    arr = np.full((256, 256), 128, dtype=np.uint8)
    score = _tenengrad(arr)
    assert score < 1.0


def test_sml_sharp_image_high() -> None:
    """High-frequency image should have high SML."""
    # Create a pattern with actual gradients (diagonal stripes)
    arr = np.zeros((256, 256), dtype=np.uint8)
    for i in range(256):
        arr[i, :] = (i % 20) * 12  # Repeating gradient pattern
    score = _sml(arr)
    assert score > 50.0


def test_sml_uniform_image_low() -> None:
    """Solid image should have near-zero SML."""
    arr = np.full((256, 256), 128, dtype=np.uint8)
    score = _sml(arr)
    assert score < 1.0


def test_score_sharpness_detailed_returns_dataclass() -> None:
    """score_sharpness_detailed should return a SharpnessScores."""
    img = (np.indices((256, 256)).sum(axis=0) % 2 * 255).astype(np.uint8)
    ctx = _make_context(img)
    result = score_sharpness_detailed(ctx)
    assert isinstance(result, SharpnessScores)
    assert 0.0 <= result.overall <= 1.0
    assert result.blur_type in ("sharp", "bokeh", "motion_subject", "motion_global", "misfocused")


def test_sharp_subject_blurry_background_classified_bokeh() -> None:
    """Sharp center + blurry surround should classify as 'bokeh'."""
    img = np.full((256, 256), 128, dtype=np.uint8)
    # Sharp center (checkerboard)
    center = (np.indices((128, 128)).sum(axis=0) % 2 * 255).astype(np.uint8)
    img[64:192, 64:192] = center

    mask = np.zeros((256, 256), dtype=np.uint8)
    mask[64:192, 64:192] = 1
    ctx = _make_context(img, subject_mask=mask)

    result = score_sharpness_detailed(ctx)
    assert result.subject > result.background
    assert result.blur_type in ("bokeh", "sharp")


def test_uniform_blur_classified_motion_global() -> None:
    """Uniformly blurry image should classify as 'motion_global'."""
    # Create blurry image: apply Gaussian blur to reduce edges
    import cv2
    img = np.random.randint(50, 200, (256, 256), dtype=np.uint8)
    img = cv2.GaussianBlur(img, (51, 51), 0)  # Heavy blur removes all detail

    # Use full-image mask (no masking artifacts)
    h, w = img.shape
    full_mask = np.ones((h, w), dtype=np.uint8)
    bgr = np.stack([img] * 3, axis=-1)
    ctx = SubjectContext(
        image_bgr=bgr,
        image_gray=img,
        thumbnail_rgb=np.zeros((100, 100, 3), dtype=np.uint8),
        subject_mask=full_mask,
        subject_area_ratio=1.0,
        faces=[],
        detections=[],
        primary_subject_bbox=None,
        clip_embedding=np.zeros(512, dtype=np.float32),
        exif={},
    )
    result = score_sharpness_detailed(ctx)
    assert result.blur_type == "motion_global"


def test_classify_blur_logic() -> None:
    """Direct test of blur classification rules."""
    # Sharp subject, blurry background
    assert _classify_blur(subject_sharp=True, bg_sharp=False, ratio=4.0) == "bokeh"
    # Both blurry
    assert _classify_blur(subject_sharp=False, bg_sharp=False, ratio=1.0) == "motion_global"
    # Background sharp, subject blurry
    assert _classify_blur(subject_sharp=False, bg_sharp=True, ratio=0.3) == "misfocused"
    # Both sharp
    assert _classify_blur(subject_sharp=True, bg_sharp=True, ratio=1.2) == "sharp"


def test_backward_compat_score_sharpness(sharp_image) -> None:
    """Original score_sharpness(path) still works and returns float."""
    from photo_workflow.sharpness import score_sharpness
    result = score_sharpness(sharp_image)
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0


def test_region_sharpness_independent_of_mask_area():
    """Regression: the region mean was taken over the whole frame after zeroing
    non-mask pixels, so a sharp subject at 2% of frame scored ~2% of its value."""
    import numpy as np
    from photo_workflow.sharpness import _compute_region_sharpness

    rng = np.random.default_rng(42)
    base = np.tile(np.linspace(60, 190, 256, dtype=np.float64), (256, 1))
    gray = np.clip(base + rng.normal(0, 6, (256, 256)), 0, 255).astype(np.uint8)

    full = np.ones((256, 256), dtype=np.uint8)
    small = np.zeros_like(full)
    small[100:140, 100:140] = 1  # ~2.4% of the frame, same texture

    s_full = _compute_region_sharpness(gray, full)
    s_small = _compute_region_sharpness(gray, small)
    assert 0.05 < s_full < 1.0, f"fixture texture out of range: {s_full}"
    assert s_small > 0.5 * s_full, (
        f"small-mask score {s_small:.4f} diluted vs full-frame {s_full:.4f}"
    )


def test_classify_blur_motion_subject_reachable():
    """Regression: both ratio branches returned 'bokeh' and the soft-subject
    branch always returned 'misfocused', leaving motion_subject unreachable."""
    from photo_workflow.sharpness import _classify_blur

    assert _classify_blur(True, True, 1.0) == "sharp"
    assert _classify_blur(True, False, 5.0) == "bokeh"
    assert _classify_blur(False, False, 1.0) == "motion_global"
    assert _classify_blur(False, True, 0.5, subject_anisotropy=4.0) == "motion_subject"
    assert _classify_blur(False, True, 0.5, subject_anisotropy=1.1) == "misfocused"


def test_gradient_anisotropy_detects_directional_smear():
    import cv2
    import numpy as np
    from photo_workflow.sharpness import _gradient_anisotropy

    rng = np.random.default_rng(7)
    gray = (rng.random((128, 128)) * 255).astype(np.uint8)
    smeared = cv2.blur(gray, (15, 1))  # horizontal motion smear

    def aniso(img):
        gx = cv2.Sobel(img, cv2.CV_64F, 1, 0, ksize=3)
        gy = cv2.Sobel(img, cv2.CV_64F, 0, 1, ksize=3)
        region = np.ones(img.shape, dtype=bool)
        return _gradient_anisotropy(gx, gy, region)

    assert aniso(gray) < 1.5
    assert aniso(smeared) > 2.5
