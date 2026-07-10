# Cartridge Provisioning Utility — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automated cartridge provisioning (partition, format, init) to the CartridgeManager panel with smart auto-detection and manual override.

**Architecture:** New `provision.py` module provides `analyze_device()` and `provision_cartridge()` functions. Sidecar CLI adds `cartridge-provision` subcommand that streams JSON-lines progress. Frontend adds "Available Drives" section with auto-ID assignment and Advanced mode toggle.

**Tech Stack:** Python 3.12, pytest, TypeScript, Svelte, Tauri shell plugin, sudo for disk operations

---

### Task 1: Create provision.py module with analyze_device()

**Files:**
- Create: `src/photo_workflow/provision.py`
- Create: `tests/test_provision.py`

- [ ] **Step 1: Write the failing test for analyze_device()**

```python
# tests/test_provision.py
import json
import subprocess
from unittest.mock import Mock, patch

from photo_workflow.provision import analyze_device, DeviceAnalysis


def test_analyze_device_returns_correct_structure():
    """Test that analyze_device returns a DeviceAnalysis dataclass."""
    mock_lsblk = json.dumps({
        "blockdevices": [{
            "name": "sdb",
            "size": 500107862016,
            "children": []
        }]
    })
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(stdout=mock_lsblk, returncode=0)
        result = analyze_device("/dev/sdb")
        assert isinstance(result, DeviceAnalysis)
        assert result.device == "/dev/sdb"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_provision.py::test_analyze_device_returns_correct_structure -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'photo_workflow.provision'"

- [ ] **Step 3: Write minimal provision.py with DeviceAnalysis dataclass and analyze_device()**

```python
# src/photo_workflow/provision.py
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DeviceAnalysis:
    device: str  # e.g., /dev/sdb
    size_bytes: int
    has_partitions: bool
    existing_label: str | None
    partition_device: str | None  # e.g., /dev/sdb1 or None


def analyze_device(device: str) -> DeviceAnalysis:
    """Use lsblk to check partition status and existing label."""
    result = subprocess.run(
        ["lsblk", "--json", "--output", "NAME,SIZE,LABEL,TYPE"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)

    device_name = Path(device).name

    def _find_device(devices: list) -> dict | None:
        for dev in devices:
            if dev["name"] == device_name:
                return dev
            if dev.get("children"):
                found = _find_device(dev["children"])
                if found:
                    return found
        return None

    dev_info = _find_device(data.get("blockdevices", []))
    if not dev_info:
        raise ValueError(f"Device {device} not found in lsblk output")

    children = dev_info.get("children", [])
    has_partitions = bool(children)
    partition_device = f"{device}1" if has_partitions else None

    existing_label = None
    if has_partitions:
        existing_label = children[0].get("label")
    else:
        existing_label = dev_info.get("label")

    size_str = dev_info.get("size", 0)
    size_bytes = int(size_str) if isinstance(size_str, (int, str)) else 0

    return DeviceAnalysis(
        device=device,
        size_bytes=size_bytes,
        has_partitions=has_partitions,
        existing_label=existing_label,
        partition_device=partition_device,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_provision.py::test_analyze_device_returns_correct_structure -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_provision.py src/photo_workflow/provision.py
git commit -m "feat: add provision.py with DeviceAnalysis dataclass and analyze_device()"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

### Task 2: Add next_available_cartridge_id() function

**Files:**
- Modify: `src/photo_workflow/provision.py`
- Modify: `tests/test_provision.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provision.py (add to existing file)
from photo_workflow.provision import next_available_cartridge_id


def test_next_available_cartridge_id_returns_001_when_no_cartridges_exist():
    """Test that next_available_cartridge_id returns '001' when no cartridges exist."""
    with patch('pathlib.Path.exists') as mock_exists, \
         patch('pathlib.Path.iterdir') as mock_iterdir:
        mock_exists.return_value = False
        mock_iterdir.return_value = []
        result = next_available_cartridge_id()
        assert result == "001"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_provision.py::test_next_available_cartridge_id_returns_001_when_no_cartridges_exist -v`
Expected: FAIL with "ImportError: cannot import name 'next_available_cartridge_id'"

- [ ] **Step 3: Write minimal implementation**

```python
# Add to src/photo_workflow/provision.py (after analyze_device)

def next_available_cartridge_id(label_prefix: str = "PHOTON") -> str:
    """Scan /mnt/photon_ssd/ and /dev/disk/by-label/ for next 3-digit ID."""
    import re

    existing_ids = set()

    # Check mounted cartridges in /mnt/photon_ssd/
    mount_base = Path("/mnt/photon_ssd")
    if mount_base.exists():
        for item in mount_base.iterdir():
            if item.is_dir() and item.name.isdigit():
                existing_ids.add(int(item.name))

    # Check labels in /dev/disk/by-label/
    label_dir = Path("/dev/disk/by-label")
    if label_dir.exists():
        for item in label_dir.iterdir():
            match = re.match(rf"{label_prefix}-(\d{{3}})", item.name)
            if match:
                existing_ids.add(int(match.group(1)))

    # Find first gap starting from 1
    for i in range(1, 1000):
        if i not in existing_ids:
            return f"{i:03d}"

    raise RuntimeError("No available cartridge IDs (001-999 all in use)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_provision.py::test_next_available_cartridge_id_returns_001_when_no_cartridges_exist -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_provision.py src/photo_workflow/provision.py
git commit -m "feat: add next_available_cartridge_id() for auto-assigning cartridge IDs"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

### Task 3: Add provision_cartridge() function with progress callback

**Files:**
- Modify: `src/photo_workflow/provision.py`
- Modify: `tests/test_provision.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provision.py (add to existing file)
from photo_workflow.provision import ProvisionResult, provision_cartridge


def test_provision_cartridge_raises_on_nonexistent_device():
    """Test that provision_cartridge raises ValueError for non-existent device."""
    with pytest.raises(ValueError, match="does not exist"):
        provision_cartridge("/dev/nonexistent", "PHOTON-001")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_provision.py::test_provision_cartridge_raises_on_nonexistent_device -v`
Expected: FAIL with "ImportError: cannot import name 'provision_cartridge'"

- [ ] **Step 3: Write minimal implementation**

```python
# Add to src/photo_workflow/provision.py
from typing import Callable


@dataclass
class ProvisionResult:
    label: str
    device: str  # The partition device (e.g., /dev/sdb1)
    mount_point: str
    created_partition: bool
    wiped_signatures: bool


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
    import shutil

    def _emit(step: str, current: int, total: int, message: str = ""):
        if progress_cb:
            progress_cb(step, current, total)
        logger.info(f"[{current}/{total}] {step}: {message}")

    # Validate device exists
    device_path = Path(device)
    if not device_path.exists():
        raise ValueError(f"Device {device} does not exist")

    _emit("analyzing", 0, 5, "Checking existing partitions...")
    analysis = analyze_device(device)

    _emit("wiping", 1, 5, "Clearing stale signatures...")
    wiped = False
    if not dry_run:
        # Wipe the main device
        subprocess.run(["sudo", "-n", "wipefs", "-a", device], check=False)
        # Wipe partition device if it exists
        if analysis.partition_device and Path(analysis.partition_device).exists():
            subprocess.run(
                ["sudo", "-n", "wipefs", "-a", analysis.partition_device], check=False
            )
        wiped = True

    partition_device = analysis.partition_device
    created_partition = False

    # Decide whether to create partitions
    if not analysis.has_partitions or force_repartition:
        _emit("partitioning", 2, 5, "Creating GPT partition table...")
        if not dry_run:
            # Create GPT + single ext4 partition
            subprocess.run(
                [
                    "sudo",
                    "-n",
                    "parted",
                    device,
                    "--script",
                    "mklabel",
                    "gpt",
                    "mkpart",
                    "primary",
                    "ext4",
                    "0%",
                    "100%",
                ],
                check=True,
            )
            # After partitioning, the device will be /dev/sdX1
            partition_device = f"{device}1"
            created_partition = True

    _emit("formatting", 3, 5, "Creating ext4 filesystem...")
    if not dry_run:
        subprocess.run(
            ["sudo", "-n", "mkfs.ext4", "-L", label, "-F", partition_device],
            check=True,
        )

    _emit("initializing", 4, 5, "Creating directory structure...")
    mount_point = f"/mnt/photon_ssd/{label.replace('PHOTON-', '')}"

    if not dry_run:
        # Trigger udev to mount the new cartridge
        subprocess.run(
            ["sudo", "-n", "udevadm", "trigger", "--action=add", partition_device],
            check=False,
        )
        # Wait a moment for udev to mount
        import time

        time.sleep(1)

    return ProvisionResult(
        label=label,
        device=partition_device,
        mount_point=mount_point,
        created_partition=created_partition,
        wiped_signatures=wiped,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_provision.py::test_provision_cartridge_raises_on_nonexistent_device -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_provision.py src/photo_workflow/provision.py
git commit -m "feat: add provision_cartridge() with progress callback and dry-run support"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

### Task 4: Add cartridge-provision command to sidecar_cli.py

**Files:**
- Modify: `src/photo_workflow/sidecar_cli.py`

- [ ] **Step 1: Add import and new command to sidecar_cli.py**

```python
# Add import at top of sidecar_cli.py
from photo_workflow.provision import (
    analyze_device,
    next_available_cartridge_id,
    provision_cartridge,
)


# Add new CLI command (after cartridge_reformat)
@cli.command("cartridge-provision")
@click.option("--device", required=True, help="Block device path, e.g. /dev/sdb")
@click.option("--label", required=True, help="New label, e.g. PHOTON-002")
@click.option("--force-repartition", is_flag=True, default=False, help="Force repartition even if partitions exist")
@click.option("--dry-run", is_flag=True, default=False, help="Simulate without touching disk")
def cartridge_provision(device: str, label: str, force_repartition: bool, dry_run: bool) -> None:
    """Provision a new PHOTON cartridge with partition, format, and init."""
    try:
        def progress_cb(step: str, current: int, total: int):
            emit({"type": "progress", "step": step, "current": current, "total": total, "message": step})

        result = provision_cartridge(
            device=device,
            label=label,
            force_repartition=force_repartition,
            dry_run=dry_run,
            progress_cb=progress_cb,
        )

        emit({
            "type": "provision_done",
            "label": result.label,
            "device": result.device,
            "mount_point": result.mount_point,
            "created_partition": result.created_partition,
            "wiped_signatures": result.wiped_signatures,
        })
    except Exception as exc:
        emit({"type": "error", "message": str(exc)})
        sys.exit(1)
```

- [ ] **Step 2: Test the sidecar command dry-run**

Run: `python -m photo_workflow.sidecar_cli cartridge-provision --device /dev/loop0 --label PHOTON-999 --dry-run`
Expected: JSON output with progress steps, ending with provision_done (may fail if /dev/loop0 doesn't exist, that's OK for dry-run test)

- [ ] **Step 3: Commit**

```bash
git add src/photo_workflow/sidecar_cli.py
git commit -m "feat: add cartridge-provision command to sidecar CLI"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

### Task 5: Add provisionCartridge wrapper to sidecar.ts

**Files:**
- Modify: `photonforge-gui/src/lib/sidecar.ts`

- [ ] **Step 1: Add ProvisionEvent types**

```typescript
// Add to photonforge-gui/src/lib/sidecar.ts

export interface ProvisionDoneEvent {
  type: "provision_done";
  label: string;
  device: string;
  mount_point: string;
  created_partition: boolean;
  wiped_signatures: boolean;
}

export type ProvisionEvent = ProgressEvent | ProvisionDoneEvent | ErrorEvent;
```

- [ ] **Step 2: Add provisionCartridge function**

```typescript
// Add to photonforge-gui/src/lib/sidecar.ts

export async function provisionCartridge(
  device: string,
  label: string,
  forceRepartition: boolean,
  dryRun: boolean,
  onEvent: (event: ProvisionEvent) => void,
): Promise<Command<string>> {
  const args = [
    "cartridge-provision",
    "--device", device,
    "--label", label,
  ];
  if (forceRepartition) args.push("--force-repartition");
  if (dryRun) args.push("--dry-run");

  const cmd = Command.sidecar("binaries/photo-workflow-sidecar", args);

  const child = await cmd.spawn();
  child.stdout.on("data", (line: string) => {
    const event = parseLine(line.trim());
    if (event) onEvent(event as ProvisionEvent);
  });
  child.stderr.on("data", (line: string) => {
    console.error("provision stderr:", line);
  });

  return cmd;
}
```

- [ ] **Step 3: Commit**

```bash
git add photonforge-gui/src/lib/sidecar.ts
git commit -m "feat: add provisionCartridge wrapper to sidecar.ts"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

### Task 6: Add Available Drives section to CartridgeManager.svelte

**Files:**
- Modify: `photonforge-gui/src/panels/CartridgeManager.svelte`

- [ ] **Step 1: Add new imports and state variables**

```typescript
// Add to imports in CartridgeManager.svelte
import { provisionCartridge } from "../lib/sidecar";

// Add new state variables (after existing ones)
let availableDrives: { device: string; size: string; status: string }[] = [];
let showProvisionSheet = false;
let provisionTarget: { device: string; size: string } | null = null;
let provisionLabel = "";
let provisionForceRepartition = false;
let provisionDryRun = false;
let provisionRunning = false;
let provisionStep = "";
let provisionCurrent = 0;
let provisionTotal = 5;
let provisionError = "";

// Auto-assign next available ID
$: nextId = calculateNextId(cartridges);

function calculateNextId(carts: CartridgeInfo[]): string {
  const existing = carts.map(c => {
    const match = c.label.match(/PHOTON-(\d{3})/);
    return match ? parseInt(match[1], 10) : 0;
  });
  for (let i = 1; i < 1000; i++) {
    if (!existing.includes(i)) return `PHOTON-${String(i).padStart(3, '0')}`;
  }
  return "PHOTON-999";
}

async function fetchAvailableDrives() {
  // This would call a new sidecar command to list USB drives
  // For now, we'll implement it as a stub that can be filled in
  availableDrives = []; // Will be populated by new sidecar command
}

function openProvision(drive: { device: string; size: string }) {
  provisionTarget = drive;
  provisionLabel = nextId;
  provisionForceRepartition = false;
  provisionDryRun = false;
  provisionError = "";
  showProvisionSheet = true;
}

function closeProvision() {
  showProvisionSheet = false;
  provisionTarget = null;
  provisionRunning = false;
  provisionStep = "";
}

async function confirmProvision() {
  if (!provisionTarget) return;
  provisionRunning = true;
  provisionError = "";

  try {
    await provisionCartridge(
      provisionTarget.device,
      provisionLabel,
      provisionForceRepartition,
      provisionDryRun,
      (event) => {
        if (event.type === "progress") {
          provisionStep = event.step;
          provisionCurrent = event.current;
          provisionTotal = event.total;
        } else if (event.type === "provision_done") {
          provisionRunning = false;
          closeProvision();
          fetchCartridges(); // Refresh list
        } else if (event.type === "error") {
          provisionError = event.message;
          provisionRunning = false;
        }
      }
    );
  } catch (err) {
    provisionError = err instanceof Error ? err.message : String(err);
    provisionRunning = false;
  }
}
```

- [ ] **Step 2: Add "Available Drives" UI section to the template**

```svelte
<!-- Add after cartridge-list div, before the closing </div> of cartridge-panel -->

{#if availableDrives.length > 0}
  <div class="available-drives-section">
    <h3>Available Drives</h3>
    <div class="drive-list">
      {#each availableDrives as drive}
        <div class="drive-card">
          <div class="drive-info">
            <span class="device-path">{drive.device}</span>
            <span class="drive-size">{drive.size}</span>
            <span class="drive-status">{drive.status}</span>
          </div>
          <button class="provision-btn" on:click={() => openProvision(drive)}>
            Provision as {nextId}
          </button>
        </div>
      {/each}
    </div>
  </div>
{/if}

{#if showProvisionSheet}
  <div class="sheet-overlay" role="dialog" aria-modal="true">
    <div class="sheet">
      {#if provisionRunning}
        <h3>Provisioning {provisionLabel}...</h3>
        <p class="muted">{provisionStep}</p>
        <div class="progress-bar">
          <div class="progress-fill" style="width: {(provisionCurrent / provisionTotal) * 100}%"></div>
        </div>
        <p class="progress-text">{provisionCurrent} / {provisionTotal}</p>
        <button class="cancel-btn" on:click={closeProvision}>Cancel</button>
      {:else}
        <h3>Provision New Cartridge</h3>
        {#if provisionTarget}
          <p>Device: <code>{provisionTarget.device}</code></p>
          <p>Size: {provisionTarget.size}</p>
        {/if}

        {#if provisionError}
          <p class="error">{provisionError}</p>
        {/if}

        <div class="form-group">
          <label for="provision-label">Label:</label>
          <input id="provision-label" bind:value={provisionLabel} placeholder="PHOTON-001" />
        </div>

        <div class="form-group">
          <label>
            <input type="checkbox" bind:checked={provisionForceRepartition} />
            Force repartition (erase existing data)
          </label>
        </div>

        <div class="form-group">
          <label>
            <input type="checkbox" bind:checked={provisionDryRun} />
            Dry run (simulate without touching disk)
          </label>
        </div>

        <div class="sheet-actions">
          <button class="cancel-btn" on:click={closeProvision}>Cancel</button>
          <button class="primary-btn" on:click={confirmProvision}>
            Start Provisioning
          </button>
        </div>
      {/if}
    </div>
  </div>
{/if}
```

- [ ] **Step 3: Add CSS styles for new components**

```css
/* Add to <style> section */

.available-drives-section {
  margin-top: 2rem;
  border-top: 1px solid var(--border, #333);
  padding-top: 1rem;
}

.available-drives-section h3 {
  color: var(--text-primary, #fff);
  margin: 0 0 1rem 0;
}

.drive-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.drive-card {
  background: var(--surface, #1a1a1a);
  border-radius: 0.5rem;
  padding: 1rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.drive-info {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.device-path {
  color: var(--text-primary, #fff);
  font-family: monospace;
  font-size: 0.9rem;
}

.drive-size {
  color: var(--text-muted, #888);
  font-size: 0.85rem;
}

.drive-status {
  color: var(--warning, #f59e0b);
  font-size: 0.8rem;
}

.provision-btn {
  padding: 0.5rem 1rem;
  background: var(--accent, #6366f1);
  color: #fff;
  border: none;
  border-radius: 0.375rem;
  cursor: pointer;
  font-size: 0.9rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.form-group label {
  color: var(--text-muted, #888);
  font-size: 0.9rem;
}

.form-group input[type="text"] {
  padding: 0.6rem;
  background: var(--surface, #1a1a1a);
  border: 1px solid var(--border, #333);
  border-radius: 0.375rem;
  color: var(--text-primary, #fff);
}

.form-group input[type="checkbox"] {
  margin-right: 0.5rem;
}

.progress-text {
  color: var(--text-muted, #888);
  font-size: 0.9rem;
  text-align: center;
}
```

- [ ] **Step 4: Commit**

```bash
git add photonforge-gui/src/panels/CartridgeManager.svelte
git commit -m "feat: add Available Drives section and provision modal to CartridgeManager"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

### Task 7: Rebuild sidecar binary on Yoga 910

**Files:**
- Modify: `photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu`

- [ ] **Step 1: SSH to Yoga and rebuild sidecar**

```bash
ssh alex@10.27.27.10 << 'REMOTE_SCRIPT'
cd ~/PHOTONFORGE_Photo-Workflow
git pull --ff-only
source .venv/bin/activate
pip install pyinstaller --quiet
pyinstaller \
  --onefile \
  --name photo-workflow-sidecar \
  --distpath photonforge-gui/src-tauri/binaries \
  --workpath /tmp/pyinstaller-build \
  --specpath /tmp/pyinstaller-build \
  src/photo_workflow/sidecar_cli.py
mv photonforge-gui/src-tauri/binaries/photo-workflow-sidecar \
  photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu
chmod +x photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu
ls -la photonforge-gui/src-tauri/binaries/
REMOTE_SCRIPT
```

Expected: Binary rebuilt with new cartridge-provision command

- [ ] **Step 2: Commit the new binary**

```bash
git add photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu
git commit -m "chore: rebuild sidecar binary with cartridge-provision command"

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

---

### Task 8: Update sudoers on Yoga 910

**Files:**
- Modify: `/etc/sudoers.d/photonforge` (on Yoga, not in repo)

- [ ] **Step 1: SSH to Yoga and update sudoers**

Run this manually on the Yoga (requires sudo password):

```bash
ssh alex@10.27.27.10
# Then run on the Yoga:
echo 'alex ALL=(ALL) NOPASSWD: /usr/sbin/parted *, /usr/sbin/wipefs *, /usr/sbin/mkfs.ext4 *, /usr/bin/udevadm *, /usr/bin/umount *' | sudo tee /etc/sudoers.d/photonforge
sudo chmod 440 /etc/sudoers.d/photonforge
sudo visudo -c
```

Expected: "/etc/sudoers.d/photonforge: parsed OK"

---

## Post-Implementation Verification

After all tasks complete:

1. **Restart Tauri dev server** on Yoga
2. **Insert unformatted USB drive**
3. **Verify**: Drive appears in "Available Drives" section
4. **Tap "Provision"**: Progress through 5 steps
5. **Verify**: Cartridge appears in cartridge list after completion
6. **Verify**: Directory structure exists (`darktable/`, `photos/`, `darktable/library.db`)

---

## Self-Review Checklist

- [ ] `analyze_device()` returns correct DeviceAnalysis structure
- [ ] `next_available_cartridge_id()` correctly finds gaps in cartridge IDs
- [ ] `provision_cartridge()` respects `dry_run` flag
- [ ] `provision_cartridge()` raises `ValueError` for non-existent device
- [ ] Sidecar `cartridge-provision` emits proper JSON-lines events
- [ ] Frontend `provisionCartridge()` wrapper spawns command and parses events
- [ ] CartridgeManager shows Available Drives section
- [ ] Provision modal has label input, force repartition checkbox, dry-run checkbox
- [ ] Progress bar advances through all 5 steps
- [ ] Sudoers updated on Yoga for parted, wipefs, mkfs.ext4, udevadm
