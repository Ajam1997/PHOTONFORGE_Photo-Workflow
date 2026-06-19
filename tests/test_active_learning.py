"""Tests for active-learning representative selection."""
from __future__ import annotations

import numpy as np

from photo_workflow.active_learning import select_representatives


def test_select_representatives_picks_one_per_cluster() -> None:
    # Three well-separated clusters of different sizes.
    rng = np.random.RandomState(0)
    a = rng.randn(30, 8) * 0.05 + np.array([5, 0, 0, 0, 0, 0, 0, 0])
    b = rng.randn(15, 8) * 0.05 + np.array([0, 5, 0, 0, 0, 0, 0, 0])
    c = rng.randn(5, 8) * 0.05 + np.array([0, 0, 5, 0, 0, 0, 0, 0])
    X = np.vstack([a, b, c]).astype(np.float32)

    reps = select_representatives(X, k=3)
    assert len(reps) == 3
    # sorted by cluster size desc, and sizes recover the planted clusters
    sizes = [s for _, s in reps]
    assert sizes == sorted(sizes, reverse=True)
    assert sizes == [30, 15, 5]
    # each representative index is valid and the three are distinct
    idxs = [i for i, _ in reps]
    assert len(set(idxs)) == 3 and all(0 <= i < len(X) for i in idxs)


def test_select_representatives_edge_cases() -> None:
    assert select_representatives(np.zeros((0, 8), dtype=np.float32), k=5) == []
    X = np.random.RandomState(1).randn(3, 8).astype(np.float32)
    assert select_representatives(X, k=0) == []
    # k larger than n -> at most n picks
    assert len(select_representatives(X, k=10)) <= 3
