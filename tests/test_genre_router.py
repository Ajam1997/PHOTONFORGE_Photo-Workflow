"""Tests for genre routing logic."""

from __future__ import annotations

import numpy as np

from photo_workflow.scoring_types import (
    GenreResult,
    ObjectDetection,
    SubjectContext,
)
from photo_workflow.genre_router import (
    GENRES,
    SUBJECTS,
    PHOTO_TYPES,
    ALL_LABELS,
    route_genre,
    _compute_exif_prior_axis,
    _compute_yolo_evidence_subject,
    _compute_yolo_evidence_type,
    _SUBJECT_EXIF_PRIORS,
    _TYPE_EXIF_PRIORS,
)


def _make_context(
    clip_embedding: np.ndarray | None = None,
    detections: list[ObjectDetection] | None = None,
    exif: dict | None = None,
    image_shape: tuple = (1000, 1500, 3),
    sharpness_contrast: float = 1.0,
) -> SubjectContext:
    """Helper to build a minimal SubjectContext for router tests."""
    h, w = image_shape[:2]
    return SubjectContext(
        image_bgr=np.zeros((h, w, 3), dtype=np.uint8),
        image_gray=np.zeros((h, w), dtype=np.uint8),
        thumbnail_rgb=np.zeros((384, 384, 3), dtype=np.uint8),
        subject_mask=np.ones((h, w), dtype=np.uint8),
        subject_area_ratio=0.3,
        faces=[],
        detections=detections or [],
        primary_subject_bbox=None,
        clip_embedding=clip_embedding
        if clip_embedding is not None
        else np.zeros(512, dtype=np.float32),
        exif=exif or {},
        sharpness_contrast=sharpness_contrast,
    )


def test_genres_list_complete() -> None:
    """All built-in labels should be defined across both axes."""
    assert len(SUBJECTS) == 13
    assert len(PHOTO_TYPES) == 11
    # 13 + 11, fully orthogonal (no shared labels) = 24 unique
    assert len(ALL_LABELS) == 24
    assert GENRES is ALL_LABELS
    for s in ("people", "pet", "wildlife", "plant", "landscape",
              "seascape", "sky", "cityscape", "building", "vehicle",
              "food", "object", "abstract"):
        assert s in SUBJECTS
    for t in ("portrait", "candid", "scenic", "street", "macro",
              "architecture", "action", "aerial", "long-exposure",
              "still-life", "documentary"):
        assert t in PHOTO_TYPES


def test_route_genre_returns_valid_result() -> None:
    """route_genre should return a GenreResult with valid two-axis distributions."""
    ctx = _make_context()
    result = route_genre(ctx)
    assert isinstance(result, GenreResult)
    assert result.subject in SUBJECTS
    assert result.photo_type in PHOTO_TYPES
    assert 0.0 <= result.subject_confidence <= 1.0
    assert 0.0 <= result.type_confidence <= 1.0
    assert abs(sum(result.subject_distribution.values()) - 1.0) < 0.01
    assert abs(sum(result.type_distribution.values()) - 1.0) < 0.01
    assert len(result.genres) > 0
    # Backward compat: primary_genre maps to subject
    assert result.primary_genre == result.subject


def test_route_genre_fallback_no_clip() -> None:
    """With zero CLIP embedding, should still return valid genres."""
    ctx = _make_context(clip_embedding=np.zeros(512, dtype=np.float32))
    result = route_genre(ctx)
    assert result.subject in SUBJECTS
    assert result.photo_type in PHOTO_TYPES
    assert len(result.genres) > 0


def test_yolo_evidence_cat_boosts_pet() -> None:
    """YOLO detecting a cat should boost pet on subject axis."""
    cat_det = ObjectDetection(
        class_id=15, class_name="cat", bbox=(100, 100, 400, 400), confidence=0.9
    )
    evidence = _compute_yolo_evidence_subject([cat_det], image_area=1500 * 1000)
    assert evidence["pet"] > evidence["landscape"]
    assert evidence["wildlife"] > evidence["landscape"]


def test_yolo_evidence_car_boosts_vehicle() -> None:
    """YOLO detecting a car should boost vehicle on subject axis."""
    car_det = ObjectDetection(
        class_id=2, class_name="car", bbox=(100, 100, 500, 400), confidence=0.85
    )
    evidence = _compute_yolo_evidence_subject([car_det], image_area=1500 * 1000)
    assert evidence["vehicle"] > evidence["people"]
    assert evidence["vehicle"] > evidence["landscape"]


def test_yolo_evidence_person_boosts_portrait() -> None:
    """YOLO detecting a large person should boost portrait on type axis."""
    person_det = ObjectDetection(
        class_id=0, class_name="person", bbox=(100, 50, 600, 800), confidence=0.9
    )
    evidence = _compute_yolo_evidence_type([person_det], image_area=1500 * 1000)
    assert evidence["portrait"] > evidence["scenic"]


def test_yolo_evidence_no_detections_neutral() -> None:
    """No YOLO detections should give uniform evidence on both axes."""
    subj_evidence = _compute_yolo_evidence_subject([], image_area=1500 * 1000)
    vals = list(subj_evidence.values())
    assert all(abs(v - vals[0]) < 0.01 for v in vals)

    type_evidence = _compute_yolo_evidence_type([], image_area=1500 * 1000)
    vals = list(type_evidence.values())
    assert all(abs(v - vals[0]) < 0.01 for v in vals)


def test_exif_prior_telephoto_boosts_wildlife() -> None:
    """Long focal length + fast shutter boosts wildlife on subject axis."""
    exif = {"focal_length": 400.0, "aperture": 5.6, "shutter": 1 / 2000, "iso": 800}
    prior = _compute_exif_prior_axis(exif, SUBJECTS, _SUBJECT_EXIF_PRIORS)
    assert prior["wildlife"] > prior["landscape"]


def test_exif_prior_wide_angle_boosts_scenic() -> None:
    """Wide focal length + small aperture boosts scenic on type axis."""
    exif = {"focal_length": 16.0, "aperture": 11.0, "shutter": 1 / 30, "iso": 100}
    prior = _compute_exif_prior_axis(exif, PHOTO_TYPES, _TYPE_EXIF_PRIORS)
    assert prior["scenic"] > prior["portrait"]


def test_exif_prior_empty_returns_uniform() -> None:
    """Missing EXIF should give uniform prior."""
    prior = _compute_exif_prior_axis({}, SUBJECTS, _SUBJECT_EXIF_PRIORS)
    values = list(prior.values())
    assert all(abs(v - values[0]) < 0.01 for v in values)


def test_low_confidence_marks_for_review() -> None:
    """When no evidence is strong, needs_review should be True."""
    ctx = _make_context(
        clip_embedding=np.zeros(512, dtype=np.float32),
        detections=[],
        exif={},
    )
    result = route_genre(ctx)
    assert result.subject_confidence >= 0.0
    assert result.type_confidence >= 0.0
    # Low confidence should trigger needs_review flag
    if result.subject_confidence < 0.15 or result.type_confidence < 0.15:
        assert result.needs_review
