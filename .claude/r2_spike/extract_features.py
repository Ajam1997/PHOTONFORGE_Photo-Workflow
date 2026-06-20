#!/usr/bin/env python3
"""R2 spike — single cached feature-extraction pass (feeds Track A and Track B).

For each image in {label corpus} u {eval frames}, run the candidate backbones
ONCE and cache to .npz so every downstream probe/head/prompt reads the cache
instead of re-running models:

    clip_s2_emb[512]   reused from photonforge.db when available, else recomputed
    clip_s0_emb[..]    MobileCLIP-S0 (if provisioned)
    mit_pooled[256]    SegFormer-b0 MiT-b0 pooled feature (dual-output export)
    region_hist[8]     normalized region-type composition (region_taxonomy order)
    region_map         128x128 uint8 region-type index map (low-res; scale-free hist)
    subject/photo_type ground-truth labels for corpus images (None for eval frames)

Run on the dev-box venv (onnxruntime + the photo_workflow package on PYTHONPATH).

    python .claude/r2_spike/extract_features.py \
        --segformer models/segformer_b0_ade_int8/model.onnx \
        --corpus corpus/genre_labels.jsonl --image-root /mnt/photon_ssd/CURATED \
        --eval-dirs /mnt/.../ICELAND /mnt/.../MISC2026 \
        --photon-db /mnt/.../photonforge.db --cache-dir .claude/r2_spike/cache
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("extract_features")

_SEG_SIZE = 512
_SEG_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_SEG_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".arw", ".cr2", ".nef", ".dng", ".raf", ".tif", ".tiff"}

sys.path.insert(0, str(Path(__file__).resolve().parent))
from region_taxonomy import REGION_TYPES  # noqa: E402


def _ort_session(path: Path):
    import onnxruntime as ort

    return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])


def _load_rgb(path: Path) -> np.ndarray:
    """Load any supported image as RGB uint8 (reuses the package loaders)."""
    import cv2

    from photo_workflow.raw_loader import is_raw, load_rgb

    if is_raw(path):
        bgr = load_rgb(path)
    else:
        bgr = cv2.imread(str(path))
        if bgr is None:
            bgr = load_rgb(path)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _run_clip(image_rgb: np.ndarray, session, size: int | None = None) -> np.ndarray:
    import cv2

    if size is None:  # read the model's own spatial size (S2=256, S0=224)
        shp = session.get_inputs()[0].shape
        size = shp[2] if isinstance(shp[2], int) and shp[2] > 0 else 256
    img = cv2.resize(image_rgb, (size, size)).astype(np.float32) / 255.0
    img = np.transpose(img, (2, 0, 1))[None]
    out = session.run(None, {session.get_inputs()[0].name: img})[0].flatten()
    n = np.linalg.norm(out)
    return (out / n if n > 0 else out).astype(np.float32)


def _run_segformer(image_rgb: np.ndarray, session, lut: dict[int, str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    import cv2

    img = cv2.resize(image_rgb, (_SEG_SIZE, _SEG_SIZE)).astype(np.float32) / 255.0
    img = (img - _SEG_MEAN) / _SEG_STD
    img = np.transpose(img, (2, 0, 1))[None].astype(np.float32)
    logits, pooled = session.run(["logits", "pooled_feat"], {session.get_inputs()[0].name: img})
    cls_map = logits[0].argmax(axis=0).astype(np.int32)  # [H/4, W/4] class indices

    rtype_index = {rt: i for i, rt in enumerate(REGION_TYPES)}
    region_map = np.zeros_like(cls_map, dtype=np.uint8)
    for cls_idx, rtype in lut.items():
        region_map[cls_map == cls_idx] = rtype_index[rtype]

    hist = np.bincount(region_map.ravel(), minlength=len(REGION_TYPES)).astype(np.float32)
    hist /= hist.sum() if hist.sum() > 0 else 1.0
    return pooled[0].astype(np.float32), hist, region_map


def _db_embeddings(db_path: Path, filenames: set[str]) -> dict[str, np.ndarray]:
    """Best-effort pull of cached CLIP-S2 embeddings by filename."""
    out: dict[str, np.ndarray] = {}
    if not db_path or not db_path.exists():
        return out
    try:
        conn = sqlite3.connect(str(db_path))
        existing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("photos", "embeddings"):
            if table not in existing:
                continue
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if not ({"filename", "clip_embedding"} <= cols):
                continue
            for fn, blob in conn.execute(f"SELECT filename, clip_embedding FROM {table}"):
                if fn in filenames and blob is not None and fn not in out:
                    out[fn] = np.frombuffer(blob, dtype=np.float32)
        conn.close()
    except Exception as e:  # noqa: BLE001
        log.warning("DB embedding pull failed: %s", e)
    return out


def _build_index(root: Path | None) -> dict[str, Path]:
    """One-time filename -> path index (handles source_folder name mismatches)."""
    idx: dict[str, Path] = {}
    if not root or not root.exists():
        return idx
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if Path(f).suffix.lower() in _IMG_EXTS:
                idx.setdefault(f, Path(dirpath) / f)
    return idx


def _iter_corpus(corpus: Path, index: dict[str, Path]):
    for line in corpus.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        fn = rec.get("filename")
        if not fn:
            continue
        yield fn, index.get(fn), rec.get("subject"), rec.get("photo_type")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--segformer", type=Path, required=True)
    ap.add_argument("--models-dir", type=Path, default=Path("models"))
    ap.add_argument("--clip-s2-subdir", default="mobileclip_s2_int8")
    ap.add_argument("--clip-s0-subdir", default="mobileclip_s0_int8")
    ap.add_argument("--corpus", type=Path)
    ap.add_argument("--image-root", type=Path)
    ap.add_argument("--eval-dirs", type=Path, nargs="*", default=[])
    ap.add_argument("--photon-db", type=Path)
    ap.add_argument("--cache-dir", type=Path, default=Path(".claude/r2_spike/cache"))
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    args.cache_dir.mkdir(parents=True, exist_ok=True)
    lut = {int(k): v for k, v in json.loads(
        (args.segformer.parent / "region_lut.json").read_text(encoding="utf-8")).items()}

    seg = _ort_session(args.segformer)
    s2_path = args.models_dir / args.clip_s2_subdir / "vision_encoder.onnx"
    s0_path = args.models_dir / args.clip_s0_subdir / "vision_encoder.onnx"
    s2 = _ort_session(s2_path) if s2_path.exists() else None
    s0 = _ort_session(s0_path) if s0_path.exists() else None
    log.info("Sessions: segformer=yes clip_s2=%s clip_s0=%s", bool(s2), bool(s0))

    # Build the work list.
    work: list[tuple[str, Path | None, str | None, str | None, str]] = []
    if args.corpus:
        index = _build_index(args.image_root)
        log.info("Indexed %d image files under %s", len(index), args.image_root)
        work += [(fn, p, subj, pt, "corpus") for fn, p, subj, pt in _iter_corpus(args.corpus, index)]
    for d in args.eval_dirs:
        for p in sorted(d.rglob("*")):
            if p.suffix.lower() in _IMG_EXTS:
                work.append((p.name, p, None, None, f"eval:{d.name}"))
    if args.limit:
        work = work[: args.limit]
    log.info("Work list: %d images", len(work))

    db_embs = _db_embeddings(args.photon_db, {w[0] for w in work}) if args.photon_db else {}

    done = skipped = 0
    for fn, path, subj, pt, source in work:
        out_npz = args.cache_dir / f"{source.replace(':', '_')}__{Path(fn).stem}.npz"
        if out_npz.exists():
            continue
        if path is None or not path.exists():
            skipped += 1
            continue
        try:
            rgb = _load_rgb(path)
            pooled, hist, region_map = _run_segformer(rgb, seg, lut)
            rec: dict[str, object] = {
                "filename": fn, "source": source,
                "subject": subj or "", "photo_type": pt or "",
                "mit_pooled": pooled, "region_hist": hist, "region_map": region_map,
            }
            if fn in db_embs:
                rec["clip_s2_emb"] = db_embs[fn]
            elif s2 is not None:
                rec["clip_s2_emb"] = _run_clip(rgb, s2)
            if s0 is not None:
                rec["clip_s0_emb"] = _run_clip(rgb, s0)
            np.savez_compressed(out_npz, **rec)
            done += 1
            if done % 25 == 0:
                log.info("  ... %d cached", done)
        except Exception as e:  # noqa: BLE001
            log.warning("Failed %s: %s", path, e)
            skipped += 1

    log.info("Extraction done: %d cached, %d skipped -> %s", done, skipped, args.cache_dir)


if __name__ == "__main__":
    main()
