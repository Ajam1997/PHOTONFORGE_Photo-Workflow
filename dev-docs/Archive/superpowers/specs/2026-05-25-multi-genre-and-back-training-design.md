# Multi-Genre Tagging & Back-Training Design

**Date:** 2026-05-25
**Author:** @architect
**Status:** Approved — implementation pending

**Scope:** FR-1.7.1 (genre back-training) and FR-1.7.2 (multi-genre tagging).
Translates the recommendations in
[`docs/research/2026-05-24-genre-back-training-research.md`](../../research/2026-05-24-genre-back-training-research.md)
into a concrete implementation plan, with design-decision overrides captured
during the 2026-05-25 design discussion.

## Problem

The current genre router classifies 81% of the user's 3,770-image library as
"general". The two functional requirements that address this — FR-1.7.1
(calibration and back-training) and FR-1.7.2 (multi-genre tagging) — are
defined as separate issues but interact. This document locks the joint design.

## Decisions

### D1. `route_genre()` returns a list of genres

`GenreResult` becomes:

```python
@dataclass
class GenreResult:
    genres: list[tuple[str, float]]   # top-3 above 0.15 floor
    distribution: dict[str, float]    # full softmax over GENRES (9-way as of 2026-05-25)
    needs_review: bool                # True when forced to general

    @property
    def primary_genre(self) -> str:
        return self.genres[0][0]

    @property
    def primary_confidence(self) -> float:
        return self.genres[0][1]
```

When no genre clears the 0.15 floor, the router returns
`genres=[("general", 1.0)]` and `needs_review=True`. `needs_review` is the
"this image might need a new genre added" flag — the working genre is still
"general", but the flag tells the correction pipeline to watch for new tags on
this image.

### D2. Five-signal fusion (lands in FR-1.7.2)

```
P(genre) ∝ P_CLIP × P_EXIF × P_YOLO × P_subject_context × P_sharpness_profile
```

Both new signals reuse existing computation:

- `P_subject_context` — computed from `subject_context.faces` (face_count),
  `subject_area_ratio`, and the primary detection's class. Per-genre likelihood
  comes from hand-tuned Gaussians (face_count peaks for portrait/event,
  subject_area_ratio peaks for macro/portrait, etc.).
- `P_sharpness_profile` — computed from the subject/background sharpness ratio.
  Promoted to a new field `SubjectContext.sharpness_contrast` so the router can
  consume it before scoring runs.

`SubjectContext` gains:

```python
sharpness_contrast: float = 0.0   # subject Tenengrad / background Tenengrad
```

Computed once in `build_subject_context()` from a quick Tenengrad on the
subject-mask pixels vs. the background pixels (~20 ms).

### D3. photonforge.db schema additions (per-folder table)

```sql
ALTER TABLE [folder] ADD COLUMN genres TEXT DEFAULT '';
    -- JSON array: [{"g":"wildlife","c":0.87},{"g":"portrait","c":0.62}]
ALTER TABLE [folder] ADD COLUMN primary_genre TEXT DEFAULT '';
    -- top-1 fallback for legacy queries
ALTER TABLE [folder] ADD COLUMN needs_review INTEGER DEFAULT 0;
ALTER TABLE [folder] ADD COLUMN clip_embedding BLOB;
    -- 512-dim float32 cached at score time so correction sync is instant
```

The existing `genre` column is preserved as an alias for `primary_genre`
during the migration window. Old reads continue to work.

`clip_embedding` adds ~2 KB per row — at 7000 photos per cartridge, ~14 MB
total. Acceptable; makes the correction sync command O(N rows) on SQL only,
no model invocation.

### D4. Cartridge-resident `training_weights.db`

Lives at `<cartridge>/training_weights.db`, separate from `photonforge.db`.
Separation is intentional: photonforge.db is per-folder library state,
training_weights.db is the calibration model. They have different
backup/portability semantics — you might copy training weights between
cartridges without copying the photo metadata.

```sql
CREATE TABLE genre_prototypes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL,
    genre TEXT NOT NULL,
    prototype BLOB NOT NULL,        -- numpy float32, 512 dims
    n_corrections INTEGER DEFAULT 0,
    alpha REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now')),
    is_active INTEGER DEFAULT 1,
    UNIQUE(version, genre)
);

CREATE TABLE genre_corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_path TEXT NOT NULL,
    clip_embedding BLOB NOT NULL,
    aux_features BLOB,
    original_genres TEXT NOT NULL,   -- JSON
    corrected_genres TEXT NOT NULL,  -- JSON
    correction_source TEXT DEFAULT 'darktable',
    corrected_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE genre_adapter (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL,
    model_onnx BLOB NOT NULL,
    n_training_samples INTEGER,
    f1_score REAL,
    created_at TEXT DEFAULT (datetime('now')),
    is_active INTEGER DEFAULT 1
);

CREATE TABLE custom_genres (
    name TEXT PRIMARY KEY,
    first_seen_at TEXT DEFAULT (datetime('now')),
    n_examples INTEGER DEFAULT 0,
    promoted INTEGER DEFAULT 0   -- 1 once promoted to a real genre
);
```

### D5. Darktable tag model — flat tags

Multi-genre is expressed in Darktable as multiple flat keywords on the photo:
`wildlife`, `portrait`. **No hierarchical prefix** like `photon|genre|wildlife`.

Two implications:
- The correction-sync pass must distinguish genre tags from arbitrary user
  keywords. We resolve this by maintaining a reference set: every keyword that
  matches an active genre name (built-in or promoted custom) is treated as a
  genre tag. Other tags are ignored.
- Adding a new keyword that doesn't match any known genre on a `needs_review`
  photo registers it as a candidate `custom_genre`.

### D6. Correction promotion threshold

A `custom_genres` row with `n_examples >= 10` becomes eligible for promotion.
The user must explicitly promote it (via the Lua plugin button or CLI). 10 is
the starting threshold — may be raised after we observe noise.

### D7. Per-genre score breakdown — deferred

`master_score` stays a single blended scalar for FR-1.7.2. The richer
per-genre score breakdown is tracked as a separate enhancement
([#77](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/77)) for
later evaluation.

## New CLI surface

```
photo-workflow score                       # populates genres, clip_embedding, needs_review
photo-workflow sync                        # writes flat keywords to Darktable + XMP
photo-workflow correct-genres              # reads Darktable tags → logs corrections
photo-workflow training recalibrate        # re-blend prototypes + retrain LR adapter
photo-workflow training promote --genre X  # promote a custom genre to a real genre
photo-workflow training export --out F     # bundle prototypes+adapter+custom_genres as tarball
photo-workflow training import --in F      # validate and apply imported weights
```

All training commands take `--training-db <path>` defaulting to
`<cartridge>/training_weights.db`.

## Module changes

| Module | Change |
|---|---|
| `scoring_types.py` | `GenreResult` shape; `SubjectContext.sharpness_contrast` |
| `genre_router.py` | Five-signal fusion; top-N output; needs_review flag |
| `subject_context.py` | Compute `sharpness_contrast` once during build |
| `score_fusion.py` | Blend `GENRE_WEIGHTS` across `genres` weighted by confidence |
| `photondb.py` | Schema migration for `genres`, `primary_genre`, `needs_review`, `clip_embedding` |
| `darktable_bridge.py` | Multi-keyword writer + reader (new function `read_darktable_tags`) |
| `pipeline.py` | New `correct-genres` and `training` sub-CLIs |
| **NEW** `training_weights_db.py` | Schema + accessors for `training_weights.db` |
| **NEW** `genre_trainer.py` | Prototype blending, LR adapter training, ONNX export |
| **NEW** `training_io.py` | Tarball export/import for porting weights between cartridges |

## Lua plugin integration

Tracked in [#76](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/76).
Three buttons in the PHOTONForge panel: **Sync Corrections**,
**Recalibrate Genre Model**, **Promote Custom Genre**. Each spawns the
matching CLI command and reports status via Darktable's notification API.

## Implementation order

| Stage | What | Issue |
|---|---|---|
| A | FR-1.7.2 — multi-genre output, 5-signal fusion, schema migration, multi-keyword XMP/Darktable writer | [#67](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/67) |
| B | Extend fixture corpus with genre labels | [#75](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/75) |
| C | FR-1.7.1 — `training_weights.db` schema, prototype blending math, `recalibrate` CLI | [#66](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/66) |
| D | `correct-genres` CLI + Darktable tag reader + `custom_genres` open-set tracking | [#66](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/66) |
| E | LR adapter training + ONNX export + inference blending | [#66](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/66) |
| F | `training export`/`training import` tarball format | [#66](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/66) |
| G | Lua plugin buttons | [#76](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/76) |
| H | Per-genre score breakdown (deferred enhancement) | [#77](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/77) |

## Open items

- **Aux-feature schema for the LR adapter** — 5 dims (face_count,
  subject_area_ratio, sharpness_contrast, focal_length_bucket, animal_class_id)
  is the working set. Final ordering and normalisation locked in Stage E.
- **Recalibration trigger thresholds** — design uses 20 new corrections since
  last calibration as the auto-suggest threshold. May tune after seeing
  actual usage.

## References

- [Research brief](../../research/2026-05-24-genre-back-training-research.md)
- [FR-1.7.1 issue](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/66)
- [FR-1.7.2 issue](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/67)
- [Lua plugin buttons issue](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/76)
- [Per-genre score breakdown enhancement](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/77)
- [Fixture corpus issue](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/75)
