# Ingest Pipeline — Full Pipeline with Stage Controls

## Goal

Extend the Ingest tab to run the full PHOTONForge analysis pipeline (not just file copy), with per-stage checkboxes the user can toggle. Settings persist between sessions. After copy completes, the SD card is automatically ejected so the user can resume shooting while the remaining stages process in the background.

---

## Pipeline Stages

| Stage | Checkbox | Default | Notes |
|-------|----------|---------|-------|
| Copy | — (locked) | always on | rsync SD → SSD, streams per-file progress |
| Deduplication | ✓ | on | dHash near-duplicate removal (Hamming ≤ 2) |
| Scoring | ✓ | on | sharpness + composition + exposure, one checkbox |
| AI Naming | ✓ | on | Florence-2-base-ft INT8 ONNX, slowest stage |
| Darktable sync | ✓ | on | XMP sidecar write + library.db upsert |

Grouping (`cluster_sessions`) runs internally before dedup and is not exposed as a checkbox — it is a prerequisite for dedup and fast enough to always run.

---

## Sidecar Changes (`ingest` command)

### New flags

```
--skip-dedup        skip deduplication
--skip-scoring      skip sharpness/composition/exposure scoring
--skip-naming       skip Florence-2 AI naming
--skip-darktable    skip XMP write + DB sync
```

### Execution sequence

1. rsync copy (per-file `progress` events, `step: "copying"`)
2. Emit `{"type": "stage_done", "stage": "copy", "copied": N}`
3. Resolve SD block device from `/proc/mounts`, call `udisksctl power-off -b <device>`
4. Emit `{"type": "sd_ejected"}`
5. `cluster_sessions()` — internal, no event
6. If not `--skip-dedup`: run `deduplicate()`, emit per-file progress (`step: "dedup"`), emit `stage_done dedup`
7. If not `--skip-scoring`: run sharpness/composition/exposure per non-duplicate file, emit per-file progress (`step: "scoring"`), emit `stage_done scoring`
8. If not `--skip-naming`: run `generate_name()` per non-duplicate file, emit per-file progress (`step: "naming"`), emit `stage_done naming`
9. If not `--skip-darktable`: run `sync_to_darktable()`, emit `stage_done darktable`
10. Emit `done` with full summary

### New event shapes

```json
{"type": "sd_ejected"}

{"type": "stage_done", "stage": "copy",       "copied": 143}
{"type": "stage_done", "stage": "dedup",      "dupes_found": 12}
{"type": "stage_done", "stage": "scoring",    "scored": 131}
{"type": "stage_done", "stage": "naming",     "named": 131}
{"type": "stage_done", "stage": "darktable",  "xmp_written": 131, "db_upserted": 131}
```

Existing `progress` and `done` event shapes are unchanged. `done` summary gains `dupes_found`, `named`, `xmp_written`, `db_upserted` populated from stage results.

### SD ejection

```python
def _eject_sd(mount_point: str) -> None:
    # Resolve block device from /proc/mounts
    device = None
    for line in Path("/proc/mounts").read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == mount_point:
            device = parts[0]
            break
    if not device:
        return
    # Get parent disk (e.g. /dev/mmcblk0p1 -> /dev/mmcblk0, /dev/sda1 -> /dev/sda)
    disk = re.sub(r'p?\d+$', '', device)
    subprocess.run(["udisksctl", "power-off", "-b", disk], check=False)
```

`udisksctl` does not require sudo. Failure is non-fatal — processing continues regardless.

---

## Frontend Changes

### Settings store (`src/stores/pipeline.ts` — new file)

```ts
// Persisted to localStorage under key "photon.pipeline"
interface PipelineSettings {
  dedup: boolean;
  scoring: boolean;
  naming: boolean;
  darktable: boolean;
}
// Defaults: all true
```

Svelte writable store that reads from `localStorage` on init and writes back on every change.

### `sidecar.ts` additions

- Add `StageDoneEvent` interface with discriminated union per stage
- Add `SdEjectedEvent` interface  
- Add both to `SidecarEvent` union
- Update `runIngest()` to accept stage-skip flags and pass them as CLI args

### `IngestDashboard.svelte` changes

**Idle view additions** — below device rows, a "Pipeline" section:

```
Pipeline
[✓] Copy                    Required
[✓] Deduplication
[✓] Scoring
[✓] AI Naming
[✓] Darktable sync
```

Copy row is rendered with a "Required" badge and its checkbox is disabled.

**Running view** — replace single progress bar with stage list:

```
✓  Copy              143 files
⏏  SD card ejected   you can continue shooting
▶  Scoring           67 / 131  [████████░░]
○  AI Naming         pending
—  Darktable sync    (skipped)
```

Stage states: `pending` (○), `active` (▶ with inline progress bar), `done` (✓), `skipped` (—, muted), `sd_ejected` (⏏, accent colour).

**Done view** — summary card gains rows:

- Duplicates skipped
- Images scored
- Images named
- XMP written
- DB rows upserted
- Elapsed

### Ingest store (`src/stores/ingest.ts`) additions

Add `stageDone` map `Record<string, object>` and `sdEjected: boolean` to ingest state so the running view can render completed stage metadata.

---

## Testing

- `pytest tests/test_sidecar_cli.py` — add cases for `--skip-*` flag combinations using `CliRunner`
- Dry-run end-to-end: all stages enabled, verify event sequence matches spec
- Dry-run: `--skip-naming --skip-darktable`, verify those stages emit no events
- SD ejection: mock `subprocess.run` and `/proc/mounts`, verify `udisksctl power-off` called with correct disk device

---

## Constraints

- `udisksctl` is available on Ubuntu 24.04 without sudo
- Ejection is non-fatal — sidecar continues on failure
- Scoring and naming only run on non-duplicate files
- `cluster_sessions` always runs (fast, prerequisite for dedup)
- All inference remains CPU-only (no GPU paths)
- KPM-1.2: Florence-2 naming ≤ 2.5s/image on i7-7500U
