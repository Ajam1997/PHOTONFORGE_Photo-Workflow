# IF-3.1 — Genre/Subject Classifier → Scoring + Naming

**Side A:** Genre/Subject Classifier (`genre_router.py`)
**Side B:** Scoring System + Semantic Naming
**Status:** living
**Owner:** @software_lead

## What crosses

A `GenreResult` per photo: the two-axis classification (16 Subjects ×
12 Photo Types) plus per-axis distributions and confidences. Subject
drives region routing in scoring; Photo-Type drives aesthetic
weighting; both seed Florence-2 naming priors.

## Contract

```python
@dataclass
class GenreResult:
    subject: str                              # argmax — backward-compat scalar
    photo_type: str                           # argmax — backward-compat scalar
    subject_confidence: float
    photo_type_confidence: float
    top_subjects: list[tuple[str, float]]     # multi-label (FR-1.7.2)
    top_photo_types: list[tuple[str, float]]  # multi-label (FR-1.7.2)
    subject_distribution: dict[str, float]
    photo_type_distribution: dict[str, float]
```

Invariants:
- **Subject → `region_router`** (IF-2.1): selects which sub-score
  regions run (e.g. eye-sharpness for `person`/`pet`).
- **Photo-Type → `aesthetic_weighter`** (IF-2.1): selects/blends the
  per-Type weight vector from the `aesthetic_weights` SQLite table.
- Scalar `subject` / `photo_type` (argmax) are preserved for
  backward compatibility even after multi-label (FR-1.7.2) lands —
  they equal `top_subjects[0]` / `top_photo_types[0]`.
- Confidence floor for routing is 0.45; multi-label selection floor
  is 0.15. Below floor → unclassified on that axis.

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
