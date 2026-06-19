"""Learned linear genre classifier (subject + type heads) over CLIP embeddings.

Replaces hand-tuned product-of-experts fusion with a small logistic-regression
head per axis, fit on the labeled corpus. Training uses scikit-learn (offline /
optional dependency); inference is a pure-numpy matmul + softmax, so the scoring
runtime needs no extra dependency.
"""
from __future__ import annotations

import numpy as np


def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def predict_axis(
    clip_embedding: np.ndarray,
    head: dict,
    axis_labels: list[str],
) -> dict[str, float]:
    """Probability over ``axis_labels`` from a stored linear head.

    head = {"classes": [...], "weight": (n_classes, dim), "bias": (n_classes,)}.
    Classes the head never saw map to probability 0.0.
    """
    e = np.asarray(clip_embedding, dtype=np.float32)
    logits = head["weight"] @ e + head["bias"]
    probs = _softmax(logits)
    classes = head["classes"]
    pmap = {classes[i]: float(probs[i]) for i in range(len(classes))}
    return {g: pmap.get(g, 0.0) for g in axis_labels}


def train_linear_adapter(
    X: np.ndarray,
    y_subject: np.ndarray,
    y_type: np.ndarray,
    cv_folds: int = 5,
) -> dict[str, dict]:
    """Fit subject + type logistic-regression heads on CLIP embeddings.

    Returns {axis: {"classes", "weight" (n,dim), "bias" (n,), "n_samples",
    "cv_accuracy"}}. Requires scikit-learn (training-time only).
    """
    from collections import Counter

    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict

    out: dict[str, dict] = {}
    for axis, y in (("subject", y_subject), ("type", y_type)):
        counts = Counter(y)
        nsplit = max(2, min(cv_folds, min(counts.values())))
        clf = LogisticRegression(max_iter=2000, C=1.0, class_weight="balanced")
        try:
            skf = StratifiedKFold(n_splits=nsplit, shuffle=True, random_state=0)
            acc = float(accuracy_score(y, cross_val_predict(clf, X, y, cv=skf)))
        except Exception:
            acc = float("nan")
        clf.fit(X, y)
        classes = [str(c) for c in clf.classes_]
        coef = np.atleast_2d(clf.coef_).astype(np.float32)
        intercept = np.atleast_1d(clf.intercept_).astype(np.float32)
        # Binary LR returns a single decision row; expand to one row per class
        # (class 0 as the reference logit) so inference is a uniform softmax.
        if coef.shape[0] == 1 and len(classes) == 2:
            coef = np.vstack([np.zeros_like(coef[0]), coef[0]])
            intercept = np.array([0.0, float(intercept[0])], dtype=np.float32)
        out[axis] = {
            "classes": classes,
            "weight": coef,
            "bias": intercept,
            "n_samples": int(len(y)),
            "cv_accuracy": acc,
        }
    return out
