"""Tests for the learned linear genre adapter (training, inference, routing, storage)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from photo_workflow.genre_adapter import predict_axis
from photo_workflow.genre_router import SUBJECTS, PHOTO_TYPES, route_genre
from photo_workflow.scoring_types import SubjectContext
from photo_workflow.training_weights_db import (
    open_training_db, ensure_schema, upsert_linear_adapter, get_active_linear_adapter,
)


def _ctx(clip: np.ndarray) -> SubjectContext:
    return SubjectContext(
        image_bgr=np.zeros((10, 10, 3), dtype=np.uint8),
        image_gray=np.zeros((10, 10), dtype=np.uint8),
        thumbnail_rgb=np.zeros((8, 8, 3), dtype=np.uint8),
        subject_mask=np.ones((10, 10), dtype=np.uint8),
        subject_area_ratio=0.3,
        faces=[],
        detections=[],
        primary_subject_bbox=None,
        clip_embedding=clip,
        exif={},
        sharpness_contrast=1.0,
    )


def _head(classes, dim=512):
    """A head that maps unit vector e_i -> classes[i]."""
    w = np.zeros((len(classes), dim), dtype=np.float32)
    for i in range(len(classes)):
        w[i, i] = 10.0
    return {"classes": list(classes), "weight": w, "bias": np.zeros(len(classes), dtype=np.float32)}


def test_predict_axis_distribution_and_missing_classes() -> None:
    e = np.zeros(512, dtype=np.float32); e[0] = 1.0
    head = _head(["vehicle", "object"])
    dist = predict_axis(e, head, SUBJECTS)
    assert abs(sum(dist.values()) - 1.0) < 1e-5
    assert max(dist, key=dist.__getitem__) == "vehicle"
    # a label the head never saw is exactly 0
    assert dist["monument"] == 0.0


def test_route_genre_uses_adapter_over_poe() -> None:
    e = np.zeros(512, dtype=np.float32); e[0] = 1.0
    adapter = {"subject": _head(["vehicle", "object"]),
               "type": _head(["documentary", "scenic"])}
    res = route_genre(_ctx(e), genre_prototypes=None, adapter=adapter)
    assert res.subject == "vehicle"
    assert res.photo_type == "documentary"
    assert res.subject in SUBJECTS and res.photo_type in PHOTO_TYPES


def test_route_genre_falls_back_without_clip() -> None:
    # zero embedding -> adapter not usable -> PoE fallback still returns valid labels
    adapter = {"subject": _head(["vehicle"]), "type": _head(["documentary"])}
    res = route_genre(_ctx(np.zeros(512, dtype=np.float32)), genre_prototypes=None, adapter=adapter)
    assert res.subject in SUBJECTS and res.photo_type in PHOTO_TYPES


def test_long_exposure_gate_fires_on_slow_shutter() -> None:
    # CLIP head says scenic; a 2s exposure should gate the TYPE to long-exposure.
    e = np.zeros(512, dtype=np.float32); e[0] = 1.0
    adapter = {"subject": _head(["landscape", "waterfall"]),
               "type": _head(["scenic", "documentary"])}
    ctx = _ctx(e); ctx.exif = {"shutter": 2.0}
    res = route_genre(ctx, genre_prototypes=None, adapter=adapter)
    assert res.photo_type == "long-exposure"
    assert res.type_confidence >= 0.8
    # subject axis is untouched by the type gate
    assert res.subject == "landscape"


def test_long_exposure_gate_silent_on_fast_shutter() -> None:
    e = np.zeros(512, dtype=np.float32); e[0] = 1.0
    adapter = {"subject": _head(["landscape", "waterfall"]),
               "type": _head(["scenic", "documentary"])}
    ctx = _ctx(e); ctx.exif = {"shutter": 0.002}  # 1/500s
    res = route_genre(ctx, genre_prototypes=None, adapter=adapter)
    assert res.photo_type == "scenic"


def test_long_exposure_gate_via_poe_path() -> None:
    # No adapter -> PoE fallback; the gate still applies from EXIF alone.
    e = np.zeros(512, dtype=np.float32); e[0] = 1.0
    ctx = _ctx(e); ctx.exif = {"shutter": 3.0}
    res = route_genre(ctx, genre_prototypes=None, adapter=None)
    assert res.photo_type == "long-exposure"


def test_linear_adapter_db_roundtrip(tmp_path: Path) -> None:
    conn = open_training_db(tmp_path / "tw.db")
    ensure_schema(conn)
    classes = ["vehicle", "object", "monument"]
    W = np.random.randn(3, 16).astype(np.float32)
    b = np.random.randn(3).astype(np.float32)
    upsert_linear_adapter(conn, 1, "subject", classes, W, b, 42, 0.9)
    got = get_active_linear_adapter(conn)
    conn.close()
    assert "subject" in got
    assert got["subject"]["classes"] == classes
    assert np.allclose(got["subject"]["weight"], W)
    assert np.allclose(got["subject"]["bias"], b)


def test_train_linear_adapter_roundtrip() -> None:
    pytest.importorskip("sklearn")
    from photo_workflow.genre_adapter import train_linear_adapter
    rng = np.random.RandomState(0)
    # two separable clusters per axis
    X = np.vstack([rng.randn(20, 512) + 3 * np.eye(512)[0],
                   rng.randn(20, 512) + 3 * np.eye(512)[1]]).astype(np.float32)
    ys = np.array(["vehicle"] * 20 + ["object"] * 20)
    yt = np.array(["documentary"] * 20 + ["scenic"] * 20)
    heads = train_linear_adapter(X, ys, yt, cv_folds=3)
    assert set(heads) == {"subject", "type"}
    assert heads["subject"]["weight"].shape[1] == 512
    # predicts the right class on a clean exemplar
    e = np.zeros(512, dtype=np.float32); e[0] = 3.0
    dist = predict_axis(e, heads["subject"], SUBJECTS)
    assert max(dist, key=dist.__getitem__) == "vehicle"
