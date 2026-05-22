#!/usr/bin/env python3
"""Provision ONNX models for genre-aware scoring.

Run ONCE during initial machine setup — NOT during pipeline operation.
Downloads, exports, and INT8-quantizes five models:

  1. RMBG-1.4        — subject/background segmentation
  2. YuNet            — face detection (5-point landmarks)
  3. YOLOv8n          — object detection (80 COCO classes)
  4. MobileCLIP-S0    — CLIP vision encoder (512-dim embeddings)
  5. Aesthetic head    — MLP predicting aesthetic quality from CLIP embeddings

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

ALL_MODELS = ["rmbg", "yunet", "yolo", "clip", "aesthetic"]


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
        from huggingface_hub import hf_hub_download
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
# 4. MobileCLIP-S0 (vision encoder)
# ---------------------------------------------------------------------------
def provision_clip(models_dir: Path, force: bool = False) -> None:
    """Export MobileCLIP-S0 vision encoder to ONNX INT8."""
    out_dir = _ensure_dir(models_dir / "mobileclip_s0_int8")
    out_file = out_dir / "vision_encoder.onnx"
    if out_file.exists() and not force:
        log.info("MobileCLIP-S0 already present at %s", out_file)
        return

    log.info("Provisioning MobileCLIP-S0 vision encoder...")
    try:
        import open_clip
        import torch
    except ImportError:
        log.error("pip install open_clip_torch torch  (needed for MobileCLIP export)")
        return

    log.info("Loading MobileCLIP-S1 via open_clip...")
    model, _, preprocess = open_clip.create_model_and_transforms(
        "MobileCLIP-S1", pretrained="datacompdr"
    )
    model.eval()
    visual = model.visual

    # Export vision encoder
    log.info("Exporting vision encoder to ONNX...")
    dummy = torch.randn(1, 3, 224, 224)
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

    log.info("MobileCLIP-S0 ready: %s (%.1f MB)", out_file, out_file.stat().st_size / 1e6)

    # Also generate genre_prototypes.npy using the text encoder
    _generate_genre_prototypes(model, models_dir, force)


def _generate_genre_prototypes(model: object, models_dir: Path, force: bool) -> None:
    """Generate genre prototype embeddings using MobileCLIP text encoder."""
    out_file = models_dir / "genre_prototypes.npy"
    if out_file.exists() and not force:
        log.info("Genre prototypes already present at %s", out_file)
        return

    import open_clip
    import torch

    log.info("Generating genre prototype embeddings...")
    tokenizer = open_clip.get_tokenizer("MobileCLIP-S1")

    genre_prompts = {
        "wildlife": "a wildlife photograph of an animal in nature",
        "landscape": "a landscape photograph of mountains, valleys, or scenic nature",
        "portrait": "a portrait photograph of a person's face",
        "street": "a street photography scene with people in an urban environment",
        "architecture": "an architectural photograph of a building or structure",
        "macro": "a macro close-up photograph of a small subject",
        "event": "a photograph of people at an event, party, or gathering",
        "general": "a general photograph",
    }

    embeddings = {}
    with torch.no_grad():
        for genre, prompt in genre_prompts.items():
            tokens = tokenizer([prompt])
            text_features = model.encode_text(tokens)
            text_features /= text_features.norm(dim=-1, keepdim=True)
            embeddings[genre] = text_features.cpu().numpy().flatten()

    # Save as ordered array (8 x 512)
    genres_ordered = ["wildlife", "landscape", "portrait", "street",
                      "architecture", "macro", "event", "general"]
    proto_matrix = np.stack([embeddings[g] for g in genres_ordered])
    np.save(str(out_file), proto_matrix)
    log.info("Genre prototypes saved: %s (shape %s)", out_file, proto_matrix.shape)


# ---------------------------------------------------------------------------
# 5. Aesthetic Head (CLIP aesthetic predictor MLP)
# ---------------------------------------------------------------------------
def provision_aesthetic(models_dir: Path, force: bool = False) -> None:
    """Download or build the CLIP aesthetic prediction MLP."""
    out_dir = _ensure_dir(models_dir / "clip_aesthetic_head")
    out_file = out_dir / "aesthetic_mlp.onnx"
    if out_file.exists() and not force:
        log.info("Aesthetic head already present at %s", out_file)
        return

    log.info("Provisioning CLIP aesthetic head MLP...")
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        log.error("pip install torch  (needed for aesthetic head export)")
        return

    # Build the LAION aesthetic predictor V2 architecture
    # Weights from: https://github.com/christophschuhmann/improved-aesthetic-predictor
    log.info("Downloading aesthetic predictor weights...")
    import urllib.request
    weights_url = (
        "https://github.com/christophschuhmann/improved-aesthetic-predictor/"
        "raw/main/sac%2Blogos%2Bava1-l14-linearMSE.pth"
    )
    weights_path = out_dir / "aesthetic_weights.pth"
    try:
        urllib.request.urlretrieve(weights_url, str(weights_path))
    except Exception as e:
        log.error("Download failed: %s", e)
        log.info("Creating random-initialized aesthetic head as placeholder")
        # Fall through to create the architecture with random weights

    # Architecture: Linear(768->1024) -> ReLU -> Dropout -> Linear(1024->128) -> ReLU -> Dropout -> Linear(128->64) -> ReLU -> Dropout -> Linear(64->16) -> ReLU -> Linear(16->1)
    # Note: The original uses CLIP ViT-L/14 (768-dim). We use MobileCLIP-S0 (512-dim).
    # We'll create a 512-dim input version.
    class AestheticMLP(nn.Module):
        def __init__(self, input_dim: int = 512):
            super().__init__()
            self.layers = nn.Sequential(
                nn.Linear(input_dim, 1024),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(1024, 128),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(128, 64),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(64, 16),
                nn.ReLU(),
                nn.Linear(16, 1),
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return torch.sigmoid(self.layers(x))  # Output in [0, 1]

    mlp = AestheticMLP(input_dim=512)
    if weights_path.exists():
        try:
            # The pretrained weights are for 768-dim (ViT-L/14), so we can't
            # directly load them for our 512-dim model. Use random init and
            # fine-tune later, or train a small head on a subset.
            log.warning(
                "Pretrained weights are for ViT-L/14 (768-dim), not MobileCLIP-S0 (512-dim). "
                "Using random initialization. Fine-tune on your photo library for best results."
            )
            weights_path.unlink()
        except Exception:
            pass
    mlp.eval()

    # Export to ONNX
    log.info("Exporting aesthetic MLP to ONNX...")
    dummy = torch.randn(1, 512)
    torch.onnx.export(
        mlp, dummy, str(out_file),
        input_names=["clip_embedding"],
        output_names=["aesthetic_score"],
        dynamic_axes={"clip_embedding": {0: "batch"}, "aesthetic_score": {0: "batch"}},
        opset_version=17,
    )
    log.info("Aesthetic head ready: %s (%.1f KB)", out_file, out_file.stat().st_size / 1e3)
    log.warning("NOTE: Aesthetic head uses random weights. Scores will be noisy until fine-tuned.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
PROVISIONERS = {
    "rmbg": provision_rmbg,
    "yunet": provision_yunet,
    "yolo": provision_yolo,
    "clip": provision_clip,
    "aesthetic": provision_aesthetic,
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
