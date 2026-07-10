# ADR-005 — R2 Captioner: LFM2-VL-450M (Grounded), Florence-2 Until Then

**Status:** Accepted for R2 (decided 2026-06-19); R1 unchanged

## Context

Semantic naming (FR-1.7) runs Florence-2-base-ft INT8 ONNX today
(`models/florence2_int8/`, provisioned by `scripts/provision_models.sh`). The
R2 model-stack investigation
([r2-model-stack-investigation.md](../r2-model-stack-investigation.md))
spiked small VLM replacements with blind side-by-side caption judging across a
model × prompt-tier matrix.

## Decision

- **R1/today:** Florence-2-base-ft stays the captioner.
- **R2:** **LFM2-VL-450M with grounded (SceneRecord-context) prompting** —
  the best cell in the blind judging (4.08 mean; LFM2 bare was weak at 3.08).
  Contingent on cleaning the genre labels that feed grounding (its 8 %
  hallucination rate traced to trusting wrong labels).
- **Fallback:** SmolVLM-500M (strongest bare, lowest hallucination; grounding
  *hurts* it).
- **NIMA is deleted** (dead INT8 model that emitted a uniform distribution —
  the 2026-06-19 audit P1); the aesthetic signal is the CLIP-embedding MLP.
- **No depth model will be added** — SegFormer's semantic layers subsume the
  planned front-to-back ordering; metric depth is overkill.

## Consequences

- The captioner swap is a *quality* play, not a speed play (LFM2 is ~2× the
  parameters of Florence-2-base); naming speedups come architecturally:
  template filenames from the SceneRecord and captioning only keepers.
- Swap requires an INT8 ONNX export + i7-7500U benchmark before landing
  (KPM-1.2 budget).
