# ADR-006 — Per-Type Weight Calibration vs R2 SceneRecord Per-Region Scoring

**Status:** OPEN — decision pending (do not spend calibration effort until decided)

## Context

The aesthetic weighting layer has two possible futures:

- **Option A — calibrate the per-Type weight table.** The
  `aesthetic_weights` table (`training_weights_db.py`) is built to hold
  tuned, versioned per-Subject/per-Type profiles. Calibration needs on the
  order of 30–50 corrections per class (taxonomy brief estimate) — a
  substantial labeling investment that taxonomy churn has repeatedly reset
  (see [ADR-002](ADR-002-taxonomy-evolution-15x11.md)).
- **Option B — R2 SceneRecord per-region scoring.** The R2 direction
  ([r2-model-stack-investigation.md](../r2-model-stack-investigation.md))
  replaces the binary subject mask with a semantic region map and scores per
  region; the `SceneRecord` structure (FusionResult + region map +
  enrichments) may **obsolete the per-Type weight table entirely** — weights
  would derive from region composition rather than a Type label.

The 2026-07-08 review (strategic item 10) flagged that this must be decided
*before* investing calibration effort, and recorded as an ADR — this one.

## Decision

**Pending.** Until decided:

- The bootstrapped defaults (`score_fusion.SUBJECT_WEIGHTS`/`TYPE_WEIGHTS`,
  seeded into the DB by `training bootstrap-aesthetic-weights`) remain the
  active profiles.
- No labeling campaigns aimed at weight calibration.
- The R2 Track-A/segmentation spikes are the gating input: if SegFormer-based
  region scoring proves out, Option B wins and the weight table becomes a
  fallback; if not, Option A proceeds against the (now stable) 15×11 taxonomy.

## Consequences

Deferring costs nothing today (defaults are reasonable); deciding late only
delays fine-tuning, not correctness. Revisit when the R2 spikes report.
