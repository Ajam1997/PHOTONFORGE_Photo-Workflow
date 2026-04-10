"""FR-1.7: Semantic filename generation via Florence-2 INT8 ONNX."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

MODEL_SUBDIR = "florence2_int8"
MAX_TOKENS = 16
CAPTION_TASK = "<CAPTION>"


def _load_session(model_dir: Path):
    """Load ONNX Runtime session for Florence-2 INT8."""
    import onnxruntime as ort

    model_path = model_dir / MODEL_SUBDIR / "model.onnx"
    if not model_path.exists():
        raise FileNotFoundError(f"Florence-2 model not found at {model_path}")

    opts = ort.SessionOptions()
    opts.inter_op_num_threads = 2
    opts.intra_op_num_threads = 4
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

    return ort.InferenceSession(
        str(model_path),
        sess_options=opts,
        providers=["CPUExecutionProvider"],
    )


_session_cache: dict[str, object] = {}


def generate_name(path: Path, model_dir: Path = Path("models")) -> str:
    """
    Run Florence-2 INT8 caption on the image and return a slug suitable for use as a filename.
    Falls back to the original stem if inference fails.
    """
    cache_key = str(model_dir)
    if cache_key not in _session_cache:
        try:
            _session_cache[cache_key] = _load_session(model_dir)
        except FileNotFoundError as e:
            logger.warning("Florence-2 model unavailable: %s — using original name", e)
            return path.stem

    session = _session_cache[cache_key]

    try:
        import cv2
        img = cv2.imread(str(path))
        if img is None:
            return path.stem

        # Resize to model input size (224×224) and normalize
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img_resized = cv2.resize(img_rgb, (224, 224)).astype(np.float32) / 255.0
        img_input = np.transpose(img_resized, (2, 0, 1))[np.newaxis, :]  # NCHW

        outputs = session.run(None, {"pixel_values": img_input})
        caption: str = outputs[0] if isinstance(outputs[0], str) else str(outputs[0])

        slug = re.sub(r"[^a-z0-9]+", "_", caption.lower().strip()).strip("_")
        slug = slug[:64] if slug else path.stem
        return slug

    except Exception as e:
        logger.warning("Naming inference failed for %s: %s", path.name, e)
        return path.stem
