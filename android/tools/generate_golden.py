#!/usr/bin/env python3
"""Generate golden test vectors for the Kotlin core by running the Python
reference on deterministic synthetic inputs. The same synthetic-image formulas
are re-implemented in the Kotlin tests (see core/src/test/.../Golden.kt) —
keep them in lockstep.

Usage: python3 android/tools/generate_golden.py   (repo root; needs numpy+cv2)
"""
from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
OUT = REPO / "android" / "core" / "src" / "test" / "resources" / "golden"

from photo_workflow.exposure import score_exposure_detailed  # noqa: E402
from photo_workflow.genre_router import PHOTO_TYPES, SUBJECTS, route_genre  # noqa: E402
from photo_workflow.score_fusion import (  # noqa: E402
    absolute_star,
    estimate_eye_openness,
    fuse_scores,
    hybrid_star,
    stars_to_color_label,
)
from photo_workflow.scoring_types import (  # noqa: E402
    CompositionScores,
    ExposureScores,
    FaceDetection,
    GenreResult,
    SharpnessScores,
    SubjectContext,
)
from photo_workflow.sharpness import score_sharpness_detailed  # noqa: E402
from photo_workflow.composition import score_composition_detailed  # noqa: E402


# --- deterministic synthetic images (mirror in Kotlin!) ---------------------

def synth_gray(w: int, h: int, variant: int) -> np.ndarray:
    """uint8 gray image from a fixed integer formula."""
    y, x = np.mgrid[0:h, 0:w]
    if variant == 0:      # diagonal gradient
        v = (x * 255 // max(w - 1, 1) + y * 255 // max(h - 1, 1)) // 2
    elif variant == 1:    # high-frequency texture
        v = (x * 37 + y * 91 + (x * y) % 23) % 256
    elif variant == 2:    # flat dark with bright square
        v = np.full((h, w), 20)
        v[h // 4: h // 2, w // 4: w // 2] = 230
    else:                 # soft blob
        cy, cx = h / 2.0, w / 2.0
        d2 = (y - cy) ** 2 + (x - cx) ** 2
        v = 255.0 * np.exp(-d2 / (2 * (min(h, w) / 4.0) ** 2))
    return v.astype(np.uint8)


def synth_rgb(w: int, h: int, variant: int) -> np.ndarray:
    """uint8 RGB (H,W,3) from fixed formulas; BGR view is np[..., ::-1]."""
    y, x = np.mgrid[0:h, 0:w]
    if variant == 0:      # colorful gradient
        r = (x * 255 // max(w - 1, 1))
        g = (y * 255 // max(h - 1, 1))
        b = ((x + y) * 255 // max(w + h - 2, 1))
    elif variant == 1:    # muted gray-ish
        base = (x * 3 + y * 5) % 40 + 100
        r, g, b = base, base + 5, base - 5
    elif variant == 2:    # dark low-key with highlight
        r = np.full((h, w), 8)
        g = np.full((h, w), 8)
        b = np.full((h, w), 8)
        r[: h // 8, : w // 8] = 255
        g[: h // 8, : w // 8] = 255
        b[: h // 8, : w // 8] = 255
    else:                 # clipped bright
        r = g = b = np.full((h, w), 253)
    return np.stack([r, g, b], axis=-1).astype(np.uint8)


def center_mask(w: int, h: int) -> np.ndarray:
    m = np.zeros((h, w), dtype=np.uint8)
    m[h // 4: 3 * h // 4, w // 4: 3 * w // 4] = 1
    return m


def ctx_for(rgb: np.ndarray, mask: np.ndarray, faces=None) -> SubjectContext:
    import cv2

    bgr = rgb[..., ::-1].copy()
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    return SubjectContext(
        image_bgr=bgr,
        image_gray=gray,
        thumbnail_rgb=rgb,
        subject_mask=mask,
        subject_area_ratio=float(mask.mean()),
        faces=faces or [],
        detections=[],
        primary_subject_bbox=None,
        clip_embedding=np.zeros(512, dtype=np.float32),
        exif={},
        sharpness_contrast=0.0,
        image_rgb=rgb,
    )


def main() -> None:
    # cv2 build in some environments returns HoughLinesP as (N,4) instead of
    # (N,1,4); normalize so the reference code runs identically everywhere.
    import cv2

    _orig_hough = cv2.HoughLinesP

    def _hough(*args, **kwargs):
        r = _orig_hough(*args, **kwargs)
        return r.reshape(-1, 1, 4) if r is not None else None

    cv2.HoughLinesP = _hough

    OUT.mkdir(parents=True, exist_ok=True)
    golden: dict = {}

    # ---- exposure ---------------------------------------------------------
    exposure_cases = []
    for variant in range(4):
        rgb = synth_rgb(96, 64, variant)
        scores = score_exposure_detailed(ctx_for(rgb, center_mask(96, 64)))
        exposure_cases.append({"variant": variant, "w": 96, "h": 64, **asdict(scores)})
    golden["exposure"] = exposure_cases

    # ---- sharpness --------------------------------------------------------
    sharpness_cases = []
    for variant in range(4):
        gray = synth_gray(96, 64, variant)
        rgb = np.stack([gray] * 3, axis=-1)
        scores = score_sharpness_detailed(ctx_for(rgb, center_mask(96, 64)))
        sharpness_cases.append({"variant": variant, "w": 96, "h": 64, **asdict(scores)})
    golden["sharpness"] = sharpness_cases

    # ---- composition (leading_lines compared loosely in Kotlin) -----------
    composition_cases = []
    for variant in range(4):
        rgb = synth_rgb(96, 64, variant)
        scores = score_composition_detailed(ctx_for(rgb, center_mask(96, 64)))
        composition_cases.append({"variant": variant, "w": 96, "h": 64, **asdict(scores)})
    golden["composition"] = composition_cases

    # ---- eye openness ------------------------------------------------------
    eye_cases = []
    for variant in range(4):
        gray = synth_gray(96, 64, variant)
        face = FaceDetection(
            bbox=(20, 10, 40, 30), confidence=0.9,
            landmarks={"left_eye": (30, 20), "right_eye": (50, 20)},
        )
        eye_cases.append({
            "variant": variant, "w": 96, "h": 64,
            "openness": estimate_eye_openness(face, gray),
        })
    golden["eye_openness"] = eye_cases

    # ---- fusion (uses exported weights.json profiles == bundled DB) -------
    weights = json.loads(
        (REPO / "android/core/src/main/resources/photonforge/weights.json").read_text()
    )
    rng = np.random.RandomState(42)
    fusion_cases = []
    blur_types = ["sharp", "bokeh", "motion_subject", "motion_global", "misfocused"]
    for i in range(12):
        sharp = SharpnessScores(
            subject=float(rng.uniform(0, 1)), eye_region=float(rng.uniform(0, 1)),
            background=float(rng.uniform(0, 1)), sharpness_contrast=float(rng.uniform(0, 8)),
            blur_type=blur_types[i % 5], overall=float(rng.uniform(0, 1)),
        )
        comp = CompositionScores(
            rule_of_thirds=float(rng.uniform(0, 1)), symmetry=float(rng.uniform(0, 1)),
            leading_lines=float(rng.uniform(0, 1)), negative_space=float(rng.uniform(0, 1)),
            subject_isolation=float(rng.uniform(0, 1)), balance=float(rng.uniform(0, 1)),
            overall=float(rng.uniform(0, 1)), colorfulness=float(rng.uniform(0, 1)),
        )
        expo = ExposureScores(
            zone_entropy=float(rng.uniform(0, 1)), zone_diversity=int(rng.randint(0, 11)),
            clipping_shadows=float(rng.uniform(0, 0.2)), clipping_highlights=float(rng.uniform(0, 0.2)),
            dynamic_range=float(rng.uniform(0, 1)), midtone_density=float(rng.uniform(0, 1)),
            face_exposure=-1.0, style="normal", style_confidence=0.0,
            overall=float(rng.uniform(0, 1)),
        )
        genre = GenreResult(
            subject=SUBJECTS[i % len(SUBJECTS)],
            subject_confidence=float(rng.uniform(0.2, 0.9)),
            photo_type=PHOTO_TYPES[i % len(PHOTO_TYPES)],
            type_confidence=float(rng.uniform(0.2, 0.9)),
            subject_distribution={}, type_distribution={},
            needs_review=bool(i % 2),
        )
        aesthetic = None if i % 3 == 0 else float(rng.uniform(0, 1))
        result = fuse_scores(sharp, comp, expo, genre, aesthetic, None, None, weights)
        fusion_cases.append({
            "sharpness": asdict(sharp), "composition": asdict(comp),
            "exposure": asdict(expo),
            "genre": {"subject": genre.subject, "subject_confidence": genre.subject_confidence,
                      "photo_type": genre.photo_type, "type_confidence": genre.type_confidence,
                      "needs_review": genre.needs_review},
            "aesthetic": aesthetic,
            "expected": {
                "master_score": result.master_score,
                "hard_reject": result.hard_reject,
                "hard_reject_reason": result.hard_reject_reason,
                "star_rating": result.star_rating,
                "color_label": result.color_label,
                "sub_scores": {k: v for k, v in result.sub_scores.items()
                               if isinstance(v, (int, float))},
            },
        })
    golden["fusion"] = fusion_cases

    # ---- stars ------------------------------------------------------------
    star_cases = []
    kept = sorted(float(x) for x in rng.uniform(0.25, 0.8, size=20))
    for m in [0.0, 0.2, 0.25, 0.3, 0.39, 0.4, 0.45, 0.5, 0.55, 0.6, 0.8, 1.0]:
        star_cases.append({
            "master": m,
            "absolute": absolute_star(m, False),
            "absolute_reject": absolute_star(m, True),
            "hybrid": hybrid_star(m, False, kept),
            "color": stars_to_color_label(absolute_star(m, False)),
        })
    golden["stars"] = {"kept_sorted": kept, "cases": star_cases}

    # ---- genre routing (adapter from the bundled DB + prototypes) ---------
    db = sqlite3.connect(str(REPO / "src/photo_workflow/data/genre_weights.db"))
    adapter = {}
    for axis, classes_json, weight_blob, bias_blob, dim in db.execute(
        "SELECT axis, classes, weight, bias, dim FROM genre_adapter_linear WHERE is_active=1"
    ):
        classes = json.loads(classes_json)
        adapter[axis] = {
            "classes": classes,
            "weight": np.frombuffer(weight_blob, dtype=np.float32).reshape(len(classes), dim),
            "bias": np.frombuffer(bias_blob, dtype=np.float32),
        }
    protos_json = json.loads(
        (REPO / "android/core/src/main/resources/photonforge/prototypes.json").read_text()
    )
    prototypes = np.array(protos_json["rows"], dtype=np.float32)

    from photo_workflow.genre_router import (
        _REVIEW_MARGIN,
        _apply_motion_blur_gate,
        _compute_clip_similarity_axis,
        _top2_margin,
    )

    genre_cases = []
    for i in range(8):
        emb = rng.randn(512).astype(np.float32)
        emb /= np.linalg.norm(emb)
        shutter = 0.6 if i == 5 else (0.001 if i == 6 else None)
        use_adapter = i != 7
        if use_adapter:
            rgb = synth_rgb(32, 32, 0)
            ctx = ctx_for(rgb, center_mask(32, 32))
            ctx.clip_embedding = emb
            ctx.exif = {"shutter": shutter} if shutter is not None else {}
            res = route_genre(ctx, genre_prototypes=None, adapter=adapter)
            expected = {
                "subject": res.subject,
                "subject_confidence": res.subject_confidence,
                "photo_type": res.photo_type,
                "type_confidence": res.type_confidence,
                "needs_review": res.needs_review,
            }
        else:
            # The Kotlin fallback is CLIP-prototype-only (documented Phase 2
            # scope cut) — generate the expectation through the same sub-path,
            # not the full five-expert PoE.
            subj = _compute_clip_similarity_axis(emb, prototypes[: len(SUBJECTS)], SUBJECTS)
            typ = _compute_clip_similarity_axis(emb, prototypes[len(SUBJECTS):], PHOTO_TYPES)
            typ = _apply_motion_blur_gate(typ, {"shutter": shutter} if shutter else None)
            s_best = max(subj, key=subj.get)
            t_best = max(typ, key=typ.get)
            expected = {
                "subject": s_best,
                "subject_confidence": round(subj[s_best], 4),
                "photo_type": t_best,
                "type_confidence": round(typ[t_best], 4),
                "needs_review": _top2_margin(subj) < _REVIEW_MARGIN
                or _top2_margin(typ) < _REVIEW_MARGIN,
            }
        genre_cases.append({
            "embedding": [float(x) for x in emb],
            "shutter": shutter,
            "use_adapter": bool(use_adapter),
            "expected": expected,
        })
    golden["genre"] = genre_cases

    (OUT / "golden.json").write_text(json.dumps(golden))
    print("golden.json", (OUT / "golden.json").stat().st_size, "bytes")


if __name__ == "__main__":
    main()
