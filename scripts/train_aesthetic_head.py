"""Train the CLIP-embedding aesthetic head (models/clip_aesthetic_head/aesthetic_mlp.onnx).

Provisioning / data-prep step — uses the internet to fetch the AVA aesthetics
dataset; the resulting model runs fully offline at runtime (NFR-2.1). The head
maps a 512-d MobileCLIP-S2 embedding -> aesthetic score in [0,1], reusing the
embedding already computed for genre routing (no extra image forward pass).

Pipeline: download an AVA subset (parquet, images + mean scores) -> embed each
image with OUR ONNX MobileCLIP-S2 encoder (identical to inference) -> train a
small MLP to predict the *quantile rank* of the AVA mean score (uniform [0,1]
target: preserves ranking while giving full dynamic range) -> export ONNX:
    input  clip_embedding [batch, 512]
    output aesthetic_score [batch, 1]   in [0, 1]

Embeddings are cached per split so re-runs / hyperparameter changes are fast.
Held-out Spearman ~0.66 on AVA (comparable to the LAION CLIP aesthetic predictor).

  python scripts/train_aesthetic_head.py --models-dir models --train-shards 4

Requires the [train] extra (torch, scikit-learn) plus: pyarrow, scipy,
huggingface_hub, Pillow, onnx export support (onnxruntime). open_clip is not
needed — embedding uses the vendored ONNX MobileCLIP-S2.
"""
from __future__ import annotations

import argparse
import glob
import io
import os
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

REPO_ID = "trojblue/AVA-aesthetics-10pct-min50-10bins"


def _embed_split(split, n_shards, models_dir, cache_dir, hf_cache):
    import pyarrow.parquet as pq
    from PIL import Image
    from huggingface_hub import hf_hub_download, list_repo_files
    from photo_workflow.subject_context import ModelSessions, _run_clip

    cache_f = cache_dir / f"{split}_{n_shards}.npz"
    if cache_f.exists():
        d = np.load(cache_f)
        print(f"[{split}] cached: {d['X'].shape[0]} embeddings")
        return d["X"], d["y"]

    files = sorted(f for f in list_repo_files(REPO_ID, repo_type="dataset")
                   if f.startswith(f"data/{split}-"))[:n_shards]
    sess = ModelSessions(model_dir=models_dir).clip_vision
    assert sess is not None, f"MobileCLIP vision encoder not found under {models_dir}"

    X, y = [], []
    for fi, fn in enumerate(files):
        p = hf_hub_download(REPO_ID, filename=fn, repo_type="dataset", cache_dir=str(hf_cache))
        tbl = pq.read_table(p, columns=["image", "mean_score"])
        for im, sc in zip(tbl["image"].to_pylist(), tbl["mean_score"].to_pylist()):
            try:
                arr = np.array(Image.open(io.BytesIO(im["bytes"])).convert("RGB"))
                X.append(_run_clip(arr, sess)); y.append(float(sc))
            except Exception:
                continue
            if len(X) % 500 == 0:
                print(f"[{split}] embedded {len(X)} (shard {fi+1}/{len(files)})", flush=True)
    X = np.vstack(X).astype(np.float32); y = np.array(y, dtype=np.float32)
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.savez(cache_f, X=X, y=y)
    print(f"[{split}] done: {X.shape[0]} embeddings -> {cache_f}")
    return X, y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-dir", type=Path, default=REPO / "models")
    ap.add_argument("--cache-dir", type=Path, default=REPO / ".aesthetic_train_cache")
    ap.add_argument("--train-shards", type=int, default=4)
    ap.add_argument("--val-shards", type=int, default=1)
    ap.add_argument("--epochs", type=int, default=120)
    args = ap.parse_args()

    hf_cache = args.cache_dir / "hf"
    Xtr, ytr = _embed_split("train", args.train_shards, args.models_dir, args.cache_dir, hf_cache)
    Xva, yva = _embed_split("validation", args.val_shards, args.models_dir, args.cache_dir, hf_cache)

    # Train target = quantile rank of AVA mean score (uniform [0,1]): preserves
    # ranking (all we use downstream) while giving the head full dynamic range,
    # so the aesthetic term discriminates in the weighted-sum fusion instead of
    # clustering near the AVA mean.
    ranks = ytr.argsort().argsort().astype(np.float32)
    ttr = (ranks + 0.5) / len(ytr)

    import torch
    import torch.nn as nn
    from scipy.stats import pearsonr, spearmanr
    torch.manual_seed(0)

    Xt = torch.from_numpy(Xtr); Yt = torch.from_numpy(ttr).view(-1, 1)
    net = nn.Sequential(
        nn.Linear(512, 256), nn.ReLU(), nn.Dropout(0.3),
        nn.Linear(256, 64), nn.ReLU(), nn.Dropout(0.1),
        nn.Linear(64, 1), nn.Sigmoid(),
    )
    opt = torch.optim.Adam(net.parameters(), lr=1e-3, weight_decay=1e-4)
    lossf = nn.MSELoss(); n = Xt.shape[0]; bs = 256
    for ep in range(args.epochs):
        net.train(); perm = torch.randperm(n)
        for i in range(0, n, bs):
            idx = perm[i:i + bs]
            opt.zero_grad(); loss = lossf(net(Xt[idx]), Yt[idx]); loss.backward(); opt.step()
        if (ep + 1) % 20 == 0:
            net.eval()
            with torch.no_grad():
                pv = net(torch.from_numpy(Xva)).numpy().flatten()
            print(f"epoch {ep+1}: val Spearman={spearmanr(pv, yva).statistic:.3f} "
                  f"Pearson={pearsonr(pv, yva)[0]:.3f}")

    net.eval()
    with torch.no_grad():
        pv = net(torch.from_numpy(Xva)).numpy().flatten()
    print(f"\nFINAL val: Spearman={spearmanr(pv, yva).statistic:.3f} "
          f"Pearson={pearsonr(pv, yva)[0]:.3f}  "
          f"pred[min={pv.min():.3f} mean={pv.mean():.3f} max={pv.max():.3f} std={pv.std():.3f}]")

    out = args.models_dir / "clip_aesthetic_head" / "aesthetic_mlp.onnx"
    out.parent.mkdir(parents=True, exist_ok=True)
    for f in glob.glob(str(out) + "*"):
        os.remove(f)
    torch.onnx.export(
        net, torch.zeros(1, 512), str(out),
        input_names=["clip_embedding"], output_names=["aesthetic_score"],
        dynamic_axes={"clip_embedding": {0: "batch"}, "aesthetic_score": {0: "batch"}},
        opset_version=17, dynamo=False,
    )
    print(f"exported -> {out} ({os.path.getsize(out)} bytes)")

    import onnxruntime as ort
    s = ort.InferenceSession(str(out), providers=["CPUExecutionProvider"])
    ov = s.run(None, {"clip_embedding": Xva})[0].flatten()
    assert ov.std() > 1e-3, "exported model is degenerate (constant output)"
    print(f"ONNX verify OK: out std={ov.std():.4f} max|onnx-torch|={np.abs(ov - pv).max():.2e}")


if __name__ == "__main__":
    main()
