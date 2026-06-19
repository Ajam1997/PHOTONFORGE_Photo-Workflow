"""Active-learning sample selection for the training loop.

Given the CLIP embeddings of a folder's needs_review frames (already the
uncertain ones — top-2 genres nearly tied), pick a small, diverse, representative
subset most worth labeling. Strategy: k-means in embedding space, take the frame
closest to each centroid. Each pick (a) is spread across the embedding space
(diversity, no near-duplicates) and (b) represents a dense pocket of similar
uncertain frames, so one label improves the model for many. Returns picks sorted
by cluster size (biggest, highest-impact pockets first).
"""
from __future__ import annotations

import numpy as np


def _spherical_kmeans(X: np.ndarray, k: int, iters: int = 50, seed: int = 0):
    """Lightweight spherical k-means (cosine) in pure numpy.

    CLIP embeddings are L2-normalized, so nearest-centroid by max dot product is
    cosine clustering. Pure numpy keeps this usable from the lean runtime venv
    (no scikit-learn, which is a training-only extra). Returns (labels, centers).
    """
    rng = np.random.RandomState(seed)
    Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-8)
    centers = Xn[rng.choice(len(Xn), k, replace=False)].copy()
    labels = np.full(len(Xn), -1)
    for _ in range(iters):
        new = (Xn @ centers.T).argmax(axis=1)
        if np.array_equal(new, labels):
            break
        labels = new
        for ci in range(k):
            m = labels == ci
            if m.any():
                c = Xn[m].mean(axis=0)
                nrm = np.linalg.norm(c)
                if nrm > 0:
                    centers[ci] = c / nrm
    return labels, centers


def select_representatives(embeddings: np.ndarray, k: int) -> list[tuple[int, int]]:
    """Pick ~k representative rows from `embeddings`.

    Returns a list of (row_index, cluster_size), sorted by cluster_size desc.
    """
    n = len(embeddings)
    if n == 0 or k <= 0:
        return []
    k = min(k, n)
    X = np.asarray(embeddings, dtype=np.float32)
    labels, centers = _spherical_kmeans(X, k)

    reps: list[tuple[int, int]] = []
    for ci in range(k):
        idx = np.where(labels == ci)[0]
        if len(idx) == 0:
            continue
        # representative = highest cosine similarity to the (unit) centroid
        sims = (X[idx] / (np.linalg.norm(X[idx], axis=1, keepdims=True) + 1e-8)) @ centers[ci]
        reps.append((int(idx[int(sims.argmax())]), int(len(idx))))
    reps.sort(key=lambda t: -t[1])
    return reps
