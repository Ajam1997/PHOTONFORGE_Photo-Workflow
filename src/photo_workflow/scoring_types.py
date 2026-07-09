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

    # Sharpness contrast (subject Tenengrad / background Tenengrad)
    sharpness_contrast: float = 0.0

    # RGB view of image_bgr (channel-swapped). Defaulted so existing
    # constructors keep working; populated by build_subject_context.
    image_rgb: np.ndarray | None = None

    @classmethod
    def degraded(cls, image_bgr: np.ndarray, image_gray: np.ndarray) -> "SubjectContext":
        """Model-free context: full-frame mask, no faces/detections/embedding.

        Used by the legacy path-based scorers when no models are loaded.
        """
        h, w = image_gray.shape[:2]
        return cls(
            image_bgr=image_bgr,
            image_gray=image_gray,
            thumbnail_rgb=np.zeros((100, 100, 3), dtype=np.uint8),
            subject_mask=np.ones((h, w), dtype=np.uint8),
            subject_area_ratio=1.0,
            faces=[],
            detections=[],
            primary_subject_bbox=None,
            clip_embedding=np.zeros(512, dtype=np.float32),
            exif={},
        )


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
    colorfulness: float = 0.0  # Hasler-Süsstrunk color richness (defaulted for back-compat)


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
    """Two-axis genre classification: Subject (what) x Photo Type (how).

    Subject axis: people, cat, wildlife, vehicle, signage, general
    Photo Type axis: landscape, portrait, street, event, macro, architecture, waterfall, general
    """

    subject: str
    subject_confidence: float
    photo_type: str
    type_confidence: float
    subject_distribution: dict[str, float]
    type_distribution: dict[str, float]
    needs_review: bool

    # Legacy compatibility: genres list as [(subject, conf), (type, conf)]
    @property
    def genres(self) -> list[tuple[str, float]]:
        result = [(self.subject, self.subject_confidence)]
        if self.photo_type != "general":
            result.append((self.photo_type, self.type_confidence))
        return result

    @property
    def primary_genre(self) -> str:
        return self.subject

    @property
    def primary_confidence(self) -> float:
        return self.subject_confidence


@dataclass
class FusionResult:
    """Final scored output combining all modules."""

    master_score: float
    subject: str
    subject_confidence: float
    photo_type: str
    type_confidence: float
    sub_scores: dict[str, float]
    hard_reject: bool
    hard_reject_reason: str
    star_rating: int
    color_label: int
    needs_review: bool = False

    @property
    def genre(self) -> str:
        return self.subject

    @property
    def genre_confidence(self) -> float:
        return self.subject_confidence

    @property
    def genres(self) -> list[tuple[str, float]]:
        result = [(self.subject, self.subject_confidence)]
        if self.photo_type != "general":
            result.append((self.photo_type, self.type_confidence))
        return result
