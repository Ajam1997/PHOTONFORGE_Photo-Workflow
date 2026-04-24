# Cartridge Provisioning Utility — Design Specification

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:writing-plans after this spec is approved.

## Goal

Add a "Provision New Cartridge" feature to the CartridgeManager panel that automates the manual partitioning/formatting workflow from UDEV_NOTES.md. This eliminates the need for command-line tools (`parted`, `wipefs`, `mkfs.ext4`) when setting up a new PHOTON cartridge.

## Architecture

The backend gains a new `provision.py` module with `analyze_device()` (intelligence) and `provision_cartridge()` (execution). A new sidecar subcommand `cartridge-provision` streams progress events via JSON-lines. The frontend CartridgeManager panel gains an "Available Drives" section showing unprovisioned USB drives with smart auto-detection + manual override controls.

**Smart partitioning logic:**
1. Check existing partitions via `lsblk --json`
2. If no partitions → create GPT + single ext4 partition
3. If partitions exist → use first partition (unless `--force-repartition`)
4. Always run `wipefs -a` before mkfs.ext4 to clear stale signatures
5. Run `udevadm trigger` after format so udev rule auto-mounts the new cartridge

## Sidecar Interface

### Command
```bash
photo-workflow-sidecar cartridge-provision \
  --device /dev/sdb \
  --label PHOTON-002 \
  [--force-repartition] \
  [--dry-run]
```

### Event Shapes (JSON-lines)
```json
{"type": "progress", "step": "analyzing", "current": 0, "total": 5, "message": "Checking existing partitions..."}
{"type": "progress", "step": "wiping", "current": 1, "total": 5, "message": "Clearing stale signatures..."}
{"type": "progress", "step": "partitioning", "current": 2, "total": 5, "message": "Creating GPT partition table..."}
{"type": "progress", "step": "formatting", "current": 3, "total": 5, "message": "Creating ext4 filesystem..."}
{"type": "progress", "step": "initializing", "current": 4, "total": 5, "message": "Creating directory structure..."}
{"type": "provision_done", "label": "PHOTON-002", "device": "/dev/sdb1", "mount_point": "/mnt/photon_ssd/002"}
{"type": "error", "message": "Device /dev/sdb does not exist"}
```

## Backend: provision.py

```python
@dataclass
class DeviceAnalysis:
    device: str                    # /dev/sdb
    size_bytes: int
    has_partitions: bool
    existing_label: str | None
    partition_device: str | None   # /dev/sdb1 or None

@dataclass
class ProvisionResult:
    label: str
    device: str                    # The partition device (e.g. /dev/sdb1)
    mount_point: str
    created_partition: bool
    wiped_signatures: bool

def analyze_device(device: str) -> DeviceAnalysis:
    """Use lsblk to check partition status and existing label."""
    ...

def provision_cartridge(
    device: str,
    label: str,
    force_repartition: bool = False,
    dry_run: bool = False,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> ProvisionResult:
    """
    Full provisioning workflow:
    1. Analyze device
    2. Wipefs -a on device and partition (if exists)
    3. Create GPT + single ext4 partition (if !has_partitions or force_repartition)
    4. mkfs.ext4 -L <label> on partition device
    5. udevadm trigger --action=add on partition device
    6. Initialize directory structure via cartridge.init_cartridge()
    """
    ...

def next_available_cartridge_id(label_prefix: str = "PHOTON") -> str:
    """Scan /mnt/photon_ssd/ and /dev/disk/by-label/ for next 3-digit ID."""
    ...
```

## Frontend: CartridgeManager Panel Additions

### New Section: "Available Drives"

Shows when unprovisioned USB drives are detected (USB block devices that don't match `PHOTON-*` label).

**Card per drive:**
- Device path (e.g., `/dev/sdb`)
- Size (human readable)
- Current status: "Unpartitioned", "Has partitions", or "Other filesystem"
- "Provision as PHOTON-XXX" button (auto-assigns next available ID)
- "Advanced..." link reveals:
  - Label input (pre-filled with auto ID, editable)
  - "Force repartition" checkbox (default off)
  - "Dry run" checkbox (simulates without touching disk)

### New Modal: Provisioning Progress

- Progress bar showing step names (Analyzing → Wiping → Partitioning → Formatting → Initializing)
- Cancel button (kills sidecar process)
- On completion: show success, auto-refresh cartridge list
- On error: show error details, option to retry

## Sudoers Requirements

The `cartridge-provision` command requires passwordless sudo for:
- `/usr/sbin/parted` — create GPT partition table
- `/usr/sbin/wipefs` — clear stale signatures
- `/sbin/mkfs.ext4` — create ext4 filesystem
- `/usr/bin/udevadm` — trigger mount after format

Add to `/etc/sudoers.d/photonforge`:
```
alex ALL=(ALL) NOPASSWD: /usr/sbin/parted *, /usr/sbin/wipefs *, /usr/sbin/mkfs.ext4 *, /usr/bin/udevadm *, /usr/bin/umount *
```

## File Structure

| Action | Path |
|--------|------|
| Create | `src/photo_workflow/provision.py` |
| Create | `tests/test_provision.py` |
| Modify | `src/photo_workflow/sidecar_cli.py` (add cartridge-provision command) |
| Modify | `src/photo_workflow/cartridge.py` (call init_cartridge from provision) |
| Modify | `photonforge-gui/src/lib/sidecar.ts` (add provisionCartridge wrapper) |
| Modify | `photonforge-gui/src/panels/CartridgeManager.svelte` (add Available Drives UI) |
| Create | `photonforge-gui/src/panels/CartridgeManager.test.ts` (provision flow tests) |

## Testing

### Unit tests (provision.py)
- `analyze_device()` correctly identifies partitioned vs unpartitioned drives
- `next_available_cartridge_id()` skips existing IDs correctly
- `provision_cartridge()` raises on non-existent device
- `provision_cartridge()` respects dry_run flag (no actual disk changes)

### Sidecar tests
- `cartridge-provision --dry-run` emits expected progress events, exits 0
- `cartridge-provision` with invalid device emits error event, exits 1

### Frontend tests
- "Available Drives" section shows when unprovisioned USB drives detected
- Auto ID pre-fills correctly based on existing cartridges
- "Force repartition" checkbox toggles command flag
- Progress bar advances through all 5 steps
- On provision_done, cartridge list refreshes and shows new cartridge

## Manual Acceptance Criteria

- **AC-1**: Insert a fresh USB drive (no partitions) → appears in "Available Drives"
- **AC-2**: Tap "Provision as PHOTON-XXX" → flows through 5 steps, ends with cartridge mounted and visible in CartridgeManager list
- **AC-3**: Directory structure (`darktable/`, `photos/`, `darktable/library.db`) exists on new cartridge
- **AC-4**: Advanced mode allows custom label override and force repartition
- **AC-5**: Dry-run mode simulates without creating partitions

## Constraints

- Must run on Yoga 910 with Ubuntu 24.04
- All disk operations require root (via sudo -n)
- `wipefs -a` must run before mkfs.ext4 to clear stale ZFS/NTFS signatures
- Auto-mount depends on udev rule from 99-photo-ssd.rules firing after `udevadm trigger`
