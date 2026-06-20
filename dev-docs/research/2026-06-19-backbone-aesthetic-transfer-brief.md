# Research Brief — Backbone choice for genre vs. aesthetic, and why FastViT isn't a CLIP replacement

**Date:** 2026-06-19
**Status:** findings recorded; one optional empirical check open
**Context:** R2 model-stack simplification — the "can we evict CLIP?" question.
**Companion:** [r2-model-stack-investigation.md](../architecture/r2-model-stack-investigation.md)
(full spike spec + results); spike code in `.claude/r2_spike/`.

## TL;DR

**Aesthetic transfer is a function of the *pretraining objective*, not the
backbone architecture.** A vision encoder predicts AVA aesthetic scores well only
if it was trained with a signal that captured style/quality — i.e. CLIP-style
contrastive image-text pretraining. Strong architectures trained on the wrong
objective (segmentation, ImageNet classification) carry little aesthetic signal.

Consequence for R2: **CLIP cannot be evicted from the aesthetic role.** Genre
routing *can* move to the SegFormer (MiT-b0) encoder we run anyway, but the
aesthetic head must keep riding a CLIP embedding.

## Evidence (dev box, AVA capped 600 train / 300 val; genre on 146-frame corpus)

| backbone | pretraining | genre subj/type | aesthetic Spearman |
|---|---|---|---|
| MiT-b0 (SegFormer encoder) | ADE20K segmentation | **0.703 / 0.596** | **0.208** |
| MobileCLIP-S2 (MCi2) | CLIP contrastive | 0.627 / 0.548 | **0.575** |
| MobileCLIP-S0 (MCi0) | CLIP contrastive | 0.607 / 0.527 | 0.496 |

Two clean reads:
- **Genre** rewards scene-semantic features → the segmentation encoder *wins* and
  is free (it runs for region decomposition regardless).
- **Aesthetic** rewards the CLIP objective → MiT-b0 collapses to near-floor
  (0.208), while both CLIP variants retain signal. This is the same scene-vs-
  quality split, now measured.

(Caveat: capped AVA depresses absolutes — CLIP-S2 is ~0.66 on the full set — but
the *relative* gaps are far larger than sample noise.)

## Why FastViT is not a separate CLIP replacement

**MobileCLIP's image tower is already a FastViT derivative.** The MCi / RepMixer
encoders (MCi0→S0, MCi2→S2) are built on the FastViT hybrid CNN-transformer
blocks (same Apple lineage). So the current "CLIP" backbone *is* a FastViT,
trained with the CLIP objective. "FastViT instead of CLIP" therefore resolves to
one of two non-options:

1. **ImageNet-classification FastViT** (e.g. timm weights) — the architecture is
   fine, but the objective is wrong. Expected to hit the **same aesthetic wall as
   MiT-b0** (likely ~0.35–0.45 Spearman: better than segmentation, still well
   under CLIP). Does not justify evicting CLIP-S2.
2. **FastViT + CLIP training** — that is MobileCLIP. Already in the stack.

**The only real lever FastViT exposes is size.** MobileCLIP-S0 (the smaller
FastViT-CLIP) trades ~0.08 aesthetic Spearman (0.496 vs 0.575) for RAM/latency.
Since genre has moved off CLIP onto MiT-b0, CLIP now serves *only* aesthetic, so
the S0-vs-S2 decision is purely "how much aesthetic quality is the saving worth."

## Implications for the R2 stack

- **Genre routing → MiT-b0 features** (beats CLIP, no added model).
- **Aesthetic stays on a MobileCLIP (FastViT-CLIP) embedding** — S2 by default;
  S0 if RAM/latency pressure outweighs ~0.08 Spearman.
- **No new backbone buys a full-eviction win** — the constraint is the CLIP
  training objective, which no classification/segmentation backbone replicates.

## Open empirical check (optional, ~5 min)

The AVA harness (`.claude/r2_spike/track_a_aesthetic.py`) accepts any embedder.
Adding an ImageNet-trained FastViT (timm) and re-running the capped pass would
confirm the prediction that it lands between MiT-b0 (0.208) and CLIP (0.575) and
does not justify replacing CLIP-S2. Not run yet — current decision rests on the
"objective, not architecture" principle plus the MiT-b0 and S0/S2 data points.

## Related

- [[project-scoring-audit]] — the broken-aesthetic history that motivated a real
  AVA-trained head in the first place.
