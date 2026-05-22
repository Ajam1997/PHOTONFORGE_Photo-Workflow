"""Shared dataclasses for the genre-aware scoring pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class FaceDetection:
    """A detected human face with landmark positions."""

    bbox: tuple[int, int, int, int]  # x, y, w, h
    landmarks: dict[str, tuple[int, int]]  # left_eye, right_eye, nose, mouth_left, mouth_right
    confidence: float


@dataclass
class ObjectDetection:
    """A detected object from YOLOv8n."""

    class_id: int
    class_name: str
    bbox: tuple[int, int, int, int]  # x, y, w, h
    confidence: float


@dataclass
class SubjectContext:
    """Shared context computed once per image by all neural models."""

    # Image data
    image_bgr: np.ndarray
    image_gray: np.ndarray
    thumbnail_rgb: np.ndarray

    # RMBG-1.4 output
    subject_mask: np.ndarray
    subject_area_ratio: float

    # YuNet output
    faces: list[FaceDetection]

    # YOLOv8n output
    detections: list[ObjectDetection]
    primary_subject_bbox: tuple[int, int, int, int] | None

    # MobileCLIP output
    clip_embedding: np.ndarray

    # EXIF metadata
    exif: dict


@dataclass
class SharpnessScores:
    """Multi-region sharpness analysis results."""

    subject: float  # Tenengrad+SML on subject mask
    eye_region: float  # Tenengrad+SML on eye region
    background: float  # Tenengrad+SML on background
    sharpness_contrast: float  # subject / background ratio
    blur_type: str  # sharp|bokeh|motion_subject|motion_global|misfocused
    overall: float  # Genre-independent combined score


@dataclass
class CompositionScores:
    """Composition analysis sub-scores."""

    rule_of_thirds: float
    symmetry: float
    leading_lines: float
    negative_space: float
    subject_isolation: float
    balance: float
    overall: float


@dataclass
class ExposureScores:
    """Exposure analysis sub-scores."""

    zone_entropy: float
    zone_diversity: int
    clipping_shadows: float
    clipping_highlights: float
    dynamic_range: float
    midtone_density: float
    face_exposure: float  # -1.0 if no face detected
    style: str  # normal|high_key|low_key|silhouette
    style_confidence: float
    overall: float


@dataclass
class GenreResult:
    """Genre classification output."""

    genre: str
    confidence: float
    distribution: dict[str, float]


@dataclass
class FusionResult:
    """Final scored output combining all modules."""

    master_score: float
    genre: str
    genre_confidence: float
    sub_scores: dict[str, float]
    hard_reject: bool
    hard_reject_reason: str
    star_rating: int
    color_label: int
