"""Tests for scoring type dataclasses."""

from __future__ import annotations

import numpy as np

from photo_workflow.scoring_types import (
    FaceDetection,
    ObjectDetection,
    SubjectContext,
    SharpnessScores,
    CompositionScores,
    ExposureScores,
    GenreResult,
    FusionResult,
)


def test_face_detection_construction() -> None:
    face = FaceDetection(
        bbox=(10, 20, 100, 100),
        landmarks={
            "left_eye": (35, 55),
            "right_eye": (75, 55),
            "nose": (55, 70),
            "mouth_left": (40, 85),
            "mouth_right": (70, 85),
        },
        confidence=0.95,
    )
    assert face.confidence == 0.95
    assert face.landmarks["left_eye"] == (35, 55)


def test_object_detection_construction() -> None:
    det = ObjectDetection(
        class_id=15,
        class_name="cat",
        bbox=(50, 50, 200, 200),
        confidence=0.88,
    )
    assert det.class_name == "cat"
    assert det.bbox == (50, 50, 200, 200)


def test_subject_context_construction() -> None:
    ctx = SubjectContext(
        image_bgr=np.zeros((100, 100, 3), dtype=np.uint8),
        image_gray=np.zeros((100, 100), dtype=np.uint8),
        thumbnail_rgb=np.zeros((384, 384, 3), dtype=np.uint8),
        subject_mask=np.ones((100, 100), dtype=np.uint8),
        subject_area_ratio=0.3,
        faces=[],
        detections=[],
        primary_subject_bbox=None,
        clip_embedding=np.zeros(512, dtype=np.float32),
        exif={},
    )
    assert ctx.subject_area_ratio == 0.3
    assert ctx.clip_embedding.shape == (512,)


def test_sharpness_scores_construction() -> None:
    scores = SharpnessScores(
        subject=0.85,
        eye_region=0.90,
        background=0.30,
        sharpness_contrast=2.83,
        blur_type="bokeh",
        overall=0.78,
    )
    assert scores.blur_type == "bokeh"
    assert scores.overall == 0.78


def test_composition_scores_construction() -> None:
    scores = CompositionScores(
        rule_of_thirds=0.72,
        symmetry=0.45,
        leading_lines=0.30,
        negative_space=0.65,
        subject_isolation=0.80,
        balance=0.55,
        overall=0.58,
    )
    assert scores.overall == 0.58


def test_exposure_scores_construction() -> None:
    scores = ExposureScores(
        zone_entropy=0.82,
        zone_diversity=9,
        clipping_shadows=0.01,
        clipping_highlights=0.02,
        dynamic_range=0.88,
        midtone_density=0.45,
        face_exposure=0.75,
        style="normal",
        style_confidence=0.0,
        overall=0.80,
    )
    assert scores.zone_diversity == 9
    assert scores.style == "normal"


def test_genre_result_construction() -> None:
    result = GenreResult(
        subject="wildlife",
        subject_confidence=0.87,
        photo_type="landscape",
        type_confidence=0.65,
        subject_distribution={"wildlife": 0.87, "general": 0.13},
        type_distribution={"landscape": 0.65, "general": 0.35},
        needs_review=False,
    )
    assert result.primary_genre == "wildlife"
    assert result.primary_confidence == 0.87
    assert result.subject == "wildlife"
    assert result.photo_type == "landscape"
    assert abs(sum(result.subject_distribution.values()) - 1.0) < 0.01
    assert len(result.genres) == 2  # wildlife + landscape


def test_genre_result_properties() -> None:
    """Test primary_genre and primary_confidence backward-compat properties."""
    result = GenreResult(
        subject="people",
        subject_confidence=0.92,
        photo_type="portrait",
        type_confidence=0.80,
        subject_distribution={"people": 0.92, "general": 0.08},
        type_distribution={"portrait": 0.80, "general": 0.20},
        needs_review=False,
    )
    assert result.primary_genre == "people"
    assert result.primary_confidence == 0.92
    assert result.genres == [("people", 0.92), ("portrait", 0.80)]


def test_subject_context_sharpness_contrast() -> None:
    """SubjectContext should have sharpness_contrast field with default 0.0."""
    ctx = SubjectContext(
        image_bgr=np.zeros((100, 100, 3), dtype=np.uint8),
        image_gray=np.zeros((100, 100), dtype=np.uint8),
        thumbnail_rgb=np.zeros((384, 384, 3), dtype=np.uint8),
        subject_mask=np.ones((100, 100), dtype=np.uint8),
        subject_area_ratio=0.3,
        faces=[],
        detections=[],
        primary_subject_bbox=None,
        clip_embedding=np.zeros(512, dtype=np.float32),
        exif={},
        sharpness_contrast=2.5,
    )
    assert ctx.sharpness_contrast == 2.5


def test_fusion_result_construction() -> None:
    result = FusionResult(
        master_score=0.72,
        subject="wildlife",
        subject_confidence=0.87,
        photo_type="landscape",
        type_confidence=0.65,
        sub_scores={"eye_sharpness": 0.90, "subject_sharpness": 0.85},
        hard_reject=False,
        hard_reject_reason="",
        star_rating=4,
        color_label=2,
    )
    assert result.star_rating == 4
    assert not result.hard_reject
    assert result.genre == "wildlife"  # backward compat
    assert result.subject == "wildlife"
    assert result.photo_type == "landscape"
