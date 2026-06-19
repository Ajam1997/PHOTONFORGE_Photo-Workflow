#!/usr/bin/env python3
"""R2 spike Track A — aesthetic transfer per backbone (the load-bearing metric).

Mirrors scripts/train_aesthetic_head.py's AVA pipeline, but embeds each AVA
image with EVERY backbone candidate and reports held-out Spearman per backbone:

    clip_s2     (baseline, ~0.66 today)
    clip_s0     (if provisioned)
    mit_pooled  (SegFormer-b0 dual-output pooled feature)

Decides Track A's branch: if mit_pooled's Spearman >= ~0.60 (and within reach of
clip_s2), full CLIP eviction is on the table; if it tanks, aesthetic stays on a
small CLIP while genre moves to mit_pooled.

Deps (dev-box venv): torch, scipy, pyarrow, Pillow, huggingface_hub,
onnxruntime, and the photo_workflow package. open_clip not needed.

    python .claude/r2_spike/track_a_aesthetic.py \
        --segformer models/segformer_b0_ade_int8/model.onnx --train-shards 4
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
REPO_ID = "trojblue/AVA-aesthetics-10pct-min50-10bins"

_SEG_SIZE = 512
_SEG_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_SEG_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _ort(path: Path):
    import onnxruntime as ort

    return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])


def _run_clip(rgb: np.ndarray, session) -> np.ndarray:
    import cv2

    shp = session.get_inputs()[0].shape  # S2=256, S0=224
    size = shp[2] if isinstance(shp[2], int) and shp[2] > 0 else 256
    img = cv2.resize(rgb, (size, size)).astype(np.float32) / 255.0
    img = np.transpose(img, (2, 0, 1))[None]
    out = session.run(None, {session.get_inputs()[0].name: img})[0].flatten()
    n = np.linalg.norm(out)
    return (out / n if n > 0 else out).astype(np.float32)


def _seg_pooled(rgb: np.ndarray, session) -> np.ndarray:
    import cv2

    img = cv2.resize(rgb, (_SEG_SIZE, _SEG_SIZE)).astype(np.float32) / 255.0
    img = (img - _SEG_MEAN) / _SEG_STD
    img = np.transpose(img, (2, 0, 1))[None].astype(np.float32)
    pooled = session.run(["pooled_feat"], {session.get_inputs()[0].name: img})[0]
    return pooled[0].astype(np.float32)


def _build_embedders(models_dir: Path, segformer: Path | None, s0_subdir: str):
    """Return {name: callable(rgb)->vec} for each available backbone."""
    from photo_workflow.subject_context import ModelSessions

    emb = {}
    s2 = ModelSessions(model_dir=models_dir).clip_vision
    if s2 is not None:
        emb["clip_s2"] = lambda rgb, s=s2: _run_clip(rgb, s)
    s0_path = models_dir / s0_subdir / "vision_encoder.onnx"
    if s0_path.exists():
        s0 = _ort(s0_path)
        emb["clip_s0"] = lambda rgb, s=s0: _run_clip(rgb, s)
    if segformer and segformer.exists():
        seg = _ort(segformer)
        emb["mit_pooled"] = lambda rgb, s=seg: _seg_pooled(rgb, s)
    return emb


def _embed_split(split, n_shards, embedders, cache_dir, hf_cache):
    """Embed one AVA split with all backbones. Returns {name: X}, y."""
    import pyarrow.parquet as pq
    from PIL import Image
    from huggingface_hub import hf_hub_download, list_repo_files

    names = sorted(embedders)
    cache_f = cache_dir / f"{split}_{n_shards}_{'-'.join(names)}.npz"
    if cache_f.exists():
        d = np.load(cache_f)
        print(f"[{split}] cached: {d['y'].shape[0]} samples")
        return {n: d[n] for n in names}, d["y"]

    files = sorted(f for f in list_repo_files(REPO_ID, repo_type="dataset")
                   if f.startswith(f"data/{split}-"))[:n_shards]
    Xs = {n: [] for n in names}
    y = []
    for fi, fn in enumerate(files):
        p = hf_hub_download(REPO_ID, filename=fn, repo_type="dataset", cache_dir=str(hf_cache))
        tbl = pq.read_table(p, columns=["image", "mean_score"])
        for im, sc in zip(tbl["image"].to_pylist(), tbl["mean_score"].to_pylist()):
            try:
                rgb = np.array(Image.open(io.BytesIO(im["bytes"])).convert("RGB"))
                vecs = {n: embedders[n](rgb) for n in names}
            except Exception:
                continue
            for n in names:
                Xs[n].append(vecs[n])
            y.append(float(sc))
            if len(y) % 500 == 0:
                print(f"[{split}] embedded {len(y)} (shard {fi+1}/{len(files)})", flush=True)
    Xs = {n: np.vstack(v).astype(np.float32) for n, v in Xs.items()}
    y = np.array(y, dtype=np.float32)
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.savez(cache_f, y=y, **Xs)
    print(f"[{split}] done: {y.shape[0]} samples -> {cache_f}")
    return Xs, y


def _train_eval(Xtr, ytr, Xva, yva, epochs):
    import torch
    import torch.nn as nn
    from scipy.stats import spearmanr

    torch.manual_seed(0)
    ranks = ytr.argsort().argsort().astype(np.float32)
    ttr = (ranks + 0.5) / len(ytr)
    Xt = torch.from_numpy(Xtr); Yt = torch.from_numpy(ttr).view(-1, 1)
    dim = Xtr.shape[1]
    net = nn.Sequential(
        nn.Linear(dim, 256), nn.ReLU(), nn.Dropout(0.3),
        nn.Linear(256, 64), nn.ReLU(), nn.Dropout(0.1),
        nn.Linear(64, 1), nn.Sigmoid(),
    )
    opt = torch.optim.Adam(net.parameters(), lr=1e-3, weight_decay=1e-4)
    lossf = nn.MSELoss(); n = Xt.shape[0]; bs = 256
    for _ in range(epochs):
        net.train(); perm = torch.randperm(n)
        for i in range(0, n, bs):
            idx = perm[i:i + bs]
            opt.zero_grad(); lossf(net(Xt[idx]), Yt[idx]).backward(); opt.step()
    net.eval()
    with torch.no_grad():
        pv = net(torch.from_numpy(Xva)).numpy().flatten()
    return float(spearmanr(pv, yva).statistic)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models-dir", type=Path, default=REPO / "models")
    ap.add_argument("--segformer", type=Path)
    ap.add_argument("--s0-subdir", default="mobileclip_s0_int8")
    ap.add_argument("--cache-dir", type=Path, default=Path(".claude/r2_spike/ava_cache"))
    ap.add_argument("--train-shards", type=int, default=4)
    ap.add_argument("--val-shards", type=int, default=1)
    ap.add_argument("--epochs", type=int, default=120)
    args = ap.parse_args()

    embedders = _build_embedders(args.models_dir, args.segformer, args.s0_subdir)
    print("Backbones:", ", ".join(sorted(embedders)) or "(none found!)")
    hf_cache = args.cache_dir / "hf"
    Xtr, ytr = _embed_split("train", args.train_shards, embedders, args.cache_dir, hf_cache)
    Xva, yva = _embed_split("validation", args.val_shards, embedders, args.cache_dir, hf_cache)

    print("\n=== Track A — aesthetic Spearman (AVA held-out) ===")
    print(f"{'backbone':12s} | {'dim':>5s} | {'val Spearman':>12s}")
    print("-" * 36)
    for name in sorted(embedders):
        rho = _train_eval(Xtr[name], ytr, Xva[name], yva, args.epochs)
        print(f"{name:12s} | {Xtr[name].shape[1]:5d} | {rho:12.3f}")
    print("\nThreshold: mit_pooled >= ~0.60 (and near clip_s2) => CLIP eviction viable.")


if __name__ == "__main__":
    main()
