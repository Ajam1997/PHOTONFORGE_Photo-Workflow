# Scoring Methodology Audit — 2026-06-19

**Scope:** `score_fusion.py` and its sub-score producers (`sharpness.py`,
`composition.py`, `exposure.py`, NIMA aesthetic head), end to end through
`pipeline.py`. Motivated by the question: *are we missing an obvious structural
pitfall in scoring the way we did with the product-of-experts tagging fusion?*

**Method:** static read of the fusion + weight profiles; an empirical scan of
the **6,716 already-scored rows** in `photonforge.db` (stored `master_score` +
`sub_scores` JSON); and live tests of the NIMA aesthetic model on real RAWs.

**Verdict:** yes — there is a critical, tagging-style pitfall (a silently
swallowed exception that has neutralized the single most-weighted signal for the
entire life of the feature), plus a broken model behind it, plus several
secondary defects. None of these are visible without measuring, because every
failure degrades *quietly* to a neutral 0.5.

---

## Evidence snapshot (n = 6,716 scored photos)

Master score: min 0.178, **mean 0.525, median 0.530, std 0.119**, max 0.847.
Star distribution: `{1: 194, 2: 2623, 3: 3465, 4: 434, 5: 0}` — **no photo has
ever scored 5 stars**; ~90% land on 2–3.

Per-sub-score spread (flagged where std < 0.05 = effectively constant):

| sub-score | mean | std | note |
|---|---|---|---|
| **aesthetic_clip** | 0.50 | **0.000** | dead constant (see P1) |
| **face_exposure** | 0.50 | **0.000** | sentinel for no-face |
| **expression_proxy** | 0.50 | **0.000** | sentinel for no-face |
| **behavior_proxy** | 0.50 | **0.000** | motion_subject ~never fires |
| **symmetry** | 0.02 | **0.033** | metric effectively dead (see P2) |
| highlight_clip | 0.99 | 0.042 | near-constant (rarely clips) |
| subject_isolation | 0.54 | 0.294 | healthy |
| color_contrast | 0.54 | 0.294 | identical to subject_isolation (P3) |
| sharpness/exposure/composition signals | 0.4–0.6 | 0.16–0.49 | healthy |

---

## Findings (ranked by impact)

### P1 — CRITICAL: the aesthetic signal has never worked. `aesthetic_clip` = 0.5 for every image.

A triple failure, all collapsing to 0.5:

1. **Pipeline bug.** `pipeline.py` (both score paths) calls
   `_run_nima(ctx.image_rgb, …)`, but `SubjectContext` has **no `image_rgb`
   attribute** (it exposes `image_bgr`). Every call raises `AttributeError`,
   which is caught by `except Exception: aesthetic_score = 0.5`. The aesthetic
   model is never reached.
2. **Dead model.** Even when called correctly, the INT8 NIMA model
   (`models/nima_mobilenet_int8/model.onnx`) emits a **uniform `[0.1]×10`
   distribution for every image** (verified on multiple RAWs: raw output sums to
   1.0 but is perfectly flat). Mean bin = 5.5 → `(5.5−1)/9 = 0.5`. The quantized
   model is non-functional regardless of input.
3. **Masking `except`.** A broad `try/except → 0.5` swallowed (1) silently for
   the entire life of the feature. This is the same failure shape as the tagging
   bug (silent fallback neutralizing the primary signal).

**Impact.** `aesthetic_clip` is the **highest-weighted dimension in most genre
profiles** (0.10–0.30; abstract 0.30, still-life 0.22, landscape/sky/seascape
0.20). So **15–30% of every master score is a fixed constant**, and the system
has **zero aesthetic discrimination** — it has been ranking purely on technical
and geometric signals. The constant also compresses the score range and is a
prime cause of P6 (no 5-star photos).

**Proposed fix.**
- Repair the call: give `SubjectContext` an `image_rgb` (it is already computed
  inside `build_subject_context`; expose it as a field/cached property) and pass
  that to `_run_nima`. Single source of truth, no per-call conversion.
- Replace the dead NIMA. `models/clip_aesthetic_head/` is already vendored (a
  CLIP-embedding → aesthetic regressor) and is the likely working replacement —
  it can reuse the CLIP embedding we already compute, so it's near-free at
  runtime. **Gate on a spike that proves it returns varying, sensible scores**
  before wiring it in; if it too is degenerate, re-quantize NIMA from FP32 or
  drop in another small aesthetic head.
- Make the failure loud: log-once (or surface) when the aesthetic model errors or
  returns a degenerate constant, instead of silently defaulting.

**Effort:** M. **Risk:** low for the call fix; the model swap needs verification.

---

### P2 — `symmetry` is effectively dead, yet heavily weighted.

Measured mean 0.02 / std 0.033 across 6,716 images. Root cause in
`composition._symmetry_score`: it mirrors ORB **keypoint coordinates** and then
recomputes descriptors **on the original (un-mirrored) image** before matching.
Descriptors at a mirrored coordinate describe the original local patch, not its
mirror, so genuine bilateral symmetry rarely produces matches — the score is
~0 almost always. Meanwhile `symmetry` is weighted **0.20 for architecture,
0.15 for cityscape and aerial**, so those genres are systematically dragged down
by a near-zero term.

**Proposed fix.** Recompute the metric correctly — flip the **image** (or one
half) horizontally and compare to the other half (descriptor match on the
flipped image, or SSIM/feature correlation between halves). If, after fixing,
symmetry is genuinely sparse in this library, also down-weight it for the three
architecture-family genres. **Effort:** S–M. **Risk:** low.

---

### P3 — `color_contrast` is a fake signal (literal alias of `subject_isolation`).

`_build_sub_score_dict` sets `scores["color_contrast"] = composition.subject_isolation`.
No color information is involved. Five genres weight **both** as if independent →
double-counting subject isolation: plant **0.35** effective, food/object/macro/
still-life **0.25**.

**Proposed fix.** Implement a real colorfulness metric (Hasler–Süsstrunk
colorfulness is ~5 lines on the RGB channels and is a genuinely useful aesthetic
dimension for plant/food/object/abstract) and feed it to `color_contrast`. This
turns a double-count into a real independent signal. Alternative (cheaper): drop
`color_contrast` and fold its weight into `subject_isolation`. **Effort:** S.
**Risk:** low.

---

### P4 — dead/sentinel proxy weights waste discrimination capacity.

- `behavior_proxy` = 1.0 iff `motion_subject` else 0.5 — almost always 0.5;
  weighted 0.10–0.15 for people/pet/wildlife. Near-useless.
- `expression_proxy` = 0.5 with no face (crude eye-variance heuristic otherwise);
  **documentary weights it 0.20** and people 0.18.
- `face_exposure` = 0.5 with no face (legitimate sentinel).

When a sub-score is "not applicable," injecting a constant 0.5 silently consumes
weight mass that real signals could use, flattening the achievable range.

**Proposed fix (structural).** When a sub-score is a not-applicable sentinel for
an image, **exclude its weight and renormalize** the remaining profile weights
to sum to 1, rather than scoring a constant 0.5. Separately, consider dropping
`behavior_proxy` (and redistributing) and replacing `expression_proxy` with a
real open-eyes/expression check or removing it from no-face contexts. **Effort:**
M. **Risk:** medium (changes scores; needs re-measurement).

---

### P5 — structural: master is a weighted SUM, not `min(technical, aesthetic)`.

`_compute_master_score` = `Σ (0.5·subject_w + 0.5·type_w) · sub_score`. There is
no technical *floor*. Hard gates only catch extremes (`motion_global` with
subject < 0.2; `misfocused` with eye_region < 0.15; all eyes closed). Between
"hard reject" and "pass", a soft or mildly misfocused **non-face** shot loses
only `blur_type_penalty` weight (~5–15%) and still scores mid-range. This is the
stage-6 `min(technical, aesthetic)` design that was never built.

**Proposed fix (follow-up, after P1).** Split scoring into a `technical_gate`
(sharpness/exposure/blur must-pass aggregate → [0,1]) and an `aesthetic_weighter`
(genre-weighted aesthetic/composition → [0,1]); `master = min(technical,
aesthetic)` (or a soft-min). This only becomes meaningful **once the aesthetic
axis actually varies (P1)** — otherwise `min(technical, 0.5)` just caps
everything at 0.5. **Effort:** M–L. **Risk:** medium.

---

### P6 — score compression / star miscalibration.

mean 0.525, std 0.119, zero 5-star, ~90% in 2–3 stars. Largely an artifact of the
dead constants (P1/P2/P4) pulling every score toward the middle, combined with
fixed star thresholds (0.3 / 0.5 / 0.75) that the compressed range can't reach.

**Proposed fix.** Re-measure the distribution after P1–P4, then either recalibrate
the thresholds or — better for a culling tool — rank **relative to the shoot**
(per-folder/genre percentiles) so stars mean "top X% of this batch" rather than an
absolute the model can't hit. **Effort:** S. **Risk:** low.

---

## Cross-cutting recommendation: a model self-check

Both this audit and the earlier tagging regression trace to the same root cause:
**a model silently degrading to a neutral default, hidden by a broad `except`.**
Recommend a startup/`provision` self-check that runs each model on a fixed test
image and asserts the output is **non-degenerate** (varies across two distinct
inputs / isn't a uniform distribution). That single check would have caught the
no-CLIP tagging failure *and* the dead NIMA here.

## Suggested sequencing

1. **P1** — fix the call + swap to a verified-working aesthetic head (unblocks
   everything; restores the aesthetic axis).
2. **P3** (real colorfulness) and **P2** (symmetry) — cheap, independent, remove
   two systematic distortions.
3. **P4** — weight renormalization for not-applicable sentinels.
4. **Re-measure** the master/star distribution.
5. **P5** — build the `min(technical, aesthetic)` gate on the now-working axes.
6. **P6** — recalibrate stars / move to relative ranking.
7. Add the **model self-check** (cross-cutting) so this class of bug fails loud.

## Appendix — what is healthy

To be clear about scope: the technical and geometric signals are working —
`subject_sharpness`, `eye_sharpness`, `sharpness_contrast`, `exposure_overall`,
`dynamic_range`, `zone_entropy`, `composition_rot`, `leading_lines`,
`negative_space`, `subject_isolation`, `balance`, `blur_type_*`, `motion_tolerance`
all show healthy spread (std 0.16–0.49). Within-genre **technical** ranking is
therefore meaningful today; what's missing is the **aesthetic** half and the
technical **veto**.

---

## Addendum (2026-07-10): resolution status

All findings in this audit have since been addressed. Recorded here so
readers do not re-chase fixed bugs; the body above is unchanged history.

| Finding | Status | Fixed by |
|---|---|---|
| P1 — dead `aesthetic_clip` (constant 0.5) | **Fixed** — CLIP aesthetic head trained and wired; the NIMA placeholder was removed | PR #102 |
| P2 — dead `symmetry` | **Fixed** (earlier symmetry rework) | pre-#111 |
| P3 — `color_contrast` alias of `subject_isolation` | **Fixed** — real colorfulness signal | consolidation series |
| P4 — dead/sentinel proxy weights | **Fixed** — not-applicable signals are dropped and remaining weights renormalized (no constant fill) | scoring fixes |
| P5 — weighted sum, no technical veto | **Fixed** — hard-reject gates in `score_fusion.py` floor technically unusable photos | scoring fixes |
| P6 — score compression / star miscalibration | **Fixed** — per-shoot percentile star rating; hard-rejects excluded from the percentile pool | #115 |

Related completions: `motion_subject` (gradient-anisotropy motion
classification) and faces wired into `fuse_scores` landed via PRs #114/#115.
The cross-cutting **model self-check** recommendation is **partially**
implemented: the aesthetic head is self-checked; the other model loads are not.

**Next action:** re-run this audit's scoring methodology measurement on the
Yoga corpus post-fix and compare against the June baseline (needs hardware).

via: @systems_lead
