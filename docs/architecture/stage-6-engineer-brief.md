# Stage 6 — Step 1 Engineer Brief: New Scoring Dataclasses

**Owner:** @engineer
**Reviewer on completion:** @verification
**Source of truth for interfaces:** [scoring-module-contracts.md](./scoring-module-contracts.md)
**Step:** 1 of 6 from the migration checklist (final section of the contracts doc)

---

## Goal

Land the new typed dataclasses from the contracts doc into
`src/photo_workflow/scoring_types.py` **alongside the existing types**,
with zero behavior change anywhere in the codebase. This unblocks Steps 2–6
without forcing any consumer to migrate yet.

## Scope (in)

1. In `src/photo_workflow/scoring_types.py`, add — exactly as specified in
   sections 1–5 of the contracts doc:
   - Enums: `BlurType`, `ExposureStyle` (use `enum.StrEnum`, Python 3.11+).
   - `RegionSpec` (frozen dataclass, includes the depth fields).
   - Sub-score dataclasses: `SharpnessSubScores`, `ExposureSubScores`,
     `CompositionSubScores`, `AestheticSubScores`, `FaceSubScores`.
   - `SubScoreBundle` with an `as_flat_dict() -> dict[str, float]` method
     that returns a flat namespaced view (`"sharpness.subject"`,
     `"composition.rule_of_thirds"`, etc.) suitable for XMP serialization.
   - `GateCheck`, `TechnicalResult`.
   - `AestheticResult`.
   - `Correction` (the typed correction record from the "Module state
     ownership" section).
2. Extend the existing `FusionResult` with the three additive fields:
   `technical: TechnicalResult | None = None`, `aesthetic: AestheticResult |
   None = None`, `region_spec: RegionSpec | None = None`. All default to
   `None` so no existing constructor call breaks.
3. Keep all existing dataclasses (`SharpnessScores`, `CompositionScores`,
   `ExposureScores`, `SubjectContext`, `GenreResult`, etc.) byte-for-byte
   unchanged. They become deprecated aliases-in-spirit; do **not** mark
   them with `DeprecationWarning` yet (that happens in Step 6).
4. Type-construction smoke tests in `tests/test_scoring_types.py`:
   - One test per new dataclass that instantiates it with minimal valid
     args and asserts field round-trip.
   - One test that builds a `SubScoreBundle` and checks `as_flat_dict()`
     returns a flat `dict[str, float]` with the expected namespaced keys.
   - One test that constructs a `FusionResult` with only the legacy fields
     (the three new fields default to `None`) — proves back-compat.

## Scope (out — explicit non-goals)

- Do **not** touch `score_fusion.py`, `pipeline.py`, `darktable_bridge.py`,
  any sub-score module, or any other consumer of the existing types.
- Do **not** implement `region_router`, `technical_gate`,
  `aesthetic_weighter`, or `fusion.fuse()`. Those are Steps 2 and 4.
- Do **not** create the SQLite `aesthetic_weights` table or bootstrap from
  priors. That is Step 4.
- Do **not** wire `as_flat_dict()` into the XMP writer. That is Step 6.
- Do **not** delete or refactor `SharpnessScores`, `CompositionScores`, or
  `ExposureScores`. Deletion is Step 6.
- Do **not** introduce `DepthModel` Protocol or any model handle. Step 2.
- Do **not** add new dependencies. The new types are pure-Python dataclasses
  using `numpy` (already present).

## Acceptance criteria

- `ruff check src/photo_workflow/scoring_types.py tests/test_scoring_types.py`
  is clean.
- `pytest tests/test_scoring_types.py -q` passes.
- `pytest -q` shows **zero regressions** in the existing suite. The new
  types must not be imported by any existing code path yet.
- No diff outside `src/photo_workflow/scoring_types.py` and
  `tests/test_scoring_types.py`.

## Handoff signal to @verification

When Step 1 lands on `main`:

```bash
python scripts/github_comment.py verify-fr FR-scoring-step1 \
  "pytest tests/test_scoring_types.py: N/N passed; full suite no regressions"
```

@verification then confirms: (a) no behavior change in the integration
tests from Stage 5, (b) the new types are importable but unreferenced
elsewhere, and (c) the checklist line for Step 1 in the contracts doc gets
ticked. After verification signs off, @engineer can open Step 2
(`region_router`).

## Pointers

- New type shapes: `docs/architecture/scoring-module-contracts.md` §§1–5.
- Existing types to leave alone: `src/photo_workflow/scoring_types.py`.
- Migration checklist (the canonical 6 steps): bottom of the contracts
  doc.
- Bootstrap priors (Step 4, not now): `docs/research/scoring-redesign.md`
  §5.
