# Release 1 — Scope & Pre-Docs Readiness

**Decision (2026-06-19):** Release 1 is the **Darktable-plugin-driven workflow**. The
fully-automatic appliance behaviors (SD-insert auto-ingest, auto-eject, no-SSD
dialog) are **deferred to v2** and documented as manual steps for v1.

## R1 user workflow (the happy path the docs will describe)
1. Connect the PHOTON SSD cartridge; insert the SD card.
2. Open Darktable → PHOTONForge panel. Set SD path + destination (SSD) path.
3. **Run** → ingest (SD→SSD staging) → import → dedup → score → name.
4. Review in Darktable: star ratings, color labels, reject flag, `photon|subject|*`
   / `photon|type|*` tags. (Legend: blue=5★, green=4★, none=2–3★, yellow=1★,
   red=duplicate, reject=technically broken; purple reserved for the user.)
5. **Sync Tags → DT** if scoring was run from the CLI.
6. Improve the model: **✨ Suggest Training Set** → label the ~20 tagged
   `photon|train_candidate` frames → **Collect Corrections** → **Recalibrate**.
   (**↻ Refresh Review Flags** recomputes needs_review without a re-score.)
7. Manually safe-eject the SSD when done.

## In scope for R1
- Staged pipeline via the plugin: UN-010/011/012/013/014, UN-020, UN-021,
  UN-040 (SD→SSD staging), UN-050–054 (CLI stages, state, resume, progress, errors).
- Genre-aware scoring + per-shoot ratings + margin-based needs_review + reject flag
  (this PR's work).
- Training/review loop: suggest-training-set, collect-corrections, recalibrate,
  refresh-review.
- SSD as portable library (UN-031); manual safe-eject (UN-032).
- NFR-2.1 offline runtime, NFR-2.2 RSS/CPU budget, NFR-2.3 library on SSD.

## Deferred to v2 (documented as manual in v1)
- UN-030 auto-ingest on SD insertion (udev).
- UN-041 auto-eject + notify SD after transfer.
- NFR-2.4 no-SSD zenity dialog.
- UN-022 genre-enriched semantic filenames.

## Pre-docs checklist (gates the user docs)

| # | Item | Maps to | Owner | Status |
|---|---|---|---|---|
| 1 | **Freeze scoring; clean re-score a reference shoot** as the behavior baseline | this PR | engineer | TODO |
| 2 | **E2E happy-path on the Yoga 910** (SD+SSD → Run → review → sync → train loop) | UN-010–014/020/021/040/031/032/050–054 → VALIDATED | validation | TODO |
| 3 | **Performance KPMs on i7-7500U** — KPM-1.2 ≤2.5s/img, **KPM-1.3 RSS ≤1.5GB**, KPM-1.5 ≥10/min, KPM-1.9 CPU ≤80% (scoring got heavier: CLIP adapter + AVA aesthetic MLP + min-gate) | KPM dashboard | verification | TODO — highest risk |
| 4 | **Install/provisioning from scratch** — provision models (incl. clip_aesthetic_head; remove dead NIMA placeholder), venv on PATH, DT plugin install, models_path pref; repeatable | UN-001, UN-003 | devops | TODO |
| 5 | **Data-integrity smoke** — several eject cycles, no SQLite corruption | KPM-1.4 | devops | TODO |
| 6 | **Capture new features as UN entries** — genre classification, aesthetic rating, per-shoot stars, needs_review, training loop (currently untracked; UN-022 still DEFINED) | living-user-needs | architect | TODO |

## Acceptable-as-is for R1 (document, don't block)
- Naming accuracy: Florence-2 captions are sometimes semantically off but non-trivial
  (KPM-1.7 metric passes); fine for filenames in v1.
- needs_review margin (0.02) and the per-shoot rating thresholds — reasonable defaults;
  tune later from user feedback.
- Aesthetic head domain shift (rates casual RAWs below curated AVA) — handled by the
  per-shoot relative star ranking; fine for v1.

## Recommended order
Scope (done) → #1 freeze + re-score → #2/#3 E2E + KPMs on the Yoga → #4 provisioning →
#5 integrity smoke → #6 UN entries → **then write the install + user guide** against the
validated workflow.

## Current state snapshot
Functionality for the R1 plugin flow is built and unit-tested (381 pass). The gap is
**validation**: 0 UNs are VALIDATED and all 10 KPMs are untested on target hardware. None
of #1–#6 require new features — they are verification/packaging of what exists.
