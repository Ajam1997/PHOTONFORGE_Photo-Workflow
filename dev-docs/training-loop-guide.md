# Training Loop — Operator Guide

How to teach PHOTONForge your genre judgments from inside Darktable. The
buttons live on the PHOTONFORGE panel's **Training** tab
(`lua/photonforge/panel.lua`); each one shells out to a `photo-workflow`
command (`lua/photonforge/runner.lua` shows the exact invocation via the
developer-mode "Show resolved command").

## The cycle at a glance

```
score a folder
   └─ frames tagged photon|subject|* + photon|type|* (+ photon|needs_review)
✨ Suggest Training Set        -> ~20 frames tagged photon|train_candidate
   you: fix subject/type tags on those frames in Darktable
1 ⇅ Collect Corrections        -> corrections harvested into the corpus + DB
2 ★ Recalibrate                -> new prototype version + adapter retrain
   rescore (or ↻ Full Correction Loop does all three)
↻ Refresh Flags                -> recompute needs_review, no re-score
```

## The buttons, what they run, and where data lands

| Panel button | Command | What it does |
|---|---|---|
| ✨ Suggest Training Set | `photo-workflow suggest-training-set` | Clusters the CLIP embeddings of this folder's `needs_review` frames (`src/photo_workflow/active_learning.py`) and picks ~20 diverse representatives; the applicator tags them `photon|train_candidate`. Label just these — each one stands in for a cluster of similar uncertain frames. |
| *(you, in Darktable)* | — | Filter to `photon|train_candidate`; set the correct `photon|subject|<x>` and `photon|type|<y>` (exactly one each — decision flows in [photonforge-labeling-quick-reference.md](research/photonforge-labeling-quick-reference.md)). |
| 1 ⇅ Collect Corrections | `photo-workflow training collect-corrections` | Reads the `photon\|*` tags back out of Darktable's `library.db`, diffs them against what `photonforge.db` recorded, and: appends full `(subject, photo_type)` labels to the corpus JSONL; logs type-tag changes to the secondary-feedback JSONL; updates `photonforge.db` genres (confidence 1.0); writes the corrected-files manifest used by `rescore`. After Recalibrate, the runner clears stale `photon\|train_candidate` tags. |
| 2 ★ Recalibrate | `photo-workflow training recalibrate` | Blends the hardcoded CLIP prototypes with per-genre correction centroids (α shrinks as corrections accumulate; `--min-samples` 10 per genre) and writes a **new version** to `training_weights.db`. Then retrains the **learned linear adapter** (the primary classifier) on all labeled embeddings — needs ≥ 10 labeled frames with embeddings, prints per-axis CV accuracy. |
| rescore (in ↻ Full Correction Loop) | `photo-workflow score --only-files <manifest> --skip-genre` | Re-scores just the corrected images, preserving their (now human-set) genres and recalculating ratings; falls back to `--force` (whole folder) when no manifest exists. Picks up the cartridge's `training_weights.db` automatically. |
| ↻ Full Correction Loop | collect-corrections → recalibrate → rescore | The three steps above in sequence. |
| ↻ Refresh Flags | `photo-workflow refresh-review` | Recomputes `needs_review` from the **cached** CLIP embeddings (no image re-decode) with the current adapter, updates the DB, and re-emits records only for frames whose flag flipped, so the applicator detaches stale `photon\|needs_review` tags. Use after a recalibrate or a review-logic change instead of a full re-score. |
| ↥ Sync Tags | `photo-workflow sync-tags` | Pushes genres from `photonforge.db` into Darktable — only needed when scoring ran from the CLI with the plugin closed. |

CLI-only pieces:

- `photo-workflow training train-adapter` — explicit adapter training run
  (same math as the recalibrate tail, with `--cv-folds` control).
- `photo-workflow training bootstrap-aesthetic-weights` — one-time seeding of
  the `aesthetic_weights` table from the code defaults (see
  [scoring-architecture.md §4](architecture/scoring-architecture.md)).
- `scripts/label_corpus.py` — Tk bulk-labeling tool (buttons + keyboard
  shortcuts, resume-safe) for building the corpus outside Darktable.

## Where the data lives

All portable state rides the cartridge root (the Destination folder's
parent), unless overridden by the panel's "Corpus JSONL" preference:

| File | Content |
|---|---|
| `<cartridge>/genre_labels.jsonl` | the correction corpus — one JSON per label: filename, subject, photo_type, source_folder, labeler, timestamp, `correction_of` |
| `<cartridge>/secondary_feedback.jsonl` | type-tag add/remove feedback events |
| `<cartridge>/training_weights.db` | versioned model state: `genre_prototypes`, `genre_adapter_linear`, `aesthetic_weights` (each row `is_active`-flagged; see `src/photo_workflow/training_weights_db.py`) |
| `<cartridge>/photonforge.db` | per-frame scores, genres JSON, and the cached CLIP embeddings the trainer reads |
| `src/photo_workflow/data/genre_weights.db` | bundled baseline weights used when no cartridge training DB exists |
| `%TEMP%/photonforge_corrected_files.txt` | transient manifest from collect-corrections → consumed by rescore |

CLI defaults (dev use, no cartridge): `corpus/genre_labels.jsonl` and
`corpus/secondary_feedback.jsonl` under the repo root.

## When to recalibrate

- After each labeling session of Suggest-Training-Set candidates (~20 frames)
  — the adapter retrains from 10 labeled embeddings up, and the margin-based
  `needs_review` rate is the feedback signal: run **Refresh Flags** afterward
  and watch the flagged count drop.
- After correcting systematic misroutes you noticed while culling (collect →
  recalibrate → the loop's targeted rescore handles just those frames).
- Prototype re-estimation skips genres with fewer than `--min-samples` (10)
  corrections — sparse genres keep the hardcoded prototype until they
  accumulate labels, which is fine.

## Rollback

Every Recalibrate writes a new version and deactivates the previous rows, so
history stays in `training_weights.db`.
`training_weights_db.rollback_to_version(conn, version)` reactivates a prior
version — **with a known limitation** (2026-07-08 full-codebase review,
finding #24, still open per its resolution addendum):

- it only flips rows whose `version` equals the target exactly — a genre whose
  latest prototype predates the target version is left with *no* active row;
- it touches `genre_prototypes` only — the learned adapter and the
  `aesthetic_weights` profiles are **not** rolled back, so a rollback can
  leave prototypes and adapter out of step.

Until that's fixed, the reliable "rollback" is forward: re-run Recalibrate
against the corpus as of the state you want (the corpus JSONL is append-only,
so trimming it to a timestamp and recalibrating reproduces any past state).
