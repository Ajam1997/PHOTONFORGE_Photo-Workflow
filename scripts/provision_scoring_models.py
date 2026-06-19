#!/usr/bin/env python3
"""Provision ONNX models for genre-aware scoring.

Run ONCE during initial machine setup — NOT during pipeline operation.
Downloads, exports, and INT8-quantizes four models:

  1. RMBG-1.4        — subject/background segmentation
  2. YuNet            — face detection (5-point landmarks)
  3. YOLOv8n          — object detection (80 COCO classes)
  4. MobileCLIP-S2    — CLIP vision encoder (512-dim embeddings)

The aesthetic head (clip_aesthetic_head/aesthetic_mlp.onnx) is a CLIP-embedding
regressor trained separately by scripts/train_aesthetic_head.py, not here.

Usage:
    python scripts/provision_scoring_models.py [--models-dir models] [--force]
    python scripts/provision_scoring_models.py --only rmbg yunet   # subset

NFR-2.1: This script intentionally uses the internet.
After it completes, the pipeline runs 100% offline.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("provision_scoring")

ALL_MODELS = ["rmbg", "yunet", "yolo", "clip"]


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# 1. RMBG-1.4 (background removal / subject segmentation)
# ---------------------------------------------------------------------------
def provision_rmbg(models_dir: Path, force: bool = False) -> None:
    """Download and export RMBG-1.4 to ONNX INT8."""
    out_dir = _ensure_dir(models_dir / "rmbg14_int8")
    out_file = out_dir / "model.onnx"
    if out_file.exists() and not force:
        log.info("RMBG-1.4 already present at %s", out_file)
        return

    log.info("Provisioning RMBG-1.4...")
    try:
        import torch
        import huggingface_hub  # noqa: F401 — availability check
    except ImportError:
        log.error("pip install torch huggingface_hub  (needed for RMBG export)")
        return

    # Download the safetensors checkpoint
    log.info("Downloading briaai/RMBG-1.4 from HuggingFace...")
    cache_dir = models_dir / ".cache" / "rmbg14"
    _ensure_dir(cache_dir)

    try:
        from transformers import AutoModelForImageSegmentation
        model = AutoModelForImageSegmentation.from_pretrained(
            "briaai/RMBG-1.4",
            trust_remote_code=True,
            cache_dir=str(cache_dir),
        )
        model.eval()
    except Exception as e:
        log.error("Failed to load RMBG-1.4: %s", e)
        log.error("Try: pip install transformers torch")
        return

    # Export to ONNX
    log.info("Exporting to ONNX...")
    dummy = torch.randn(1, 3, 320, 320)
    fp32_path = out_dir / "model_fp32.onnx"
    torch.onnx.export(
        model, dummy, str(fp32_path),
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
        opset_version=17,
    )

    # Quantize to INT8
    log.info("Quantizing to INT8...")
    try:
        from onnxruntime.quantization import quantize_dynamic, QuantType
        quantize_dynamic(str(fp32_path), str(out_file), weight_type=QuantType.QUInt8)
        fp32_path.unlink()
        log.info("RMBG-1.4 ready: %s (%.1f MB)", out_file, out_file.stat().st_size / 1e6)
    except Exception as e:
        log.warning("INT8 quantization failed (%s), keeping FP32", e)
        shutil.move(str(fp32_path), str(out_file))


# ---------------------------------------------------------------------------
# 2. YuNet (face detection)
# ---------------------------------------------------------------------------
def provision_yunet(models_dir: Path, force: bool = False) -> None:
    """Download YuNet face detection model (already ONNX)."""
    out_dir = _ensure_dir(models_dir / "yunet")
    out_file = out_dir / "face_detection_yunet.onnx"
    if out_file.exists() and not force:
        log.info("YuNet already present at %s", out_file)
        return

    log.info("Provisioning YuNet face detector...")
    import urllib.request

    url = (
        "https://github.com/opencv/opencv_zoo/raw/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx"
    )
    log.info("Downloading from opencv_zoo...")
    try:
        urllib.request.urlretrieve(url, str(out_file))
        log.info("YuNet ready: %s (%.1f MB)", out_file, out_file.stat().st_size / 1e6)
    except Exception as e:
        log.error("Download failed: %s", e)


# ---------------------------------------------------------------------------
# 3. YOLOv8n (object detection)
# ---------------------------------------------------------------------------
def provision_yolo(models_dir: Path, force: bool = False) -> None:
    """Export YOLOv8n to ONNX and quantize to INT8."""
    out_dir = _ensure_dir(models_dir / "yolov8n_int8")
    out_file = out_dir / "model.onnx"
    if out_file.exists() and not force:
        log.info("YOLOv8n already present at %s", out_file)
        return

    log.info("Provisioning YOLOv8n...")
    try:
        from ultralytics import YOLO
    except ImportError:
        log.error("pip install ultralytics  (needed for YOLOv8n export)")
        return

    log.info("Downloading and exporting YOLOv8n...")
    model = YOLO("yolov8n.pt")
    fp32_path = model.export(format="onnx", imgsz=640, simplify=True)
    fp32_path = Path(fp32_path)

    # Quantize
    log.info("Quantizing to INT8...")
    try:
        from onnxruntime.quantization import quantize_dynamic, QuantType
        quantize_dynamic(str(fp32_path), str(out_file), weight_type=QuantType.QUInt8)
        fp32_path.unlink()
        log.info("YOLOv8n ready: %s (%.1f MB)", out_file, out_file.stat().st_size / 1e6)
    except Exception as e:
        log.warning("INT8 quantization failed (%s), keeping FP32", e)
        shutil.move(str(fp32_path), str(out_file))


# ---------------------------------------------------------------------------
# 4. MobileCLIP-S2 (vision encoder)
# ---------------------------------------------------------------------------
def provision_clip(models_dir: Path, force: bool = False) -> None:
    """Export MobileCLIP-S2 vision encoder to ONNX INT8."""
    out_dir = _ensure_dir(models_dir / "mobileclip_s2_int8")
    out_file = out_dir / "vision_encoder.onnx"
    if out_file.exists() and not force:
        log.info("MobileCLIP-S2 already present at %s", out_file)
        return

    log.info("Provisioning MobileCLIP-S2 vision encoder...")
    try:
        import open_clip
        import torch
    except ImportError:
        log.error("pip install open_clip_torch torch  (needed for MobileCLIP export)")
        return

    log.info("Loading MobileCLIP-S2 via open_clip...")
    model, _, preprocess = open_clip.create_model_and_transforms(
        "MobileCLIP-S2", pretrained="datacompdr"
    )
    model.eval()
    visual = model.visual

    # Export vision encoder
    log.info("Exporting vision encoder to ONNX...")
    dummy = torch.randn(1, 3, 256, 256)
    fp32_path = out_dir / "vision_encoder_fp32.onnx"
    torch.onnx.export(
        visual, dummy, str(fp32_path),
        input_names=["pixel_values"],
        output_names=["embedding"],
        dynamic_axes={"pixel_values": {0: "batch"}, "embedding": {0: "batch"}},
        opset_version=17,
    )

    # Quantize
    log.info("Quantizing to INT8...")
    try:
        from onnxruntime.quantization import quantize_dynamic, QuantType
        quantize_dynamic(str(fp32_path), str(out_file), weight_type=QuantType.QUInt8)
        fp32_path.unlink()
    except Exception as e:
        log.warning("INT8 quantization failed (%s), keeping FP32", e)
        shutil.move(str(fp32_path), str(out_file))

    log.info("MobileCLIP-S2 ready: %s (%.1f MB)", out_file, out_file.stat().st_size / 1e6)

    # Also generate genre_prototypes.npy using the text encoder
    _generate_genre_prototypes(model, models_dir, force)


def _generate_genre_prototypes(model: object, models_dir: Path, force: bool) -> None:
    """Generate two-axis prototype embeddings using MobileCLIP-S2 text encoder.

    Uses a 7-template prompt ensemble for both subject and photo type classes.
    Output shape: (26, 512) — first 15 rows = subjects, next 11 rows = types.
    Each prototype is the L2-normalized mean of all template embeddings for that class.
    """
    out_file = models_dir / "genre_prototypes.npy"
    if out_file.exists() and not force:
        log.info("Genre prototypes already present at %s", out_file)
        return

    import open_clip
    import torch

    log.info("Generating genre prototypes with 7-template prompt ensemble (MobileCLIP-S2)...")
    tokenizer = open_clip.get_tokenizer("MobileCLIP-S2")

    # OpenAI CLIP 7-template ensemble for subjects
    _SUBJECT_TEMPLATES = [
        "itap of a {}",
        "a bad photo of the {}",
        "a origami {}",
        "a photo of the large {}",
        "a {} in a video game",
        "art of the {}",
        "a photo of the small {}",
    ]

    # Photography-specific 7-template ensemble for photo types
    _TYPE_TEMPLATES = [
        "a {} photograph",
        "an example of {} photography",
        "a professional {} photo",
        "a {} style photograph",
        "a stunning {} photograph",
        "a beautiful {} photo",
        "an award-winning {} photograph",
    ]

    # Subject fill text — descriptive phrases for each class
    _SUBJECT_FILL = {
        "people": "people",
        "pet": "domestic pet",
        "wildlife": "wild animal in nature",
        "plant": "plant or flower",
        "landscape": "natural landscape",
        "seascape": "ocean or sea",
        "sky": "sky with clouds or stars",
        "cityscape": "city skyline",
        "building": "building or architecture",
        "vehicle": "vehicle",
        "food": "food or meal",
        "object": "object or product",
        "abstract": "abstract pattern",
        "monument": "monument statue or memorial",
        "waterfall": "waterfall cascading water",
    }

    # Photo type fill text
    _TYPE_FILL = {
        "portrait": "portrait",
        "candid": "candid",
        "scenic": "scenic vista or wide view",
        "street": "street",
        "macro": "macro close-up",
        "architecture": "architectural",
        "action": "action or sports",
        "aerial": "aerial or drone",
        "long-exposure": "long exposure",
        "still-life": "still life",
        "documentary": "documentary",
    }

    # Order matching the class labels (must match genre_router.SUBJECTS)
    subjects_ordered = [
        "people", "pet", "wildlife", "plant", "landscape",
        "seascape", "sky", "cityscape", "building", "vehicle",
        "food", "object", "abstract", "monument", "waterfall"
    ]
    types_ordered = [
        "portrait", "candid", "scenic", "street", "macro",
        "architecture", "action", "aerial", "long-exposure",
        "still-life", "documentary"
    ]

    embeddings = {}
    with torch.no_grad():
        # Process subjects with 7-template ensemble
        for subject in subjects_ordered:
            fill_text = _SUBJECT_FILL[subject]
            prompts = [template.format(fill_text) for template in _SUBJECT_TEMPLATES]
            tokens = tokenizer(prompts)
            text_features = model.encode_text(tokens)
            text_features /= text_features.norm(dim=-1, keepdim=True)
            # Average the 7 template embeddings
            mean_embedding = text_features.mean(dim=0)
            mean_embedding /= mean_embedding.norm()
            embeddings[subject] = mean_embedding.cpu().numpy()

        # Process photo types with 7-template ensemble
        for photo_type in types_ordered:
            fill_text = _TYPE_FILL[photo_type]
            prompts = [template.format(fill_text) for template in _TYPE_TEMPLATES]
            tokens = tokenizer(prompts)
            text_features = model.encode_text(tokens)
            text_features /= text_features.norm(dim=-1, keepdim=True)
            # Average the 7 template embeddings
            mean_embedding = text_features.mean(dim=0)
            mean_embedding /= mean_embedding.norm()
            embeddings[photo_type] = mean_embedding.cpu().numpy()

    # Stack in order: subjects (13) then types (11)
    all_ordered = subjects_ordered + types_ordered
    proto_matrix = np.stack([embeddings[g] for g in all_ordered])
    np.save(str(out_file), proto_matrix)
    log.info(
        "Genre prototypes saved: %s (shape %s, MobileCLIP-S2 + 7-template ensemble)",
        out_file, proto_matrix.shape
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
PROVISIONERS = {
    "rmbg": provision_rmbg,
    "yunet": provision_yunet,
    "yolo": provision_yolo,
    "clip": provision_clip,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision scoring ONNX models")
    parser.add_argument("--models-dir", type=Path, default=Path("models"),
                        help="Output directory for models (default: models/)")
    parser.add_argument("--force", action="store_true",
                        help="Re-download and overwrite existing models")
    parser.add_argument("--only", nargs="+", choices=ALL_MODELS,
                        help="Provision only specific models")
    args = parser.parse_args()

    models = args.only or ALL_MODELS
    log.info("Provisioning %d model(s): %s", len(models), ", ".join(models))
    log.info("Output: %s", args.models_dir.resolve())

    failed = []
    for name in models:
        try:
            PROVISIONERS[name](args.models_dir, args.force)
        except Exception:
            log.exception("Failed to provision %s", name)
            failed.append(name)

    if failed:
        log.error("Failed: %s. Other models are ready.", ", ".join(failed))
        sys.exit(1)
    else:
        log.info("All models provisioned successfully.")


if __name__ == "__main__":
    main()
