# Stage 7.2 — IngestDashboard & CartridgeManager Implementation Plan

## Goal

Wire the IngestDashboard and CartridgeManager panel stubs to the Python backend via a PyInstaller sidecar, giving the operator a touch-friendly UI for triggering photo ingestion and managing SSD cartridges.

## Architecture

The Python backend (`src/photo_workflow/`) gains a thin CLI wrapper (`src/photo_workflow/sidecar_cli.py`) exposing three subcommands: `ingest`, `cartridge-list`, and `cartridge-reformat`. This wrapper is compiled by PyInstaller on the Yoga 910 into a self-contained Linux binary placed at `photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu`.

Tauri's `tauri-plugin-shell` spawns the sidecar once per command. The sidecar streams JSON-lines to stdout (one object per progress tick, one final `done`/`error`). A TypeScript module `photonforge-gui/src/lib/sidecar.ts` wraps each command into a typed async generator. Both panels consume that module directly — no panel talks to Rust or the sidecar directly.

`cartridge-reformat` requires root for `mkfs.ext4`. A polkit rule installed by `scripts/install_polkit.sh` grants the sidecar binary passwordless permission to run the format command. This is a one-time setup step on the Yoga.

## DeviceState Extension

`mount_monitor.rs` and `src/stores/devices.ts` must be extended to carry the actual mount paths (already parsed from `/proc/mounts`) so the frontend can pass them directly to the sidecar:

```rust
// mount_monitor.rs — added fields
pub struct DeviceState {
    pub ssd_mounted: bool,
    pub ssd_label: Option<String>,
    pub ssd_mount_point: Option<String>,  // e.g. "/mnt/photon_ssd/001"
    pub sd_mounted: bool,
    pub sd_path: Option<String>,          // e.g. "/mnt/photon_sd" or "/media/alex/5BF9-1DE9"
}
```

```typescript
// stores/devices.ts — added fields
export interface DeviceState {
  ssd_mounted: boolean;
  ssd_label: string | null;
  ssd_mount_point: string | null;
  sd_mounted: boolean;
  sd_path: string | null;
}
```

`IngestDashboard` passes `deviceState.sd_path` as `--source` and `deviceState.ssd_mount_point` as `--output`. The `--db` path is derived as `ssd_mount_point + "/library.db"`.

## File Structure

| Action | Path |
|--------|------|
| Create | `src/photo_workflow/sidecar_cli.py` |
| Create | `scripts/build_sidecar.sh` |
| Create | `scripts/install_polkit.sh` |
| Create | `photonforge-gui/src/lib/sidecar.ts` |
| Modify | `photonforge-gui/src/panels/IngestDashboard.svelte` |
| Modify | `photonforge-gui/src/panels/CartridgeManager.svelte` |
| Create | `photonforge-gui/src/panels/IngestDashboard.test.ts` |
| Create | `photonforge-gui/src/panels/CartridgeManager.test.ts` |
| Create | `tests/test_sidecar_cli.py` |
| Create | `photonforge-gui/src-tauri/src/sidecar.rs` |
| Modify | `photonforge-gui/src-tauri/src/main.rs` |
| Modify | `photonforge-gui/src-tauri/tauri.conf.json` |
| Modify | `photonforge-gui/src-tauri/capabilities/default.json` |
| Create | `photonforge-gui/src-tauri/binaries/.gitkeep` |
| Modify | `photonforge-gui/src-tauri/src/mount_monitor.rs` |
| Modify | `photonforge-gui/src/stores/devices.ts` |

## Sidecar Interface

### Commands

```bash
# Stream progress events, then a done/error event
photo-workflow-sidecar ingest \
  --source /mnt/photon_sd \
  --output /mnt/photon_ssd/001 \
  --db /mnt/photon_ssd/001/library.db

# Print one cartridges event then exit
photo-workflow-sidecar cartridge-list

# Stream progress, then reformat_done/error (requires polkit)
photo-workflow-sidecar cartridge-reformat \
  --device /dev/sdb \
  --label PHOTON-002 \
  [--dry-run]
```

### Event Shapes (JSON-lines on stdout)

```json
{"type": "progress", "step": "copying",   "current": 42,  "total": 150, "message": "DSC_0042.ARW"}
{"type": "progress", "step": "scoring",   "current": 10,  "total": 42,  "message": ""}
{"type": "progress", "step": "naming",    "current": 5,   "total": 42,  "message": ""}
{"type": "progress", "step": "darktable", "current": 42,  "total": 42,  "message": ""}
{"type": "done",     "summary": {"total": 150, "duplicates_skipped": 8, "scored": 142, "xmp_written": 142, "db_upserted": 142, "elapsed_seconds": 47.2}}
{"type": "error",    "message": "SD card not mounted"}
{"type": "cartridges", "items": [{"label": "PHOTON-001", "mount_point": "/mnt/photon_ssd/001", "free_bytes": 214748364800, "size_bytes": 500107862016}]}
{"type": "reformat_done", "label": "PHOTON-002", "mount_point": "/mnt/photon_ssd/002"}
```

Step labels rendered in UI: `copying → Copying files`, `scoring → Scoring images`, `naming → Generating names`, `darktable → Syncing to Darktable`.

## Panel Behaviour

### IngestDashboard

Three states:

**Idle**
- Shows source path (from `deviceState.sd_mounted` / auto-detected `/media/` path)
- Shows destination label (from `deviceState.ssd_label`)
- "Start Ingest" button disabled when SD or SSD absent
- Warning labels: "Insert SD card" / "No cartridge mounted" when missing

**Running**
- Progress bar + step label (`Copying files… 42 / 150`)
- "Cancel" button kills the sidecar process via Tauri shell API

**Done**
- Summary card: total files, duplicates skipped, images scored, elapsed time
- "New Ingest" button resets to idle

### CartridgeManager

Two areas:

**Cartridge list**
- Fetched via `cartridge-list` on panel mount and on every `device-state-changed` event
- Each cartridge shown as a card: label, mount point, free/total space bar
- "Reformat" button per card

**Reformat flow**
- Tapping "Reformat" opens a confirmation sheet showing label and warning: "All data will be erased"
- User must type the cartridge label exactly to enable the "Confirm Reformat" button
- On confirm: progress view replaces the card during operation
- On completion: list refreshes via `cartridge-list`

## Testing

### Rust unit tests (`cargo test --no-default-features`)

`photonforge-gui/src-tauri/src/sidecar.rs`:
- Valid progress event parsed correctly
- Valid done event parsed correctly
- Malformed JSON line ignored without panic
- Error event propagated

### Python tests (`pytest tests/test_sidecar_cli.py`)

- `cartridge-list` prints valid JSON to stdout and exits 0
- `ingest` with fixture source dir streams at least one progress event and one done event, exits 0
- `cartridge-reformat --dry-run` streams events without touching disk, exits 0

### Frontend tests (`vitest`)

`IngestDashboard.test.ts`:
- Idle: "Start Ingest" disabled when `ssd_mounted=false`
- Idle: "Start Ingest" enabled when both SD and SSD present
- Running: progress bar visible, cancel button present
- Done: summary card shows total, duplicates, elapsed

`CartridgeManager.test.ts`:
- Renders cartridge cards from mock sidecar `cartridges` event
- Reformat confirm button disabled until label typed correctly
- Reformat confirm button enabled when label matches

### Manual Acceptance Criteria

- **AC-1**: With SD inserted and SSD mounted, "Start Ingest" is enabled; tapping it streams live progress to the screen
- **AC-2**: When ingest completes, summary shows correct file counts and elapsed time
- **AC-3**: Cartridge list shows PHOTON-001 with correct free space bar
- **AC-4**: Reformat confirmation rejects a wrong label and accepts the correct label, then runs to completion

## Constraints

- PyInstaller binary must be built on the Yoga 910 (Linux x86_64); the binary is committed to `src-tauri/binaries/` and not rebuilt on every dev cycle
- `cartridge-reformat` requires the polkit rule from `scripts/install_polkit.sh` to be installed once on the Yoga
- `tauri-plugin-shell` must be added to `Cargo.toml` and its permissions added to `capabilities/default.json`
- The sidecar binary path in `tauri.conf.json` must use Tauri's required target-triple naming: `photo-workflow-sidecar-x86_64-unknown-linux-gnu`
