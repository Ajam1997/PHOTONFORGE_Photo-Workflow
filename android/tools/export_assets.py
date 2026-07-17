#!/usr/bin/env python3
"""Export scoring assets from the Python reference into android/core resources.

Single source of truth: the bundled training DB (genre_weights.db) and
score_fusion's hardcoded profiles. Re-run after any recalibration that should
ship to the app, then commit the regenerated JSON.

Usage: python3 android/tools/export_assets.py  (from the repo root)
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
OUT = REPO / "android" / "core" / "src" / "main" / "resources" / "photonforge"

sys.path.insert(0, str(SRC))


def export_weight_profiles(conn: sqlite3.Connection) -> dict:
    """Active aesthetic_weights rows (the DB layout the desktop runtime uses),
    falling back to score_fusion's hardcoded profiles for any missing label."""
    from photo_workflow.score_fusion import SUBJECT_WEIGHTS, TYPE_WEIGHTS

    profiles = {"subject": {k: dict(v) for k, v in SUBJECT_WEIGHTS.items()},
                "type": {k: dict(v) for k, v in TYPE_WEIGHTS.items()}}
    rows = conn.execute(
        "SELECT axis, label, weights FROM aesthetic_weights WHERE is_active=1"
    ).fetchall()
    for axis, label, weights_json in rows:
        profiles.setdefault(axis, {})[label] = json.loads(weights_json)
    return profiles


def export_adapter(conn: sqlite3.Connection) -> dict:
    import numpy as np

    out = {}
    rows = conn.execute(
        "SELECT axis, classes, weight, bias, dim FROM genre_adapter_linear WHERE is_active=1"
    ).fetchall()
    for axis, classes_json, weight_blob, bias_blob, dim in rows:
        classes = json.loads(classes_json)
        w = np.frombuffer(weight_blob, dtype=np.float32).reshape(len(classes), dim)
        b = np.frombuffer(bias_blob, dtype=np.float32)
        out[axis] = {
            "classes": classes,
            "dim": int(dim),
            "weight": [[float(x) for x in row] for row in w],
            "bias": [float(x) for x in b],
        }
    return out


def export_prototypes(conn: sqlite3.Connection) -> dict:
    """Active CLIP prototypes (26 rows: 15 subjects then 11 types)."""
    import numpy as np

    from photo_workflow.genre_router import PHOTO_TYPES, SUBJECTS

    rows = conn.execute(
        "SELECT genre, prototype FROM genre_prototypes WHERE is_active=1"
    ).fetchall()
    by_genre = {g: np.frombuffer(blob, dtype=np.float32) for g, blob in rows}
    order = SUBJECTS + PHOTO_TYPES
    missing = [g for g in order if g not in by_genre]
    if missing:
        raise SystemExit(f"prototypes missing for: {missing}")
    return {
        "subjects": SUBJECTS,
        "photo_types": PHOTO_TYPES,
        "rows": [[float(x) for x in by_genre[g]] for g in order],
    }


def main() -> None:
    db = SRC / "photo_workflow" / "data" / "genre_weights.db"
    conn = sqlite3.connect(str(db))
    OUT.mkdir(parents=True, exist_ok=True)

    (OUT / "weights.json").write_text(
        json.dumps(export_weight_profiles(conn), indent=None, separators=(",", ":"))
    )
    (OUT / "adapter.json").write_text(
        json.dumps(export_adapter(conn), indent=None, separators=(",", ":"))
    )
    (OUT / "prototypes.json").write_text(
        json.dumps(export_prototypes(conn), indent=None, separators=(",", ":"))
    )
    for f in ("weights.json", "adapter.json", "prototypes.json"):
        print(f, (OUT / f).stat().st_size, "bytes")


if __name__ == "__main__":
    main()
