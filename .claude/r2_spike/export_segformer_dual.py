#!/usr/bin/env python3
"""R2 spike — export SegFormer-b0 (ADE20K) to a DUAL-OUTPUT INT8 ONNX model.

Outputs BOTH:
  - ``logits``       [B, 150, H/4, W/4]  -> seg map (argmax + upsample at use)
  - ``pooled_feat``  [B, 256]            -> global-avg-pooled MiT-b0 last-stage
                                            feature (Track A backbone candidate)

Stock SegFormer ONNX exposes only the seg map; the pooled-feature tap is the
whole point of this script. Run ONCE on the dev-box venv (transformers + torch +
onnxruntime). NFR-2.1: provisioning may use the network; runtime stays offline.

    python .claude/r2_spike/export_segformer_dual.py \
        --out-dir models/segformer_b0_ade_int8

Then eyeball models/segformer_b0_ade_int8/region_lut.json and correct any
class -> region-type assignment before the extraction pass.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("export_segformer_dual")

DEFAULT_MODEL_ID = "nvidia/segformer-b0-finetuned-ade-512-512"
DEFAULT_IMG_SIZE = 512


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    ap.add_argument("--out-dir", type=Path, default=Path("models/segformer_b0_ade_int8"))
    ap.add_argument("--img-size", type=int, default=DEFAULT_IMG_SIZE)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    out_file = args.out_dir / "model.onnx"
    if out_file.exists() and not args.force:
        log.info("Already present: %s (use --force to re-export)", out_file)
        return
    args.out_dir.mkdir(parents=True, exist_ok=True)

    import torch
    from torch import nn
    from transformers import SegformerForSemanticSegmentation

    log.info("Loading %s ...", args.model_id)
    model = SegformerForSemanticSegmentation.from_pretrained(args.model_id)
    model.eval()

    id2label = {int(k): v for k, v in model.config.id2label.items()}
    log.info("Model has %d classes.", len(id2label))

    class SegformerDual(nn.Module):
        """Wraps the HF model to emit (logits, pooled last-stage feature)."""

        def __init__(self, m: nn.Module) -> None:
            super().__init__()
            self.m = m

        def forward(self, pixel_values: "torch.Tensor"):
            out = self.m(pixel_values=pixel_values, output_hidden_states=True, return_dict=True)
            # hidden_states[-1]: [B, C_last, H/32, W/32]; C_last = 256 for b0.
            pooled = out.hidden_states[-1].mean(dim=(2, 3))
            return out.logits, pooled

    wrapper = SegformerDual(model).eval()

    dummy = torch.randn(1, 3, args.img_size, args.img_size)
    with torch.no_grad():
        logits, pooled = wrapper(dummy)
    log.info("Sanity: logits %s, pooled %s", tuple(logits.shape), tuple(pooled.shape))
    if pooled.shape[1] != 256:
        log.warning("Expected pooled dim 256 for b0, got %d — check the backbone.", pooled.shape[1])

    fp32_path = args.out_dir / "model_fp32.onnx"
    log.info("Exporting FP32 ONNX -> %s", fp32_path)
    torch.onnx.export(
        wrapper,
        dummy,
        str(fp32_path),
        input_names=["pixel_values"],
        output_names=["logits", "pooled_feat"],
        dynamic_axes={
            "pixel_values": {0: "batch"},
            "logits": {0: "batch"},
            "pooled_feat": {0: "batch"},
        },
        opset_version=17,
        do_constant_folding=True,
        dynamo=False,
    )

    log.info("Quantizing dynamic INT8 -> %s", out_file)
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic

        quantize_dynamic(str(fp32_path), str(out_file), weight_type=QuantType.QUInt8)
        fp32_path.unlink()
        log.info("INT8 model ready: %s (%.1f MB)", out_file, out_file.stat().st_size / 1e6)
    except Exception as e:  # noqa: BLE001 — keep FP32 as a usable fallback
        import shutil

        log.warning("INT8 quantization failed (%s); keeping FP32.", e)
        shutil.move(str(fp32_path), str(out_file))

    # Persist id2label + the generated region LUT for review.
    (args.out_dir / "id2label.json").write_text(
        json.dumps(id2label, indent=2), encoding="utf-8"
    )

    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from region_taxonomy import REGION_TYPES, build_lut

    lut = build_lut(id2label)
    (args.out_dir / "region_lut.json").write_text(
        json.dumps({str(k): v for k, v in lut.items()}, indent=2), encoding="utf-8"
    )

    # Print the mapping grouped by region-type so it's easy to eyeball.
    log.info("--- ADE20K -> region-type mapping (review me) ---")
    for rtype in REGION_TYPES:
        members = sorted(id2label[i] for i, r in lut.items() if r == rtype)
        if members:
            log.info("%-11s (%2d): %s", rtype, len(members), ", ".join(members))
    log.info("LUT written to %s — edit it before extraction if any class is wrong.",
             args.out_dir / "region_lut.json")


if __name__ == "__main__":
    main()
