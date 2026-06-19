"""Subject context builder — runs all models once per image."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .scoring_types import FaceDetection, ObjectDetection, SubjectContext
from .sharpness import _tenengrad

logger = logging.getLogger(__name__)

# CLIP input size for MobileCLIP-S2
_CLIP_INPUT_SIZE = 256

# RMBG input size
_RMBG_INPUT_SIZE = 320

# YOLO input size
_YOLO_INPUT_SIZE = 640


# Default trained genre prototypes shipped with the package. Used when no
# explicit training DB (e.g. an evolving cartridge calibration) is supplied, so a
# fresh install scores against the bundled baseline weights rather than the raw
# text-template prototypes in genre_prototypes.npy.
DEFAULT_TRAINING_DB = Path(__file__).resolve().parent / "data" / "genre_weights.db"


class ModelSessions:
    """Lazy-loaded, long-lived ONNX inference sessions."""

    def __init__(self, model_dir: Path, training_db_path: Path | None = None) -> None:
        self._model_dir = model_dir
        # Precedence for genre prototypes: explicit training DB (cartridge) >
        # bundled default weights > hardcoded genre_prototypes.npy.
        if training_db_path is None and DEFAULT_TRAINING_DB.exists():
            training_db_path = DEFAULT_TRAINING_DB
        self._training_db_path = training_db_path
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
        return self._load_session("clip_vision", "mobileclip_s2_int8", "vision_encoder.onnx")

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
    def aesthetic_head(self) -> Any:
        """NIMA aesthetic session, or None if missing OR degenerate.

        Both vendored aesthetic models have shipped as untrained placeholders
        that emit a constant for any input (provisioning fell back when
        TensorFlow was absent). A one-time self-check rejects such a model so it
        can't silently pin every aesthetic_clip to a constant — the failure that
        this property exists to make loud.
        """
        if "aesthetic_head_checked" not in self._sessions:
            sess = self._load_session("aesthetic_head", "nima_mobilenet_int8", "model.onnx")
            if sess is not None and _aesthetic_session_is_degenerate(sess):
                logger.warning(
                    "Aesthetic model at nima_mobilenet_int8 is degenerate (constant "
                    "output) — disabling. Re-provision a trained model "
                    "(scripts/provision_scoring_models.py aesthetic)."
                )
                sess = None
            self._sessions["aesthetic_head_checked"] = sess
        return self._sessions["aesthetic_head_checked"]

    @property
    def genre_prototypes(self) -> np.ndarray | None:
        if "genre_prototypes" not in self._sessions:
            # Try loading from training_weights.db if configured
            if self._training_db_path and self._training_db_path.exists():
                try:
                    from .training_weights_db import open_training_db, get_active_prototypes

                    conn = open_training_db(self._training_db_path)
                    active = get_active_prototypes(conn)
                    conn.close()

                    if active:
                        from .genre_router import SUBJECTS, PHOTO_TYPES

                        prototypes_list = []
                        for label in SUBJECTS:
                            if label in active:
                                prototypes_list.append(active[label]["prototype"])
                            else:
                                prototypes_list.append(np.zeros(512, dtype=np.float32))
                        for label in PHOTO_TYPES:
                            if label in active:
                                prototypes_list.append(active[label]["prototype"])
                            elif "general" in active and label == "general":
                                prototypes_list.append(active["general"]["prototype"])
                            else:
                                prototypes_list.append(np.zeros(512, dtype=np.float32))
                        protos = np.array(prototypes_list, dtype=np.float32)
                        self._sessions["genre_prototypes"] = protos
                        logger.info("Loaded genre prototypes from training_weights.db")
                        return protos
                except Exception as e:
                    logger.warning(
                        "Failed to load prototypes from training_weights.db: %s", e
                    )

            # Fallback to hardcoded file
            proto_path = self._model_dir / "genre_prototypes.npy"
            if proto_path.exists():
                try:
                    self._sessions["genre_prototypes"] = np.load(str(proto_path))
                    logger.info("Loaded genre prototypes: %s", proto_path)
                except Exception as e:
                    logger.warning("Failed to load genre prototypes: %s", e)
                    self._sessions["genre_prototypes"] = None
            else:
                logger.warning("Genre prototypes not found: %s", proto_path)
                self._sessions["genre_prototypes"] = None
        return self._sessions["genre_prototypes"]

    @property
    def genre_adapter(self) -> dict | None:
        """Learned linear classifier heads {axis: head} from the training DB.

        Returns None when no adapter is stored (callers fall back to prototypes).
        """
        if "genre_adapter" not in self._sessions:
            adapter = None
            if self._training_db_path and self._training_db_path.exists():
                try:
                    from .training_weights_db import open_training_db, get_active_linear_adapter

                    conn = open_training_db(self._training_db_path)
                    active = get_active_linear_adapter(conn)
                    conn.close()
                    if active.get("subject") and active.get("type"):
                        adapter = active
                        logger.info("Loaded learned genre adapter from training DB")
                except Exception as e:
                    logger.warning("Failed to load genre adapter: %s", e)
            self._sessions["genre_adapter"] = adapter
        return self._sessions["genre_adapter"]

    @property
    def aesthetic_weights(self) -> dict | None:
        """Per-genre aesthetic weight profiles from the training DB.

        Returns {'subject': {label: {key: w}}, 'type': {...}}, or None when none
        are stored (score fusion then falls back to its hardcoded defaults).
        """
        if "aesthetic_weights" not in self._sessions:
            profiles = None
            if self._training_db_path and self._training_db_path.exists():
                try:
                    from .training_weights_db import (
                        open_training_db, get_active_aesthetic_weights,
                    )

                    conn = open_training_db(self._training_db_path)
                    active = get_active_aesthetic_weights(conn)
                    conn.close()
                    if active.get("subject") and active.get("type"):
                        profiles = active
                        logger.info("Loaded aesthetic weight profiles from training DB")
                except Exception as e:
                    logger.warning("Failed to load aesthetic weights: %s", e)
            self._sessions["aesthetic_weights"] = profiles
        return self._sessions["aesthetic_weights"]


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
    """Run MobileCLIP-S2 vision encoder, return 512-dim embedding."""
    # Preprocess: resize, scale to [0,1], CHW, batch
    # MobileCLIP-S2 uses identity normalization: mean=(0,0,0), std=(1,1,1)
    img = cv2.resize(image_rgb, (_CLIP_INPUT_SIZE, _CLIP_INPUT_SIZE))
    img = img.astype(np.float32) / 255.0
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


def _aesthetic_session_is_degenerate(session: Any) -> bool:
    """True if the model emits ~identical output for two very different inputs.

    Catches untrained/placeholder models (zero weights -> constant output). Input
    shape is taken from the session so this works for image- or embedding-input
    heads. Conservative: any error -> not degenerate (don't disable on a fluke).
    """
    try:
        inp = session.get_inputs()[0]
        shape = [1 if (not isinstance(d, int) or d <= 0) else d for d in inp.shape]
        # Two clearly different, valid-range inputs; any non-trivial model maps
        # them to different outputs.
        a = np.full(shape, -0.5, dtype=np.float32)
        b = np.full(shape, 0.5, dtype=np.float32)
        name = inp.name
        oa = np.asarray(session.run(None, {name: a})[0]).flatten()
        ob = np.asarray(session.run(None, {name: b})[0]).flatten()
        return float(np.abs(oa - ob).max()) < 1e-4
    except Exception:
        return False


def _run_nima(image_rgb: np.ndarray, session: Any) -> float:
    """Run NIMA aesthetic model, return score in [0, 1].

    NIMA outputs a 10-bin probability distribution over scores 1-10.
    Mean score = sum(i * p_i), normalized to [0, 1] by dividing by 10.
    """
    # Resize to NIMA input size (224x224)
    img = cv2.resize(image_rgb, (224, 224))
    img = img.astype(np.float32)
    # MobileNet preprocessing: scale to [-1, 1]
    img = (img / 127.5) - 1.0
    img = np.expand_dims(img, axis=0)  # Add batch: (1, 224, 224, 3)
    # Note: NIMA uses NHWC format (TensorFlow convention)

    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: img})
    probs = outputs[0].flatten()  # 10-bin distribution

    # Mean score: sum(i * p_i) for i=1..10, then normalize to [0, 1]
    bins = np.arange(1, 11, dtype=np.float32)
    mean_score = float(np.sum(bins * probs))
    # Normalize: NIMA scores range 1-10, map to 0-1
    # Typical "good" photos score 5-7, exceptional 7+
    return max(0.0, min(1.0, (mean_score - 1.0) / 9.0))


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
        if len(det) < 5:
            continue  # Skip malformed detections
        conf = float(det[4])
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
    # Load image — use raw_loader for RAW formats (cv2.imread reads broken
    # embedded TIFF thumbnails from ARW/CR2/etc), cv2 for JPG/PNG.
    from .raw_loader import is_raw, load_rgb

    if is_raw(path):
        try:
            image_bgr = load_rgb(path)
        except Exception as e:
            raise ValueError(f"Cannot load RAW image: {path}") from e
    else:
        image_bgr = cv2.imread(str(path))
        if image_bgr is None:
            try:
                image_bgr = load_rgb(path)
            except Exception as e:
                raise ValueError(f"Cannot load image: {path}") from e

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

    # Compute sharpness contrast (subject Tenengrad / background Tenengrad)
    sharpness_contrast = 1.0
    if subject_mask.sum() > 0:
        inv_mask = 1 - subject_mask
        subject_ten = _tenengrad(image_gray[subject_mask > 0])
        bg_ten = _tenengrad(image_gray[inv_mask > 0])
        if bg_ten > 0:
            sharpness_contrast = subject_ten / bg_ten
        else:
            sharpness_contrast = 1.0 if subject_ten == 0 else max(subject_ten / 0.01, 1.0)

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
        sharpness_contrast=sharpness_contrast,
        image_rgb=image_rgb,
    )
