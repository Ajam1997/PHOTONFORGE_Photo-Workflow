#!/usr/bin/env python3
"""R2 spike Track A — genre linear-probe over the cached features.

Reads the .npz cache from extract_features.py and, for each backbone candidate,
runs stratified k-fold logistic-regression probes on the two genre axes:

    subject (N-way)   from clip_s2 / clip_s0 / mit_pooled / mit_pooled+region_hist
    photo_type (N-way)            "

Prints a decision table of mean +/- std accuracy per candidate per axis. The
hypothesis under test: mit_pooled (+region_hist) lands within ~3% of CLIP-S2.

Aesthetic Spearman (the other half of Track A) uses AVA, a different dataset —
see track_a_aesthetic.py (separate; needs an AVA feature pass).

Deps: numpy, scikit-learn. No photo_workflow import required.

    python .claude/r2_spike/track_a_probe.py --cache-dir .claude/r2_spike/cache
"""

from __future__ import annotations

import argparse
import logging
from collections import Counter
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("track_a_probe")

# Candidate feature builders: name -> function(record) -> vector or None.
CANDIDATES = {
    "clip_s2": lambda r: r.get("clip_s2_emb"),
    "clip_s0": lambda r: r.get("clip_s0_emb"),
    "mit_pooled": lambda r: r.get("mit_pooled"),
    "mit+hist": lambda r: (
        np.concatenate([r["mit_pooled"], r["region_hist"]])
        if "mit_pooled" in r and "region_hist" in r else None
    ),
}


def _load_corpus(cache_dir: Path) -> list[dict]:
    records = []
    for npz in sorted(cache_dir.glob("corpus*__*.npz")):
        d = np.load(npz, allow_pickle=True)
        rec = {k: d[k] for k in d.files}
        rec["subject"] = str(rec.get("subject", ""))
        rec["photo_type"] = str(rec.get("photo_type", ""))
        records.append(rec)
    return records


def _probe(X: np.ndarray, y: np.ndarray, folds: int) -> tuple[float, float, int, int]:
    """Stratified CV accuracy. Drops classes too small to stratify."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_score

    counts = Counter(y)
    keep = {c for c, n in counts.items() if n >= 2}
    mask = np.array([lbl in keep for lbl in y])
    X, y = X[mask], y[mask]
    if len(set(y)) < 2:
        return float("nan"), 0.0, len(y), len(set(y))
    k = min(folds, min(Counter(y).values()))
    cv = StratifiedKFold(n_splits=k, shuffle=True, random_state=0)
    clf = LogisticRegression(max_iter=2000, C=1.0)
    scores = cross_val_score(clf, X, y, cv=cv, scoring="accuracy")
    return float(scores.mean()), float(scores.std()), len(y), len(set(y))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache-dir", type=Path, default=Path(".claude/r2_spike/cache"))
    ap.add_argument("--folds", type=int, default=5)
    args = ap.parse_args()

    records = _load_corpus(args.cache_dir)
    log.info("Loaded %d labelled corpus records.", len(records))
    if not records:
        log.error("No corpus*.npz in %s — run extract_features.py first.", args.cache_dir)
        return

    results: dict[str, dict[str, tuple]] = {}
    for cand, getter in CANDIDATES.items():
        present = [r for r in records if getter(r) is not None]
        if not present:
            log.info("Candidate %-9s: no features cached, skipping.", cand)
            continue
        results[cand] = {}
        for axis in ("subject", "photo_type"):
            rows = [(getter(r), r[axis]) for r in present if r[axis] and r[axis] != "general"]
            if len(rows) < args.folds:
                results[cand][axis] = (float("nan"), 0.0, len(rows), 0)
                continue
            X = np.stack([np.asarray(v, dtype=np.float32) for v, _ in rows])
            y = np.array([lbl for _, lbl in rows])
            results[cand][axis] = _probe(X, y, args.folds)

    # Decision table.
    print("\n=== Track A — genre probe (stratified %d-fold accuracy) ===" % args.folds)
    print(f"{'candidate':12s} | {'subject acc':>22s} | {'photo_type acc':>22s}")
    print("-" * 64)
    for cand, axes in results.items():
        cells = []
        for axis in ("subject", "photo_type"):
            m, s, n, k = axes.get(axis, (float("nan"), 0, 0, 0))
            cells.append(f"{m:.3f}±{s:.3f} (n={n},k={k})" if m == m else f"{'n/a':>22s}")
        print(f"{cand:12s} | {cells[0]:>22s} | {cells[1]:>22s}")
    print("\nThreshold: within ~0.03 of clip_s2 == consolidation viable on genre.")


if __name__ == "__main__":
    main()
