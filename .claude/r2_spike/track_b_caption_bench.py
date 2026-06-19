#!/usr/bin/env python3
"""R2 spike Track B — caption bench: VLM candidates x prompt tiers.

Runs each candidate VLM over the eval frames under {bare, instruction, grounded}
prompts and emits a table of caption + latency, plus a BLIND CSV (source hidden,
shuffled) for human quality judging.

Quality is model-intrinsic, so this uses transformers .generate() on CPU — no
hand-rolled ONNX decode. The latency column is a RELATIVE dev-box ranking signal;
absolute INT8-ONNX / KPM-1.2 numbers are measured on the Yoga for the winner.

Candidates share one API (AutoModelForImageTextToText + apply_chat_template);
Florence-2 (control) uses its own task-prompt branch.

Deps (dev-box venv): transformers, torch, Pillow, (psutil optional for RSS).

    python .claude/r2_spike/track_b_caption_bench.py \
        --eval-dirs <ICELAND> <MISC2026> --cache-dir .claude/r2_spike/cache \
        --out .claude/r2_spike/track_b_results
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import time
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("track_b")

_IMG_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

CHAT_MODELS = [
    "HuggingFaceTB/SmolVLM2-500M-Video-Instruct",
    "HuggingFaceTB/SmolVLM2-256M-Video-Instruct",
    "LiquidAI/LFM2-VL-450M",
]
FLORENCE_ID = "microsoft/Florence-2-base-ft"
FLORENCE_TASK = "What does the image describe?"  # matches naming.py CAPTION_PROMPT_TEXT

BARE = "Describe this image."
INSTRUCTION = ("Write one concise, natural caption describing this photograph. "
               "Output only the caption, no preamble.")


def _region_summary(cache_dir: Path, stem: str) -> str:
    """Build 'Visible regions: ...' from the extraction cache region_hist, if any."""
    from region_taxonomy import REGION_TYPES

    hits = list(cache_dir.glob(f"*__{stem}.npz")) if cache_dir else []
    if not hits:
        return ""
    hist = np.load(hits[0], allow_pickle=True)["region_hist"]
    parts = [f"{REGION_TYPES[i]} {p*100:.0f}%" for i, p in
             sorted(enumerate(hist), key=lambda kv: -kv[1]) if p >= 0.08]
    return "Visible regions: " + ", ".join(parts) + ". " if parts else ""


def _grounded(stem: str, cache_dir: Path, grounding: dict) -> str:
    g = grounding.get(stem, {}) if grounding else {}
    ctx = []
    if g.get("subject"):
        ctx.append(f"a {g['subject']}" + (f"/{g['type']}" if g.get("type") else "") + " photo")
    for k in ("time_of_day", "shutter_class", "aperture_class"):
        if g.get(k):
            ctx.append(g[k])
    facts = ("Facts: " + ", ".join(ctx) + ". ") if ctx else ""
    regions = _region_summary(cache_dir, stem)
    colors = (f"Dominant colors: {g['colors']}. " if g.get("colors") else "")
    return (facts + regions + colors +
            "Write ONE natural sentence describing what is visible. Use the facts as "
            "context but describe the specific subject, action, and mood you see. "
            "Do not invent names, places, or text. Output only the caption.")


def _prompts(stem: str, cache_dir: Path, grounding: dict) -> dict[str, str]:
    return {"bare": BARE, "instruction": INSTRUCTION,
            "grounded": _grounded(stem, cache_dir, grounding)}


def _caption_chat(model, processor, image, prompt: str, max_new: int) -> str:
    messages = [{"role": "user", "content": [
        {"type": "image", "image": image}, {"type": "text", "text": prompt}]}]
    inputs = processor.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=True,
        return_dict=True, return_tensors="pt").to(model.device)
    ids = model.generate(**inputs, max_new_tokens=max_new, do_sample=False)
    text = processor.batch_decode(ids, skip_special_tokens=True)[0]
    # Strip the echoed prompt turn if present.
    return text.split("Assistant:")[-1].strip()


def _caption_florence(model, processor, image, max_new: int) -> str:
    inputs = processor(text=FLORENCE_TASK, images=image, return_tensors="pt").to(model.device)
    ids = model.generate(input_ids=inputs["input_ids"], pixel_values=inputs["pixel_values"],
                         max_new_tokens=max_new, num_beams=1, do_sample=False)
    text = processor.batch_decode(ids, skip_special_tokens=False)[0]
    return processor.post_process_generation(
        text, task=FLORENCE_TASK, image_size=(image.width, image.height)
    ).get(FLORENCE_TASK, text).strip()


def _load(model_id: str):
    import torch
    if model_id == FLORENCE_ID:
        from transformers import AutoModelForCausalLM, AutoProcessor
        m = AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True,
                                                 torch_dtype=torch.float32).eval()
        return m, AutoProcessor.from_pretrained(model_id, trust_remote_code=True), True
    from transformers import AutoModelForImageTextToText, AutoProcessor
    m = AutoModelForImageTextToText.from_pretrained(model_id, torch_dtype=torch.float32).eval()
    return m, AutoProcessor.from_pretrained(model_id), False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eval-dirs", type=Path, nargs="+", required=True)
    ap.add_argument("--cache-dir", type=Path, default=Path(".claude/r2_spike/cache"))
    ap.add_argument("--grounding-json", type=Path,
                    help="optional {stem: {subject,type,time_of_day,colors,...}}")
    ap.add_argument("--models", nargs="+", default=CHAT_MODELS + [FLORENCE_ID])
    ap.add_argument("--max-new-tokens", type=int, default=48)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", type=Path, default=Path(".claude/r2_spike/track_b_results"))
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from PIL import Image

    grounding = json.loads(args.grounding_json.read_text()) if args.grounding_json else {}
    frames = [p for d in args.eval_dirs for p in sorted(d.rglob("*"))
              if p.suffix.lower() in _IMG_EXTS]
    if args.limit:
        frames = frames[: args.limit]
    log.info("Eval frames: %d", len(frames))
    args.out.mkdir(parents=True, exist_ok=True)

    rows = []
    for model_id in args.models:
        log.info("Loading %s ...", model_id)
        try:
            model, processor, is_florence = _load(model_id)
        except Exception as e:  # noqa: BLE001
            log.warning("Skip %s: %s", model_id, e)
            continue
        for fp in frames:
            image = Image.open(fp).convert("RGB")
            tiers = {"florence": FLORENCE_TASK} if is_florence else _prompts(fp.stem, args.cache_dir, grounding)
            for tier, prompt in tiers.items():
                t0 = time.perf_counter()
                try:
                    cap = (_caption_florence(model, processor, image, args.max_new_tokens)
                           if is_florence else
                           _caption_chat(model, processor, image, prompt, args.max_new_tokens))
                except Exception as e:  # noqa: BLE001
                    cap = f"<error: {e}>"
                dt = time.perf_counter() - t0
                rows.append({"model": model_id, "tier": tier, "file": fp.name,
                             "latency_s": round(dt, 2), "caption": cap})
                log.info("[%s | %-11s | %5.2fs] %s", model_id.split('/')[-1], tier, dt, cap[:70])
        del model

    # Full results.
    (args.out / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    # Blind CSV for judging: shuffled, source hidden behind an opaque id.
    order = np.random.RandomState(0).permutation(len(rows))
    with open(args.out / "blind.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["blind_id", "file", "caption", "score_1to5", "halluc_y_n"])
        for bid, i in enumerate(order):
            w.writerow([bid, rows[i]["file"], rows[i]["caption"], "", ""])
    (args.out / "blind_key.json").write_text(
        json.dumps({int(bid): {"model": rows[i]["model"], "tier": rows[i]["tier"]}
                    for bid, i in enumerate(order)}, indent=2), encoding="utf-8")

    # Latency summary.
    print("\n=== Track B — mean latency (relative, dev-box PyTorch CPU) ===")
    agg: dict[tuple, list] = {}
    for r in rows:
        agg.setdefault((r["model"].split("/")[-1], r["tier"]), []).append(r["latency_s"])
    for (m, tier), lats in sorted(agg.items()):
        print(f"{m:32s} | {tier:11s} | {np.mean(lats):5.2f}s (n={len(lats)})")
    print(f"\nJudge blind.csv (fill score_1to5 + halluc_y_n); reveal via blind_key.json.")


if __name__ == "__main__":
    main()
