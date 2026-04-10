"""FR-1.7: Semantic filename generation via Florence-2 INT8 ONNX."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import click
import numpy as np

logger = logging.getLogger(__name__)

MODEL_SUBDIR = "florence2_int8"
MAX_WORDS = 5
CAPTION_TASK = "<CAPTION>"
_KPM_INFERENCE_LIMIT = 1.5  # seconds (KPM-1.2)


def _load_session(model_dir: Path) -> object:
    """Load ONNX Runtime session for Florence-2 INT8 (CPU provider only)."""
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


def _caption_to_slug(caption: str, stem_fallback: str) -> str:
    """Extract first MAX_WORDS words from caption and return a clean slug."""
    words = caption.split()[:MAX_WORDS]
    if not words:
        return stem_fallback
    phrase = " ".join(words)
    slug = re.sub(r"[^a-z0-9]+", "_", phrase.lower().strip()).strip("_")
    slug = slug[:64] if slug else stem_fallback
    return slug


def generate_name(path: Path, model_dir: Path = Path("models")) -> str:
    """
    Run Florence-2 INT8 caption on the image and return a slug (first 5 words).
    Falls back to the original stem if the model is absent or inference fails.
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

        # Pre-process: resize to 224×224, normalize to [0, 1], NCHW float32
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img_resized = cv2.resize(img_rgb, (224, 224)).astype(np.float32) / 255.0
        pixel_values = np.transpose(img_resized, (2, 0, 1))[np.newaxis, :]  # (1, 3, 224, 224)

        # Minimal task-prompt token sequence for <CAPTION>: [BOS, EOS]
        input_ids = np.array([[0, 2]], dtype=np.int64)
        attention_mask = np.ones((1, 2), dtype=np.int64)

        t0 = time.perf_counter()
        outputs = session.run(  # type: ignore[union-attr]
            None,
            {
                "pixel_values": pixel_values,
                "input_ids": input_ids,
                "attention_mask": attention_mask,
            },
        )
        elapsed = time.perf_counter() - t0

        if elapsed > _KPM_INFERENCE_LIMIT:
            logger.warning(
                "Florence-2 inference took %.2fs for %s (KPM-1.2 limit: 1.5s)",
                elapsed,
                path.name,
            )

        raw = outputs[0]
        caption: str = raw if isinstance(raw, str) else str(raw)
        return _caption_to_slug(caption, path.stem)

    except Exception as e:
        logger.warning("Naming inference failed for %s: %s", path.name, e)
        return path.stem


@click.command("name")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--model-dir",
    default="models",
    show_default=True,
    type=click.Path(path_type=Path),
    help="Directory containing the florence2_int8/ model weights.",
)
def main(path: Path, model_dir: Path) -> None:
    """Generate a 5-word semantic filename slug for PATH using Florence-2 INT8."""
    result = generate_name(path, model_dir=model_dir)
    click.echo(result)
