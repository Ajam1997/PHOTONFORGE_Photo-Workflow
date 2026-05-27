# Stage-Based CLI for Batch Photo Processing

**Date:** 2026-05-12
**Status:** Approved
**Author:** Alex Meyer
**Scope:** Enhance `photo-workflow` CLI from a monolithic single command to a staged subcommand group with manifest-based checkpointing, enabling batch processing of 7000+ photos with resume capability.

## Motivation

The current `photo-workflow` CLI runs the entire pipeline in one shot with no progress reporting, no stage skipping, and no resume. At 7000 photos, Florence-2 naming alone takes ~5 hours. A crash at photo 5000 means starting over. The Tauri sidecar CLI has some of these features but outputs JSON-lines for the GUI and is tightly coupled to rsync-based SD card ingest.

The user needs to:
1. Run stages independently (dedup, score, review results, then name)
2. Resume any stage after a crash without re-processing completed photos
3. See progress with ETA during long-running stages
4. Test the full pipeline on the current machine (not the Yoga 910) with photos already on an SSD

## Command Structure

`photo-workflow` becomes a `click.Group` with these subcommands:

```
photo-workflow scan   --source /path/to/photos [--manifest manifest.jsonl] [--recursive]
photo-workflow dedup  --manifest manifest.jsonl
photo-workflow score  --manifest manifest.jsonl [--resume] [--force]
photo-workflow name   --manifest manifest.jsonl --model-dir models/florence2_int8 [--resume] [--force]
photo-workflow sync   --manifest manifest.jsonl --db /path/to/library.db [--dry-run]
photo-workflow status --manifest manifest.jsonl
```

### Subcommand Details

**`scan`** — Discover photos and create the manifest.
- Walks source directory for supported extensions: `.cr3`, `.arw`, `.nef`, `.dng`, `.raf`, `.jpg`, `.tiff` (case-insensitive)
- Default: non-recursive (flat directory). `--recursive` enables `rglob`.
- Extracts EXIF timestamps using the same EXIF logic as `grouping.py` (needed for session grouping in dedup)
- Does NOT copy files — assumes photos are already at their target location
- Creates one JSONL line per photo
- Output: `Scanned 7042 photos → manifest.jsonl`

**`dedup`** — Group by session, flag duplicates.
- Reads manifest, runs `cluster_sessions()` then `deduplicate()`
- Updates each line with `session_id` and `is_duplicate`
- Skips photos already through dedup stage
- Output: `Grouped into 47 sessions, flagged 312 duplicates`

**`score`** — Sharpness, composition, exposure scoring.
- Only processes non-duplicate photos
- `--resume`: skips photos with `score` in `stages_completed`
- `--force`: re-scores all photos regardless
- Progress counter with ETA
- Writes manifest checkpoint every 50 photos (crash-safe)
- Output: `Scored 6730 photos (312 duplicates skipped)`

**`name`** — Florence-2 semantic naming.
- Only processes non-duplicate, scored photos
- `--resume` / `--force` same as score
- Renames files on disk, updates `path` in manifest
- Progress counter with ETA (rolling average per-image time)
- Writes manifest checkpoint every 50 photos (crash-safe)
- Output: `Named 6730 photos`

**`sync`** — XMP sidecar writing + Darktable library.db upsert.
- Processes all non-duplicate photos
- `--dry-run`: prints what would happen without touching DB
- Output: `Wrote 6730 XMP sidecars, upserted 6730 DB rows`

**`status`** — Read-only summary of manifest state.
- Prints: total photos, per-stage completion counts, duplicate count, error count, peak RSS from last run

### Stage Prerequisites

Each stage enforces that prior stages are complete:
- `dedup` requires `scan`
- `score` requires `dedup`
- `name` requires `score`
- `sync` requires `name`

If prerequisites are not met:
```
Error: 7042 photos have not been through 'dedup'. Run 'photo-workflow dedup' first.
```

## Manifest Format

JSONL file (one JSON object per line). Each line represents one photo:

```json
{"path": "/ssd/photos/IMG_1234.CR3", "exif_timestamp": "2026-03-15T14:23:01", "session_id": "", "is_duplicate": false, "sharpness": null, "composition": null, "exposure": null, "semantic_name": null, "error": null, "stages_completed": ["scan"]}
```

### Fields

| Field | Type | Set by | Description |
|-------|------|--------|-------------|
| `path` | string | scan, name | Absolute path to photo. Updated by `name` after rename. |
| `exif_timestamp` | string\|null | scan | ISO 8601 EXIF capture time. Null if no EXIF. |
| `session_id` | string | dedup | Session cluster ID from `cluster_sessions()`. |
| `is_duplicate` | bool | dedup | True if flagged as duplicate by dHash. |
| `sharpness` | float\|null | score | Laplacian variance score. |
| `composition` | float\|null | score | Spectral saliency + rule-of-thirds score. |
| `exposure` | float\|null | score | Shannon entropy of 11-zone luminance histogram. |
| `semantic_name` | string\|null | name | Slug from Florence-2 caption. |
| `error` | string\|null | any | Last error message. Cleared on successful retry. |
| `stages_completed` | list[str] | all | Stages this photo has passed: `scan`, `dedup`, `score`, `name`, `sync`. |

## Resume & Crash Safety

### Checkpoint Strategy
- Load full manifest into memory at stage start
- Process photos, updating in-memory list
- Flush to `manifest.jsonl.tmp` every 50 photos and on clean exit
- Atomic rename via `os.replace()` to `manifest.jsonl`
- On crash: lose at most 50 photos of progress

### `--resume` Behavior
- Checks `stages_completed` per photo, skips completed ones
- Prints: `Resuming: 2999 already scored, 3731 remaining`
- Without `--resume` on already-completed manifest: error with guidance

### `--force` Behavior
- Reruns the stage on all photos regardless of `stages_completed`
- Use case: changed model weights, want to re-score

### Per-Photo Atomicity
- A photo either completed a stage or it didn't
- No partial-stage state — crash mid-photo means retry that photo

## Progress Output

Simple in-place counter using `\r` (no external dependency):

```
[score] 2341/6730 (34.8%) | 1.2 img/s | ETA 61m | RSS 842MB
```

Components: stage name, count/total, percentage, throughput, ETA, memory usage.

### Verbosity Flags
- Default: progress counter + final summary
- `--verbose`: per-photo logging (path, scores, timing)
- `--quiet`: final summary only

## Error Handling

### Per-Photo Errors
- Corrupt file, EXIF parse failure, ONNX inference error → log warning, continue
- Failed photo gets `"error": "reason"` in manifest
- Stage NOT added to `stages_completed` — `--resume` will retry
- Final output: `Completed 6728/6730. 2 errors (see manifest for details).`

### Stage-Level Errors
- Missing prerequisite stage → clear error message with guidance
- Missing model directory → error before processing starts
- Missing Darktable DB → error before processing starts

## Code Changes

### Modified Files
- `src/photo_workflow/pipeline.py` — Refactor `main()` from `click.command` to `click.Group` with subcommands. `AnalysisPipeline` class and `PipelineConfig`/`PhotoRecord`/`PipelineSummary` dataclasses remain unchanged (used internally by subcommands).

### New Files
- `src/photo_workflow/manifest.py` — Manifest read/write/checkpoint logic. Functions: `create_manifest()`, `load_manifest()`, `save_manifest()`, `checkpoint()`.
- `src/photo_workflow/progress.py` — Progress counter rendering. Class: `ProgressTracker` with `update()`, `finish()` methods.
- `tests/test_manifest.py` — Unit tests for manifest CRUD, checkpoint, atomic write.
- `tests/test_cli_stages.py` — Integration tests for subcommand flow with small fixture set.

### Unchanged
- All analysis modules (`grouping.py`, `dedup.py`, `sharpness.py`, `composition.py`, `exposure.py`, `naming.py`, `darktable_bridge.py`) — these are called by the subcommands but not modified.
- `sidecar_cli.py` — left untouched; may be deprecated later.
- `pyproject.toml` — `photo-workflow` entry point still points to `pipeline:main`, no change needed.

## Non-Goals
- No changes to the analysis modules themselves
- No GUI or TUI — terminal progress counter only
- No parallel/multi-process execution (single-threaded, sequential)
- No changes to the Darktable bridge logic
- No network/remote execution — this runs locally
