# ADR-001 — Stage-6 Five-Module Scoring Split: Superseded by the score_fusion Monolith

**Status:** Superseded design, decision accepted (2026-07, recorded retroactively)

## Context

Build-sequence Stage 6 planned to replace scoring with a five-module pipeline
(`region_router` → `sub_scores/*` → `technical_gate` + `aesthetic_weighter` →
`fusion`) with interfaces locked in a contracts doc and a 6-step migration
checklist. The scoring redesign's *behaviors* (two-axis weighting, hard gates,
renormalization, percentile stars) were implemented directly, but the module
split never happened — the plan was silently bypassed, and the contracts doc
kept describing modules that do not exist (16×12 taxonomy, NIMA, a
`SubScoreBundle.as_flat_dict()` API found nowhere in `src/`).

## Decision

Keep the as-built single module `src/photo_workflow/score_fusion.py` as the
scoring implementation. Archive the unbuilt design:
[scoring-module-contracts.md](../../Archive/architecture/scoring-module-contracts.md),
[stage-6-engineer-brief.md](../../Archive/architecture/stage-6-engineer-brief.md),
[subject-enabled-subscores.md](../../Archive/architecture/subject-enabled-subscores.md)
(all banner-marked). The authoritative reference is the as-built
[scoring-architecture.md](../scoring-architecture.md).

## Consequences

- Do not implement from the archived contracts; they describe a different
  taxonomy and deleted models.
- Any future modularization (e.g. R2 region-aware scoring) starts from the
  as-built doc, not the Stage-6 plan.
- CLAUDE.md's Stage-6 paragraph was rewritten to reflect completion as-built.
