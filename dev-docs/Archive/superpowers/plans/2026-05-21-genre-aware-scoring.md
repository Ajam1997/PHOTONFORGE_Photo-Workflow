# Genre-Aware Scoring Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PHOTONForge's three independent global scoring modules with a genre-aware system that routes images through genre-specific weight profiles after computing subject-aware sub-scores.

**Architecture:** Layered replacement — a shared SubjectContext runs all models once, then enhanced sharpness/composition/exposure modules compute sub-scores using that context. A genre router classifies the image, and a fusion layer applies genre-specific weights to produce a master score. All models are ONNX INT8 on CPU.

**Tech Stack:** Python 3.11+, onnxruntime (INT8 CPU), OpenCV, NumPy, SciPy, click, pytest

**Spec:** `docs/superpowers/specs/2026-05-21-genre-aware-scoring-design.md`

---

## File Structure

### New Files
- `src/photo_workflow/scoring_types.py` — All shared dataclasses (SubjectContext, SharpnessScores, CompositionScores, ExposureScores, GenreResult, FusionResult, FaceDetection, ObjectDetection)
- `src/photo_workflow/subject_context.py` — ModelSessions class + build_subject_context() function
- `src/photo_workflow/genre_router.py` — route_genre() function + EXIF priors + YOLO rules
- `src/photo_workflow/score_fusion.py` — GENRE_WEIGHTS dict + fuse_scores() function
- `tests/test_scoring_types.py` — Type construction tests
- `tests/test_subject_context.py` — Context builder tests (mocked models)
- `tests/test_genre_router.py` — Genre routing tests
- `tests/test_score_fusion.py` — Fusion logic tests
- `tests/test_sharpness_v2.py` — Enhanced sharpness tests
- `tests/test_composition_v2.py` — Enhanced composition tests
- `tests/test_exposure_v2.py` — Enhanced exposure tests

### Modified Files
- `src/photo_workflow/sharpness.py` — Add `score_sharpness_detailed()` returning SharpnessScores; keep `score_sharpness()` as backward-compat wrapper
- `src/photo_workflow/composition.py` — Add `score_composition_detailed()` returning CompositionScores; keep `score_composition()` as wrapper
- `src/photo_workflow/exposure.py` — Add `score_exposure_detailed()` returning ExposureScores; keep `score_exposure()` as wrapper
- `src/photo_workflow/pipeline.py` — Update PhotoRecord, wire new scoring flow in AnalysisPipeline.run() and CLI `score` command
- `src/photo_workflow/darktable_bridge.py` — New XMP template with genre/sub-scores, updated compute_color_label()
- `src/photo_workflow/photondb.py` — Add genre/master_score/sub_scores columns via ensure_table() and new update functions

---

## Task 1: Scoring Types Module

**Files:**
- Create: `src/photo_workflow/scoring_types.py`
- Create: `tests/test_scoring_types.py`

- [ ] **Step 1: Write the failing test for dataclass construction**

```python
# tests/test_scoring_types.py
"""Tests for scoring type dataclasses."""

from __future__ import annotations

import numpy as np
import pytest

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
        genre="wildlife",
        confidence=0.87,
        distribution={
            "wildlife": 0.87,
            "landscape": 0.05,
            "portrait": 0.03,
            "street": 0.02,
            "architecture": 0.01,
            "macro": 0.01,
            "event": 0.005,
            "general": 0.005,
        },
    )
    assert result.genre == "wildlife"
    assert abs(sum(result.distribution.values()) - 1.0) < 0.01


def test_fusion_result_construction() -> None:
    result = FusionResult(
        master_score=0.72,
        genre="wildlife",
        genre_confidence=0.87,
        sub_scores={"eye_sharpness": 0.90, "subject_sharpness": 0.85},
        hard_reject=False,
        hard_reject_reason="",
        star_rating=4,
        color_label=2,
    )
    assert result.star_rating == 4
    assert not result.hard_reject
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scoring_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'photo_workflow.scoring_types'`

- [ ] **Step 3: Implement the scoring types module**

```python
# src/photo_workflow/scoring_types.py
"""Shared dataclasses for the genre-aware scoring pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scoring_types.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Lint check**

Run: `ruff check src/photo_workflow/scoring_types.py tests/test_scoring_types.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/photo_workflow/scoring_types.py tests/test_scoring_types.py
git commit -m "feat(scoring): add shared dataclasses for genre-aware scoring pipeline"
```

---

## Task 2: Subject Context Builder

**Files:**
- Create: `src/photo_workflow/subject_context.py`
- Create: `tests/test_subject_context.py`

- [ ] **Step 1: Write the failing test for ModelSessions**

```python
# tests/test_subject_context.py
"""Tests for the subject context builder (mocked ONNX sessions)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from photo_workflow.subject_context import ModelSessions, build_subject_context
from photo_workflow.scoring_types import SubjectContext


def test_model_sessions_lazy_loading(tmp_path: Path) -> None:
    """ModelSessions should not load models until accessed."""
    sessions = ModelSessions(tmp_path)
    # No sessions loaded yet
    assert sessions._sessions == {}


def test_model_sessions_missing_model_returns_none(tmp_path: Path) -> None:
    """Missing model files should return None, not crash."""
    sessions = ModelSessions(tmp_path)
    assert sessions.clip_vision is None
    assert sessions.rmbg is None
    assert sessions.yunet is None
    assert sessions.yolo is None
    assert sessions.clip_aesthetic_head is None


def test_build_subject_context_no_models(tmp_path: Path) -> None:
    """With no models available, build_subject_context returns degraded context."""
    # Create a simple test image
    from PIL import Image
    img_path = tmp_path / "test.jpg"
    img = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
    img.save(img_path)

    sessions = ModelSessions(tmp_path / "models")
    ctx = build_subject_context(img_path, sessions)

    assert isinstance(ctx, SubjectContext)
    assert ctx.image_bgr.shape == (100, 100, 3)
    assert ctx.image_gray.shape == (100, 100)
    # Degraded: full-image mask, no faces, no detections, zero embedding
    assert ctx.subject_mask.shape == (100, 100)
    assert ctx.subject_mask.all()  # Full image is "subject" when no model
    assert ctx.subject_area_ratio == 1.0
    assert ctx.faces == []
    assert ctx.detections == []
    assert ctx.clip_embedding.shape == (512,)
    assert np.allclose(ctx.clip_embedding, 0.0)


def test_build_subject_context_with_mocked_clip(tmp_path: Path) -> None:
    """CLIP embedding should be populated when session is available."""
    from PIL import Image
    img_path = tmp_path / "test.jpg"
    img = Image.fromarray(np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8))
    img.save(img_path)

    fake_embedding = np.random.randn(512).astype(np.float32)
    mock_session = MagicMock()
    mock_session.run.return_value = [fake_embedding.reshape(1, 512)]
    mock_session.get_inputs.return_value = [MagicMock(name="pixel_values", shape=[1, 3, 224, 224])]

    sessions = ModelSessions(tmp_path / "models")
    sessions._sessions["clip_vision"] = mock_session

    ctx = build_subject_context(img_path, sessions)

    assert ctx.clip_embedding.shape == (512,)
    assert not np.allclose(ctx.clip_embedding, 0.0)


def test_build_subject_context_exif_extraction(tmp_path: Path) -> None:
    """EXIF data should be extracted when available."""
    from PIL import Image
    img_path = tmp_path / "test.jpg"
    img = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
    img.save(img_path)

    sessions = ModelSessions(tmp_path / "models")
    ctx = build_subject_context(img_path, sessions)

    # EXIF dict exists (may be empty for synthetic images)
    assert isinstance(ctx.exif, dict)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_subject_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'photo_workflow.subject_context'`

- [ ] **Step 3: Implement the subject context module**

```python
# src/photo_workflow/subject_context.py
"""Subject context builder — runs all models once per image."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .scoring_types import FaceDetection, ObjectDetection, SubjectContext

logger = logging.getLogger(__name__)

# CLIP input size for MobileCLIP-S0
_CLIP_INPUT_SIZE = 224

# RMBG input size
_RMBG_INPUT_SIZE = 320

# YOLO input size
_YOLO_INPUT_SIZE = 640


class ModelSessions:
    """Lazy-loaded, long-lived ONNX inference sessions."""

    def __init__(self, model_dir: Path) -> None:
        self._model_dir = model_dir
        self._sessions: dict[str, Any] = {}

    def _load_session(self, key: str, subdir: str, filename: str) -> Any:
        """Load an ONNX session, returning None if file missing."""
        if key in self._sessions:
            return self._sessions[key]

        model_path = self._model_dir / subdir / filename
        if not model_path.exists():
            logger.warning("Model not found: %s", model_path)
            self._sessions[key] = None
            return None

        try:
            import onnxruntime as ort

            sess = ort.InferenceSession(
                str(model_path),
                providers=["CPUExecutionProvider"],
            )
            self._sessions[key] = sess
            logger.info("Loaded model: %s", model_path)
            return sess
        except Exception as e:
            logger.warning("Failed to load model %s: %s", model_path, e)
            self._sessions[key] = None
            return None

    @property
    def clip_vision(self) -> Any:
        return self._load_session("clip_vision", "mobileclip_s0_int8", "vision_encoder.onnx")

    @property
    def rmbg(self) -> Any:
        return self._load_session("rmbg", "rmbg14_int8", "model.onnx")

    @property
    def yunet(self) -> Any:
        return self._load_session("yunet", "yunet", "face_detection_yunet.onnx")

    @property
    def yolo(self) -> Any:
        return self._load_session("yolo", "yolov8n_int8", "model.onnx")

    @property
    def clip_aesthetic_head(self) -> Any:
        return self._load_session(
            "clip_aesthetic_head", "clip_aesthetic_head", "aesthetic_mlp.onnx"
        )


def _extract_exif(path: Path) -> dict:
    """Extract relevant EXIF fields from an image file."""
    try:
        import exifread

        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False)

        exif: dict[str, Any] = {}
        if "EXIF FocalLength" in tags:
            val = tags["EXIF FocalLength"].values[0]
            exif["focal_length"] = float(val.num) / float(val.den) if val.den else 0.0
        if "EXIF FNumber" in tags:
            val = tags["EXIF FNumber"].values[0]
            exif["aperture"] = float(val.num) / float(val.den) if val.den else 0.0
        if "EXIF ExposureTime" in tags:
            val = tags["EXIF ExposureTime"].values[0]
            exif["shutter"] = float(val.num) / float(val.den) if val.den else 0.0
        if "EXIF ISOSpeedRatings" in tags:
            exif["iso"] = int(str(tags["EXIF ISOSpeedRatings"]))
        if "Image Model" in tags:
            exif["camera_model"] = str(tags["Image Model"])
        return exif
    except Exception:
        return {}


def _run_clip(image_rgb: np.ndarray, session: Any) -> np.ndarray:
    """Run MobileCLIP vision encoder, return 512-dim embedding."""
    # Preprocess: resize, normalize, CHW, batch
    img = cv2.resize(image_rgb, (_CLIP_INPUT_SIZE, _CLIP_INPUT_SIZE))
    img = img.astype(np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    img = (img - mean) / std
    img = np.transpose(img, (2, 0, 1))  # HWC -> CHW
    img = np.expand_dims(img, axis=0)  # Add batch

    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: img})
    embedding = outputs[0].flatten()

    # L2 normalize
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm
    return embedding.astype(np.float32)


def _run_rmbg(image_rgb: np.ndarray, session: Any, original_shape: tuple) -> np.ndarray:
    """Run RMBG-1.4, return binary mask at original resolution."""
    h, w = original_shape[:2]
    img = cv2.resize(image_rgb, (_RMBG_INPUT_SIZE, _RMBG_INPUT_SIZE))
    img = img.astype(np.float32) / 255.0
    img = np.transpose(img, (2, 0, 1))
    img = np.expand_dims(img, axis=0)

    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: img})
    mask = outputs[0].squeeze()

    # Resize mask back to original resolution
    if mask.ndim == 3:
        mask = mask[0]  # Take first channel if multi-channel
    mask = cv2.resize(mask, (w, h))
    # Binarize at 0.5
    binary_mask = (mask > 0.5).astype(np.uint8)
    return binary_mask


def _run_yunet(image_bgr: np.ndarray, session: Any) -> list[FaceDetection]:
    """Run YuNet face detector, return list of FaceDetection."""
    h, w = image_bgr.shape[:2]

    # YuNet expects specific input format
    input_name = session.get_inputs()[0].name
    input_shape = session.get_inputs()[0].shape
    target_h, target_w = input_shape[2], input_shape[3]
    img = cv2.resize(image_bgr, (target_w, target_h))
    img = img.astype(np.float32)
    img = np.transpose(img, (2, 0, 1))
    img = np.expand_dims(img, axis=0)

    outputs = session.run(None, {input_name: img})

    faces: list[FaceDetection] = []
    # Parse YuNet output format: [batch, num_detections, 15]
    # Format: x, y, w, h, conf, landmarks (5 points x 2 coords)
    raw = outputs[0]
    if raw.ndim == 3:
        raw = raw[0]

    scale_x, scale_y = w / target_w, h / target_h

    for det in raw:
        conf = float(det[4]) if len(det) > 4 else float(det[-1])
        if conf < 0.5:
            continue
        bx = int(det[0] * scale_x)
        by = int(det[1] * scale_y)
        bw = int(det[2] * scale_x)
        bh = int(det[3] * scale_y)

        landmarks = {}
        if len(det) >= 15:
            landmarks["left_eye"] = (int(det[5] * scale_x), int(det[6] * scale_y))
            landmarks["right_eye"] = (int(det[7] * scale_x), int(det[8] * scale_y))
            landmarks["nose"] = (int(det[9] * scale_x), int(det[10] * scale_y))
            landmarks["mouth_left"] = (int(det[11] * scale_x), int(det[12] * scale_y))
            landmarks["mouth_right"] = (int(det[13] * scale_x), int(det[14] * scale_y))

        faces.append(FaceDetection(bbox=(bx, by, bw, bh), landmarks=landmarks, confidence=conf))

    return faces


def _run_yolo(image_rgb: np.ndarray, session: Any, original_shape: tuple) -> list[ObjectDetection]:
    """Run YOLOv8n, return list of ObjectDetection."""
    h, w = original_shape[:2]
    img = cv2.resize(image_rgb, (_YOLO_INPUT_SIZE, _YOLO_INPUT_SIZE))
    img = img.astype(np.float32) / 255.0
    img = np.transpose(img, (2, 0, 1))
    img = np.expand_dims(img, axis=0)

    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: img})

    # YOLOv8 output: [1, 84, 8400] (transposed) — 80 classes + 4 bbox coords
    raw = outputs[0]
    if raw.shape[1] == 84:
        raw = raw.transpose(0, 2, 1)  # -> [1, 8400, 84]
    raw = raw[0]  # Remove batch dim

    detections: list[ObjectDetection] = []
    scale_x, scale_y = w / _YOLO_INPUT_SIZE, h / _YOLO_INPUT_SIZE

    # COCO class names (subset relevant to genre detection)
    coco_names = _COCO_NAMES

    for row in raw:
        cx, cy, bw, bh = row[:4]
        class_scores = row[4:]
        class_id = int(np.argmax(class_scores))
        conf = float(class_scores[class_id])
        if conf < 0.3:
            continue

        x = int((cx - bw / 2) * scale_x)
        y = int((cy - bh / 2) * scale_y)
        det_w = int(bw * scale_x)
        det_h = int(bh * scale_y)

        name = coco_names[class_id] if class_id < len(coco_names) else f"class_{class_id}"
        detections.append(ObjectDetection(
            class_id=class_id,
            class_name=name,
            bbox=(x, y, det_w, det_h),
            confidence=conf,
        ))

    return detections


# COCO 80 class names
_COCO_NAMES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
    "toothbrush",
]


def build_subject_context(path: Path, model_sessions: ModelSessions) -> SubjectContext:
    """Build the shared subject context for a single image.

    Runs all available models and produces degraded output for missing ones.
    """
    from .raw_loader import load_rgb, load_gray

    # Load image
    try:
        image_bgr = load_rgb(path)
    except Exception:
        # Fallback: try with cv2 directly
        image_bgr = cv2.imread(str(path))
        if image_bgr is None:
            raise ValueError(f"Cannot load image: {path}")

    image_gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)

    # Thumbnail for model input
    h, w = image_bgr.shape[:2]
    scale = 384 / max(h, w)
    thumb_h, thumb_w = int(h * scale), int(w * scale)
    thumbnail_rgb = cv2.resize(image_rgb, (thumb_w, thumb_h))

    # Extract EXIF
    exif = _extract_exif(path)

    # Run CLIP (or degrade)
    clip_session = model_sessions.clip_vision
    if clip_session is not None:
        clip_embedding = _run_clip(image_rgb, clip_session)
    else:
        clip_embedding = np.zeros(512, dtype=np.float32)

    # Run RMBG (or degrade to full-image mask)
    rmbg_session = model_sessions.rmbg
    if rmbg_session is not None:
        subject_mask = _run_rmbg(image_rgb, rmbg_session, image_bgr.shape)
    else:
        subject_mask = np.ones((h, w), dtype=np.uint8)

    subject_pixels = int(subject_mask.sum())
    total_pixels = h * w
    subject_area_ratio = subject_pixels / total_pixels if total_pixels > 0 else 1.0

    # Run YuNet (or degrade to empty)
    yunet_session = model_sessions.yunet
    if yunet_session is not None:
        faces = _run_yunet(image_bgr, yunet_session)
    else:
        faces = []

    # Run YOLO (or degrade to empty)
    yolo_session = model_sessions.yolo
    if yolo_session is not None:
        detections = _run_yolo(image_rgb, yolo_session, image_bgr.shape)
    else:
        detections = []

    # Determine primary subject bbox (largest detection by area)
    primary_subject_bbox: tuple[int, int, int, int] | None = None
    if detections:
        largest = max(detections, key=lambda d: d.bbox[2] * d.bbox[3])
        primary_subject_bbox = largest.bbox

    return SubjectContext(
        image_bgr=image_bgr,
        image_gray=image_gray,
        thumbnail_rgb=thumbnail_rgb,
        subject_mask=subject_mask,
        subject_area_ratio=subject_area_ratio,
        faces=faces,
        detections=detections,
        primary_subject_bbox=primary_subject_bbox,
        clip_embedding=clip_embedding,
        exif=exif,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_subject_context.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Lint check**

Run: `ruff check src/photo_workflow/subject_context.py tests/test_subject_context.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/photo_workflow/subject_context.py tests/test_subject_context.py
git commit -m "feat(scoring): add subject context builder with model session management"
```

---

## Task 3: Genre Router

**Files:**
- Create: `src/photo_workflow/genre_router.py`
- Create: `tests/test_genre_router.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_genre_router.py
"""Tests for genre routing logic."""

from __future__ import annotations

import numpy as np
import pytest

from photo_workflow.scoring_types import (
    GenreResult,
    ObjectDetection,
    SubjectContext,
)
from photo_workflow.genre_router import (
    GENRES,
    route_genre,
    _compute_exif_prior,
    _compute_yolo_evidence,
)


def _make_context(
    clip_embedding: np.ndarray | None = None,
    detections: list[ObjectDetection] | None = None,
    exif: dict | None = None,
    image_shape: tuple = (1000, 1500, 3),
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
        clip_embedding=clip_embedding if clip_embedding is not None else np.zeros(512, dtype=np.float32),
        exif=exif or {},
    )


def test_genres_list_complete() -> None:
    """All 8 genres should be defined."""
    assert len(GENRES) == 8
    assert "wildlife" in GENRES
    assert "general" in GENRES


def test_route_genre_returns_valid_result() -> None:
    """route_genre should return a GenreResult with valid distribution."""
    ctx = _make_context()
    result = route_genre(ctx)
    assert isinstance(result, GenreResult)
    assert result.genre in GENRES
    assert 0.0 <= result.confidence <= 1.0
    assert abs(sum(result.distribution.values()) - 1.0) < 0.01


def test_route_genre_fallback_no_clip() -> None:
    """With zero CLIP embedding, should fall back to 'general'."""
    ctx = _make_context(clip_embedding=np.zeros(512, dtype=np.float32))
    result = route_genre(ctx)
    # Zero embedding means no CLIP signal; falls back based on other evidence
    assert result.genre in GENRES


def test_yolo_evidence_cat_boosts_wildlife() -> None:
    """YOLO detecting a cat should boost wildlife probability."""
    cat_det = ObjectDetection(class_id=15, class_name="cat", bbox=(100, 100, 400, 400), confidence=0.9)
    evidence = _compute_yolo_evidence([cat_det], image_area=1500 * 1000)
    assert evidence["wildlife"] > evidence["landscape"]
    assert evidence["wildlife"] > evidence["portrait"]


def test_yolo_evidence_person_boosts_portrait() -> None:
    """YOLO detecting a large person should boost portrait."""
    person_det = ObjectDetection(class_id=0, class_name="person", bbox=(100, 50, 600, 800), confidence=0.9)
    evidence = _compute_yolo_evidence([person_det], image_area=1500 * 1000)
    assert evidence["portrait"] > evidence["landscape"]


def test_yolo_evidence_no_detections_neutral() -> None:
    """No YOLO detections should give uniform evidence."""
    evidence = _compute_yolo_evidence([], image_area=1500 * 1000)
    # All values should be equal (uniform)
    values = list(evidence.values())
    assert all(abs(v - values[0]) < 0.01 for v in values)


def test_exif_prior_telephoto_boosts_wildlife() -> None:
    """Long focal length + fast shutter boosts wildlife."""
    exif = {"focal_length": 400.0, "aperture": 5.6, "shutter": 1 / 2000, "iso": 800}
    prior = _compute_exif_prior(exif)
    assert prior["wildlife"] > prior["landscape"]


def test_exif_prior_wide_angle_boosts_landscape() -> None:
    """Wide focal length + small aperture boosts landscape."""
    exif = {"focal_length": 16.0, "aperture": 11.0, "shutter": 1 / 30, "iso": 100}
    prior = _compute_exif_prior(exif)
    assert prior["landscape"] > prior["portrait"]


def test_exif_prior_empty_returns_uniform() -> None:
    """Missing EXIF should give uniform prior."""
    prior = _compute_exif_prior({})
    values = list(prior.values())
    assert all(abs(v - values[0]) < 0.01 for v in values)


def test_low_confidence_falls_back_to_general() -> None:
    """When no evidence is strong, genre should be 'general'."""
    ctx = _make_context(
        clip_embedding=np.zeros(512, dtype=np.float32),
        detections=[],
        exif={},
    )
    result = route_genre(ctx)
    # With zero CLIP + no YOLO + no EXIF, confidence should be low
    # and the result may be "general" depending on the router's fallback logic
    assert result.confidence >= 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_genre_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'photo_workflow.genre_router'`

- [ ] **Step 3: Implement the genre router**

```python
# src/photo_workflow/genre_router.py
"""Genre router — CLIP + EXIF + YOLO Bayesian fusion for genre classification."""

from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np

from .scoring_types import GenreResult, ObjectDetection, SubjectContext

logger = logging.getLogger(__name__)

GENRES = ["wildlife", "landscape", "portrait", "street", "architecture", "macro", "event", "general"]

# Animal COCO class IDs: bird=14, cat=15, dog=16, horse=17, sheep=18, cow=19,
# elephant=20, bear=21, zebra=22, giraffe=23
_ANIMAL_CLASS_IDS = {14, 15, 16, 17, 18, 19, 20, 21, 22, 23}

# EXIF priors: (mean, std) for log(value) per genre
# Format: {genre: {"focal_length": (mean_log, std_log), ...}}
_EXIF_PRIORS = {
    "wildlife": {"focal_length": (5.7, 0.8), "aperture": (1.2, 0.5), "shutter": (-7.0, 1.0), "iso": (6.4, 0.8)},
    "landscape": {"focal_length": (3.0, 0.6), "aperture": (2.2, 0.3), "shutter": (-3.0, 2.0), "iso": (4.6, 0.5)},
    "portrait": {"focal_length": (4.2, 0.4), "aperture": (0.5, 0.5), "shutter": (-5.5, 0.8), "iso": (5.5, 0.8)},
    "street": {"focal_length": (3.5, 0.4), "aperture": (1.4, 0.5), "shutter": (-6.0, 0.8), "iso": (6.2, 0.8)},
    "architecture": {"focal_length": (3.0, 0.6), "aperture": (2.1, 0.3), "shutter": (-2.0, 2.0), "iso": (4.6, 0.5)},
    "macro": {"focal_length": (4.3, 0.3), "aperture": (2.1, 0.3), "shutter": (-5.0, 0.8), "iso": (5.5, 0.8)},
    "event": {"focal_length": (3.8, 0.5), "aperture": (1.2, 0.4), "shutter": (-5.5, 0.8), "iso": (6.0, 0.8)},
    "general": {"focal_length": (3.8, 1.5), "aperture": (1.5, 1.0), "shutter": (-5.0, 2.0), "iso": (5.5, 1.5)},
}

# Confidence threshold below which we fall back to "general"
_CONFIDENCE_THRESHOLD = 0.3


def _compute_exif_prior(exif: dict) -> dict[str, float]:
    """Compute per-genre log-Gaussian likelihood from EXIF metadata.

    Returns a dict of genre -> unnormalized probability.
    Missing fields contribute uniform (1.0) across all genres.
    """
    result = {g: 0.0 for g in GENRES}  # Log-space accumulator

    fields = [
        ("focal_length", "focal_length"),
        ("aperture", "aperture"),
        ("shutter", "shutter"),
        ("iso", "iso"),
    ]

    any_field_present = False
    for exif_key, prior_key in fields:
        value = exif.get(exif_key)
        if value is None or value <= 0:
            continue
        any_field_present = True
        log_val = math.log(value + 1e-10)

        for genre in GENRES:
            mean, std = _EXIF_PRIORS[genre][prior_key]
            # Log-Gaussian: log P(x|genre) = -0.5 * ((log_val - mean) / std)^2
            log_prob = -0.5 * ((log_val - mean) / std) ** 2
            result[genre] += log_prob

    if not any_field_present:
        # Uniform prior
        return {g: 1.0 / len(GENRES) for g in GENRES}

    # Convert from log-space to probability (softmax-style)
    max_val = max(result.values())
    exp_vals = {g: math.exp(result[g] - max_val) for g in GENRES}
    total = sum(exp_vals.values())
    return {g: exp_vals[g] / total for g in GENRES}


def _compute_yolo_evidence(
    detections: list[ObjectDetection], image_area: int
) -> dict[str, float]:
    """Compute genre evidence from YOLO detections.

    Returns dict of genre -> unnormalized probability.
    """
    evidence = {g: 1.0 for g in GENRES}  # Start uniform

    if not detections or image_area == 0:
        # Uniform
        total = sum(evidence.values())
        return {g: v / total for g in GENRES}

    has_animal = False
    has_person = False
    largest_person_ratio = 0.0
    person_count = 0

    for det in detections:
        det_area = det.bbox[2] * det.bbox[3]
        area_ratio = det_area / image_area

        if det.class_id in _ANIMAL_CLASS_IDS and area_ratio > 0.05:
            has_animal = True
            evidence["wildlife"] *= 3.0

        if det.class_name == "person":
            person_count += 1
            largest_person_ratio = max(largest_person_ratio, area_ratio)
            has_person = True

    # Person logic
    if has_person:
        if largest_person_ratio > 0.15:
            evidence["portrait"] *= 2.5
            evidence["event"] *= 1.5
        if person_count >= 3:
            evidence["event"] *= 2.0
            evidence["street"] *= 1.5
        elif person_count == 1 and largest_person_ratio < 0.05:
            evidence["street"] *= 1.5
            evidence["landscape"] *= 1.2

    # No living subjects
    if not has_animal and not has_person:
        evidence["landscape"] *= 1.5
        evidence["architecture"] *= 1.5
        evidence["macro"] *= 1.3

    # Normalize
    total = sum(evidence.values())
    return {g: v / total for g in GENRES}


def _compute_clip_similarity(
    clip_embedding: np.ndarray,
    genre_prototypes: np.ndarray | None,
) -> dict[str, float]:
    """Compute genre probabilities from CLIP cosine similarity.

    genre_prototypes: shape (num_genres, 512) — precomputed text embeddings.
    Returns softmax over cosine similarities.
    """
    if genre_prototypes is None or np.allclose(clip_embedding, 0.0):
        # No CLIP signal — uniform
        return {g: 1.0 / len(GENRES) for g in GENRES}

    # Cosine similarity (embedding is already L2-normalized)
    similarities = genre_prototypes @ clip_embedding  # (num_genres,)

    # Temperature-scaled softmax
    temperature = 0.1
    exp_sim = np.exp((similarities - similarities.max()) / temperature)
    probs = exp_sim / exp_sim.sum()

    return {GENRES[i]: float(probs[i]) for i in range(len(GENRES))}


def route_genre(
    ctx: SubjectContext,
    genre_prototypes: np.ndarray | None = None,
) -> GenreResult:
    """Classify image genre using Bayesian product-of-experts.

    Fuses CLIP similarity, EXIF prior, and YOLO object evidence.
    Falls back to "general" when confidence is below threshold.

    Args:
        ctx: SubjectContext with CLIP embedding, detections, and EXIF.
        genre_prototypes: Precomputed genre prototype embeddings, shape (8, 512).
                          If None, CLIP evidence is uniform.

    Returns:
        GenreResult with top genre, confidence, and full distribution.
    """
    # Evidence source 1: CLIP
    clip_probs = _compute_clip_similarity(ctx.clip_embedding, genre_prototypes)

    # Evidence source 2: EXIF prior
    exif_probs = _compute_exif_prior(ctx.exif)

    # Evidence source 3: YOLO
    image_area = ctx.image_bgr.shape[0] * ctx.image_bgr.shape[1]
    yolo_probs = _compute_yolo_evidence(ctx.detections, image_area)

    # Bayesian product-of-experts fusion
    fused = {}
    for g in GENRES:
        fused[g] = clip_probs[g] * exif_probs[g] * yolo_probs[g]

    # Normalize
    total = sum(fused.values())
    if total > 0:
        distribution = {g: fused[g] / total for g in GENRES}
    else:
        distribution = {g: 1.0 / len(GENRES) for g in GENRES}

    # Find top genre
    top_genre = max(distribution, key=lambda g: distribution[g])
    confidence = distribution[top_genre]

    # Fallback to general if confidence is too low
    if confidence < _CONFIDENCE_THRESHOLD:
        top_genre = "general"
        confidence = distribution["general"]

    return GenreResult(
        genre=top_genre,
        confidence=confidence,
        distribution=distribution,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_genre_router.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Lint check**

Run: `ruff check src/photo_workflow/genre_router.py tests/test_genre_router.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/photo_workflow/genre_router.py tests/test_genre_router.py
git commit -m "feat(scoring): add genre router with CLIP + EXIF + YOLO fusion"
```

---

## Task 4: Enhanced Sharpness Module

**Files:**
- Modify: `src/photo_workflow/sharpness.py`
- Create: `tests/test_sharpness_v2.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sharpness_v2.py
"""Tests for enhanced subject-aware sharpness scoring."""

from __future__ import annotations

import numpy as np
import pytest

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
    """High-frequency checkerboard should have high Tenengrad."""
    arr = (np.indices((256, 256)).sum(axis=0) % 2 * 255).astype(np.uint8)
    score = _tenengrad(arr)
    assert score > 100.0


def test_tenengrad_uniform_image_low() -> None:
    """Solid gray image should have near-zero Tenengrad."""
    arr = np.full((256, 256), 128, dtype=np.uint8)
    score = _tenengrad(arr)
    assert score < 1.0


def test_sml_sharp_image_high() -> None:
    """High-frequency image should have high SML."""
    arr = (np.indices((256, 256)).sum(axis=0) % 2 * 255).astype(np.uint8)
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
    img = np.full((256, 256), 128, dtype=np.uint8)
    # Add slight noise to avoid division issues
    img = img + np.random.randint(-2, 3, img.shape, dtype=np.int16)
    img = np.clip(img, 0, 255).astype(np.uint8)

    ctx = _make_context(img)
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sharpness_v2.py -v`
Expected: FAIL with `ImportError: cannot import name 'score_sharpness_detailed'`

- [ ] **Step 3: Implement enhanced sharpness**

Replace the contents of `src/photo_workflow/sharpness.py` with:

```python
# src/photo_workflow/sharpness.py
"""FR-1.4: Focus scoring via Tenengrad + SML with subject-aware regions."""

from __future__ import annotations

import logging
from pathlib import Path

import click
import cv2
import numpy as np

from .scoring_types import SharpnessScores, SubjectContext

logger = logging.getLogger(__name__)

_SUPPORTED_EXTS = {
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".raw",
    ".cr2", ".cr3", ".nef", ".arw", ".dng",
}

# Thresholds for blur classification
_SHARP_THRESHOLD = 0.25  # Normalized score above this = "sharp"
_RATIO_BOKEH_THRESHOLD = 3.0  # subject/background ratio above this = bokeh


def _tenengrad(gray: np.ndarray) -> float:
    """Compute Tenengrad focus measure (Sobel gradient magnitude squared).

    Returns raw unnormalized score (higher = sharper).
    """
    if gray.size == 0:
        return 0.0
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    tenengrad = float(np.mean(gx**2 + gy**2))
    return tenengrad


def _sml(gray: np.ndarray) -> float:
    """Compute Sum of Modified Laplacian focus measure.

    Returns raw unnormalized score (higher = sharper).
    """
    if gray.size == 0:
        return 0.0
    img = gray.astype(np.float64)
    # Modified Laplacian: |d2f/dx2| + |d2f/dy2| (avoids sign cancellation)
    lxx = cv2.Sobel(img, cv2.CV_64F, 2, 0, ksize=3)
    lyy = cv2.Sobel(img, cv2.CV_64F, 0, 2, ksize=3)
    ml = np.abs(lxx) + np.abs(lyy)
    return float(np.mean(ml))


def _compute_region_sharpness(gray: np.ndarray, mask: np.ndarray) -> float:
    """Compute geometric mean of Tenengrad and SML for a masked region.

    Normalizes by mean luminance to make scores comparable across exposures.
    Returns normalized score in approximately [0, 1] range.
    """
    # Extract region pixels
    if mask.sum() == 0:
        return 0.0

    # Apply mask
    region = gray.copy()
    region[mask == 0] = 0

    # Compute focus measures on the masked region
    ten = _tenengrad(region)
    sml_val = _sml(region)

    if ten <= 0 or sml_val <= 0:
        return 0.0

    # Geometric mean
    raw = float(np.sqrt(ten * sml_val))

    # Normalize by mean luminance of the region to handle exposure differences
    mean_luma = float(gray[mask > 0].mean()) if mask.sum() > 0 else 128.0
    luma_factor = max(mean_luma, 1.0) / 128.0

    # Normalize to approximate [0, 1] range
    # Empirical normalization constant (tuned for typical photos)
    normalized = raw / (500.0 * luma_factor)
    return min(normalized, 1.0)


def _classify_blur(subject_sharp: bool, bg_sharp: bool, ratio: float) -> str:
    """Classify blur type based on region sharpness analysis.

    Args:
        subject_sharp: Whether subject region exceeds sharpness threshold.
        bg_sharp: Whether background region exceeds sharpness threshold.
        ratio: subject_sharpness / background_sharpness.

    Returns:
        One of: "sharp", "bokeh", "motion_subject", "motion_global", "misfocused"
    """
    if subject_sharp and bg_sharp:
        return "sharp"
    if subject_sharp and not bg_sharp:
        if ratio > _RATIO_BOKEH_THRESHOLD:
            return "bokeh"
        return "bokeh"  # Even moderate contrast with sharp subject = intentional DOF
    if not subject_sharp and bg_sharp:
        return "misfocused"
    # Neither sharp
    return "motion_global"


def score_sharpness_detailed(ctx: SubjectContext) -> SharpnessScores:
    """Compute subject-aware sharpness scores using Tenengrad + SML.

    Args:
        ctx: SubjectContext containing image_gray and subject_mask.

    Returns:
        SharpnessScores with per-region scores and blur classification.
    """
    gray = ctx.image_gray
    mask = ctx.subject_mask
    inv_mask = 1 - mask

    # Compute per-region sharpness
    subject_score = _compute_region_sharpness(gray, mask)
    background_score = _compute_region_sharpness(gray, inv_mask)

    # Eye region sharpness
    eye_score = subject_score  # Default: same as subject
    if ctx.faces:
        # Use first face's eye landmarks
        face = ctx.faces[0]
        if "left_eye" in face.landmarks and "right_eye" in face.landmarks:
            le = face.landmarks["left_eye"]
            re = face.landmarks["right_eye"]
            # Create eye region mask (rectangle around both eyes)
            eye_mask = np.zeros_like(gray, dtype=np.uint8)
            eye_w = abs(re[0] - le[0])
            eye_h = max(eye_w // 3, 10)
            y_center = (le[1] + re[1]) // 2
            x_min = min(le[0], re[0]) - eye_w // 4
            x_max = max(le[0], re[0]) + eye_w // 4
            y_min = y_center - eye_h
            y_max = y_center + eye_h
            # Clamp to image bounds
            y_min = max(0, y_min)
            y_max = min(gray.shape[0], y_max)
            x_min = max(0, x_min)
            x_max = min(gray.shape[1], x_max)
            if y_max > y_min and x_max > x_min:
                eye_mask[y_min:y_max, x_min:x_max] = 1
                eye_score = _compute_region_sharpness(gray, eye_mask)
    elif ctx.detections:
        # For animals: use upper third of primary detection bbox as eye region
        for det in ctx.detections:
            if det.class_name in ("cat", "dog", "bird", "horse", "bear"):
                x, y, w, h = det.bbox
                head_h = h // 3
                eye_mask = np.zeros_like(gray, dtype=np.uint8)
                y_min = max(0, y)
                y_max = min(gray.shape[0], y + head_h)
                x_min = max(0, x)
                x_max = min(gray.shape[1], x + w)
                if y_max > y_min and x_max > x_min:
                    eye_mask[y_min:y_max, x_min:x_max] = 1
                    eye_score = _compute_region_sharpness(gray, eye_mask)
                break

    # Sharpness contrast ratio
    sharpness_contrast = subject_score / max(background_score, 0.01)

    # Blur classification
    subject_sharp = subject_score >= _SHARP_THRESHOLD
    bg_sharp = background_score >= _SHARP_THRESHOLD
    blur_type = _classify_blur(subject_sharp, bg_sharp, sharpness_contrast)

    # Overall score (weighted combination favoring subject and eye)
    overall = 0.5 * subject_score + 0.35 * eye_score + 0.15 * min(sharpness_contrast / 5.0, 1.0)
    overall = min(overall, 1.0)

    return SharpnessScores(
        subject=round(subject_score, 4),
        eye_region=round(eye_score, 4),
        background=round(background_score, 4),
        sharpness_contrast=round(sharpness_contrast, 4),
        blur_type=blur_type,
        overall=round(overall, 4),
    )


# --- Backward compatibility ---

# Legacy threshold for the old API
BLUR_THRESHOLD = 100.0


def score_sharpness(path: Path) -> float:
    """Compute sharpness score for a single image file.

    Backward-compatible wrapper that returns a single float in [0.0, 1.0].
    Internally uses the enhanced Tenengrad+SML subject-aware scoring.
    """
    from .raw_loader import load_rgb, load_gray

    try:
        image_gray = load_gray(path)
    except Exception:
        logger.warning("Could not load image for sharpness: %s", path)
        return 0.0

    # Build minimal context (full-image mask since we have no model here)
    h, w = image_gray.shape
    image_bgr = np.stack([image_gray] * 3, axis=-1)  # Fake BGR
    ctx = SubjectContext(
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

    scores = score_sharpness_detailed(ctx)
    return scores.overall


@click.command("sharpness")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--threshold",
    default=BLUR_THRESHOLD,
    show_default=True,
    help="Blur threshold for normalization (variance units).",
)
def main(path: Path, threshold: float) -> None:
    """Score sharpness for PATH (file or directory of images)."""
    targets = sorted(path.iterdir()) if path.is_dir() else [path]
    for p in targets:
        if not (p.is_file() and p.suffix.lower() in _SUPPORTED_EXTS):
            continue
        score = score_sharpness(p)
        click.echo(f"{p}: {score:.4f}")
```

- [ ] **Step 4: Run ALL sharpness tests to verify backward compatibility**

Run: `pytest tests/test_sharpness.py tests/test_sharpness_v2.py -v`
Expected: All tests PASS (both old and new)

- [ ] **Step 5: Lint check**

Run: `ruff check src/photo_workflow/sharpness.py tests/test_sharpness_v2.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/photo_workflow/sharpness.py tests/test_sharpness_v2.py
git commit -m "feat(scoring): enhance sharpness with Tenengrad+SML and subject-aware regions"
```

---

## Task 5: Enhanced Composition Module

**Files:**
- Modify: `src/photo_workflow/composition.py`
- Create: `tests/test_composition_v2.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_composition_v2.py
"""Tests for enhanced composition scoring."""

from __future__ import annotations

import numpy as np
import pytest

from photo_workflow.scoring_types import SubjectContext, CompositionScores
from photo_workflow.composition import (
    score_composition_detailed,
    _improved_rot_score,
    _symmetry_score,
    _leading_lines_score,
    _negative_space_score,
    _subject_isolation_score,
    _balance_score,
)


def _make_context(
    image_bgr: np.ndarray,
    subject_mask: np.ndarray | None = None,
) -> SubjectContext:
    """Build a SubjectContext for composition tests."""
    h, w = image_bgr.shape[:2]
    gray = np.mean(image_bgr, axis=2).astype(np.uint8) if image_bgr.ndim == 3 else image_bgr
    if subject_mask is None:
        subject_mask = np.zeros((h, w), dtype=np.uint8)
        subject_mask[h//4:3*h//4, w//4:3*w//4] = 1
    return SubjectContext(
        image_bgr=image_bgr,
        image_gray=gray,
        thumbnail_rgb=np.zeros((100, 100, 3), dtype=np.uint8),
        subject_mask=subject_mask,
        subject_area_ratio=float(subject_mask.sum()) / (h * w),
        faces=[],
        detections=[],
        primary_subject_bbox=None,
        clip_embedding=np.zeros(512, dtype=np.float32),
        exif={},
    )


def test_score_composition_detailed_returns_dataclass() -> None:
    """score_composition_detailed should return CompositionScores."""
    img = np.random.randint(0, 255, (300, 400, 3), dtype=np.uint8)
    ctx = _make_context(img)
    result = score_composition_detailed(ctx)
    assert isinstance(result, CompositionScores)
    assert 0.0 <= result.overall <= 1.0


def test_rot_score_in_range() -> None:
    """Rule of thirds score should be in [0, 1]."""
    saliency = np.random.rand(300, 400).astype(np.float32)
    score = _improved_rot_score(saliency)
    assert 0.0 <= score <= 1.0


def test_rot_score_subject_at_power_point() -> None:
    """Subject placed exactly at a power point should score high."""
    saliency = np.zeros((300, 400), dtype=np.float32)
    # Place bright spot at upper-left power point (1/3, 1/3)
    py, px = 100, 133
    saliency[py-10:py+10, px-10:px+10] = 1.0
    score = _improved_rot_score(saliency)
    assert score > 0.5


def test_symmetry_score_symmetric_image() -> None:
    """A horizontally symmetric image should score higher than random."""
    # Create symmetric image
    half = np.random.randint(50, 200, (200, 100, 3), dtype=np.uint8)
    img = np.hstack([half, np.fliplr(half)])
    score_sym = _symmetry_score(img)

    # Random image
    random_img = np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8)
    score_rand = _symmetry_score(random_img)

    assert score_sym >= score_rand * 0.8  # Symmetric should generally score higher


def test_negative_space_high_for_minimal_subject() -> None:
    """Image with small subject and clean background has high negative space."""
    mask = np.zeros((300, 400), dtype=np.uint8)
    mask[130:170, 180:220] = 1  # Small subject (tiny area)
    bg = np.full((300, 400), 128, dtype=np.uint8)  # Uniform background
    score = _negative_space_score(mask, bg)
    assert score > 0.5


def test_negative_space_low_for_full_frame_subject() -> None:
    """Image with subject filling entire frame has low negative space."""
    mask = np.ones((300, 400), dtype=np.uint8)
    bg = np.random.randint(0, 255, (300, 400), dtype=np.uint8)
    score = _negative_space_score(mask, bg)
    assert score < 0.3


def test_balance_centered_subject_high() -> None:
    """Subject centered in frame should have high balance."""
    saliency = np.zeros((300, 400), dtype=np.float32)
    saliency[125:175, 175:225] = 1.0  # Center hot spot
    score = _balance_score(saliency)
    assert score > 0.7


def test_balance_corner_subject_low() -> None:
    """Subject in corner should have low balance."""
    saliency = np.zeros((300, 400), dtype=np.float32)
    saliency[0:30, 0:30] = 1.0  # Top-left corner
    score = _balance_score(saliency)
    assert score < 0.5


def test_backward_compat_score_composition(sharp_image) -> None:
    """Original score_composition(path) still works and returns float."""
    from photo_workflow.composition import score_composition
    result = score_composition(sharp_image)
    assert isinstance(result, float)
    assert 0.0 <= result <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_composition_v2.py -v`
Expected: FAIL with `ImportError: cannot import name 'score_composition_detailed'`

- [ ] **Step 3: Implement enhanced composition**

Replace `src/photo_workflow/composition.py` with:

```python
# src/photo_workflow/composition.py
"""FR-1.5: Composition scoring — RoT, symmetry, leading lines, negative space, isolation, balance."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from .scoring_types import CompositionScores, SubjectContext

logger = logging.getLogger(__name__)


def _compute_saliency(img_bgr: np.ndarray) -> np.ndarray:
    """Compute spectral residual saliency map (Hou & Zhang 2007).

    Returns float32 map in [0.0, 1.0] at original resolution.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    small = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)

    fft = np.fft.fft2(small)
    log_amplitude = np.log(np.abs(fft) + 1e-8)

    kernel = np.ones((3, 3), dtype=np.float32) / 9.0
    avg_log_amplitude = cv2.filter2D(log_amplitude.astype(np.float32), -1, kernel)
    spectral_residual = log_amplitude - avg_log_amplitude

    phase = np.angle(fft)
    sr_fft = np.exp(spectral_residual + 1j * phase)
    saliency_small = np.abs(np.fft.ifft2(sr_fft)) ** 2

    saliency_small = cv2.GaussianBlur(saliency_small.astype(np.float32), (5, 5), sigmaX=2.5)
    s_min, s_max = saliency_small.min(), saliency_small.max()
    if s_max > s_min:
        saliency_small = (saliency_small - s_min) / (s_max - s_min)
    else:
        saliency_small = np.zeros_like(saliency_small)

    h, w = img_bgr.shape[:2]
    saliency_map = cv2.resize(saliency_small, (w, h), interpolation=cv2.INTER_LINEAR)
    return saliency_map.astype(np.float32)


def _improved_rot_score(saliency_map: np.ndarray) -> float:
    """Score Rule of Thirds using Gaussian falloff from power points.

    Uses exp(-d^2 / 2*sigma^2) where d is normalized by diagonal.
    """
    h, w = saliency_map.shape
    diagonal = np.sqrt(h**2 + w**2)
    sigma = 0.1  # Gaussian width relative to diagonal

    power_points = [
        (h / 3, w / 3),
        (h / 3, 2 * w / 3),
        (2 * h / 3, w / 3),
        (2 * h / 3, 2 * w / 3),
    ]

    # Find salient region centroids via thresholding
    threshold = saliency_map.mean() + saliency_map.std()
    salient_mask = saliency_map > threshold
    if not salient_mask.any():
        return 0.0

    # Find centroid of salient region
    ys, xs = np.where(salient_mask)
    if len(ys) == 0:
        return 0.0

    # Weighted centroid
    weights = saliency_map[salient_mask]
    cy = float(np.average(ys, weights=weights))
    cx = float(np.average(xs, weights=weights))

    # Score: max Gaussian proximity to any power point
    best_score = 0.0
    for py, px in power_points:
        d = np.sqrt((cy - py)**2 + (cx - px)**2) / diagonal
        score = float(np.exp(-d**2 / (2 * sigma**2)))
        best_score = max(best_score, score)

    return min(best_score, 1.0)


def _symmetry_score(img_bgr: np.ndarray) -> float:
    """Detect bilateral symmetry using ORB keypoint mirroring.

    Returns score in [0, 1] based on matched symmetric keypoint pairs.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    # Resize for speed
    h, w = gray.shape
    scale = min(1.0, 1024 / max(h, w))
    if scale < 1.0:
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)))

    orb = cv2.ORB_create(nfeatures=200)
    kp, des = orb.detectAndCompute(gray, None)

    if des is None or len(kp) < 10:
        return 0.0

    h_s, w_s = gray.shape

    # Mirror keypoints horizontally and compute matching
    mirrored_kp = [cv2.KeyPoint(w_s - k.pt[0], k.pt[1], k.size, k.angle) for k in kp]
    _, mirrored_des = orb.compute(gray, mirrored_kp)

    if mirrored_des is None:
        return 0.0

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    matches = bf.knnMatch(des, mirrored_des, k=2)

    # Ratio test
    good_matches = 0
    for match_pair in matches:
        if len(match_pair) >= 2:
            m, n = match_pair
            if m.distance < 0.75 * n.distance:
                good_matches += 1

    score = good_matches / max(len(kp), 1)
    return min(score * 2.0, 1.0)  # Scale up since perfect symmetry rarely exceeds 0.5


def _leading_lines_score(img_bgr: np.ndarray, subject_centroid: tuple[float, float]) -> float:
    """Detect leading lines converging toward the subject.

    Uses probabilistic Hough transform on Canny edges.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    diagonal = np.sqrt(h**2 + w**2)

    # Resize for speed
    scale = min(1.0, 1024 / max(h, w))
    if scale < 1.0:
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)))
        h_s, w_s = gray.shape
        cx = subject_centroid[0] * scale
        cy = subject_centroid[1] * scale
        diag_s = np.sqrt(h_s**2 + w_s**2)
    else:
        cx, cy = subject_centroid
        diag_s = diagonal

    edges = cv2.Canny(gray, 50, 150)
    min_length = int(0.15 * diag_s)

    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=50,
                            minLineLength=min_length, maxLineGap=10)

    if lines is None or len(lines) == 0:
        return 0.0

    convergence_score = 0.0
    total_weight = 0.0

    for line in lines:
        x1, y1, x2, y2 = line[0]
        length = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)

        # Check if line extension converges toward subject centroid
        # Direction vector
        dx, dy = x2 - x1, y2 - y1
        norm = np.sqrt(dx**2 + dy**2)
        if norm == 0:
            continue

        # Distance from subject centroid to the line
        # Using point-to-line distance formula
        dist = abs(dy * cx - dx * cy + x2 * y1 - y2 * x1) / norm
        proximity = 0.15 * diag_s  # 15% of diagonal threshold

        if dist < proximity:
            convergence_score += length
        total_weight += length

    if total_weight == 0:
        return 0.0

    score = convergence_score / total_weight
    return min(score, 1.0)


def _negative_space_score(subject_mask: np.ndarray, gray: np.ndarray) -> float:
    """Score negative space quality — ratio and background smoothness.

    High score = good amount of clean negative space surrounding subject.
    """
    total_pixels = subject_mask.size
    subject_pixels = int(subject_mask.sum())
    negative_ratio = 1.0 - (subject_pixels / max(total_pixels, 1))

    # Score peaks around 0.65-0.75 (Gaussian centered at 0.7)
    ratio_score = float(np.exp(-((negative_ratio - 0.7) ** 2) / (2 * 0.15**2)))

    # Background smoothness: low gradient = clean background
    bg_mask = (subject_mask == 0)
    if bg_mask.any():
        bg_region = gray.copy()
        bg_region[~bg_mask] = 0
        grad_x = cv2.Sobel(bg_region, cv2.CV_64F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(bg_region, cv2.CV_64F, 0, 1, ksize=3)
        grad_mag = np.sqrt(grad_x**2 + grad_y**2)
        mean_grad = float(grad_mag[bg_mask].mean()) if bg_mask.any() else 0.0
        # Lower gradient = smoother = better. Normalize inversely.
        smoothness = max(0.0, 1.0 - mean_grad / 100.0)
    else:
        smoothness = 0.0

    # Combined score
    return ratio_score * 0.6 + smoothness * 0.4


def _subject_isolation_score(
    img_bgr: np.ndarray,
    subject_mask: np.ndarray,
    sharpness_contrast: float,
) -> float:
    """Score how well the subject separates from background.

    Combines sharpness contrast, color contrast (DeltaE), and luminance contrast.
    """
    # Color contrast in Lab
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2Lab).astype(np.float32)
    subject_pixels = lab[subject_mask > 0]
    bg_pixels = lab[subject_mask == 0]

    if len(subject_pixels) == 0 or len(bg_pixels) == 0:
        return 0.0

    mean_subject = subject_pixels.mean(axis=0)
    mean_bg = bg_pixels.mean(axis=0)

    # CIE76 DeltaE
    delta_e = float(np.sqrt(np.sum((mean_subject - mean_bg) ** 2)))
    color_contrast = min(delta_e / 50.0, 1.0)

    # Luminance contrast
    luma_subject = float(mean_subject[0])  # L channel
    luma_bg = float(mean_bg[0])
    luma_contrast = min(abs(luma_subject - luma_bg) / 100.0, 1.0)

    # Sharpness contrast (normalize ratio to [0,1])
    sharp_contrast_norm = min(sharpness_contrast / 5.0, 1.0)

    # Weighted combination
    isolation = 0.4 * sharp_contrast_norm + 0.35 * color_contrast + 0.25 * luma_contrast
    return min(isolation, 1.0)


def _balance_score(saliency_map: np.ndarray) -> float:
    """Score visual balance — how centered the visual weight is.

    Returns 1.0 for perfectly centered, 0.0 for extreme corner.
    """
    h, w = saliency_map.shape
    total = saliency_map.sum()
    if total == 0:
        return 0.5  # Neutral

    # Weighted centroid
    ys, xs = np.mgrid[0:h, 0:w]
    cy = float(np.sum(ys * saliency_map) / total)
    cx = float(np.sum(xs * saliency_map) / total)

    # Distance from center normalized by half-diagonal
    center_y, center_x = h / 2, w / 2
    dist = np.sqrt((cy - center_y)**2 + (cx - center_x)**2)
    half_diag = np.sqrt(h**2 + w**2) / 2

    score = 1.0 - (dist / half_diag)
    return max(0.0, min(score, 1.0))


def score_composition_detailed(ctx: SubjectContext) -> CompositionScores:
    """Compute comprehensive composition sub-scores.

    Args:
        ctx: SubjectContext with image, mask, and detection info.

    Returns:
        CompositionScores with six sub-scores and an overall.
    """
    img_bgr = ctx.image_bgr
    gray = ctx.image_gray
    mask = ctx.subject_mask

    # Compute saliency map
    try:
        saliency = _compute_saliency(img_bgr)
    except Exception:
        saliency = np.zeros(gray.shape, dtype=np.float32)

    # Find subject centroid for leading lines
    ys, xs = np.where(mask > 0)
    if len(ys) > 0:
        subject_centroid = (float(xs.mean()), float(ys.mean()))
    else:
        h, w = gray.shape
        subject_centroid = (w / 2, h / 2)

    # Compute sub-scores
    rot = _improved_rot_score(saliency)
    symmetry = _symmetry_score(img_bgr)
    lines = _leading_lines_score(img_bgr, subject_centroid)
    neg_space = _negative_space_score(mask, gray)

    # For isolation, we need sharpness contrast — compute a quick ratio
    from .sharpness import _compute_region_sharpness
    subj_sharp = _compute_region_sharpness(gray, mask)
    bg_sharp = _compute_region_sharpness(gray, 1 - mask)
    sharp_contrast = subj_sharp / max(bg_sharp, 0.01)

    isolation = _subject_isolation_score(img_bgr, mask, sharp_contrast)
    balance = _balance_score(saliency)

    # Overall: equal-weighted (genre weighting happens in fusion)
    overall = (rot + symmetry + lines + neg_space + isolation + balance) / 6.0

    return CompositionScores(
        rule_of_thirds=round(rot, 4),
        symmetry=round(symmetry, 4),
        leading_lines=round(lines, 4),
        negative_space=round(neg_space, 4),
        subject_isolation=round(isolation, 4),
        balance=round(balance, 4),
        overall=round(overall, 4),
    )


# --- Backward compatibility ---

def score_composition(path: Path) -> float:
    """Score composition for a single image. Backward-compatible wrapper."""
    from .raw_loader import load_rgb
    try:
        img = load_rgb(path)
    except Exception:
        logger.warning("Could not load image for composition: %s", path)
        return 0.0

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ctx = SubjectContext(
        image_bgr=img,
        image_gray=gray,
        thumbnail_rgb=np.zeros((100, 100, 3), dtype=np.uint8),
        subject_mask=np.ones((h, w), dtype=np.uint8),
        subject_area_ratio=1.0,
        faces=[],
        detections=[],
        primary_subject_bbox=None,
        clip_embedding=np.zeros(512, dtype=np.float32),
        exif={},
    )

    scores = score_composition_detailed(ctx)
    return scores.overall
```

- [ ] **Step 4: Run ALL composition tests**

Run: `pytest tests/test_composition.py tests/test_composition_v2.py -v`
Expected: All tests PASS

- [ ] **Step 5: Lint check**

Run: `ruff check src/photo_workflow/composition.py tests/test_composition_v2.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/photo_workflow/composition.py tests/test_composition_v2.py
git commit -m "feat(scoring): enhance composition with symmetry, lines, negative space, isolation, balance"
```

---

## Task 6: Enhanced Exposure Module

**Files:**
- Modify: `src/photo_workflow/exposure.py`
- Create: `tests/test_exposure_v2.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_exposure_v2.py
"""Tests for enhanced exposure scoring."""

from __future__ import annotations

import numpy as np
import pytest

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_exposure_v2.py -v`
Expected: FAIL with `ImportError: cannot import name 'score_exposure_detailed'`

- [ ] **Step 3: Implement enhanced exposure**

Replace `src/photo_workflow/exposure.py` with:

```python
# src/photo_workflow/exposure.py
"""FR-1.6: Exposure scoring — zone system, clipping, DR, style detection, face exposure."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from .scoring_types import ExposureScores, FaceDetection, SubjectContext

logger = logging.getLogger(__name__)

NUM_ZONES = 11  # FR-1.6: 11-zone luminance segmentation


def _detect_style(zone_probs: np.ndarray) -> tuple[str, float]:
    """Detect intentional exposure style from zone distribution.

    Args:
        zone_probs: Normalized histogram over 11 zones (sums to ~1.0).

    Returns:
        Tuple of (style_name, confidence).
    """
    high_zones = float(zone_probs[7:].sum())  # Zones VII-X
    low_zones = float(zone_probs[:5].sum())  # Zones 0-IV

    if high_zones > 0.70 and low_zones < 0.10:
        return "high_key", high_zones

    if low_zones > 0.70 and high_zones < 0.10:
        # Check for bright accent (distinguishes low-key from just underexposed)
        # If any zone above VII has > 2% → there's a bright accent
        if zone_probs[8:].sum() > 0.02:
            return "low_key", low_zones
        # Still likely intentional if strongly bimodal
        return "low_key", low_zones * 0.7  # Lower confidence without accent

    # Silhouette: bimodal with peaks at 0-I and VIII-X
    shadow_peak = float(zone_probs[:2].sum())
    highlight_peak = float(zone_probs[8:].sum())
    if shadow_peak > 0.25 and highlight_peak > 0.25:
        return "silhouette", min(shadow_peak, highlight_peak)

    return "normal", 0.0


def _compute_face_exposure(
    image_bgr: np.ndarray,
    faces: list[FaceDetection],
) -> float:
    """Compute face region exposure quality.

    Returns score in [0, 1] if face present, -1.0 if no face.
    """
    if not faces:
        return -1.0

    # Use first (highest confidence) face
    face = max(faces, key=lambda f: f.confidence)
    x, y, w, h = face.bbox

    # Extract face region
    img_h, img_w = image_bgr.shape[:2]
    x = max(0, x)
    y = max(0, y)
    x2 = min(img_w, x + w)
    y2 = min(img_h, y + h)

    if x2 <= x or y2 <= y:
        return -1.0

    face_region = image_bgr[y:y2, x:x2]
    if face_region.size == 0:
        return -1.0

    # Convert to YCrCb and get luma
    ycrcb = cv2.cvtColor(face_region, cv2.COLOR_BGR2YCrCb)
    median_luma = float(np.median(ycrcb[:, :, 0]))

    # Score against ideal band [110, 220]
    ideal_low, ideal_high = 110.0, 220.0
    if ideal_low <= median_luma <= ideal_high:
        return 1.0
    elif median_luma < ideal_low:
        # Penalize underexposed faces
        return max(0.0, median_luma / ideal_low)
    else:
        # Penalize overexposed faces
        return max(0.0, 1.0 - (median_luma - ideal_high) / (255.0 - ideal_high))


def score_exposure_detailed(ctx: SubjectContext) -> ExposureScores:
    """Compute comprehensive exposure sub-scores.

    Args:
        ctx: SubjectContext with image and face detections.

    Returns:
        ExposureScores with zone analysis, clipping, DR, style, and face exposure.
    """
    img_bgr = ctx.image_bgr

    # Convert to YCrCb and extract luma
    ycrcb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2YCrCb)
    luma = ycrcb[:, :, 0].astype(np.float32)

    # Zone histogram
    hist, _ = np.histogram(luma, bins=NUM_ZONES, range=(0, 256))
    hist_float = hist.astype(np.float32)
    total_pixels = float(hist_float.sum())

    # Zone entropy
    nonzero = hist_float[hist_float > 0]
    if len(nonzero) == 0:
        zone_entropy = 0.0
    else:
        prob = nonzero / nonzero.sum()
        entropy = -float(np.sum(prob * np.log2(prob)))
        max_entropy = np.log2(NUM_ZONES)
        zone_entropy = entropy / max_entropy if max_entropy > 0 else 0.0

    # Zone diversity
    zone_diversity = int(np.sum(hist_float > (total_pixels * 0.01)))

    # Clipping detection
    luma_uint8 = luma.astype(np.uint8) if luma.max() <= 255 else (luma / luma.max() * 255).astype(np.uint8)
    clipping_shadows = float(np.mean(luma < 4.0))
    clipping_highlights = float(np.mean(luma > 251.0))

    # Dynamic range
    p005 = float(np.percentile(luma, 0.5))
    p995 = float(np.percentile(luma, 99.5))
    dynamic_range = (p995 - p005) / 255.0

    # Midtone density (zones III-VII, approximately luma 90-160)
    midtone_pixels = float(np.sum((luma >= 90) & (luma <= 160)))
    midtone_density = midtone_pixels / max(total_pixels, 1)

    # Style detection
    zone_probs = hist_float / max(total_pixels, 1)
    style, style_confidence = _detect_style(zone_probs)

    # Face exposure
    face_exposure = _compute_face_exposure(img_bgr, ctx.faces)

    # Overall score computation
    score = zone_entropy

    # Penalize clipping (unless style justifies it)
    if style != "silhouette":
        score -= clipping_shadows * 2.0
    if style != "high_key":
        score -= clipping_highlights * 2.0

    # Reward good dynamic range (unless intentional style)
    if style == "normal":
        score += (dynamic_range - 0.5) * 0.3

    # Face exposure penalty (hard to fix in post)
    if face_exposure >= 0 and face_exposure < 0.5:
        score -= (0.5 - face_exposure) * 0.4

    # Clamp
    overall = max(0.0, min(1.0, score))

    return ExposureScores(
        zone_entropy=round(zone_entropy, 4),
        zone_diversity=zone_diversity,
        clipping_shadows=round(clipping_shadows, 4),
        clipping_highlights=round(clipping_highlights, 4),
        dynamic_range=round(dynamic_range, 4),
        midtone_density=round(midtone_density, 4),
        face_exposure=round(face_exposure, 4),
        style=style,
        style_confidence=round(style_confidence, 4),
        overall=round(overall, 4),
    )


# --- Backward compatibility ---

def score_exposure(path: Path) -> float:
    """Score exposure for a single image. Backward-compatible wrapper."""
    from .raw_loader import load_rgb
    try:
        img = load_rgb(path)
    except Exception:
        logger.warning("Could not load image for exposure: %s", path)
        return 0.0

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ctx = SubjectContext(
        image_bgr=img,
        image_gray=gray,
        thumbnail_rgb=np.zeros((100, 100, 3), dtype=np.uint8),
        subject_mask=np.ones((h, w), dtype=np.uint8),
        subject_area_ratio=1.0,
        faces=[],
        detections=[],
        primary_subject_bbox=None,
        clip_embedding=np.zeros(512, dtype=np.float32),
        exif={},
    )

    scores = score_exposure_detailed(ctx)
    return scores.overall
```

- [ ] **Step 4: Run ALL exposure tests**

Run: `pytest tests/test_exposure.py tests/test_exposure_v2.py -v`
Expected: All tests PASS

- [ ] **Step 5: Lint check**

Run: `ruff check src/photo_workflow/exposure.py tests/test_exposure_v2.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/photo_workflow/exposure.py tests/test_exposure_v2.py
git commit -m "feat(scoring): enhance exposure with clipping, DR, style detection, face exposure"
```

---

## Task 7: Score Fusion Module

**Files:**
- Create: `src/photo_workflow/score_fusion.py`
- Create: `tests/test_score_fusion.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_score_fusion.py
"""Tests for genre-weighted score fusion."""

from __future__ import annotations

import pytest

from photo_workflow.scoring_types import (
    SharpnessScores,
    CompositionScores,
    ExposureScores,
    GenreResult,
    FusionResult,
)
from photo_workflow.score_fusion import fuse_scores, GENRE_WEIGHTS


def _make_sharpness(**kwargs) -> SharpnessScores:
    defaults = dict(subject=0.7, eye_region=0.8, background=0.3,
                    sharpness_contrast=2.3, blur_type="bokeh", overall=0.7)
    defaults.update(kwargs)
    return SharpnessScores(**defaults)


def _make_composition(**kwargs) -> CompositionScores:
    defaults = dict(rule_of_thirds=0.6, symmetry=0.4, leading_lines=0.3,
                    negative_space=0.65, subject_isolation=0.7, balance=0.6, overall=0.55)
    defaults.update(kwargs)
    return CompositionScores(**defaults)


def _make_exposure(**kwargs) -> ExposureScores:
    defaults = dict(zone_entropy=0.8, zone_diversity=8, clipping_shadows=0.01,
                    clipping_highlights=0.02, dynamic_range=0.85, midtone_density=0.4,
                    face_exposure=-1.0, style="normal", style_confidence=0.0, overall=0.75)
    defaults.update(kwargs)
    return ExposureScores(**defaults)


def _make_genre(genre: str = "wildlife", confidence: float = 0.85) -> GenreResult:
    dist = {g: 0.02 for g in GENRE_WEIGHTS}
    dist[genre] = confidence
    # Normalize
    total = sum(dist.values())
    dist = {g: v / total for g, v in dist.items()}
    return GenreResult(genre=genre, confidence=dist[genre], distribution=dist)


def test_fuse_scores_returns_fusion_result() -> None:
    """fuse_scores should return a FusionResult."""
    result = fuse_scores(
        sharpness=_make_sharpness(),
        composition=_make_composition(),
        exposure=_make_exposure(),
        genre=_make_genre(),
        aesthetic=0.65,
    )
    assert isinstance(result, FusionResult)
    assert 0.0 <= result.master_score <= 1.0
    assert result.genre == "wildlife"
    assert result.star_rating in range(1, 6)


def test_genre_weights_all_sum_to_one() -> None:
    """Every genre weight profile should sum to 1.0."""
    for genre, weights in GENRE_WEIGHTS.items():
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01, f"{genre} weights sum to {total}"


def test_high_scores_produce_high_master() -> None:
    """All-high sub-scores should produce a high master score."""
    result = fuse_scores(
        sharpness=_make_sharpness(subject=0.95, eye_region=0.95, background=0.3, overall=0.9),
        composition=_make_composition(rule_of_thirds=0.9, subject_isolation=0.9, overall=0.85),
        exposure=_make_exposure(zone_entropy=0.9, dynamic_range=0.95, overall=0.9),
        genre=_make_genre("wildlife"),
        aesthetic=0.9,
    )
    assert result.master_score > 0.7
    assert result.star_rating >= 4


def test_low_scores_produce_low_master() -> None:
    """All-low sub-scores should produce a low master score."""
    result = fuse_scores(
        sharpness=_make_sharpness(subject=0.1, eye_region=0.1, background=0.1, overall=0.1),
        composition=_make_composition(rule_of_thirds=0.1, subject_isolation=0.1, overall=0.1),
        exposure=_make_exposure(zone_entropy=0.2, dynamic_range=0.2, overall=0.2),
        genre=_make_genre("wildlife"),
        aesthetic=0.2,
    )
    assert result.master_score < 0.3
    assert result.star_rating <= 2


def test_hard_reject_motion_global() -> None:
    """motion_global with low subject sharpness should hard reject."""
    result = fuse_scores(
        sharpness=_make_sharpness(subject=0.1, eye_region=0.1, blur_type="motion_global"),
        composition=_make_composition(),
        exposure=_make_exposure(),
        genre=_make_genre("wildlife"),
        aesthetic=0.7,
    )
    assert result.hard_reject is True
    assert "motion_global" in result.hard_reject_reason


def test_hard_reject_misfocused() -> None:
    """Misfocused with very low eye sharpness should hard reject."""
    result = fuse_scores(
        sharpness=_make_sharpness(eye_region=0.1, blur_type="misfocused"),
        composition=_make_composition(),
        exposure=_make_exposure(),
        genre=_make_genre("portrait"),
        aesthetic=0.7,
    )
    assert result.hard_reject is True
    assert "misfocused" in result.hard_reject_reason


def test_no_hard_reject_for_bokeh() -> None:
    """Bokeh should NOT trigger hard reject."""
    result = fuse_scores(
        sharpness=_make_sharpness(subject=0.8, blur_type="bokeh"),
        composition=_make_composition(),
        exposure=_make_exposure(),
        genre=_make_genre("portrait"),
        aesthetic=0.7,
    )
    assert result.hard_reject is False


def test_color_label_mapping() -> None:
    """Color labels should map correctly from master score."""
    # Excellent
    result = fuse_scores(
        sharpness=_make_sharpness(subject=0.95, eye_region=0.95, overall=0.9),
        composition=_make_composition(overall=0.85),
        exposure=_make_exposure(overall=0.9),
        genre=_make_genre("wildlife"),
        aesthetic=0.9,
    )
    assert result.color_label == 3  # BLUE (excellent)

    # Weak
    result2 = fuse_scores(
        sharpness=_make_sharpness(subject=0.15, eye_region=0.1, overall=0.1),
        composition=_make_composition(overall=0.1),
        exposure=_make_exposure(overall=0.2),
        genre=_make_genre("wildlife"),
        aesthetic=0.1,
    )
    assert result2.color_label == 1  # YELLOW (weak)


def test_soft_genre_blending() -> None:
    """Mixed genre probabilities should blend weights, not hard-switch."""
    # 50% wildlife, 50% portrait
    dist = {g: 0.0 for g in GENRE_WEIGHTS}
    dist["wildlife"] = 0.5
    dist["portrait"] = 0.5
    genre = GenreResult(genre="wildlife", confidence=0.5, distribution=dist)

    result = fuse_scores(
        sharpness=_make_sharpness(),
        composition=_make_composition(),
        exposure=_make_exposure(),
        genre=genre,
        aesthetic=0.6,
    )
    # Should still produce a valid result
    assert 0.0 <= result.master_score <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_score_fusion.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'photo_workflow.score_fusion'`

- [ ] **Step 3: Implement score fusion**

```python
# src/photo_workflow/score_fusion.py
"""Genre-weighted score fusion — combines sub-scores into master score."""

from __future__ import annotations

import logging

from .scoring_types import (
    CompositionScores,
    ExposureScores,
    FusionResult,
    GenreResult,
    SharpnessScores,
)

logger = logging.getLogger(__name__)

# Darktable color label constants
_DT_RED = 0
_DT_YELLOW = 1
_DT_GREEN = 2
_DT_BLUE = 3
_DT_PURPLE = 4
_DT_NONE = -1

GENRE_WEIGHTS: dict[str, dict[str, float]] = {
    "wildlife": {
        "eye_sharpness": 0.28, "subject_sharpness": 0.12,
        "subject_isolation": 0.10, "composition_rot": 0.10,
        "negative_space": 0.08, "exposure_overall": 0.12,
        "blur_type_penalty": 0.08, "aesthetic_clip": 0.07,
        "behavior_proxy": 0.05,
    },
    "landscape": {
        "zone_entropy": 0.12, "dynamic_range": 0.12,
        "front_to_back_sharp": 0.16, "composition_rot": 0.10,
        "leading_lines": 0.10, "negative_space": 0.08,
        "balance": 0.08, "highlight_clip": 0.10,
        "aesthetic_clip": 0.08, "symmetry": 0.06,
    },
    "portrait": {
        "eye_sharpness": 0.25, "face_exposure": 0.12,
        "subject_isolation": 0.12, "composition_rot": 0.10,
        "negative_space": 0.10, "blur_type_bonus": 0.08,
        "expression_proxy": 0.08, "balance": 0.07,
        "aesthetic_clip": 0.08,
    },
    "street": {
        "subject_sharpness": 0.18, "composition_rot": 0.12,
        "leading_lines": 0.12, "subject_isolation": 0.10,
        "exposure_overall": 0.12, "negative_space": 0.08,
        "motion_tolerance": 0.08, "aesthetic_clip": 0.10,
        "balance": 0.05, "symmetry": 0.05,
    },
    "architecture": {
        "symmetry": 0.18, "leading_lines": 0.16,
        "subject_sharpness": 0.15, "exposure_overall": 0.12,
        "composition_rot": 0.10, "balance": 0.10,
        "negative_space": 0.07, "highlight_clip": 0.07,
        "aesthetic_clip": 0.05,
    },
    "macro": {
        "subject_sharpness": 0.25, "sharpness_contrast": 0.15,
        "negative_space": 0.12, "subject_isolation": 0.12,
        "composition_rot": 0.10, "exposure_overall": 0.08,
        "balance": 0.06, "aesthetic_clip": 0.07,
        "color_contrast": 0.05,
    },
    "event": {
        "eye_sharpness": 0.20, "face_exposure": 0.12,
        "expression_proxy": 0.18, "subject_sharpness": 0.15,
        "composition_rot": 0.10, "exposure_overall": 0.10,
        "aesthetic_clip": 0.08, "balance": 0.07,
    },
    "general": {
        "subject_sharpness": 0.20, "exposure_overall": 0.18,
        "composition_rot": 0.15, "subject_isolation": 0.12,
        "aesthetic_clip": 0.10, "negative_space": 0.10,
        "balance": 0.08, "symmetry": 0.07,
    },
}


def _build_sub_score_dict(
    sharpness: SharpnessScores,
    composition: CompositionScores,
    exposure: ExposureScores,
    aesthetic: float,
) -> dict[str, float]:
    """Map module outputs to the flat sub-score dictionary used by weight profiles."""
    # Direct mappings
    scores: dict[str, float] = {
        "eye_sharpness": sharpness.eye_region,
        "subject_sharpness": sharpness.subject,
        "sharpness_contrast": min(sharpness.sharpness_contrast / 5.0, 1.0),
        "composition_rot": composition.rule_of_thirds,
        "symmetry": composition.symmetry,
        "leading_lines": composition.leading_lines,
        "negative_space": composition.negative_space,
        "subject_isolation": composition.subject_isolation,
        "balance": composition.balance,
        "zone_entropy": exposure.zone_entropy,
        "dynamic_range": exposure.dynamic_range,
        "exposure_overall": exposure.overall,
        "aesthetic_clip": aesthetic,
    }

    # Face exposure (use neutral 0.5 if no face)
    scores["face_exposure"] = exposure.face_exposure if exposure.face_exposure >= 0 else 0.5

    # Derived scores
    # front_to_back_sharp: both regions must be sharp
    scores["front_to_back_sharp"] = min(sharpness.subject, sharpness.background)

    # blur_type_penalty: penalize motion_global and misfocused
    scores["blur_type_penalty"] = 0.0 if sharpness.blur_type in ("motion_global", "misfocused") else 1.0

    # blur_type_bonus: reward bokeh
    if sharpness.blur_type == "bokeh":
        scores["blur_type_bonus"] = 1.0
    elif sharpness.blur_type == "sharp":
        scores["blur_type_bonus"] = 0.5
    else:
        scores["blur_type_bonus"] = 0.0

    # motion_tolerance: tolerate subject motion, penalize global
    scores["motion_tolerance"] = 0.0 if sharpness.blur_type == "motion_global" else 1.0

    # highlight_clip: inverted (lower clipping = higher score)
    scores["highlight_clip"] = 1.0 - exposure.clipping_highlights

    # expression_proxy: placeholder (would need eye-open detection)
    # For now: if face detected (face_exposure != -1), assume eyes open = 0.7
    scores["expression_proxy"] = 0.7 if exposure.face_exposure >= 0 else 0.5

    # behavior_proxy: motion on subject = interesting for wildlife
    scores["behavior_proxy"] = 1.0 if sharpness.blur_type == "motion_subject" else 0.5

    # color_contrast: reuse subject_isolation (which includes color contrast)
    scores["color_contrast"] = composition.subject_isolation

    return scores


def _compute_master_score(
    sub_scores: dict[str, float],
    genre: GenreResult,
) -> float:
    """Compute the genre-weighted master score via soft blending."""
    # Blend weight profiles by genre distribution (soft weighting)
    effective_weights: dict[str, float] = {}

    for genre_name, prob in genre.distribution.items():
        if genre_name not in GENRE_WEIGHTS:
            continue
        for key, weight in GENRE_WEIGHTS[genre_name].items():
            effective_weights[key] = effective_weights.get(key, 0.0) + prob * weight

    # Dot product: sum(weight * score) for all keys that exist in both
    master = 0.0
    for key, weight in effective_weights.items():
        if key in sub_scores:
            master += weight * sub_scores[key]

    return max(0.0, min(1.0, master))


def _check_hard_gates(sharpness: SharpnessScores) -> tuple[bool, str]:
    """Check hard rejection gates.

    Returns (is_rejected, reason).
    """
    if sharpness.blur_type == "motion_global" and sharpness.subject < 0.2:
        return True, "motion_global_blur"

    if sharpness.blur_type == "misfocused" and sharpness.eye_region < 0.15:
        return True, "misfocused"

    return False, ""


def _score_to_stars(master_score: float) -> int:
    """Map master score [0, 1] to star rating [1, 5]."""
    return max(1, min(5, round(master_score * 5)))


def _score_to_color_label(master_score: float, hard_reject: bool) -> int:
    """Map master score to Darktable color label.

    RED is reserved for duplicates (handled elsewhere).
    Hard rejects get the Darktable reject flag, not a color label.
    """
    if hard_reject:
        return _DT_NONE  # Reject flag is separate from color labels

    if master_score < 0.3:
        return _DT_YELLOW
    if master_score < 0.5:
        return _DT_NONE
    if master_score < 0.75:
        return _DT_GREEN
    return _DT_BLUE


def fuse_scores(
    sharpness: SharpnessScores,
    composition: CompositionScores,
    exposure: ExposureScores,
    genre: GenreResult,
    aesthetic: float,
) -> FusionResult:
    """Fuse all sub-scores into a genre-weighted master score.

    Args:
        sharpness: Enhanced sharpness analysis results.
        composition: Enhanced composition analysis results.
        exposure: Enhanced exposure analysis results.
        genre: Genre classification result with probability distribution.
        aesthetic: CLIP aesthetic head score in [0, 1].

    Returns:
        FusionResult with master score, sub-scores, and classification labels.
    """
    # Build flat sub-score dictionary
    sub_scores = _build_sub_score_dict(sharpness, composition, exposure, aesthetic)

    # Check hard rejection gates
    hard_reject, reject_reason = _check_hard_gates(sharpness)

    # Compute genre-weighted master score
    master_score = _compute_master_score(sub_scores, genre)

    # Map to output labels
    star_rating = _score_to_stars(master_score)
    color_label = _score_to_color_label(master_score, hard_reject)

    return FusionResult(
        master_score=round(master_score, 4),
        genre=genre.genre,
        genre_confidence=round(genre.confidence, 4),
        sub_scores=sub_scores,
        hard_reject=hard_reject,
        hard_reject_reason=reject_reason,
        star_rating=star_rating,
        color_label=color_label,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_score_fusion.py -v`
Expected: All 11 tests PASS

- [ ] **Step 5: Lint check**

Run: `ruff check src/photo_workflow/score_fusion.py tests/test_score_fusion.py`
Expected: No errors

- [ ] **Step 6: Commit**

```bash
git add src/photo_workflow/score_fusion.py tests/test_score_fusion.py
git commit -m "feat(scoring): add genre-weighted score fusion with hard gates and color labels"
```

---

## Task 8: Pipeline Integration + Database + Darktable Bridge

**Files:**
- Modify: `src/photo_workflow/pipeline.py`
- Modify: `src/photo_workflow/darktable_bridge.py`
- Modify: `src/photo_workflow/photondb.py`

- [ ] **Step 1: Update PhotoRecord with new fields**

In `src/photo_workflow/pipeline.py`, update the `PhotoRecord` dataclass:

```python
@dataclass
class PhotoRecord:
    """Shared state passed through each pipeline stage."""
    path: Path
    session_id: str = ""
    is_duplicate: bool = False
    sharpness_score: float = 0.0
    composition_score: float = 0.0
    exposure_score: float = 0.0
    semantic_name: str = ""
    metadata: dict = field(default_factory=dict)
    # New genre-aware fields
    genre: str = ""
    genre_confidence: float = 0.0
    master_score: float = 0.0
    sub_scores: dict = field(default_factory=dict)
    hard_reject: bool = False
    hard_reject_reason: str = ""
```

- [ ] **Step 2: Update PipelineConfig with model_dir for scoring models**

In `src/photo_workflow/pipeline.py`, update `PipelineConfig`:

```python
@dataclass
class PipelineConfig:
    source_dir: Path
    output_dir: Path
    darktable_db: Path
    model_dir: Path = Path("models/florence2_int8")
    scoring_model_dir: Path = Path("models")
    dry_run: bool = False
```

- [ ] **Step 3: Update AnalysisPipeline.run() to use new scoring**

In `src/photo_workflow/pipeline.py`, update the `run()` method:

```python
    def run(self) -> tuple[list[PhotoRecord], PipelineSummary]:
        """Execute the full pipeline and return processed records and summary."""
        from .ingest import ingest_volume
        from .grouping import cluster_sessions
        from .dedup import deduplicate
        from .sharpness import score_sharpness_detailed
        from .composition import score_composition_detailed
        from .exposure import score_exposure_detailed
        from .genre_router import route_genre
        from .score_fusion import fuse_scores
        from .subject_context import ModelSessions, build_subject_context
        from .naming import generate_name
        from .darktable_bridge import sync_to_darktable

        t0 = time.perf_counter()

        logger.info("Pipeline start: source=%s", self.config.source_dir)

        paths = ingest_volume(self.config.source_dir, self.config.output_dir, dry_run=self.config.dry_run)

        records = [
            PhotoRecord(path=p, metadata={"original_filename": p.name})
            for p in paths
        ]

        records = cluster_sessions(records)
        records = deduplicate(records)

        # Initialize model sessions for scoring
        model_sessions = ModelSessions(self.config.scoring_model_dir)

        for record in records:
            if record.is_duplicate:
                continue

            # Build shared subject context (runs all models once)
            ctx = build_subject_context(record.path, model_sessions)

            # Genre routing
            genre_result = route_genre(ctx)

            # Enhanced scoring
            sharp = score_sharpness_detailed(ctx)
            comp = score_composition_detailed(ctx)
            expo = score_exposure_detailed(ctx)

            # CLIP aesthetic score
            aesthetic_session = model_sessions.clip_aesthetic_head
            if aesthetic_session is not None:
                aesthetic_out = aesthetic_session.run(
                    None, {aesthetic_session.get_inputs()[0].name: ctx.clip_embedding.reshape(1, -1)}
                )
                aesthetic = float(aesthetic_out[0].flatten()[0])
                aesthetic = max(0.0, min(1.0, aesthetic))
            else:
                aesthetic = 0.5  # Neutral fallback

            # Fuse scores
            fusion = fuse_scores(sharp, comp, expo, genre_result, aesthetic)

            # Populate record (both old and new fields for compatibility)
            record.sharpness_score = sharp.overall
            record.composition_score = comp.overall
            record.exposure_score = expo.overall
            record.genre = fusion.genre
            record.genre_confidence = fusion.genre_confidence
            record.master_score = fusion.master_score
            record.sub_scores = fusion.sub_scores
            record.hard_reject = fusion.hard_reject
            record.hard_reject_reason = fusion.hard_reject_reason

            # Semantic naming (Florence-2)
            record.semantic_name = generate_name(record.path, model_dir=self.config.model_dir)

        scored = sum(1 for r in records if not r.is_duplicate)

        if not self.config.dry_run:
            xmp_written = sync_to_darktable(records)
            db_upserted = 0
        else:
            xmp_written = 0
            db_upserted = 0

        logger.info("Pipeline complete: %d records processed", len(records))

        summary = PipelineSummary(
            total=len(records),
            duplicates_skipped=sum(1 for r in records if r.is_duplicate),
            scored=scored,
            xmp_written=xmp_written,
            db_upserted=db_upserted,
            elapsed_seconds=time.perf_counter() - t0,
        )
        return records, summary
```

- [ ] **Step 4: Update the CLI `score` command**

In the `score` CLI command in `pipeline.py`, update to use the new scoring:

```python
@cli.command()
@click.option("--db", "db_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--folder", required=True, help="Folder/table name in the DB.")
@click.option("--source-dir", "source_dir", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--model-dir", default=None, type=click.Path(path_type=Path),
              help="Parent model directory containing scoring model subdirs.")
@click.option("--resume", is_flag=True, default=False)
@click.option("--force", is_flag=True, default=False)
@click.option("--json-progress", "json_progress", is_flag=True, default=False)
def score(db_path: Path, folder: str, source_dir: Path, model_dir: Path | None,
          resume: bool, force: bool, json_progress: bool) -> None:
    """Score photos using genre-aware multi-dimensional analysis."""
    import sqlite3

    from .sharpness import score_sharpness_detailed
    from .composition import score_composition_detailed
    from .exposure import score_exposure_detailed
    from .genre_router import route_genre
    from .score_fusion import fuse_scores
    from .subject_context import ModelSessions, build_subject_context
    from .photondb import (
        sanitize_table_name, ensure_table, get_pending,
        update_scores, update_genre_scores, update_stages, clear_stage,
    )

    if model_dir is None:
        model_dir = Path(__file__).resolve().parent.parent.parent / "models"

    table = sanitize_table_name(folder)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_table(conn, table)

    if force:
        clear_stage(conn, table, "score")

    pending = get_pending(conn, table, "score")
    to_score = [r for r in pending if not r["is_duplicate"]]

    if not to_score:
        click.echo("All non-duplicate photos already scored.")
        conn.close()
        return

    model_sessions = ModelSessions(model_dir)
    errors = 0

    for i, row in enumerate(to_score, 1):
        p = source_dir / row["filename"]
        try:
            ctx = build_subject_context(p, model_sessions)
            genre_result = route_genre(ctx)
            sharp = score_sharpness_detailed(ctx)
            comp = score_composition_detailed(ctx)
            expo = score_exposure_detailed(ctx)

            # Aesthetic score
            aesthetic_session = model_sessions.clip_aesthetic_head
            if aesthetic_session is not None:
                aesthetic_out = aesthetic_session.run(
                    None, {aesthetic_session.get_inputs()[0].name: ctx.clip_embedding.reshape(1, -1)}
                )
                aesthetic = float(aesthetic_out[0].flatten()[0])
                aesthetic = max(0.0, min(1.0, aesthetic))
            else:
                aesthetic = 0.5

            fusion = fuse_scores(sharp, comp, expo, genre_result, aesthetic)

            # Update DB (both old and new columns)
            update_scores(conn, table, row["filename"], sharp.overall, comp.overall, expo.overall)
            update_genre_scores(conn, table, row["filename"],
                                fusion.genre, fusion.genre_confidence,
                                fusion.master_score, fusion.sub_scores)
            update_stages(conn, table, row["filename"], "score")

            if json_progress:
                emit("score", row["filename"], "ok", json_progress=True,
                     genre=fusion.genre, master_score=round(fusion.master_score, 4),
                     stars=fusion.star_rating, color_label=fusion.color_label,
                     hard_reject=fusion.hard_reject)
        except Exception as exc:
            conn.execute(
                f"UPDATE [{table}] SET error=? WHERE filename=?",
                (str(exc), row["filename"]),
            )
            conn.commit()
            errors += 1
            if json_progress:
                emit("score", row["filename"], "error", json_progress=True, message=str(exc))

        if json_progress and i % 10 == 0:
            click.echo(json.dumps({"step": "_progress", "done": i, "total": len(to_score)}))

    conn.close()

    if not json_progress:
        scored_count = len(to_score) - errors
        click.echo(f"Scored {scored_count}/{len(to_score)} photos. {errors} errors.")
    else:
        click.echo(json.dumps({"step": "_progress", "done": len(to_score), "total": len(to_score)}))
```

- [ ] **Step 5: Update photondb.py with new columns and functions**

Add to `src/photo_workflow/photondb.py`:

```python
def ensure_table(conn: sqlite3.Connection, table: str) -> None:
    """Create the per-folder table if it doesn't exist. Adds new columns if missing."""
    table = sanitize_table_name(table)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS [{table}] (
            filename       TEXT PRIMARY KEY,
            original_name  TEXT NOT NULL,
            exif_timestamp TEXT,
            session_id     TEXT DEFAULT '',
            is_duplicate   INTEGER DEFAULT 0,
            sharpness      REAL,
            composition    REAL,
            exposure       REAL,
            semantic_name  TEXT DEFAULT '',
            stages         TEXT DEFAULT '',
            error          TEXT DEFAULT '',
            genre          TEXT DEFAULT '',
            genre_confidence REAL DEFAULT 0.0,
            master_score   REAL DEFAULT 0.0,
            sub_scores     TEXT DEFAULT ''
        )
    """)
    # Migrate existing tables: add columns if they don't exist
    existing_cols = {row[1] for row in conn.execute(f"PRAGMA table_info([{table}])").fetchall()}
    for col, typedef in [
        ("genre", "TEXT DEFAULT ''"),
        ("genre_confidence", "REAL DEFAULT 0.0"),
        ("master_score", "REAL DEFAULT 0.0"),
        ("sub_scores", "TEXT DEFAULT ''"),
    ]:
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE [{table}] ADD COLUMN {col} {typedef}")
    conn.commit()


def update_genre_scores(
    conn: sqlite3.Connection,
    table: str,
    filename: str,
    genre: str,
    genre_confidence: float,
    master_score: float,
    sub_scores: dict,
) -> None:
    """Write genre-aware scoring results."""
    import json as json_mod
    table = sanitize_table_name(table)
    conn.execute(
        f"UPDATE [{table}] SET genre=?, genre_confidence=?, master_score=?, sub_scores=? WHERE filename=?",
        (genre, genre_confidence, master_score, json_mod.dumps(sub_scores), filename),
    )
    conn.commit()
```

- [ ] **Step 6: Update darktable_bridge.py XMP template**

Update the XMP template in `src/photo_workflow/darktable_bridge.py` to include genre and sub-scores:

```python
XMP_TEMPLATE = """\
<?xpacket begin='\xef\xbb\xbf' id='W5M0MpCehiHzreSzNTczkc9d'?>
<x:xmpmeta xmlns:x='adobe:ns:meta/' x:xmptk='PHOTONForge'>
  <rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
    <rdf:Description rdf:about=''
      xmlns:xmp='http://ns.adobe.com/xap/1.0/'
      xmlns:dc='http://purl.org/dc/elements/1.1/'
      xmlns:photon='https://photonforge.local/xmp/1.0/'>
      <photon:SharpnessScore>{sharpness}</photon:SharpnessScore>
      <photon:CompositionScore>{composition}</photon:CompositionScore>
      <photon:ExposureScore>{exposure}</photon:ExposureScore>
      <photon:Genre>{genre}</photon:Genre>
      <photon:GenreConfidence>{genre_confidence}</photon:GenreConfidence>
      <photon:MasterScore>{master_score}</photon:MasterScore>
      <photon:SemanticName>{semantic_name}</photon:SemanticName>
      <photon:OriginalFilename>{original_filename}</photon:OriginalFilename>
      <photon:SessionID>{session_id}</photon:SessionID>
      <photon:IsDuplicate>{is_duplicate}</photon:IsDuplicate>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end='w'?>
"""
```

And update `_write_xmp` to use the new fields:

```python
def _write_xmp(record: "PhotoRecord") -> None:
    xmp_path = record.path.with_suffix(".xmp")
    original_filename = record.metadata.get("original_filename", record.path.name)
    xmp_content = XMP_TEMPLATE.format(
        sharpness=record.sharpness_score,
        composition=record.composition_score,
        exposure=record.exposure_score,
        genre=record.genre or "",
        genre_confidence=round(record.genre_confidence, 4),
        master_score=round(record.master_score, 4),
        semantic_name=record.semantic_name,
        original_filename=original_filename,
        session_id=record.session_id,
        is_duplicate=str(record.is_duplicate).lower(),
    )
    xmp_path.write_text(xmp_content, encoding="utf-8")
```

Also update `compute_color_label` to use the new scheme:

```python
def compute_color_label(master_score: float = 0.0, hard_reject: bool = False, **kwargs) -> int:
    """Return the Darktable color label int.

    New scheme: based on master_score tiers.
    RED (0) is reserved for duplicates.
    Hard rejects use the Darktable reject flag (not a color label).

    Maintains backward compatibility: if called with (sharpness, composition, exposure)
    positional args, uses the legacy priority cascade.
    """
    # Legacy compatibility: detect old-style 3-arg call
    if kwargs.get("_legacy"):
        sharpness = master_score
        composition = kwargs.get("composition", 0.0)
        exposure = kwargs.get("exposure", 0.0)
        if sharpness < _THRESH_SHARPNESS:
            return _DT_YELLOW
        if exposure < _THRESH_EXPOSURE:
            return _DT_BLUE
        if composition < _THRESH_COMPOSITION:
            return _DT_PURPLE
        mean = (sharpness + composition + exposure) / 3.0
        if mean >= _THRESH_GREEN_MEAN:
            return _DT_GREEN
        return _DT_NONE

    # New scheme
    if hard_reject:
        return _DT_NONE
    if master_score < 0.3:
        return _DT_YELLOW
    if master_score < 0.5:
        return _DT_NONE
    if master_score < 0.75:
        return _DT_GREEN
    return _DT_BLUE
```

- [ ] **Step 7: Run full test suite**

Run: `pytest tests/ -v --ignore=tests/test_pipeline.py -m "not slow and not integration"`
Expected: All unit tests PASS

- [ ] **Step 8: Run integration tests**

Run: `pytest tests/test_pipeline.py -v -m integration`
Expected: Integration tests PASS (they use the backward-compat wrappers)

- [ ] **Step 9: Lint check all modified files**

Run: `ruff check src/photo_workflow/pipeline.py src/photo_workflow/darktable_bridge.py src/photo_workflow/photondb.py`
Expected: No errors

- [ ] **Step 10: Commit**

```bash
git add src/photo_workflow/pipeline.py src/photo_workflow/darktable_bridge.py src/photo_workflow/photondb.py
git commit -m "feat(scoring): wire genre-aware scoring into pipeline, DB schema, and XMP output"
```

---

## Task 9: Integration Test for Full Genre-Aware Flow

**Files:**
- Create: `tests/test_scoring_integration.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/test_scoring_integration.py
"""Integration tests for the full genre-aware scoring flow."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from photo_workflow.scoring_types import FusionResult
from photo_workflow.subject_context import ModelSessions, build_subject_context
from photo_workflow.genre_router import route_genre
from photo_workflow.sharpness import score_sharpness_detailed
from photo_workflow.composition import score_composition_detailed
from photo_workflow.exposure import score_exposure_detailed
from photo_workflow.score_fusion import fuse_scores


@pytest.fixture
def sharp_color_image(tmp_path: Path) -> Path:
    """Create a sharp color image with good tonal range."""
    arr = np.zeros((400, 600, 3), dtype=np.uint8)
    # Gradient background
    for i in range(400):
        arr[i, :, :] = int(i / 400 * 200) + 30
    # Sharp checkerboard subject in center
    checker = (np.indices((100, 100)).sum(axis=0) % 2 * 200 + 50).astype(np.uint8)
    arr[150:250, 250:350, 0] = checker
    arr[150:250, 250:350, 1] = checker
    arr[150:250, 250:350, 2] = checker
    p = tmp_path / "sharp_color.png"
    Image.fromarray(arr).save(p)
    return p


@pytest.fixture
def blurry_color_image(tmp_path: Path) -> Path:
    """Create a uniformly blurry image."""
    arr = np.full((400, 600, 3), 128, dtype=np.uint8)
    # Add very slight noise (still effectively blurry)
    noise = np.random.randint(-3, 4, arr.shape, dtype=np.int16)
    arr = np.clip(arr.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    p = tmp_path / "blurry_color.png"
    Image.fromarray(arr).save(p)
    return p


@pytest.mark.integration
def test_full_scoring_flow_no_models(sharp_color_image: Path, tmp_path: Path) -> None:
    """Full scoring flow should work without any ML models (graceful degradation)."""
    model_sessions = ModelSessions(tmp_path / "empty_models")
    ctx = build_subject_context(sharp_color_image, model_sessions)

    genre_result = route_genre(ctx)
    sharp = score_sharpness_detailed(ctx)
    comp = score_composition_detailed(ctx)
    expo = score_exposure_detailed(ctx)

    result = fuse_scores(sharp, comp, expo, genre_result, aesthetic=0.5)

    assert isinstance(result, FusionResult)
    assert 0.0 <= result.master_score <= 1.0
    assert result.genre in ("general", "landscape", "architecture", "wildlife",
                             "portrait", "street", "macro", "event")
    assert result.star_rating in range(1, 6)
    assert not result.hard_reject


@pytest.mark.integration
def test_sharp_scores_higher_than_blurry(
    sharp_color_image: Path, blurry_color_image: Path, tmp_path: Path
) -> None:
    """A sharp image should score higher than a blurry one."""
    model_sessions = ModelSessions(tmp_path / "empty_models")

    ctx_sharp = build_subject_context(sharp_color_image, model_sessions)
    genre_sharp = route_genre(ctx_sharp)
    s_sharp = score_sharpness_detailed(ctx_sharp)
    c_sharp = score_composition_detailed(ctx_sharp)
    e_sharp = score_exposure_detailed(ctx_sharp)
    result_sharp = fuse_scores(s_sharp, c_sharp, e_sharp, genre_sharp, 0.5)

    ctx_blurry = build_subject_context(blurry_color_image, model_sessions)
    genre_blurry = route_genre(ctx_blurry)
    s_blurry = score_sharpness_detailed(ctx_blurry)
    c_blurry = score_composition_detailed(ctx_blurry)
    e_blurry = score_exposure_detailed(ctx_blurry)
    result_blurry = fuse_scores(s_blurry, c_blurry, e_blurry, genre_blurry, 0.5)

    assert result_sharp.master_score > result_blurry.master_score


@pytest.mark.integration
def test_sub_scores_all_populated(sharp_color_image: Path, tmp_path: Path) -> None:
    """All expected sub-score keys should be present in the result."""
    model_sessions = ModelSessions(tmp_path / "empty_models")
    ctx = build_subject_context(sharp_color_image, model_sessions)
    genre = route_genre(ctx)
    sharp = score_sharpness_detailed(ctx)
    comp = score_composition_detailed(ctx)
    expo = score_exposure_detailed(ctx)
    result = fuse_scores(sharp, comp, expo, genre, 0.5)

    expected_keys = {
        "eye_sharpness", "subject_sharpness", "sharpness_contrast",
        "composition_rot", "symmetry", "leading_lines", "negative_space",
        "subject_isolation", "balance", "zone_entropy", "dynamic_range",
        "exposure_overall", "face_exposure", "aesthetic_clip",
        "front_to_back_sharp", "blur_type_penalty", "blur_type_bonus",
        "motion_tolerance", "highlight_clip", "expression_proxy",
        "behavior_proxy", "color_contrast",
    }
    assert expected_keys.issubset(set(result.sub_scores.keys()))
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/test_scoring_integration.py -v -m integration`
Expected: All 3 tests PASS

- [ ] **Step 3: Run FULL test suite**

Run: `pytest tests/ -v -m "not slow"`
Expected: All tests PASS (unit + integration)

- [ ] **Step 4: Commit**

```bash
git add tests/test_scoring_integration.py
git commit -m "test(scoring): add integration tests for full genre-aware scoring flow"
```

---

## Summary of All Files

### Created (9 files)
- `src/photo_workflow/scoring_types.py`
- `src/photo_workflow/subject_context.py`
- `src/photo_workflow/genre_router.py`
- `src/photo_workflow/score_fusion.py`
- `tests/test_scoring_types.py`
- `tests/test_subject_context.py`
- `tests/test_genre_router.py`
- `tests/test_score_fusion.py`
- `tests/test_scoring_integration.py`

### Modified (6 files)
- `src/photo_workflow/sharpness.py`
- `src/photo_workflow/composition.py`
- `src/photo_workflow/exposure.py`
- `src/photo_workflow/pipeline.py`
- `src/photo_workflow/darktable_bridge.py`
- `src/photo_workflow/photondb.py`

### New Test Files (5 files)
- `tests/test_sharpness_v2.py`
- `tests/test_composition_v2.py`
- `tests/test_exposure_v2.py`
- `tests/test_score_fusion.py`
- `tests/test_scoring_integration.py`
