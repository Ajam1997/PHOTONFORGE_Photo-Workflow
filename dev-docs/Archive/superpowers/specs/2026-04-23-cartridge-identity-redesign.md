# Cartridge Identity Redesign

**Date:** 2026-04-23
**Status:** Approved
**Author:** Alex Meyer
**Scope:** Replace label-based cartridge detection with `.photonforge/cartridge.json` metadata file

---

## Problem

The original design identified PHOTON cartridges by filesystem label (`PHOTON-*`) and assumed udev rules would mount them at `/mnt/photon_ssd/{ID}`. In practice, udisks2 mounts everything at `/media/alex/{label}` before udev scripts can act. Consequences:

- `mount_monitor.rs` never sees a mount at `/mnt/photon_ssd/` so it never detects the cartridge
- The `/media/` fallback path misidentifies the PHOTON-001 cartridge as an SD card
- Stale numbered directories accumulate in `/mnt/photon_ssd/` across label changes
- The drive label is load-bearing: changing it breaks detection; reprovisioning just to rename is destructive
- SD insertion auto-triggering ingest was unreliable and has been abandoned

**All udev scripts and rules have been deleted as of commit `0b8b899`.**

---

## Design

### 1. Cartridge Identity File

Every provisioned drive holds a hidden metadata file at:

```
{mount_point}/.photonforge/cartridge.json
```

**Schema:**

```json
{
  "cartridge_id": "PHOTON-001",
  "provisioned_at": "2026-04-23T18:00:00Z",
  "provisioned_by": "yoga-910",
  "est_raw_capacity": 4300,
  "description": ""
}
```

| Field | Type | Writable after provision |
|-------|------|--------------------------|
| `cartridge_id` | string, e.g. `PHOTON-001` | No |
| `provisioned_at` | ISO-8601 UTC string | No |
| `provisioned_by` | hostname string | No |
| `est_raw_capacity` | integer (number of ~25 MB RAW files that fit) | No |
| `description` | free-text string | Yes, via `cartridge-update-meta` |

`est_raw_capacity` = `floor(partition_size_bytes / (25 * 1024 * 1024))`.

The filesystem label is **cosmetic only** — the user may set it to anything at provision time and change it freely. Detection never reads the label.

When a drive is reformatted (`cartridge-reformat`) the metadata file is destroyed with the filesystem. Reprovisioning writes a new file with a new `cartridge_id`. This is the intended identity boundary.

---

### 2. Detection — `mount_monitor.rs`

Drop all path-based detection (`/mnt/photon_ssd/`, `/mnt/photon_sd`). The monitor polls `/proc/mounts` every 2 seconds and classifies each mounted `/dev/sd*` removable block device by metadata file presence.

**Algorithm:**

```
for each line in /proc/mounts:
    device, mount_point = line.split()[0..1]
    if not is_removable_block_device(device): skip
    if {mount_point}/.photonforge/cartridge.json exists:
        read file → CartridgeMeta { cartridge_id, mount_point, free_bytes,
                                    size_bytes, provisioned_at, provisioned_by,
                                    est_raw_capacity, description }
        append to cartridges[]
    else:
        append to sd_candidates[] as { device, mount_point, label }
        (label read from /dev/disk/by-label/ reverse lookup or lsblk)
```

`is_removable_block_device` is unchanged: strips partition suffix, reads `/sys/block/{base}/removable`.

**`DeviceState` (Rust + TypeScript):**

```rust
pub struct CartridgeMeta {
    pub cartridge_id: String,
    pub mount_point: String,
    pub free_bytes: u64,
    pub size_bytes: u64,
    pub provisioned_at: String,
    pub provisioned_by: String,
    pub est_raw_capacity: u64,
    pub description: String,
}

pub struct SdCandidate {
    pub device: String,
    pub mount_point: String,
    pub label: Option<String>,   // None if the SD card has no filesystem label
}

pub struct DeviceState {
    pub cartridges: Vec<CartridgeMeta>,
    pub sd_candidates: Vec<SdCandidate>,
}
```

`ssd_mounted`, `ssd_label`, `ssd_mount_point`, `sd_mounted`, `sd_path` are **removed**.

The `run()` polling loop and `get_device_state` Tauri command are unchanged structurally.

---

### 3. Sidecar Changes (`sidecar_cli.py`)

#### `cartridge-provision` (modify)

After `mkfs.ext4` completes, poll `/proc/mounts` up to 10 seconds for the partition to appear (udisks2 auto-mounts it). Once mounted, write `.photonforge/cartridge.json`:

```python
import json, socket
from datetime import datetime, timezone

meta = {
    "cartridge_id": label,          # label arg is the user-supplied PHOTON-NNN
    "provisioned_at": datetime.now(timezone.utc).isoformat(),
    "provisioned_by": socket.gethostname(),
    "est_raw_capacity": partition_size_bytes // (25 * 1024 * 1024),
    "description": "",
}
photonforge_dir = Path(mount_point) / ".photonforge"
photonforge_dir.mkdir(exist_ok=True)
(photonforge_dir / "cartridge.json").write_text(json.dumps(meta, indent=2))
```

`mount_point` is discovered by polling `/proc/mounts` for the partition device, not assumed from the label.

Remove: the `udevadm trigger` call and the hardcoded `/mnt/photon_ssd/{id}` path construction.

#### `cartridge-list` (modify)

Replace label/lsblk-based discovery with metadata-file-based discovery: scan all mounted removable USB block devices for `.photonforge/cartridge.json`. Return `cartridge_id`, `mount_point`, `free_bytes`, `size_bytes`, and all metadata fields.

#### `cartridge-reformat` (minor change)

Wiping the filesystem destroys `.photonforge/cartridge.json`. This is correct — reformatting ends the cartridge identity.

Remove `mount_point` from the `reformat_done` event — it was derived from the old predictable `/mnt/photon_ssd/{id}` path which no longer exists. The event becomes:

```json
{"type": "reformat_done", "label": "PHOTON-002"}
```

Update `ReformatDoneEvent` in `sidecar.ts` accordingly.

#### `cartridge-update-meta` (new command)

```
cartridge-update-meta --mount-point PATH --description TEXT
```

Reads `.photonforge/cartridge.json`, updates `description`, writes back. Emits `{"type": "meta_updated", "cartridge_id": "..."}` on success, `{"type": "error", ...}` on failure.

#### `next_available_cartridge_id` (modify in `provision.py`)

Replace `/mnt/photon_ssd/` directory scan with metadata-file scan: read `cartridge_id` from all `.photonforge/cartridge.json` files found on mounted removable USB drives. Also keep the `/dev/disk/by-label/PHOTON-*` scan as a fallback for unmounted drives.

#### `install_polkit.sh` (modify)

Remove `udevadm` from the NOPASSWD sudoers line — the sidecar no longer calls `sudo udevadm`.

---

### 4. Frontend Changes

#### `photonforge-gui/src/stores/devices.ts`

Replace `ssd_mounted`, `ssd_label`, `ssd_mount_point`, `sd_mounted`, `sd_path` with:

```typescript
export interface CartridgeMeta {
  cartridge_id: string;
  mount_point: string;
  free_bytes: number;
  size_bytes: number;
  provisioned_at: string;
  provisioned_by: string;
  est_raw_capacity: number;
  description: string;
}

export interface SdCandidate {
  device: string;
  mount_point: string;
  label: string | null;   // null if the SD card has no filesystem label
}

export interface DeviceState {
  cartridges: CartridgeMeta[];
  sd_candidates: SdCandidate[];
}
```

#### `CartridgeManager.svelte`

- Lists all entries in `cartridges[]` as cards
- Each card shows: cartridge ID, provisioned date, provisioned by, estimated capacity (read-only)
- Editable description field — on blur calls `cartridge-update-meta` sidecar command
- Reformat and Provision actions remain per-card, unchanged

#### `IngestDashboard.svelte`

- **Source picker**: dropdown of `sd_candidates[]` showing label + mount point. Auto-selects if only one candidate. Uses same visual style as the drive picker in provisioning.
- **Destination**: `cartridges[0].mount_point` — multi-cartridge destination picking is deferred (see Future Work)
- `canStart` condition: `sd_candidates.length > 0 && cartridges.length > 0 && selectedSd != null`

---

### 5. Cleanup

**Already deleted (commit `0b8b899`):**
- `scripts/on_sd_add.sh`, `on_sd_remove.sh`, `on_ssd_add.sh`, `on_ssd_remove.sh`
- `scripts/install_udev.sh`, `scripts/ingest_sd.sh`
- `deploy/udev/` directory

**To be removed on Yoga during implementation:**
- `/etc/udev/rules.d/99-photo-sd.rules`
- `/etc/udev/rules.d/99-photo-ssd.rules`
- `/opt/photonforge/` directory
- `/mnt/photon_sd/` and `/mnt/photon_ssd/` directories

**`scripts/safe_eject.sh`** — keep, still used for WAL flush + unmount.

---

### 6. File Map

| Action | Path |
|--------|------|
| Rewrite | `photonforge-gui/src-tauri/src/mount_monitor.rs` |
| Modify | `src/photo_workflow/provision.py` |
| Modify | `src/photo_workflow/sidecar_cli.py` |
| Modify | `scripts/install_polkit.sh` |
| Modify | `photonforge-gui/src/stores/devices.ts` |
| Modify | `photonforge-gui/src/panels/CartridgeManager.svelte` |
| Modify | `photonforge-gui/src/panels/IngestDashboard.svelte` |
| Modify | `photonforge-gui/src/lib/sidecar.ts` (new `MetaUpdatedEvent`, updated `CartridgesEvent`) |
| Modify | `tests/test_sidecar_cli.py` |
| Modify | `photonforge-gui/src/panels/CartridgeManager.test.ts` |
| Modify | `photonforge-gui/src/panels/IngestDashboard.test.ts` |

---

### 7. Future Work

**Multi-cartridge destination picking** — `DeviceState.cartridges` is already a `Vec`/array, so the data model supports it. When implemented, the Ingest Dashboard destination becomes a picker over `cartridges[]` instead of defaulting to index 0. Add to architecture doc under planned enhancements.
