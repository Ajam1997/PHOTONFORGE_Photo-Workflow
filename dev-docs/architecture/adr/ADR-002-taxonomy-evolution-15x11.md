# ADR-002 — Genre Taxonomy Evolution to 15 Subjects × 11 Photo Types

**Status:** Accepted (current taxonomy v2.2, 2026-06-20)

## Context

The genre taxonomy churned through four generations in ~5 weeks:

1. **8 flat genres** — the original CLIP text-prompt prototypes
   (`scripts/provision_models.sh` still generates this legacy 8×512 matrix).
2. **16 Subjects × 12 Photo Types** — first two-axis design (the counts
   CLAUDE.md and several ICDs kept citing long after they were wrong).
3. **13 × 11** (v2.0) — axes made fully orthogonal: `person`/`child` merged
   into `people`, `text` → `object`, `night-sky` → `sky`; Type `wildlife`
   removed (it's a subject), Type `landscape` renamed `scenic`.
4. **15 × 11** (v2.1) — `monument` and `waterfall` split out as subjects.
5. **v2.2 rename** — Photo Type `long-exposure` → `motion-blur`
   (effect-first, not method-first), PR #111, with data migration
   `scripts/migrate_long_exposure_to_motion_blur.py`.

## Decision

The runtime lists `genre_router.SUBJECTS` (15) and `genre_router.PHOTO_TYPES`
(11) are the code truth;
[photonforge-labeling-quick-reference.md](../../research/photonforge-labeling-quick-reference.md)
is the **canonical human-facing taxonomy doc**. All other documents point at
those two rather than restating label lists.

## Consequences

- Any taxonomy change ships in one PR with: router lists, quick-reference
  update, IF-3.1, the CLAUDE.md taxonomy line, and a DB/tag migration script
  (see the docs-impact matrix in
  [doc-maintenance-protocol.md](../doc-maintenance-protocol.md)).
- Repeated churn outpaced calibration (~30–50 corrections/class needed);
  further taxonomy changes should be batched and rare — see also
  [ADR-006](ADR-006-per-type-weights-vs-scenerecord.md).
