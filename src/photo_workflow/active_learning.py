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


def select_representatives(embeddings: np.ndarray, k: int) -> list[tuple[int, int]]:
    """Pick ~k representative rows from `embeddings`.

    Returns a list of (row_index, cluster_size), sorted by cluster_size desc.
    """
    n = len(embeddings)
    if n == 0 or k <= 0:
        return []
    k = min(k, n)
    from sklearn.cluster import KMeans

    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(embeddings)
    reps: list[tuple[int, int]] = []
    for ci in range(k):
        idx = np.where(km.labels_ == ci)[0]
        if len(idx) == 0:
            continue
        d = np.linalg.norm(embeddings[idx] - km.cluster_centers_[ci], axis=1)
        reps.append((int(idx[int(d.argmin())]), int(len(idx))))
    reps.sort(key=lambda t: -t[1])
    return reps
