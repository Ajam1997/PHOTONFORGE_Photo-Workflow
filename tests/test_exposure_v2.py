"""Tests for enhanced exposure scoring."""

from __future__ import annotations

import numpy as np

from photo_workflow.scoring_types import SubjectContext, ExposureScores, FaceDetection
from photo_workflow.exposure import (
    score_exposure_detailed,
    _detect_style,
    _compute_face_exposure,
    NUM_ZONES,
)


def _make_context(
    image_bgr: np.ndarray,
    faces: list[FaceDetection] | None = None,
) -> SubjectContext:
    """Build a SubjectContext for exposure tests."""
    h, w = image_bgr.shape[:2]
    gray = np.mean(image_bgr, axis=2).astype(np.uint8) if image_bgr.ndim == 3 else image_bgr
    return SubjectContext(
        image_bgr=image_bgr,
        image_gray=gray,
        thumbnail_rgb=np.zeros((100, 100, 3), dtype=np.uint8),
        subject_mask=np.ones((h, w), dtype=np.uint8),
        subject_area_ratio=1.0,
        faces=faces or [],
        detections=[],
        primary_subject_bbox=None,
        clip_embedding=np.zeros(512, dtype=np.float32),
        exif={},
    )


def test_score_exposure_detailed_returns_dataclass() -> None:
    """score_exposure_detailed should return ExposureScores."""
    img = np.random.randint(30, 220, (200, 300, 3), dtype=np.uint8)
    ctx = _make_context(img)
    result = score_exposure_detailed(ctx)
    assert isinstance(result, ExposureScores)
    assert 0.0 <= result.overall <= 1.0
    assert 0 <= result.zone_diversity <= NUM_ZONES


def test_gradient_image_high_entropy() -> None:
    """Full-range gradient should have high zone entropy."""
    gradient = np.linspace(0, 255, 200 * 300).reshape(200, 300).astype(np.uint8)
    img = np.stack([gradient] * 3, axis=-1)
    ctx = _make_context(img)
    result = score_exposure_detailed(ctx)
    assert result.zone_entropy > 0.8
    assert result.zone_diversity >= 9


def test_solid_image_low_entropy() -> None:
    """Solid gray image should have very low zone entropy."""
    img = np.full((200, 300, 3), 128, dtype=np.uint8)
    ctx = _make_context(img)
    result = score_exposure_detailed(ctx)
    assert result.zone_entropy < 0.2
    assert result.zone_diversity <= 2


def test_clipping_detection_shadows() -> None:
    """Very dark image should detect shadow clipping."""
    img = np.full((200, 300, 3), 2, dtype=np.uint8)
    ctx = _make_context(img)
    result = score_exposure_detailed(ctx)
    assert result.clipping_shadows > 0.9


def test_clipping_detection_highlights() -> None:
    """Very bright image should detect highlight clipping."""
    img = np.full((200, 300, 3), 253, dtype=np.uint8)
    ctx = _make_context(img)
    result = score_exposure_detailed(ctx)
    assert result.clipping_highlights > 0.9


def test_detect_style_high_key() -> None:
    """Predominantly bright image should detect as high_key."""
    zones = np.zeros(NUM_ZONES)
    zones[8] = 0.5  # Zone VIII
    zones[9] = 0.2  # Zone IX
    zones[10] = 0.1  # Zone X
    zones[5] = 0.1  # Some midtones
    zones[6] = 0.1
    style, confidence = _detect_style(zones / zones.sum())
    assert style == "high_key"
    assert confidence > 0.5


def test_detect_style_normal() -> None:
    """Even distribution should detect as normal."""
    zones = np.ones(NUM_ZONES) / NUM_ZONES
    style, confidence = _detect_style(zones)
    assert style == "normal"


def test_face_exposure_ideal_range() -> None:
    """Face in ideal luma range [110, 220] should score high."""
    # Create image with face region at luma ~160
    img = np.full((200, 300, 3), 160, dtype=np.uint8)
    face = FaceDetection(
        bbox=(100, 50, 80, 80),
        landmarks={"left_eye": (120, 70), "right_eye": (160, 70), "nose": (140, 90),
                   "mouth_left": (120, 110), "mouth_right": (160, 110)},
        confidence=0.9,
    )
    score = _compute_face_exposure(img, [face])
    assert score > 0.7


def test_face_exposure_no_face() -> None:
    """No face detected should return -1.0."""
    img = np.full((200, 300, 3), 128, dtype=np.uint8)
    score = _compute_face_exposure(img, [])
    assert score == -1.0


def test_dynamic_range_full() -> None:
    """Image spanning full range should have high DR."""
    gradient = np.linspace(0, 255, 200 * 300).reshape(200, 300).astype(np.uint8)
    img = np.stack([gradient] * 3, axis=-1)
    ctx = _make_context(img)
    result = score_exposure_detailed(ctx)
    assert result.dynamic_range > 0.9


def test_backward_compat_score_exposure(sharp_image) -> None:
    """Original score_exposure(path) still works and returns float."""
    from photo_workflow.exposure import score_exposure
    result = score_exposure(sharp_image)
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0
