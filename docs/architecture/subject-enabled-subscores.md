# Subject → enabled_subscores Table

**Status:** draft — input for Step 2 (region_router implementation)
**Date:** 2026-05-26
**Companion to:** [scoring-module-contracts.md](scoring-module-contracts.md)

## Purpose

`RegionSpec.enabled_subscores: frozenset[str]` is an optimization hint
emitted by `region_router` and consumed by the `sub_scores/*` modules. It
tells each sub-score family which keys are sensible to compute given the
regions this Subject provides.

A sub-score *not* in this set MUST be returned as `None` by the relevant
module — it does not mean "compute and weight zero." This avoids wasted
compute and prevents nonsensical numbers (eye-region sharpness for a
landscape, face exposure for a night-sky shot) from leaking into the flat
dict used by XMP / debugging.

Note: this is **not** a weight gate. `aesthetic_weighter` still controls
weights based on Type. A sub-score that is `None` simply gets dropped from
the weighted sum and the remaining weights re-normalized.

## Universal set (enabled for every Subject)

These compute on every image because they have no region dependency:

```
sharpness.subject, sharpness.background, sharpness.sharpness_contrast,
sharpness.blur_type, sharpness.overall

exposure.zone_entropy, exposure.zone_diversity, exposure.dynamic_range,
exposure.clipping_shadows, exposure.clipping_highlights,
exposure.midtone_density, exposure.style, exposure.style_confidence,
exposure.overall

composition.rule_of_thirds, composition.symmetry, composition.leading_lines,
composition.negative_space, composition.subject_isolation,
composition.balance, composition.color_contrast, composition.overall

aesthetic.nima_mean, aesthetic.nima_std, aesthetic.clip_aesthetic
```

The Subject-specific additions below are layered ON TOP of the universal
set. The table only lists what each Subject adds.

## Subject-specific additions

| Subject     | Adds                                                                                   | Rationale                                                                 |
|-------------|----------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| person      | `sharpness.eye_region`, `exposure.face_exposure`, all `faces.*`                        | Single face is the scoring focus; eye-sharpness is the dominant signal    |
| people      | `sharpness.eye_region`, `exposure.face_exposure`, all `faces.*`                        | Multiple faces; expression_proxy aggregates across all detected           |
| child       | `sharpness.eye_region`, `exposure.face_exposure`, all `faces.*`                        | Same routing as person; calibration prototypes differ but enabled set same |
| wildlife    | `sharpness.eye_region`                                                                 | Animal eye via animal_head_bbox routing; no human-face exposure check     |
| pet         | `sharpness.eye_region`                                                                 | Same as wildlife; pet vs. wildlife is a prototype/EXIF distinction        |
| plant       | —                                                                                      | Universal set only; subject_isolation and color_contrast carry the weight |
| landscape   | `sharpness.front_to_back`                                                              | Depth-binned sharpness via depth_bins; depth model runs                   |
| seascape    | `sharpness.front_to_back`                                                              | Same depth routing as landscape                                           |
| cityscape   | `sharpness.front_to_back`                                                              | Same depth routing; symmetry and leading_lines do heavy lifting via Type   |
| building    | —                                                                                      | Universal; architecture is a Type concern, not a Subject one              |
| vehicle     | —                                                                                      | Universal; motion handling is a Type (action / long-exposure) concern    |
| food        | —                                                                                      | Universal; color_contrast and subject_isolation dominate                  |
| object      | —                                                                                      | Universal; "still life" is the Type pairing that adds composition weight  |
| text        | —                                                                                      | Universal; edge sharpness across the frame is captured by sharpness.subject |
| night-sky   | —                                                                                      | Universal MINUS face_exposure / eye_region (already excluded)             |
| abstract    | —                                                                                      | Universal; no subject-specific regions exist by definition                |

## Cross-cutting rules

1. **`sharpness.eye_region`** is enabled iff the Subject implies an eye to
   focus on — humans (`person`, `people`, `child`) via face landmarks, and
   animals (`wildlife`, `pet`) via the YOLO head bbox.
2. **`exposure.face_exposure`** is enabled iff the Subject implies *human*
   skin in frame — animal fur exposure is not the same scoring concern and
   is captured by `sharpness.subject` exposure-side via `exposure.overall`.
3. **`faces.*`** (all face sub-scores including `closed_eyes_all`) is
   enabled iff Subject is one of `person`, `people`, `child`. For
   other Subjects, detected faces are incidental — the closed-eyes hard
   gate must NOT fire just because a tourist appears in a landscape.
4. **`sharpness.front_to_back`** is enabled iff Subject is one of
   `landscape`, `seascape`, `cityscape`. These are the only Subjects for
   which `region_router` invokes the depth estimator.
5. **Aesthetic sub-scores are always enabled** because NIMA and
   CLIP-aesthetic are genre-agnostic by design. Subject can never disable
   them; Type weighs them differently.

## What this implies for hard gates

The technical_gate's `enabled_for_subject` field on each `GateCheck` is
derived directly from this table:

| Hard gate              | Enabled iff Subject ∈                          |
|------------------------|------------------------------------------------|
| `all_eyes_closed`      | `{person, people, child}`                      |
| `motion_global_blur`   | universal                                       |
| `misfocused`           | universal                                       |
| `severe_clipping`      | universal MINUS `{night-sky, abstract}` (intentional darkness/extremes are common) |
| `missed_eye_focus`     | `{person, people, child, wildlife, pet}`        |
| `missed_depth_focus`   | `{landscape, seascape, cityscape}`              |

A gate firing on a Subject where it is not enabled is a contract violation
and should fail in CI via the per-Subject gate-trace tests.

## Open question for @architect review

Should `sharpness.eye_region` for `wildlife`/`pet` use a separate enum
value (e.g. `sharpness.animal_eye_region`) to make the region source
explicit, or is one field with the source recorded in `RegionSpec`
sufficient? Current contract picks the latter for simplicity, but a
separate field would make the audit trail clearer when the correction
loop replays sub-scores.

## Implementation note

The frozenset returned by `region_router.route()` is constructed by
unioning a per-Subject `frozenset` (defined as module-level constants)
with the universal set. This makes the routing decision a pure data
lookup — no conditional logic in `region_router`'s hot path beyond the
Subject tag string match.
