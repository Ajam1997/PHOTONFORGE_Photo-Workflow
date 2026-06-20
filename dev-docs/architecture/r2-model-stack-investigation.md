# R2 Model-Stack Simplification — Investigation Plan

**Status:** investigation — spikes not yet run
**Date:** 2026-06-19
**Owner:** @systems_lead (design) / @software_lead (spikes)
**Related:** [scoring-module-contracts.md](scoring-module-contracts.md),
Phase-0 region decomposition (`dev-docs/SystemReviews/2026-06-19-phase0-region-decomposition.md`),
[[project-scoring-audit]]

## Motivation

R2's headline is region-aware scoring (semantic decomposition replacing the
binary RMBG subject mask). While opening that seam, we re-examine the whole
inference stack with one goal: **reduce model overhead and inference time
without increasing hardware requirements — ideally reducing them.** Three cost
axes, weighted roughly equally:

1. **Peak RAM** — KPM-1.3 ceiling (≤ 1.5 GB analyzer RSS; 8 GB host).
2. **Scoring latency** — the per-image CLIP + RMBG + YOLO + YuNet pass (~3 s).
3. **End-to-end wall-clock** — including naming (Florence-2).

The binding constraint throughout is the runtime profile: **offline, INT8 ONNX,
onnxruntime CPU/AVX2 only, i7-7500U, 8 GB.** This filter — not raw quality —
eliminates most otherwise-attractive models.

## Current scoring model inventory

| Model | Role | Cost | R2 disposition |
|---|---|---|---|
| MobileCLIP-S2 | 512-d embedding → genre router **and** aesthetic head | image pass | **Track A** — candidate for eviction |
| RMBG-1.4 | binary *salient* subject mask | image pass | replace w/ SegFormer (pending IoU check) |
| YuNet | face + eye landmarks | image pass | keep (irreplaceable by ADE20K) |
| YOLOv8n | COCO boxes → genre evidence + animal-head eye routing | image pass | keep (instance/class info ADE20K lacks) |
| clip_aesthetic_head | MLP on the CLIP embedding | ~free | keep (re-target if backbone changes) |
| NIMA | aesthetic — **dead/abandoned** | provisioned, unused | **delete now** |
| *(depth, planned)* | front-to-back sharpness | +150 ms planned | **never add** (SegFormer subsumes, coarse) |
| Florence-2-base-ft | semantic caption / filename | own phase | **Track B** — candidate for replacement |

## Simplification thesis

- **Delete NIMA** unconditionally — dead weight literally loaded for nothing.
- **Never add the planned depth model** — SegFormer's semantic layers give the
  ordinal near/mid/far ordering front-to-back sharpness needs; metric depth is
  overkill.
- **SegFormer-b0 is a consolidation hub, not just an RMBG swap.** It absorbs the
  subject mask (for scene genres), the planned depth model, and — if Track A
  succeeds — the genre/aesthetic backbone.
- **RMBG deletion is gated** on an IoU check: SegFormer is scene-parsing, weak on
  frame-filling close-ups (food/macro/product/abstract) where RMBG saliency
  wins. Mask derived as the complement of SegFormer background classes
  (sky/wall/floor/road/water) may recover a saliency-like mask from one model;
  verify on close-up genres before deleting RMBG.
- **YOLO stays** — animal-head bbox (wildlife/pet eye sharpness) and COCO-class
  genre evidence are instance/class signals ADE20K semantic segmentation cannot
  provide.

The two open, high-value questions become two independent spikes.

---

## Track A — scoring backbone consolidation

**Hypothesis:** MiT-b0 (the SegFormer-b0 encoder we run anyway for regions) can,
via global-pooled features, serve genre classification **and** aesthetic
regression well enough to **evict MobileCLIP entirely** — collapsing CLIP + RMBG
+ NIMA into one backbone with three heads.

```
        MiT-b0 encoder  (one image pass)
        ├── seg decode head ──► region map      (R2 core)
        ├── genre head      ──► subject × type   (was CLIP + adapter)
        └── aesthetic head  ──► AVA score        (was CLIP + MLP)
```

**Anchor / risk:** MobileCLIP does double duty — genre embedding *and* the
AVA-trained aesthetic head ride the same vector. The aesthetic path is the
load-bearing unknown: MiT-b0 is trained for dense scene parsing on ADE20K
(narrow), and AVA-aesthetic is known to transfer well from CLIP-scale features
but has never been measured from a segmentation encoder. **Aesthetic Spearman is
the single measurement that decides whether full consolidation is possible.**

**Helper trick:** feed the genre head `[pooled_feat ⊕ region_histogram]` — the
explicit composition backfills MiT-b0's weakness on close-up genres.

**Method (no image re-decode beyond one pass per candidate):**
- Extract pooled MiT-b0 features over the 175-label corpus + an AVA holdout.
- Linear-probe genre (subject × type) from features (and feat ⊕ region-hist).
- Train an aesthetic head on AVA from the same features.
- Benchmark candidates: MobileCLIP-S2 (baseline), MobileCLIP-S0,
  **MiT-b0 pooled (⊕ region hist)**, optionally TinyCLIP-19M.

**Decision tree:**
- MiT-b0 serves **both** acceptably → delete CLIP entirely. Full consolidation.
- MiT-b0 serves **genre but not aesthetic** → genre on MiT-b0 ⊕ region; keep a
  *small* CLIP-S0 (or tiny dedicated aesthetic backbone) for aesthetic only.
- MiT-b0 serves **neither** → fall back to S2→S0 + SegFormer-as-3rd-genre-evidence
  (safe floor; still nets RAM from NIMA/RMBG deletes).

**Note:** dropping CLIP's text-prototype bootstrap means genre training is fully
supervised — 175 labels is thin for 26 classes. The region-histogram concat and
the safe floor mitigate; flag as a residual risk.

---

## Track B — naming VLM + prompt design

**Determination:** captioning needs a VLM (grounded perception produces the
"red boat / child holding balloon" richness a text-only LLM cannot). Florence-2
(early 2024) may simply be the wrong VLM — the small on-device VLM space matured
after this project started. **Florence-2's KV-cache latency gap is already
resolved** (merged-decoder, `naming.py`); the open question is whether a newer
model improves quality / latency / RAM / integration.

**Candidates** (filtered to official INT8-able ONNX, small enough for the CPU
target):

| Model | Size | ONNX | Notes |
|---|---|---|---|
| Florence-2-base-ft (control) | 0.23B | working | caption-*specialized*, terse COCO style |
| SmolVLM2-500M | 0.5B | official, same component pattern (minus text encoder) | conversational; near drop-in plumbing |
| SmolVLM2-256M | 0.26B | official, <1 GB | smallest; speed play |
| LFM2.5-VL-450M | 0.45B | official (LiquidAI) | freshest (late-2025), edge-optimized |
| ~~FastVLM-0.5B~~ | 0.5B | export broken (optimum #2377) | skip |
| ~~Phi-3.5-V / Gemma-3n / Qwen2.5-VL-3B~~ | 3-4B+ | n/a | too big for CPU target |

**Integration note:** SmolVLM's ONNX export (`vision_encoder` + `embed_tokens` +
`decoder_model_merged`) mirrors the existing `naming.py` orchestration **minus**
Florence-2's text-encoder session — a slightly *smaller* graph, not a bigger one.

**Quality direction:** general instruct VLMs produce fluent, conversational prose
— which favors the stated goal (human-readable descriptions) over Florence-2's
terse captions. The cost: they are prompt-steered captioners, not caption-tuned,
so hallucination rate and consistency must be measured.

### Prompt design as a first-class axis

General VLMs are steerable; Florence-2 is not. Prompt design is therefore a
quality **and** latency lever, and the vehicle for fusing scoring data into the
caption:

1. **Instruction + register** — set voice and specificity.
2. **Length/format constraints** — "one sentence, ≤15 words, caption only" —
   suppresses chatter and cuts decode tokens (latency).
3. **Anti-hallucination guardrails** — "describe only what is visible."
4. **SceneRecord grounding** — inject genre / conditions / objects+counts /
   dominant colors as *context*; ask the VLM for the *visual specifics*.
   Division of labor: structured data → scene-level facts (cheap, reliable);
   VLM → relations/attributes/actions (only it can). Reduces hallucination,
   raises richness, and lets a smaller model win. **Trap:** over-grounding makes
   the model parrot the record and ignore pixels — ground for context, not
   content.

**Spike matrix — `model × prompt-tier`:**

| | bare | instruction-tuned | **grounded (SceneRecord)** |
|---|---|---|---|
| Florence-2 (control) | current | — | n/a (rigid) |
| SmolVLM2-500M | ✓ | ✓ | ✓ |
| LFM2.5-VL-450M | ✓ | ✓ | ✓ |

**Hypothesis under test:** the bottom-right cell — *smallest model + grounded
prompt ≥ Florence-2* — which would win all three cost axes and quality at once.

**Method:** ~30 real frames; blind side-by-side caption quality, per-image CPU
latency (INT8, i7-7500U), RSS, hallucination rate (caption names entities absent
from ground truth), integration effort.

---

## SceneRecord — the connective interface

Both tracks converge on one structure. `SceneRecord` = `FusionResult` + region
map/composition + cheap enrichments (dominant color per region, YOLO instance
counts). It is:
- the per-region scoring substrate (R2 core),
- the genre-head auxiliary input (Track A: feat ⊕ region hist),
- the filename template source (zero-model naming),
- the VLM grounding context (Track B prompt).

## Results — Track A (dev box, 2026-06-19)

**Genre probe** (146 labelled corpus frames, stratified 5-fold):

| candidate | subject acc | photo_type acc |
|---|---|---|
| clip_s2 (baseline) | 0.627 | 0.548 |
| clip_s0 | 0.607 | 0.527 |
| **mit_pooled** | **0.703** | **0.596** |
| mit+hist | 0.703 | 0.596 (region_hist adds nothing to the linear probe) |

**Aesthetic Spearman** (AVA, capped 600 train / 300 val):

| backbone | Spearman |
|---|---|
| clip_s2 | 0.575 |
| clip_s0 | 0.496 |
| **mit_pooled** | **0.208** |

**Verdict — PARTIAL consolidation (middle branch).** MiT-b0 pooled features beat
CLIP on genre and are free (SegFormer runs for regions anyway), but carry **no
aesthetic signal** (0.208 — segmentation pretraining never saw quality cues). So:

- **Genre routing → MiT-b0** (better than CLIP, no extra model).
- **Aesthetic stays on CLIP-S2** — full CLIP eviction is NOT viable.
- Net R2 stack: SegFormer (regions + genre) + CLIP-S2 (aesthetic) + YOLO + YuNet;
  NIMA + RMBG deleted, depth never added. Simplification + genre-accuracy win,
  but CLIP-S2 remains resident for aesthetic.
- Possible follow-up (low confidence it closes the gap): test multi-stage MiT
  feature concat for aesthetic before fully accepting CLIP-S2 as permanent.

## Results — Track B (dev box, 2026-06-19)

12 genre-diverse frames × {bare, instruction, grounded}; 72 captions, 0 errors.

- **Both SmolVLM-500M and LFM2-VL-450M produce fluent, accurate captions** and
  are viable Florence-2 replacements. Grounded prompting visibly enriches output
  and the anti-parroting guardrail held (models described what they saw even when
  a frame's genre label was wrong).
- **Latency** (dev-box PyTorch, *relative only*): ~9 s/caption warm, LFM2
  marginally faster. Absolute KPM-1.2 needs INT8-ONNX on the Yoga — not yet run.
- **Florence-2 fails to load under transformers 5.12** (`forced_bos_token_id`);
  still ships via the ONNX `naming.py` path, but it's bit-rotting upstream — a
  mild point toward switching.
- **Final captioner pick is a prose preference** → blind judging of
  `.claude/r2_spike/track_b_results/blind.csv` (reveal via `blind_key.json`).
- Env note: these VLM image processors require `torchvision`; the decode must
  slice newly-generated tokens (format-agnostic) to avoid role-token echo.

## Track B — blind judging + captioner decision (2026-06-19)

Single judge, 72 captions (12 frames × {bare, instruction, grounded} × 2 models).

| model | mean | halluc | | tier | mean | halluc |
|---|---|---|---|---|---|---|
| LFM2-VL-450M | 3.58 | 8% | | grounded | 3.75 | 4% |
| SmolVLM-500M | 3.53 | 3% | | bare | 3.50 | 12% |
| | | | | instruction | 3.42 | 0% |

Interaction (model × tier): **LFM2 + grounded = 4.08** (best cell) but LFM2 bare
is weak (3.08, 17%); SmolVLM is strong bare (3.92) and grounding *hurts* it (3.42).

**Decision: LFM2-VL-450M with grounded prompting**, contingent on cleaning the
genre labels that feed grounding (LFM2's 8% halluc traces to trusting wrong
grounding facts, e.g. a `people/portrait`-mislabelled architecture frame).
SmolVLM-500M is the robust fallback (strong unprompted, lowest halluc). Grounding
as a strategy is validated: best tier overall, halves hallucination vs bare.

### Does the swap speed up naming? (the real question — UNRESOLVED)

**The captioner swap is NOT a speed win, and was never the speed lever:**
- LFM2-VL-450M (~0.45B) is ~2× Florence-2-base (~0.23B). More params ⇒ likely
  *slower* per caption at equal precision — though LFM2's efficiency-tuned
  backbone may offset. Either way it's a quality/grounding/maintenance choice,
  not a latency one. (Florence-2 also bit-rots on transformers 5.12.)
- The Track B ~9 s/caption is **PyTorch FP32 on the dev box** — NOT predictive of
  the production path (INT8 ONNX) on the Yoga. We have measured neither model as
  INT8 ONNX on target, so the swap's true speed delta is **unknown**.
- Florence-2's naming latency was already fixed by the KV-cache merge — the
  "naming is slow" problem this project started with is gone.

**The actual R2 naming speedups are architectural, independent of the captioner:**
1. **Structured filenames from the SceneRecord** — the *filename* path needs no
   VLM at all (genre + regions + EXIF → template), ~0 model cost for most images.
2. **Caption only keepers** — amortize the VLM over the starred subset.

**To answer the swap's speed question:** export LFM2-VL-450M to INT8 ONNX and
benchmark it vs Florence-2 on the i7-7500U. Until then, pick the captioner on
*quality* (LFM2+grounded) and bank the naming speedups from (1) and (2).

## Pinned decision thresholds (set before seeing results)

- **Genre:** within ~3% accuracy of MobileCLIP-S2 on the 175-label corpus.
- **Aesthetic:** Spearman ≥ 0.60 (current AVA head ≈ 0.66).
- **Caption:** ≥ Florence-2 on blind side-by-side of ~30 frames.
- **Naming latency:** ≤ Florence-2's current measured time.
- **RAM:** net peak RSS must not increase; target a decrease.

## Sequencing

1. **Delete NIMA** — unconditional, immediate.
2. **Run Track A + Track B spikes in parallel** — both are
   extract → score → decision-table shaped; neither blocks the other.
3. Branch each track on its decision tree.
4. **SegFormer region decomposition + per-region scoring** (R2 core) — proceeds
   regardless of Track A's backbone outcome (MiT-b0 runs either way).
5. **Structured filenames/keywords** from SceneRecord (free win) +
   chosen VLM for descriptions.

## Open risks

- Aesthetic transfer from a segmentation encoder (Track A) — primary unknown.
- 175 labels is thin for 26-class supervised genre without CLIP's text priors.
- General-VLM hallucination under grounding (Track B).
- RMBG deletion depends on close-up-genre IoU; may force RMBG/SegFormer coexist.
- CPU latency of decoder-only VLMs is unmeasured on the i7-7500U (WebGPU/M1
  figures do not transfer).

---

## Spike Specification (v1) — designed to run once

### Shared setup (the "do it once" core)

**One SegFormer-b0 export, dual-output.** Custom ONNX export exposing **both**
the seg map (→ region map + histogram) **and** the pooled encoder features (→
Track A backbone candidate). INT8. Stock seg ONNX outputs only the map — the
feature tap must be added at export.

**One cached extraction pass** over `{175-label corpus} ∪ {~30 eval frames}`,
storing per image in `.npz` (mirrors `.claude/ava_cache`):
`clip_s2_emb[512]`, `clip_s0_emb[…]`, `mit_b0_pooled[256]`, `region_hist[8]`,
`region_map`, YOLO detections, face count, EXIF. All probes/heads/prompts read
this cache — no model re-runs.

**Region-type taxonomy** (genre-agnostic map; subject role assigned
genre-conditionally on top): `sky · water · vegetation · ground · structure ·
subject · face(YuNet) · other`. (See taxonomy table above.)

### Eval frame set

~30 frames drawn from **both ICELAND and MISC2026**, deliberately spread across
*scene* genres (landscape/seascape/cityscape) **and** *close-up* genres
(food/macro/product/abstract) — the scene-vs-closeup split stresses both
SegFormer-as-mask and MiT-b0-as-backbone.

### Run location

**Dev box first** — decides the architecture via relative ranking + functional
validation. Latency/RSS there are *not* the KPM gate. **Yoga (i7-7500U) ratifies**
the absolute KPM-1.2 (≤2.5s) and RSS (≤1.5GB) budgets before anything ships.
Env prereq on the dev box: project venv with `onnxruntime`, `transformers`,
`optimum` (the current host system Python lacks `cv2`/`onnxruntime`).

### Track A protocol

- **Candidates:** MobileCLIP-S2 (baseline) · MobileCLIP-S0 · MiT-b0-pooled ·
  MiT-b0-pooled ⊕ region_hist. (TinyCLIP-19M = stretch.)
- **Genre:** two logistic-regression linear probes — subject (15-way) and type
  (11-way) — stratified 5-fold CV on the 175 labels; report mean top-1 per axis.
- **Aesthetic:** MLP head per backbone via the `train_aesthetic_head.py` harness;
  Spearman on the AVA holdout.
- **Output:** decision-matrix table → the Track A decision tree above.

### Track B protocol

- **Models:** Florence-2-base-ft (control) · SmolVLM2-500M · SmolVLM2-256M ·
  LFM2.5-VL-450M.
- **Prompt tiers** (drafts; refine before run):
  - *bare:* `"Describe this image."`
  - *instruction:* `"Write one concise, natural caption describing this
    photograph. Output only the caption, no preamble."`
  - *grounded:* `"Facts: a {subject}/{type} photo{, {time_of_day}}{,
    {shutter_class}}{, {aperture_class}}. Visible regions: {region summary}.
    Dominant colors: {colors}. Write ONE natural sentence describing what is
    visible. Use the facts as context but describe the specific subject, action,
    and mood you see. Do not invent names, places, or text. Output only the
    caption."` (grounding fields come from the SceneRecord / extraction cache.)
- **Quality:** blind side-by-side table (model × prompt, source hidden), user
  scores accuracy / richness / fluency / hallucination.
- **Cost:** latency + RSS, dev box (relative) → Yoga (absolute).
- **Hypothesis under test:** smallest model + grounded prompt ≥ Florence-2.

### Provisioning checklist

- SegFormer-b0 ADE20K → custom dual-output INT8 ONNX.
- MobileCLIP-S0 INT8 ONNX (S2 already provisioned).
- SmolVLM2-500M / -256M ONNX (onnx-community); LFM2.5-VL-450M ONNX (LiquidAI).

### SceneRecord schema (shared output; spike + per-region scoring + namer)

```
subject_tag, subject_conf, type_tag, type_conf
region_map[H×W int8], region_coverage{type: ratio}
subject_roles: list[region_type]          # genre-conditional pick of "subject"
per_region: {type: {dominant_color, sharpness, exposure}}
objects: [{class, count, bbox}]           # YOLO
faces: {count, eye_state}                  # YuNet
exif: {focal_class, aperture_class, shutter_class, time_of_day, iso}
aesthetic, master_score, stars             # from scoring
```

Aligns with the R1 passive data-collection plan (per-region sharpness/exposure +
user keep/reject/star decisions logged during R1 scoring to train the R2
region→quality policy).
