# IF-3.1 — Genre/Subject Classifier → Scoring + Naming

**Side A:** Genre/Subject Classifier (`genre_router.py`)
**Side B:** Scoring System + Semantic Naming
**Status:** living
**Owner:** @software_lead

## What crosses

A `GenreResult` per photo: the two-axis classification (15 Subjects ×
11 Photo Types — canonical lists in `genre_router.SUBJECTS` /
`genre_router.PHOTO_TYPES`) plus per-axis distributions and
confidences. Subject and Photo-Type each select a weight profile in
`score_fusion.py`; both seed Florence-2 naming priors.

## Contract

```python
@dataclass
class GenreResult:
    subject: str                          # argmax on the Subject axis
    subject_confidence: float
    photo_type: str                       # argmax on the Photo-Type axis
    type_confidence: float
    subject_distribution: dict[str, float]
    type_distribution: dict[str, float]
    needs_review: bool                    # low-confidence flag for the review queue
```

(Defined in `src/photo_workflow/scoring_types.py`; legacy `genres` /
`primary_genre` compatibility properties are derived from these
fields.)

Invariants:
- **Subject + Photo-Type → `fuse_scores()`** (IF-2.1): each axis
  selects a weight profile from the `aesthetic_weights` SQLite table
  (fallback: hardcoded defaults); the two profiles are blended, and
  not-applicable signals (e.g. eye-sharpness without `people`/`pet`
  faces) are dropped with the remaining weights renormalized.
- Scalar `subject` / `photo_type` are the per-axis argmax over
  `subject_distribution` / `type_distribution`.
- Low-confidence classifications set `needs_review` so the Darktable
  review queue (refresh-review) surfaces them for correction.

## Verified By (Side A — Classifier)

- pytest: tests/test_genre_router.py
- pytest: tests/test_subject_context.py

## Verified By (Side B — Scoring/Naming)

- pytest: tests/test_scoring_integration.py

## Validated By

- (none yet) — e2e: Stage 2 milestone — Subject/Type routing observed on fixtures

## Notes

Multi-label (FR-1.7.2) changes the contract *shape* (adds `top_*`
lists) but not the backward-compatible scalar fields. Per-axis
back-training (FR-1.7.1) updates the prototypes behind this interface
without changing the `GenreResult` schema.
