# IF-2.1 — Scoring Subsystem Internal Contracts

**Side A:** Sub-score producers (`sharpness.py`, `composition.py`, `exposure.py`, aesthetic head, face detection)
**Side B:** Score fusion (`score_fusion.py`)
**Status:** living
**Owner:** @software_lead

> As-built contract. The originally planned five-module split
> (`region_router` → `sub_scores/*` → `technical_gate` +
> `aesthetic_weighter` → `fusion`) was **superseded** — the behavior
> shipped inside the single module `src/photo_workflow/score_fusion.py`.
> The historical design lives in
> [scoring-module-contracts.md](../../dev-docs/Archive/architecture/scoring-module-contracts.md)
> (banner-marked, do not implement from it).

## What crosses

The per-photo sub-score results plus the two-axis classification, fused
into a single `FusionResult`:

```python
fuse_scores(
    sharpness: SharpnessScores,
    composition: CompositionScores,
    exposure: ExposureScores,
    genre: GenreResult,                # IF-3.1 — selects the weight profiles
    aesthetic: float | None,           # CLIP aesthetic-head score
    faces: list[FaceDetection] | None = None,
    image_gray: np.ndarray | None = None,
    weight_profiles: dict[str, dict[str, dict[str, float]]] | None = None,
) -> FusionResult
```

## Contract

- **Two-axis weighting.** `GenreResult.subject` and
  `GenreResult.photo_type` (IF-3.1) each select a weight profile;
  `fuse_scores()` blends the two axes' active profiles into the
  per-signal weights.
- **Weight storage.** Profiles live in the training weights DB
  (`training_weights_db.py`), table `aesthetic_weights`
  (`version`, `axis`, `label`, `weights` JSON, `is_active`;
  `UNIQUE(version, axis, label)`). When absent, `score_fusion.py`
  falls back to its hardcoded defaults.
- **Renormalization.** A not-applicable signal (e.g. `aesthetic` is
  `None`, no faces) is *dropped* and the remaining weights are
  renormalized — never filled with a constant.
- **Hard-reject gates.** Technically unusable photos are gated to the
  floor regardless of aesthetic weighting; hard-rejected photos are
  excluded from the percentile pool.
- **Star rating.** Stars are assigned by per-shoot percentile over the
  master scores, not by absolute thresholds.
- `FusionResult`'s flat fields (sharpness, composition, exposure,
  master, stars) are the stability boundary consumed by `pipeline.py`,
  `darktable_bridge.py`, and the XMP writer (IF-3.2).

## Verified By (Side A)

- pytest: tests/test_scoring_types.py
- pytest: tests/test_score_fusion.py

## Verified By (Side B)

- pytest: tests/test_scoring_integration.py

## Validated By

- (none yet) — e2e: Stage 2 milestone — scoring pipeline produces FusionResult on fixtures

## Notes

Do not duplicate the dataclass field lists here — they would drift.
This ICD's job is to register the boundary in the requirement tree and
point at the code: `src/photo_workflow/score_fusion.py` (`fuse_scores`)
and `src/photo_workflow/training_weights_db.py` (`aesthetic_weights`).
