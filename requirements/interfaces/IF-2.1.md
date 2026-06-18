# IF-2.1 — Scoring Subsystem Internal Contracts

**Side A:** `region_router` → `sub_scores/*`
**Side B:** `technical_gate` + `aesthetic_weighter` → `fusion`
**Status:** living
**Owner:** @software_lead

> The Stage-6 scoring-subsystem internal data contracts. **These are
> already fully specified** in
> [scoring-module-contracts.md](../../dev-docs/architecture/scoring-module-contracts.md);
> this ICD is the requirement-tree pointer to that authoritative doc.

## What crosses

The typed dataclasses that flow through the five-module scoring
pipeline:

```
region_router      → RegionSpec
sub_scores/*        → SubScoreBundle
technical_gate      → TechnicalResult
aesthetic_weighter  → AestheticResult
fusion              → FusionResult   (backward-compatible flat fields)
```

## Contract

Authoritative definitions for `RegionSpec`, `SubScoreBundle`,
`TechnicalResult`, `AestheticResult`, and `FusionResult` (including
`as_flat_dict()` backward-compat guarantees) live in
[scoring-module-contracts.md](../../dev-docs/architecture/scoring-module-contracts.md).

Key invariants:
- Master score = `min(technical, aesthetic)` with a swappable fusion strategy.
- `FusionResult.as_flat_dict()` + `SubScoreBundle.as_flat_dict()`
  preserve the flat keys that `pipeline.py`, `darktable_bridge.py`,
  and the XMP writer depend on — that backward compatibility IS the
  contract.
- Subject (from IF-3.1) is the `region_router` input; Photo-Type is
  the `aesthetic_weighter` input.

## Verified By (Side A)

- pytest: tests/test_scoring_types.py
- pytest: tests/test_score_fusion.py

## Verified By (Side B)

- pytest: tests/test_scoring_integration.py

## Validated By

- (none yet) — e2e: Stage 2 milestone — scoring pipeline produces FusionResult on fixtures

## Notes

Do not duplicate the dataclass field lists here — they would drift.
This ICD's job is to register the boundary in the requirement tree
and point at the design doc. The 6-step Stage-6 migration checklist at
the bottom of scoring-module-contracts.md is the execution plan.
