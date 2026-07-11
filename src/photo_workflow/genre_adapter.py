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


def _fit_softmax_numpy(
    X: np.ndarray, y_idx: np.ndarray, n_classes: int,
    sample_weight: np.ndarray, l2: float = 1e-3, iters: int = 1500, lr: float = 0.5,
) -> tuple[np.ndarray, np.ndarray]:
    """Multinomial logistic regression via Adam (pure numpy). Returns (W (k,d), b (k,))."""
    n, d = X.shape
    W = np.zeros((n_classes, d), dtype=np.float64)
    b = np.zeros(n_classes, dtype=np.float64)
    Y = np.zeros((n, n_classes), dtype=np.float64)
    Y[np.arange(n), y_idx] = 1.0
    sw = (sample_weight / sample_weight.mean()).reshape(-1, 1)
    mW = np.zeros_like(W)
    vW = np.zeros_like(W)
    mb = np.zeros_like(b)
    vb = np.zeros_like(b)
    b1, b2, eps = 0.9, 0.999, 1e-8
    for t in range(1, iters + 1):
        logits = X @ W.T + b
        logits -= logits.max(axis=1, keepdims=True)
        P = np.exp(logits)
        P /= P.sum(axis=1, keepdims=True)
        G = (P - Y) * sw                       # weighted residual (n,k)
        gW = G.T @ X / n + l2 * W
        gb = G.sum(axis=0) / n
        for (p, g, m, v) in ((W, gW, mW, vW), (b, gb, mb, vb)):
            m *= b1
            m += (1 - b1) * g
            v *= b2
            v += (1 - b2) * (g * g)
            p -= lr * (m / (1 - b1 ** t)) / (np.sqrt(v / (1 - b2 ** t)) + eps)
    return W.astype(np.float32), b.astype(np.float32)


def _train_axis_numpy(X: np.ndarray, y: np.ndarray, cv_folds: int) -> dict:
    """Fit one axis head + a stratified-CV accuracy estimate, in pure numpy."""

    classes = sorted(set(str(c) for c in y))
    cls_idx = {c: i for i, c in enumerate(classes)}
    k = len(classes)
    yi = np.array([cls_idx[str(c)] for c in y])
    counts = np.bincount(yi, minlength=k)
    sw_per_class = len(yi) / (k * np.maximum(counts, 1))
    sw = sw_per_class[yi]

    def fit(Xtr, ytr):
        return _fit_softmax_numpy(Xtr, ytr, k, sw_per_class[ytr])

    # Stratified k-fold CV accuracy
    nsplit = max(2, min(cv_folds, int(counts.min())))
    rng = np.random.RandomState(0)
    folds = [[] for _ in range(nsplit)]
    for c in range(k):
        idx = np.where(yi == c)[0]
        rng.shuffle(idx)
        for j, ix in enumerate(idx):
            folds[j % nsplit].append(ix)
    correct = 0
    try:
        for f in range(nsplit):
            te = np.array(folds[f])
            tr = np.array([i for g in folds if g is not folds[f] for i in g])
            W, b = fit(X[tr], yi[tr])
            pred = (X[te] @ W.T + b).argmax(axis=1)
            correct += int((pred == yi[te]).sum())
        acc = correct / len(yi)
    except Exception:
        acc = float("nan")

    W, b = _fit_softmax_numpy(X, yi, k, sw)
    return {"classes": classes, "weight": W, "bias": b,
            "n_samples": int(len(y)), "cv_accuracy": acc}


def train_linear_adapter(
    X: np.ndarray,
    y_subject: np.ndarray,
    y_type: np.ndarray,
    cv_folds: int = 5,
) -> dict[str, dict]:
    """Fit subject + type logistic-regression heads on CLIP embeddings.

    Uses scikit-learn when available (training-time / dev), else a pure-numpy
    multinomial LR so the runtime venv (no sklearn) can retrain the adapter too —
    e.g. the Darktable Recalibrate button. Returns {axis: {"classes",
    "weight" (k,dim), "bias" (k,), "n_samples", "cv_accuracy"}}.
    """
    try:
        import sklearn  # noqa: F401
    except ImportError:
        return {"subject": _train_axis_numpy(X, y_subject, cv_folds),
                "type": _train_axis_numpy(X, y_type, cv_folds)}

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
