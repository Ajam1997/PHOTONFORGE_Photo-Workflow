# Cartridge Identity Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace label-based cartridge detection with a hidden `.photonforge/cartridge.json` metadata file, making the filesystem label cosmetic and detection mount-path-agnostic.

**Architecture:** `provision.py` writes the metadata file after formatting; `mount_monitor.rs` detects cartridges by file presence instead of mount path; `DeviceState` becomes `cartridges: Vec<CartridgeMeta>` + `sd_candidates: Vec<SdCandidate>`; CartridgeManager and IngestDashboard consume the new shape directly from the store.

**Tech Stack:** Python 3.11+, pytest, Rust (serde_json already in Cargo.toml), TypeScript, Svelte

---

### File Map

| Action | Path |
|--------|------|
| Modify | `src/photo_workflow/provision.py` |
| Modify | `tests/test_provision.py` |
| Modify | `src/photo_workflow/sidecar_cli.py` |
| Modify | `tests/test_sidecar_cli.py` |
| Rewrite | `photonforge-gui/src-tauri/src/mount_monitor.rs` |
| Modify | `photonforge-gui/src/lib/sidecar.ts` |
| Modify | `photonforge-gui/src/stores/devices.ts` |
| Modify | `photonforge-gui/src/stores/ingest.ts` |
| Rewrite | `photonforge-gui/src/panels/CartridgeManager.svelte` |
| Modify | `photonforge-gui/src/panels/CartridgeManager.test.ts` |
| Rewrite | `photonforge-gui/src/panels/IngestDashboard.svelte` |
| Modify | `photonforge-gui/src/panels/IngestDashboard.test.ts` |
| Modify | `scripts/install_polkit.sh` |

---

### Task 1: `provision.py` — remove udevadm, add mount polling + metadata write

**Files:**
- Modify: `src/photo_workflow/provision.py`
- Modify: `tests/test_provision.py` (create if absent)

- [ ] **Step 1: Write the failing tests**

Check if `tests/test_provision.py` exists. If it does, append these tests; if not, create it with this content:

```python
"""Tests for provision.py — cartridge provisioning."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from photo_workflow.provision import (
    next_available_cartridge_id,
    provision_cartridge,
)


def test_next_available_id_reads_from_metadata_files(tmp_path: Path) -> None:
    """next_available_cartridge_id scans /proc/mounts for .photonforge/cartridge.json."""
    # Simulate two mounted cartridges: PHOTON-001 and PHOTON-002
    cart1 = tmp_path / "ssd1"
    cart1.mkdir()
    (cart1 / ".photonforge").mkdir()
    (cart1 / ".photonforge" / "cartridge.json").write_text(
        json.dumps({"cartridge_id": "PHOTON-001"})
    )

    cart2 = tmp_path / "ssd2"
    cart2.mkdir()
    (cart2 / ".photonforge").mkdir()
    (cart2 / ".photonforge" / "cartridge.json").write_text(
        json.dumps({"cartridge_id": "PHOTON-002"})
    )

    fake_mounts = (
        f"/dev/sda1 {cart1} ext4 rw 0 0\n"
        f"/dev/sdb1 {cart2} ext4 rw 0 0\n"
    )

    with patch("photo_workflow.provision.Path") as mock_path_cls:
        # Make Path("/proc/mounts").read_text() return fake_mounts
        # but allow Path(mount_point) / ".photonforge" / "cartridge.json" to work
        # We patch at a higher level — monkeypatch the read_text call
        pass  # see below for simpler approach

    # Simpler: patch the internal _read_proc_mounts helper
    with patch(
        "photo_workflow.provision._read_proc_mounts",
        return_value=fake_mounts,
    ):
        result = next_available_cartridge_id()

    assert result == "003"


def test_next_available_id_skips_gaps(tmp_path: Path) -> None:
    """next_available_cartridge_id returns lowest unused ID."""
    cart1 = tmp_path / "ssd1"
    cart1.mkdir()
    (cart1 / ".photonforge").mkdir()
    (cart1 / ".photonforge" / "cartridge.json").write_text(
        json.dumps({"cartridge_id": "PHOTON-001"})
    )
    cart3 = tmp_path / "ssd3"
    cart3.mkdir()
    (cart3 / ".photonforge").mkdir()
    (cart3 / ".photonforge" / "cartridge.json").write_text(
        json.dumps({"cartridge_id": "PHOTON-003"})
    )

    fake_mounts = (
        f"/dev/sda1 {cart1} ext4 rw 0 0\n"
        f"/dev/sdb1 {cart3} ext4 rw 0 0\n"
    )

    with patch("photo_workflow.provision._read_proc_mounts", return_value=fake_mounts):
        result = next_available_cartridge_id()

    assert result == "002"


def test_provision_writes_cartridge_json(tmp_path: Path) -> None:
    """provision_cartridge writes .photonforge/cartridge.json after format."""
    mount_point = tmp_path / "cartridge"
    mount_point.mkdir()
    partition_device = "/dev/sda1"

    fake_mounts_before = ""  # not mounted yet
    fake_mounts_after = f"{partition_device} {mount_point} ext4 rw 0 0\n"

    call_count = 0

    def fake_read_mounts() -> str:
        nonlocal call_count
        call_count += 1
        return fake_mounts_after if call_count > 1 else fake_mounts_before

    with patch("photo_workflow.provision.subprocess.run") as mock_run, \
         patch("photo_workflow.provision._read_proc_mounts", side_effect=fake_read_mounts), \
         patch("photo_workflow.provision.socket.gethostname", return_value="test-host"), \
         patch("photo_workflow.provision.time.sleep"):
        mock_run.return_value = MagicMock(returncode=0)
        result = provision_cartridge(
            device=str(tmp_path),  # dry_run-like: device won't be probed
            label="PHOTON-042",
            dry_run=False,
            _partition_device_override=partition_device,
        )

    meta_file = mount_point / ".photonforge" / "cartridge.json"
    assert meta_file.exists(), "cartridge.json was not written"
    meta = json.loads(meta_file.read_text())
    assert meta["cartridge_id"] == "PHOTON-042"
    assert meta["provisioned_by"] == "test-host"
    assert meta["description"] == ""
    assert isinstance(meta["est_raw_capacity"], int)
    assert "provisioned_at" in meta
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_provision.py -v 2>&1 | tail -20
```

Expected: FAIL (ImportError or AttributeError — `_read_proc_mounts` doesn't exist yet)

- [ ] **Step 3: Rewrite `provision.py`**

Replace the entire file with:

```python
# src/photo_workflow/provision.py
from __future__ import annotations

import json
import logging
import re
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class DeviceAnalysis:
    device: str
    size_bytes: int
    has_partitions: bool
    existing_label: str | None
    partition_device: str | None


def _read_proc_mounts() -> str:
    """Read /proc/mounts. Extracted for testability."""
    return Path("/proc/mounts").read_text()


def analyze_device(device: str) -> DeviceAnalysis:
    """Use lsblk to check partition status and existing label."""
    result = subprocess.run(
        ["lsblk", "--json", "--bytes", "--output", "NAME,SIZE,LABEL,TYPE"],
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
    existing_label = children[0].get("label") if has_partitions else dev_info.get("label")
    size_bytes = int(dev_info.get("size", 0) or 0)

    return DeviceAnalysis(
        device=device,
        size_bytes=size_bytes,
        has_partitions=has_partitions,
        existing_label=existing_label,
        partition_device=partition_device,
    )


def next_available_cartridge_id(label_prefix: str = "PHOTON") -> str:
    """Find lowest unused 3-digit ID by scanning mounted cartridge metadata files."""
    existing_ids: set[int] = set()

    for line in _read_proc_mounts().splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        mount_point = parts[1]
        meta_file = Path(mount_point) / ".photonforge" / "cartridge.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
                match = re.match(rf"{label_prefix}-(\d{{3}})", meta.get("cartridge_id", ""))
                if match:
                    existing_ids.add(int(match.group(1)))
            except Exception:  # noqa: BLE001
                pass

    # Fallback: also check /dev/disk/by-label/ for unmounted drives
    label_dir = Path("/dev/disk/by-label")
    if label_dir.exists():
        for item in label_dir.iterdir():
            match = re.match(rf"{label_prefix}-(\d{{3}})", item.name)
            if match:
                existing_ids.add(int(match.group(1)))

    for i in range(1, 1000):
        if i not in existing_ids:
            return f"{i:03d}"

    raise RuntimeError("No available cartridge IDs (001-999 all in use)")


@dataclass
class ProvisionResult:
    label: str
    device: str
    mount_point: str
    created_partition: bool
    wiped_signatures: bool


def _wait_for_mount(partition_device: str, timeout: int = 10) -> str | None:
    """Poll /proc/mounts until partition_device appears. Returns mount point or None."""
    real_device = str(Path(partition_device).resolve())
    for _ in range(timeout * 2):
        for line in _read_proc_mounts().splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                if str(Path(parts[0]).resolve()) == real_device:
                    return parts[1]
            except (OSError, ValueError):
                pass
        time.sleep(0.5)
    return None


def provision_cartridge(
    device: str,
    label: str,
    force_repartition: bool = False,
    dry_run: bool = False,
    progress_cb: Callable[[str, int, int], None] | None = None,
    _partition_device_override: str | None = None,
) -> ProvisionResult:
    """
    Full provisioning workflow:
    1. Analyze device
    2. Wipe signatures
    3. Create GPT + single ext4 partition
    4. mkfs.ext4 -L <label>
    5. Wait for udisks2 to auto-mount
    6. Write .photonforge/cartridge.json
    """
    def _emit(step: str, current: int, total: int) -> None:
        if progress_cb:
            progress_cb(step, current, total)
        logger.info("[%d/%d] %s", current, total, step)

    device_path = Path(device)
    if not device_path.exists():
        raise ValueError(f"Device {device} does not exist")

    _emit("analyzing", 0, 5)
    analysis = analyze_device(device)

    _emit("wiping", 1, 5)
    wiped = False
    if not dry_run:
        real_device = str(Path(device).resolve())
        for line in _read_proc_mounts().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                try:
                    resolved = str(Path(parts[0]).resolve())
                    if resolved == real_device or resolved.startswith(real_device):
                        subprocess.run(["sudo", "-n", "umount", "-l", parts[1]], check=False)
                except (OSError, ValueError):
                    pass
        subprocess.run(["sudo", "-n", "wipefs", "-a", device], check=False)
        if analysis.partition_device and Path(analysis.partition_device).exists():
            subprocess.run(["sudo", "-n", "wipefs", "-a", analysis.partition_device], check=False)
        wiped = True

    partition_device = _partition_device_override or analysis.partition_device
    created_partition = False

    if not analysis.has_partitions or force_repartition:
        _emit("partitioning", 2, 5)
        if not dry_run:
            subprocess.run(
                ["sudo", "-n", "parted", device, "--script",
                 "mklabel", "gpt", "mkpart", "primary", "ext4", "0%", "100%"],
                check=True,
            )
            partition_device = f"{device}1"
            created_partition = True
    else:
        _emit("partitioning", 2, 5)

    _emit("formatting", 3, 5)
    if not dry_run and partition_device:
        subprocess.run(
            ["sudo", "-n", "mkfs.ext4", "-L", label, "-F", partition_device],
            check=True,
        )

    _emit("initializing", 4, 5)

    mount_point: str | None = None
    if not dry_run and partition_device:
        # Wait for udisks2 to auto-mount the newly formatted partition
        mount_point = _wait_for_mount(partition_device)
        if mount_point:
            _write_cartridge_meta(mount_point, label, analysis.size_bytes)
        else:
            logger.warning("Partition did not auto-mount within 10s — metadata not written")

    final_mount = mount_point or f"/media/{label}"

    return ProvisionResult(
        label=label,
        device=partition_device or device,
        mount_point=final_mount,
        created_partition=created_partition,
        wiped_signatures=wiped,
    )


def _write_cartridge_meta(mount_point: str, cartridge_id: str, size_bytes: int) -> None:
    """Write .photonforge/cartridge.json to the mounted cartridge."""
    photonforge_dir = Path(mount_point) / ".photonforge"
    photonforge_dir.mkdir(exist_ok=True)
    meta = {
        "cartridge_id": cartridge_id,
        "provisioned_at": datetime.now(timezone.utc).isoformat(),
        "provisioned_by": socket.gethostname(),
        "est_raw_capacity": size_bytes // (25 * 1024 * 1024),
        "description": "",
    }
    (photonforge_dir / "cartridge.json").write_text(json.dumps(meta, indent=2))
```

- [ ] **Step 4: Run the tests**

```bash
pytest tests/test_provision.py -v 2>&1 | tail -20
```

Expected: All pass. (`test_provision_writes_cartridge_json` may need adjustment if the `_partition_device_override` parameter doesn't match the analyze path — that's intentional; the test skips the real lsblk call by passing the override.)

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
pytest tests/ -v 2>&1 | tail -30
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/photo_workflow/provision.py tests/test_provision.py
git commit -m "feat: provision writes .photonforge/cartridge.json; detection by metadata file"
```

---

### Task 2: `sidecar_cli.py` — cartridge-list, reformat-done, new cartridge-update-meta

**Files:**
- Modify: `src/photo_workflow/sidecar_cli.py`
- Modify: `tests/test_sidecar_cli.py`

- [ ] **Step 1: Write the failing tests**

Read `tests/test_sidecar_cli.py`. Replace `test_cartridge_list_emits_cartridges_event_and_exits_zero` with the new version and add two new tests. The full replacements and additions:

```python
def test_cartridge_list_reads_from_metadata_files(tmp_path: Path) -> None:
    """cartridge-list scans mounted paths for .photonforge/cartridge.json."""
    mount = tmp_path / "photon001"
    mount.mkdir()
    meta_dir = mount / ".photonforge"
    meta_dir.mkdir()
    (meta_dir / "cartridge.json").write_text(json.dumps({
        "cartridge_id": "PHOTON-001",
        "provisioned_at": "2026-04-23T00:00:00+00:00",
        "provisioned_by": "yoga-910",
        "est_raw_capacity": 4300,
        "description": "test cartridge",
    }))

    fake_mounts = f"/dev/sda1 {mount} ext4 rw 0 0\n"

    runner = CliRunner()
    with patch("photo_workflow.sidecar_cli._read_proc_mounts", return_value=fake_mounts), \
         patch("photo_workflow.sidecar_cli.shutil.disk_usage",
               return_value=type("U", (), {"total": 500_000_000, "free": 200_000_000})()):
        result = runner.invoke(cli, ["cartridge-list"])

    assert result.exit_code == 0, result.output
    events = parse_events(result.output)
    assert events[0]["type"] == "cartridges"
    item = events[0]["items"][0]
    assert item["cartridge_id"] == "PHOTON-001"
    assert item["provisioned_by"] == "yoga-910"
    assert item["est_raw_capacity"] == 4300
    assert item["description"] == "test cartridge"
    assert item["free_bytes"] == 200_000_000
    assert item["size_bytes"] == 500_000_000


def test_cartridge_reformat_done_has_no_mount_point(tmp_path: Path) -> None:
    """cartridge-reformat reformat_done event no longer includes mount_point."""
    runner = CliRunner()
    with patch("photo_workflow.sidecar_cli.subprocess.run") as mock_run, \
         patch("photo_workflow.sidecar_cli.Path") as mock_path_cls:
        mock_path_cls.return_value.resolve.return_value = "/dev/sda1"
        mock_path_cls.return_value.read_text.return_value = ""
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(cli, [
            "cartridge-reformat",
            "--device", "/dev/sda1",
            "--label", "PHOTON-002",
        ])

    assert result.exit_code == 0, result.output
    events = parse_events(result.output)
    done = next(e for e in events if e["type"] == "reformat_done")
    assert "mount_point" not in done
    assert done["label"] == "PHOTON-002"


def test_cartridge_update_meta_updates_description(tmp_path: Path) -> None:
    """cartridge-update-meta updates description field in cartridge.json."""
    meta_dir = tmp_path / ".photonforge"
    meta_dir.mkdir()
    (meta_dir / "cartridge.json").write_text(json.dumps({
        "cartridge_id": "PHOTON-001",
        "provisioned_at": "2026-04-23T00:00:00+00:00",
        "provisioned_by": "yoga-910",
        "est_raw_capacity": 4300,
        "description": "",
    }))

    runner = CliRunner()
    result = runner.invoke(cli, [
        "cartridge-update-meta",
        "--mount-point", str(tmp_path),
        "--description", "Lisbon trip 2026",
    ])

    assert result.exit_code == 0, result.output
    events = parse_events(result.output)
    assert events[0]["type"] == "meta_updated"
    assert events[0]["cartridge_id"] == "PHOTON-001"

    updated = json.loads((meta_dir / "cartridge.json").read_text())
    assert updated["description"] == "Lisbon trip 2026"
    assert updated["cartridge_id"] == "PHOTON-001"  # unchanged


def test_cartridge_update_meta_fails_gracefully_when_no_file(tmp_path: Path) -> None:
    """cartridge-update-meta emits error if cartridge.json missing."""
    runner = CliRunner()
    result = runner.invoke(cli, [
        "cartridge-update-meta",
        "--mount-point", str(tmp_path),
        "--description", "anything",
    ])

    assert result.exit_code == 1
    events = parse_events(result.output)
    assert events[0]["type"] == "error"
```

Also add these imports at the top of `test_sidecar_cli.py` if not already present:
```python
import shutil
from unittest.mock import MagicMock
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_sidecar_cli.py::test_cartridge_list_reads_from_metadata_files tests/test_sidecar_cli.py::test_cartridge_reformat_done_has_no_mount_point tests/test_sidecar_cli.py::test_cartridge_update_meta_updates_description tests/test_sidecar_cli.py::test_cartridge_update_meta_fails_gracefully_when_no_file -v 2>&1 | tail -20
```

Expected: FAIL

- [ ] **Step 3: Update `sidecar_cli.py`**

Read `src/photo_workflow/sidecar_cli.py`. Make these changes:

**Add imports** at top (after existing imports):
```python
import shutil
import socket
from datetime import datetime, timezone
```

**Add `_read_proc_mounts` helper** after the `emit()` function:
```python
def _read_proc_mounts() -> str:
    """Read /proc/mounts. Extracted for testability."""
    return Path("/proc/mounts").read_text()
```

**Replace `cartridge-list` command** (the function currently calls `detect_cartridges`):
```python
@cli.command("cartridge-list")
def cartridge_list() -> None:
    """List all mounted PHOTON cartridges by scanning for .photonforge/cartridge.json."""
    try:
        items = []
        seen: set[str] = set()
        for line in _read_proc_mounts().splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            mount_point = parts[1]
            if mount_point in seen:
                continue
            seen.add(mount_point)
            meta_file = Path(mount_point) / ".photonforge" / "cartridge.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text())
                    usage = shutil.disk_usage(mount_point)
                    items.append({
                        **meta,
                        "mount_point": mount_point,
                        "device": parts[0],
                        "size_bytes": usage.total,
                        "free_bytes": usage.free,
                    })
                except Exception:  # noqa: BLE001
                    pass
        emit({"type": "cartridges", "items": items})
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "message": str(exc)})
        sys.exit(1)
```

**Update `cartridge-reformat` command** — replace the `emit({"type": "reformat_done", ...})` line:
```python
        emit({"type": "reformat_done", "label": label})
```
(Remove the `mount_point` field from the emitted event and remove the `mount_point = ...` line above it.)

**Add `cartridge-update-meta` command** after `cartridge-reformat`:
```python
@cli.command("cartridge-update-meta")
@click.option("--mount-point", required=True, help="Cartridge mount point")
@click.option("--description", required=True, help="New description text")
def cartridge_update_meta(mount_point: str, description: str) -> None:
    """Update the description field in .photonforge/cartridge.json."""
    try:
        meta_file = Path(mount_point) / ".photonforge" / "cartridge.json"
        if not meta_file.exists():
            raise FileNotFoundError(f"No cartridge.json at {mount_point}")
        meta = json.loads(meta_file.read_text())
        meta["description"] = description
        meta_file.write_text(json.dumps(meta, indent=2))
        emit({"type": "meta_updated", "cartridge_id": meta["cartridge_id"]})
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "message": str(exc)})
        sys.exit(1)
```

- [ ] **Step 4: Run the new tests**

```bash
pytest tests/test_sidecar_cli.py::test_cartridge_list_reads_from_metadata_files tests/test_sidecar_cli.py::test_cartridge_reformat_done_has_no_mount_point tests/test_sidecar_cli.py::test_cartridge_update_meta_updates_description tests/test_sidecar_cli.py::test_cartridge_update_meta_fails_gracefully_when_no_file -v 2>&1 | tail -20
```

Expected: All pass.

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v 2>&1 | tail -30
```

Expected: All pass. (`test_cartridge_list_emits_cartridges_event_and_exits_zero` should be deleted since it tested the old API — remove it from `test_sidecar_cli.py`.)

- [ ] **Step 6: Commit**

```bash
git add src/photo_workflow/sidecar_cli.py tests/test_sidecar_cli.py
git commit -m "feat: cartridge-list reads metadata files; add cartridge-update-meta command"
```

---

### Task 3: Rewrite `mount_monitor.rs`

**Files:**
- Rewrite: `photonforge-gui/src-tauri/src/mount_monitor.rs`

- [ ] **Step 1: Write the failing tests**

Replace the entire `#[cfg(test)]` section at the bottom of `mount_monitor.rs` with:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    fn mock_meta(cartridge_id: &str, mount_point: &str) -> CartridgeMeta {
        CartridgeMeta {
            cartridge_id: cartridge_id.to_string(),
            device: "/dev/sda1".to_string(),
            mount_point: mount_point.to_string(),
            free_bytes: 100,
            size_bytes: 200,
            provisioned_at: "2026-04-23T00:00:00+00:00".to_string(),
            provisioned_by: "yoga-910".to_string(),
            est_raw_capacity: 4300,
            description: "".to_string(),
        }
    }

    #[test]
    fn empty_mounts_yields_empty_state() {
        let state = parse_proc_mounts("", |_| None, |_| None);
        assert!(state.cartridges.is_empty());
        assert!(state.sd_candidates.is_empty());
    }

    #[test]
    fn cartridge_detected_by_metadata_file() {
        let content = "/dev/sda1 /media/alex/PHOTON-001 ext4 rw 0 0\n";
        let state = parse_proc_mounts(
            content,
            |mp| {
                if mp == "/media/alex/PHOTON-001" {
                    Some(mock_meta("PHOTON-001", mp))
                } else {
                    None
                }
            },
            |_| None,
        );
        assert_eq!(state.cartridges.len(), 1);
        assert_eq!(state.cartridges[0].cartridge_id, "PHOTON-001");
        assert_eq!(state.cartridges[0].mount_point, "/media/alex/PHOTON-001");
        assert!(state.sd_candidates.is_empty());
    }

    #[test]
    fn sd_candidate_detected_without_metadata_file() {
        let content = "/dev/sdb1 /media/alex/B9D9-FDD6 exfat rw 0 0\n";
        let state = parse_proc_mounts(
            content,
            |_| None,
            |_| Some("B9D9-FDD6".to_string()),
        );
        assert!(state.cartridges.is_empty());
        assert_eq!(state.sd_candidates.len(), 1);
        assert_eq!(state.sd_candidates[0].device, "/dev/sdb1");
        assert_eq!(state.sd_candidates[0].mount_point, "/media/alex/B9D9-FDD6");
        assert_eq!(state.sd_candidates[0].label, Some("B9D9-FDD6".to_string()));
    }

    #[test]
    fn both_cartridge_and_sd_detected() {
        let content = "/dev/sda1 /media/alex/PHOTON-001 ext4 rw 0 0\n\
                       /dev/sdb1 /media/alex/B9D9-FDD6 exfat rw 0 0\n";
        let state = parse_proc_mounts(
            content,
            |mp| {
                if mp == "/media/alex/PHOTON-001" {
                    Some(mock_meta("PHOTON-001", mp))
                } else {
                    None
                }
            },
            |_| None,
        );
        assert_eq!(state.cartridges.len(), 1);
        assert_eq!(state.sd_candidates.len(), 1);
    }

    #[test]
    fn non_removable_device_ignored() {
        // nvme is not removable — must not appear in either list
        let content = "/dev/nvme0n1p1 /media/alex/DATA ext4 rw 0 0\n";
        let state = parse_proc_mounts(content, |_| None, |_| None);
        assert!(state.cartridges.is_empty());
        assert!(state.sd_candidates.is_empty());
    }

    #[test]
    fn malformed_line_ignored() {
        let content = "incomplete\n/dev/sda1 /media/alex/PHOTON-001 ext4 rw 0 0\n";
        let state = parse_proc_mounts(
            content,
            |mp| {
                if mp == "/media/alex/PHOTON-001" {
                    Some(mock_meta("PHOTON-001", mp))
                } else {
                    None
                }
            },
            |_| None,
        );
        assert_eq!(state.cartridges.len(), 1);
    }

    #[test]
    fn sd_label_none_when_not_found() {
        let content = "/dev/sdb1 /media/alex/UNLABELLED ext4 rw 0 0\n";
        let state = parse_proc_mounts(content, |_| None, |_| None);
        assert_eq!(state.sd_candidates.len(), 1);
        assert_eq!(state.sd_candidates[0].label, None);
    }
}
```

- [ ] **Step 2: Run to verify tests fail (won't compile)**

```bash
ssh alex@10.27.27.10 'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && cargo test --no-default-features 2>&1 | tail -20'
```

Expected: Compile error — `CartridgeMeta`, `SdCandidate`, `parse_proc_mounts` with new signature don't exist yet.

- [ ] **Step 3: Rewrite `mount_monitor.rs`**

Replace the entire file with:

```rust
use serde::Serialize;
#[cfg(feature = "tauri")]
use tauri::{AppHandle, Emitter};

#[derive(Clone, Serialize, Debug, PartialEq)]
pub struct CartridgeMeta {
    pub cartridge_id: String,
    pub device: String,
    pub mount_point: String,
    pub free_bytes: u64,
    pub size_bytes: u64,
    pub provisioned_at: String,
    pub provisioned_by: String,
    pub est_raw_capacity: u64,
    pub description: String,
}

#[derive(Clone, Serialize, Debug, PartialEq)]
pub struct SdCandidate {
    pub device: String,
    pub mount_point: String,
    pub label: Option<String>,
}

#[derive(Clone, Serialize, Debug, PartialEq)]
pub struct DeviceState {
    pub cartridges: Vec<CartridgeMeta>,
    pub sd_candidates: Vec<SdCandidate>,
}

/// Parse /proc/mounts content and classify each removable USB block device.
/// `check_cartridge(mount_point)` returns Some(CartridgeMeta) if the drive
/// has a .photonforge/cartridge.json, None otherwise.
/// `get_label(device)` returns the filesystem label if one exists.
pub fn parse_proc_mounts(
    content: &str,
    check_cartridge: impl Fn(&str) -> Option<CartridgeMeta>,
    get_label: impl Fn(&str) -> Option<String>,
) -> DeviceState {
    let mut cartridges: Vec<CartridgeMeta> = Vec::new();
    let mut sd_candidates: Vec<SdCandidate> = Vec::new();

    for line in content.lines() {
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() < 2 {
            continue;
        }
        let device = parts[0];
        let mount_point = parts[1];

        if !is_removable_block_device(device) {
            continue;
        }

        if let Some(mut meta) = check_cartridge(mount_point) {
            let (free, total) = disk_usage(mount_point);
            meta.device = device.to_string();
            meta.free_bytes = free;
            meta.size_bytes = total;
            cartridges.push(meta);
        } else {
            sd_candidates.push(SdCandidate {
                device: device.to_string(),
                mount_point: mount_point.to_string(),
                label: get_label(device),
            });
        }
    }

    DeviceState { cartridges, sd_candidates }
}

fn is_removable_block_device(device: &str) -> bool {
    let name = device.strip_prefix("/dev/").unwrap_or("");
    if !name.starts_with("sd") {
        return false;
    }
    let base = name.trim_end_matches(|c: char| c.is_ascii_digit());
    std::fs::read_to_string(format!("/sys/block/{}/removable", base))
        .map(|s| s.trim() == "1")
        .unwrap_or(false)
}

fn read_cartridge_meta(mount_point: &str) -> Option<CartridgeMeta> {
    let meta_path = std::path::Path::new(mount_point)
        .join(".photonforge")
        .join("cartridge.json");
    let content = std::fs::read_to_string(&meta_path).ok()?;
    let v: serde_json::Value = serde_json::from_str(&content).ok()?;
    Some(CartridgeMeta {
        cartridge_id: v["cartridge_id"].as_str().unwrap_or("").to_string(),
        device: String::new(), // filled in by parse_proc_mounts
        mount_point: mount_point.to_string(),
        free_bytes: 0, // filled in by parse_proc_mounts
        size_bytes: 0, // filled in by parse_proc_mounts
        provisioned_at: v["provisioned_at"].as_str().unwrap_or("").to_string(),
        provisioned_by: v["provisioned_by"].as_str().unwrap_or("").to_string(),
        est_raw_capacity: v["est_raw_capacity"].as_u64().unwrap_or(0),
        description: v["description"].as_str().unwrap_or("").to_string(),
    })
}

fn device_label(device: &str) -> Option<String> {
    let by_label = std::path::Path::new("/dev/disk/by-label");
    if !by_label.exists() {
        return None;
    }
    let canonical_device = std::fs::canonicalize(device).ok()?;
    std::fs::read_dir(by_label).ok()?.find_map(|entry| {
        let entry = entry.ok()?;
        let target = std::fs::canonicalize(entry.path()).ok()?;
        if target == canonical_device {
            Some(entry.file_name().to_string_lossy().into_owned())
        } else {
            None
        }
    })
}

fn disk_usage(mount_point: &str) -> (u64, u64) {
    // Returns (free_bytes, total_bytes) via df -B1
    let output = std::process::Command::new("df")
        .args(["-B1", mount_point])
        .output()
        .unwrap_or_default();
    let stdout = String::from_utf8_lossy(&output.stdout);
    // df -B1: Filesystem  1B-blocks  Used  Available  Use%  Mounted on
    for line in stdout.lines().skip(1) {
        let cols: Vec<&str> = line.split_whitespace().collect();
        if cols.len() >= 4 {
            let total = cols[1].parse::<u64>().unwrap_or(0);
            let avail = cols[3].parse::<u64>().unwrap_or(0);
            return (avail, total);
        }
    }
    (0, 0)
}

#[cfg(feature = "tauri")]
#[tauri::command]
pub fn get_device_state() -> DeviceState {
    read_mounts()
}

#[cfg(feature = "tauri")]
fn read_mounts() -> DeviceState {
    let content = std::fs::read_to_string("/proc/mounts").unwrap_or_default();
    parse_proc_mounts(&content, read_cartridge_meta, device_label)
}

#[cfg(feature = "tauri")]
pub fn run(app: AppHandle) {
    std::thread::sleep(std::time::Duration::from_millis(500));
    let mut prev = read_mounts();
    let _ = app.emit("device-state-changed", prev.clone());

    let mut force_remaining: u8 = 5;
    loop {
        std::thread::sleep(std::time::Duration::from_secs(2));
        let next = read_mounts();
        if next != prev || force_remaining > 0 {
            let _ = app.emit("device-state-changed", next.clone());
            prev = next;
            if force_remaining > 0 {
                force_remaining -= 1;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    // (paste the test block from Step 1 here)
}
```

- [ ] **Step 4: Run the Rust tests on Yoga**

```bash
ssh alex@10.27.27.10 'cd ~/PHOTONFORGE_Photo-Workflow && git pull --ff-only && cd photonforge-gui && cargo test --no-default-features 2>&1 | tail -30'
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add photonforge-gui/src-tauri/src/mount_monitor.rs
git commit -m "feat: rewrite mount_monitor to detect cartridges by metadata file"
```

---

### Task 4: Update `sidecar.ts` — types and new function

**Files:**
- Modify: `photonforge-gui/src/lib/sidecar.ts`

No new test file needed here — types are validated by TypeScript compilation and existing tests.

- [ ] **Step 1: Update `sidecar.ts`**

Read `photonforge-gui/src/lib/sidecar.ts`. Make these changes:

**Replace `CartridgeInfo` interface:**
```typescript
export interface CartridgeInfo {
  cartridge_id: string;
  device: string;
  mount_point: string;
  free_bytes: number;
  size_bytes: number;
  provisioned_at: string;
  provisioned_by: string;
  est_raw_capacity: number;
  description: string;
}
```

**Replace `ReformatDoneEvent` interface** (remove `mount_point`):
```typescript
export interface ReformatDoneEvent {
  type: "reformat_done";
  label: string;
}
```

**Add `MetaUpdatedEvent` interface** after `ReformatDoneEvent`:
```typescript
export interface MetaUpdatedEvent {
  type: "meta_updated";
  cartridge_id: string;
}
```

**Add `MetaUpdatedEvent` to the `SidecarEvent` union:**
```typescript
export type SidecarEvent =
  | ProgressEvent
  | DoneEvent
  | ErrorEvent
  | CartridgesEvent
  | ReformatDoneEvent
  | ProvisionDoneEvent
  | StageDoneEvent
  | SdEjectedEvent
  | MetaUpdatedEvent;
```

**Add `updateCartridgeMeta` function** after `listCartridges`:
```typescript
export async function updateCartridgeMeta(
  mountPoint: string,
  description: string,
): Promise<void> {
  const cmd = Command.sidecar("binaries/photo-workflow-sidecar", [
    "cartridge-update-meta",
    "--mount-point", mountPoint,
    "--description", description,
  ]);
  const result = await cmd.execute();
  for (const line of result.stdout.split("\n")) {
    const event = parseLine(line.trim());
    if (event?.type === "error") {
      throw new Error((event as ErrorEvent).message);
    }
  }
}
```

- [ ] **Step 2: Verify TypeScript compiles on Yoga**

```bash
ssh alex@10.27.27.10 'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && npx tsc --noEmit 2>&1 | head -20'
```

Expected: No errors (or only errors unrelated to sidecar.ts).

- [ ] **Step 3: Commit**

```bash
git add photonforge-gui/src/lib/sidecar.ts
git commit -m "feat: update CartridgeInfo with full metadata fields; add MetaUpdatedEvent and updateCartridgeMeta"
```

---

### Task 5: Update `devices.ts` and `ingest.ts`

**Files:**
- Modify: `photonforge-gui/src/stores/devices.ts`
- Modify: `photonforge-gui/src/stores/ingest.ts`

- [ ] **Step 1: Replace `devices.ts`**

Replace the entire file:

```typescript
import { writable } from "svelte/store";
import type { CartridgeInfo } from "../lib/sidecar";

export interface SdCandidate {
  device: string;
  mount_point: string;
  label: string | null;
}

export interface DeviceState {
  cartridges: CartridgeInfo[];
  sd_candidates: SdCandidate[];
}

const initial: DeviceState = {
  cartridges: [],
  sd_candidates: [],
};

export const deviceState = writable<DeviceState>(initial);

// Wired in main.ts / App.svelte to receive Tauri events
export function applyDeviceState(raw: unknown) {
  deviceState.set(raw as DeviceState);
}
```

- [ ] **Step 2: Update `ingest.ts`** — replace the old `step: "copying"` initial value (already fixed) and ensure no references to old `DeviceState` fields remain. Read the file and verify `ssd_mount_point`, `sd_path` are not referenced.

- [ ] **Step 3: Verify TypeScript compiles on Yoga**

```bash
ssh alex@10.27.27.10 'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && npx tsc --noEmit 2>&1 | head -30'
```

Expected: Errors only from CartridgeManager.svelte and IngestDashboard.svelte which still reference old field names — that's expected and will be fixed in Tasks 6 and 7.

- [ ] **Step 4: Commit**

```bash
git add photonforge-gui/src/stores/devices.ts photonforge-gui/src/stores/ingest.ts
git commit -m "feat: update DeviceState to cartridges[] + sd_candidates[] shape"
```

---

### Task 6: Rewrite `CartridgeManager.svelte` + update test

**Files:**
- Rewrite: `photonforge-gui/src/panels/CartridgeManager.svelte`
- Modify: `photonforge-gui/src/panels/CartridgeManager.test.ts`

- [ ] **Step 1: Update `CartridgeManager.test.ts`**

Replace the entire file:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import CartridgeManager from "./CartridgeManager.svelte";
import { deviceState } from "../stores/devices";
import type { CartridgeInfo } from "../lib/sidecar";

vi.mock("../lib/sidecar", () => ({
  listDrives: vi.fn().mockResolvedValue([]),
  provisionCartridge: vi.fn(),
  reformatCartridge: vi.fn(),
  updateCartridgeMeta: vi.fn().mockResolvedValue(undefined),
}));

const mockCartridge: CartridgeInfo = {
  cartridge_id: "PHOTON-001",
  device: "/dev/sda1",
  mount_point: "/media/alex/PHOTON-001",
  free_bytes: 214_748_364_800,
  size_bytes: 500_107_862_016,
  provisioned_at: "2026-04-01T10:00:00+00:00",
  provisioned_by: "yoga-910",
  est_raw_capacity: 19200,
  description: "Lisbon trip",
};

describe("CartridgeManager", () => {
  beforeEach(() => {
    deviceState.set({ cartridges: [], sd_candidates: [] });
    vi.clearAllMocks();
  });

  it("renders cartridge card from deviceState", async () => {
    deviceState.set({ cartridges: [mockCartridge], sd_candidates: [] });
    render(CartridgeManager);
    await waitFor(() => {
      expect(screen.getByText("PHOTON-001")).toBeInTheDocument();
      expect(screen.getByText("yoga-910")).toBeInTheDocument();
      expect(screen.getByText("19200 RAW")).toBeInTheDocument();
    });
  });

  it("shows empty state when no cartridges", async () => {
    render(CartridgeManager);
    await waitFor(() => {
      expect(screen.getByText(/no photon cartridges mounted/i)).toBeInTheDocument();
    });
  });

  it("reformat confirm button disabled until cartridge_id typed", async () => {
    deviceState.set({ cartridges: [mockCartridge], sd_candidates: [] });
    render(CartridgeManager);
    await waitFor(() => screen.getByText("PHOTON-001"));

    fireEvent.click(screen.getByRole("button", { name: /reformat/i }));
    await waitFor(() => screen.getByLabelText(/type the cartridge id/i));

    const btn = screen.getByRole("button", { name: /confirm reformat/i });
    expect(btn).toBeDisabled();
  });

  it("reformat confirm enabled when cartridge_id matches", async () => {
    deviceState.set({ cartridges: [mockCartridge], sd_candidates: [] });
    render(CartridgeManager);
    await waitFor(() => screen.getByText("PHOTON-001"));

    fireEvent.click(screen.getByRole("button", { name: /reformat/i }));
    await waitFor(() => screen.getByLabelText(/type the cartridge id/i));

    const input = screen.getByLabelText(/type the cartridge id/i);
    fireEvent.input(input, { target: { value: "PHOTON-001" } });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /confirm reformat/i })).not.toBeDisabled();
    });
  });

  it("description field shows current description", async () => {
    deviceState.set({ cartridges: [mockCartridge], sd_candidates: [] });
    render(CartridgeManager);
    await waitFor(() => {
      const input = screen.getByDisplayValue("Lisbon trip");
      expect(input).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
ssh alex@10.27.27.10 'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && npx vitest run src/panels/CartridgeManager.test.ts 2>&1 | tail -20'
```

Expected: FAIL

- [ ] **Step 3: Rewrite `CartridgeManager.svelte`**

Replace the entire file:

```svelte
<script lang="ts">
  import { deviceState } from "../stores/devices";
  import { listDrives, provisionCartridge, reformatCartridge, updateCartridgeMeta, type CartridgeInfo, type DriveInfo, type ProvisionEvent, type SidecarEvent } from "../lib/sidecar";

  $: cartridges = $deviceState.cartridges;

  // ── Provision ────────────────────────────────────────────────────────────
  let showProvisionSheet = false;
  let availableDrives: DriveInfo[] = [];
  let drivesLoading = false;
  let provisionDevice = "";
  let provisionLabel = "";
  let provisionForceRepartition = false;
  let provisionDryRun = false;
  let provisionRunning = false;
  let provisionStep = "";
  let provisionCurrent = 0;
  let provisionTotal = 5;
  let provisionError = "";

  $: selectedDrive = availableDrives.find((d) => d.device === provisionDevice) ?? null;

  async function openProvision() {
    provisionDevice = "";
    provisionLabel = nextId(cartridges);
    provisionForceRepartition = false;
    provisionDryRun = false;
    provisionError = "";
    showProvisionSheet = true;
    drivesLoading = true;
    try {
      availableDrives = await listDrives();
    } finally {
      drivesLoading = false;
    }
  }

  function closeProvision() {
    showProvisionSheet = false;
    provisionRunning = false;
    provisionStep = "";
    provisionError = "";
  }

  async function confirmProvision() {
    if (!provisionDevice || !provisionLabel) return;
    provisionRunning = true;
    provisionError = "";
    try {
      await provisionCartridge(
        provisionDevice, provisionLabel, provisionForceRepartition, provisionDryRun,
        (event: ProvisionEvent) => {
          if (event.type === "progress") {
            provisionStep = event.step;
            provisionCurrent = event.current;
            provisionTotal = event.total;
          } else if (event.type === "provision_done") {
            provisionRunning = false;
            closeProvision();
          } else if (event.type === "error") {
            provisionError = event.message;
            provisionRunning = false;
          }
        },
      );
    } catch (err) {
      provisionError = err instanceof Error ? err.message : String(err);
      provisionRunning = false;
    }
  }

  function nextId(carts: CartridgeInfo[]): string {
    const existing = carts.map((c) => {
      const m = c.cartridge_id.match(/PHOTON-(\d{3})/);
      return m ? parseInt(m[1], 10) : 0;
    });
    for (let i = 1; i < 1000; i++) {
      if (!existing.includes(i)) return `PHOTON-${String(i).padStart(3, "0")}`;
    }
    return "PHOTON-999";
  }

  // ── Reformat ─────────────────────────────────────────────────────────────
  let reformatTarget: CartridgeInfo | null = null;
  let confirmId = "";
  let reformatRunning = false;
  let reformatStep = "";
  let reformatError = "";

  function openReformat(c: CartridgeInfo) {
    reformatTarget = c;
    confirmId = "";
    reformatError = "";
  }

  function closeReformat() {
    reformatTarget = null;
    reformatRunning = false;
    reformatStep = "";
    reformatError = "";
  }

  async function confirmReformat() {
    if (!reformatTarget || confirmId !== reformatTarget.cartridge_id) return;
    reformatRunning = true;
    reformatError = "";
    const target = reformatTarget;

    await reformatCartridge(
      target.device,
      target.cartridge_id,
      (event: SidecarEvent) => {
        if (event.type === "progress") {
          reformatStep = event.step;
        } else if (event.type === "reformat_done") {
          reformatRunning = false;
          closeReformat();
        } else if (event.type === "error") {
          reformatError = (event as any).message;
          reformatRunning = false;
        }
      },
    );
  }

  // ── Description edit ─────────────────────────────────────────────────────
  async function saveDescription(c: CartridgeInfo, value: string) {
    try {
      await updateCartridgeMeta(c.mount_point, value);
    } catch (err) {
      console.error("Failed to save description:", err);
    }
  }

  // ── Formatting helpers ────────────────────────────────────────────────────
  function formatBytes(bytes: number): string {
    if (bytes >= 1e12) return `${(bytes / 1e12).toFixed(1)} TB`;
    if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
    return `${(bytes / 1e6).toFixed(0)} MB`;
  }

  function formatDate(iso: string): string {
    try {
      return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
    } catch {
      return iso;
    }
  }

  function usedPercent(c: CartridgeInfo): number {
    return ((c.size_bytes - c.free_bytes) / c.size_bytes) * 100;
  }
</script>

<div class="cartridge-panel">
  <div class="panel-header">
    <h2>Cartridge Manager</h2>
    <button class="provision-new-btn" on:click={openProvision}>+ Provision New</button>
  </div>

  {#if cartridges.length === 0}
    <p class="muted">No PHOTON cartridges mounted.</p>
  {:else}
    <div class="cartridge-list">
      {#each cartridges as c (c.cartridge_id)}
        <div class="cartridge-card">
          <div class="card-header">
            <span class="cartridge-id">{c.cartridge_id}</span>
            <span class="mount-point">{c.mount_point}</span>
          </div>

          <div class="meta-grid">
            <span class="meta-label">Provisioned</span>
            <span class="meta-value">{formatDate(c.provisioned_at)} by {c.provisioned_by}</span>
            <span class="meta-label">Capacity</span>
            <span class="meta-value">{c.est_raw_capacity} RAW · {formatBytes(c.size_bytes)}</span>
          </div>

          <div class="description-row">
            <label class="meta-label" for="desc-{c.cartridge_id}">Notes</label>
            <input
              id="desc-{c.cartridge_id}"
              class="description-input"
              value={c.description}
              placeholder="Add a description…"
              on:blur={(e) => saveDescription(c, e.currentTarget.value)}
            />
          </div>

          <div class="space-bar-row">
            <div class="space-bar">
              <div class="space-fill" style="width: {usedPercent(c)}%"></div>
            </div>
            <span class="space-text">{formatBytes(c.free_bytes)} free of {formatBytes(c.size_bytes)}</span>
          </div>

          <button class="reformat-btn" on:click={() => openReformat(c)}>Reformat</button>
        </div>
      {/each}
    </div>
  {/if}

  {#if showProvisionSheet}
    <div class="sheet-overlay" role="dialog" aria-modal="true">
      <div class="sheet">
        {#if provisionRunning}
          <h3>Provisioning {provisionLabel}…</h3>
          <p class="muted">{provisionStep}</p>
          <div class="progress-bar">
            <div class="progress-fill" style="width: {(provisionCurrent / provisionTotal) * 100}%"></div>
          </div>
          <p class="progress-text">{provisionCurrent} / {provisionTotal}</p>
          <button class="cancel-btn" on:click={closeProvision}>Cancel</button>
        {:else}
          <h3>Provision New Cartridge</h3>
          {#if provisionError}<p class="error">{provisionError}</p>{/if}
          <div class="form-group">
            <label>Drive to provision:</label>
            {#if drivesLoading}
              <p class="muted">Scanning for USB drives…</p>
            {:else if availableDrives.length === 0}
              <p class="warning">No USB drives detected.</p>
            {:else}
              <div class="drive-picker">
                {#each availableDrives as drive}
                  <button
                    class="drive-option"
                    class:selected={provisionDevice === drive.device}
                    on:click={() => (provisionDevice = drive.device)}
                  >
                    <span class="drive-model">{drive.model}</span>
                    <span class="drive-meta">{drive.device} · {formatBytes(drive.size_bytes)}</span>
                    {#if drive.label}<span class="drive-label-badge">{drive.label}</span>{/if}
                  </button>
                {/each}
              </div>
            {/if}
          </div>
          {#if selectedDrive}
            <div class="selected-summary">
              Formatting <strong>{selectedDrive.device}</strong> — <span class="warning">all data will be erased</span>
            </div>
          {/if}
          <div class="form-group">
            <label for="provision-label">Cartridge ID:</label>
            <input id="provision-label" bind:value={provisionLabel} placeholder="PHOTON-001" />
          </div>
          <div class="form-group">
            <label><input type="checkbox" bind:checked={provisionForceRepartition} /> Force repartition</label>
          </div>
          <div class="form-group">
            <label><input type="checkbox" bind:checked={provisionDryRun} /> Dry run</label>
          </div>
          <div class="sheet-actions">
            <button class="cancel-btn" on:click={closeProvision}>Cancel</button>
            <button class="primary-btn" disabled={!provisionDevice || !provisionLabel} on:click={confirmProvision}>Start</button>
          </div>
        {/if}
      </div>
    </div>
  {/if}

  {#if reformatTarget}
    <div class="sheet-overlay" role="dialog" aria-modal="true">
      <div class="sheet">
        {#if reformatRunning}
          <h3>Reformatting {reformatTarget.cartridge_id}…</h3>
          <p class="muted">{reformatStep}</p>
        {:else}
          <h3>Reformat {reformatTarget.cartridge_id}?</h3>
          <p class="warning">All data will be erased. This cannot be undone.</p>
          {#if reformatError}<p class="error">{reformatError}</p>{/if}
          <label for="confirm-id">Type the cartridge ID to confirm:</label>
          <input
            id="confirm-id"
            bind:value={confirmId}
            placeholder={reformatTarget.cartridge_id}
            autocomplete="off"
          />
          <div class="sheet-actions">
            <button class="cancel-btn" on:click={closeReformat}>Cancel</button>
            <button
              class="danger-btn"
              disabled={confirmId !== reformatTarget.cartridge_id}
              on:click={confirmReformat}
            >Confirm Reformat</button>
          </div>
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  .cartridge-panel { display: flex; flex-direction: column; height: 100%; padding: 2.5rem 3rem; gap: 1.25rem; }
  .panel-header { display: flex; justify-content: space-between; align-items: center; }
  h2 { color: var(--text-primary, #fff); margin: 0; }
  .provision-new-btn { padding: 0.5rem 1rem; background: var(--accent, #6366f1); color: #fff; border: none; border-radius: 0.375rem; cursor: pointer; }
  .muted { color: var(--text-muted, #888); }
  .cartridge-list { display: flex; flex-direction: column; gap: 1rem; }
  .cartridge-card { background: var(--surface, #1a1a1a); border-radius: 0.5rem; padding: 1rem; display: flex; flex-direction: column; gap: 0.75rem; }
  .card-header { display: flex; justify-content: space-between; align-items: baseline; }
  .cartridge-id { color: var(--text-primary, #fff); font-weight: 600; }
  .mount-point { color: var(--text-muted, #888); font-size: 0.85rem; }
  .meta-grid { display: grid; grid-template-columns: auto 1fr; gap: 0.25rem 0.75rem; }
  .meta-label { color: var(--text-muted, #888); font-size: 0.8rem; }
  .meta-value { color: var(--text-primary, #fff); font-size: 0.85rem; }
  .description-row { display: flex; flex-direction: column; gap: 0.25rem; }
  .description-input { padding: 0.4rem 0.6rem; background: var(--surface-elevated, #222); border: 1px solid var(--border, #333); border-radius: 0.375rem; color: var(--text-primary, #fff); font-size: 0.9rem; }
  .space-bar-row { display: flex; align-items: center; gap: 0.75rem; }
  .space-bar { flex: 1; height: 6px; background: var(--border, #333); border-radius: 3px; overflow: hidden; }
  .space-fill { height: 100%; background: var(--accent, #6366f1); }
  .space-text { color: var(--text-muted, #888); font-size: 0.8rem; white-space: nowrap; }
  .reformat-btn { padding: 0.5rem 1rem; background: transparent; color: var(--error, #ef4444); border: 1px solid var(--error, #ef4444); border-radius: 0.375rem; cursor: pointer; align-self: flex-end; }
  .sheet-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; z-index: 100; }
  .sheet { background: var(--surface-elevated, #222); border-radius: 1rem; padding: 2rem; width: 90%; max-width: 560px; max-height: 80vh; overflow-y: auto; display: flex; flex-direction: column; gap: 1rem; }
  h3 { color: var(--text-primary, #fff); margin: 0; }
  .warning { color: var(--warning, #f59e0b); }
  .error { color: var(--error, #ef4444); }
  label { color: var(--text-muted, #888); font-size: 0.9rem; }
  input:not([type="checkbox"]) { padding: 0.6rem; background: var(--surface, #1a1a1a); border: 1px solid var(--border, #333); border-radius: 0.375rem; color: var(--text-primary, #fff); font-size: 1rem; }
  .sheet-actions { display: flex; gap: 0.75rem; }
  .cancel-btn { flex: 1; padding: 0.75rem; background: transparent; color: var(--text-muted, #888); border: 1px solid var(--border, #333); border-radius: 0.375rem; cursor: pointer; }
  .danger-btn { flex: 1; padding: 0.75rem; background: var(--error, #ef4444); color: #fff; border: none; border-radius: 0.375rem; cursor: pointer; }
  .danger-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .primary-btn { flex: 1; padding: 0.75rem; background: var(--accent, #6366f1); color: #fff; border: none; border-radius: 0.375rem; cursor: pointer; }
  .primary-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .form-group { display: flex; flex-direction: column; gap: 0.5rem; }
  .progress-bar { height: 6px; background: var(--border, #333); border-radius: 3px; overflow: hidden; }
  .progress-fill { height: 100%; background: var(--accent, #6366f1); transition: width 0.3s; }
  .progress-text { color: var(--text-muted, #888); font-size: 0.9rem; text-align: center; }
  .drive-picker { display: flex; flex-direction: column; gap: 0.5rem; }
  .drive-option { display: flex; flex-direction: column; gap: 0.2rem; padding: 0.75rem 1rem; background: var(--surface, #1a1a1a); border: 1px solid var(--border, #333); border-radius: 0.5rem; cursor: pointer; text-align: left; width: 100%; }
  .drive-option:hover { border-color: var(--accent, #6366f1); }
  .drive-option.selected { border-color: var(--accent, #6366f1); background: rgba(99,102,241,0.1); }
  .drive-model { color: var(--text-primary, #fff); font-size: 0.95rem; font-weight: 500; }
  .drive-meta { color: var(--text-muted, #888); font-size: 0.8rem; font-family: monospace; }
  .drive-label-badge { display: inline-block; font-size: 0.75rem; padding: 0.1rem 0.4rem; background: rgba(245,158,11,0.2); color: var(--warning, #f59e0b); border-radius: 0.25rem; }
  .selected-summary { font-size: 0.85rem; color: var(--text-muted, #888); padding: 0.5rem 0.75rem; background: rgba(239,68,68,0.08); border-radius: 0.375rem; border-left: 3px solid var(--error, #ef4444); }
</style>
```

- [ ] **Step 4: Run CartridgeManager tests on Yoga**

```bash
ssh alex@10.27.27.10 'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && npx vitest run src/panels/CartridgeManager.test.ts 2>&1 | tail -20'
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add photonforge-gui/src/panels/CartridgeManager.svelte photonforge-gui/src/panels/CartridgeManager.test.ts
git commit -m "feat: CartridgeManager reads from deviceState; adds metadata fields and description editing"
```

---

### Task 7: Update `IngestDashboard.svelte` — SD source picker

**Files:**
- Modify: `photonforge-gui/src/panels/IngestDashboard.svelte`
- Modify: `photonforge-gui/src/panels/IngestDashboard.test.ts`

- [ ] **Step 1: Update `IngestDashboard.test.ts`**

Replace the `setDeviceState` helper and update all tests to use the new `DeviceState` shape:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import IngestDashboard from "./IngestDashboard.svelte";
import { deviceState } from "../stores/devices";
import type { CartridgeInfo } from "../lib/sidecar";
import type { SdCandidate } from "../stores/devices";

vi.mock("../lib/sidecar", () => ({
  runIngest: vi.fn(),
}));

import { runIngest } from "../lib/sidecar";

const mockCartridge: CartridgeInfo = {
  cartridge_id: "PHOTON-001",
  device: "/dev/sda1",
  mount_point: "/media/alex/PHOTON-001",
  free_bytes: 214_748_364_800,
  size_bytes: 500_107_862_016,
  provisioned_at: "2026-04-01T10:00:00+00:00",
  provisioned_by: "yoga-910",
  est_raw_capacity: 19200,
  description: "",
};

const mockSd: SdCandidate = {
  device: "/dev/sdb1",
  mount_point: "/media/alex/B9D9-FDD6",
  label: "B9D9-FDD6",
};

function setDeviceState(carts: CartridgeInfo[], sds: SdCandidate[]) {
  deviceState.set({ cartridges: carts, sd_candidates: sds });
}

describe("IngestDashboard", () => {
  beforeEach(() => {
    setDeviceState([], []);
    vi.clearAllMocks();
  });

  it("Start Ingest disabled when no cartridge mounted", () => {
    setDeviceState([], [mockSd]);
    render(IngestDashboard);
    expect(screen.getByRole("button", { name: /start ingest/i })).toBeDisabled();
  });

  it("Start Ingest disabled when no SD candidate", () => {
    setDeviceState([mockCartridge], []);
    render(IngestDashboard);
    expect(screen.getByRole("button", { name: /start ingest/i })).toBeDisabled();
  });

  it("Start Ingest enabled when both present", async () => {
    setDeviceState([mockCartridge], [mockSd]);
    render(IngestDashboard);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /start ingest/i })).not.toBeDisabled();
    });
  });

  it("Shows SD candidate label in source picker", async () => {
    setDeviceState([mockCartridge], [mockSd]);
    render(IngestDashboard);
    await waitFor(() => {
      expect(screen.getByText(/B9D9-FDD6/)).toBeInTheDocument();
    });
  });

  it("Shows warning when no SD present", () => {
    setDeviceState([mockCartridge], []);
    render(IngestDashboard);
    expect(screen.getByText(/insert sd card/i)).toBeInTheDocument();
  });

  it("Shows warning when no cartridge mounted", () => {
    setDeviceState([], [mockSd]);
    render(IngestDashboard);
    expect(screen.getByText(/no cartridge mounted/i)).toBeInTheDocument();
  });

  it("Shows progress and cancel while running", async () => {
    setDeviceState([mockCartridge], [mockSd]);

    let capturedCallback: ((e: any) => void) | null = null;
    vi.mocked(runIngest).mockImplementation(async (_s, _o, _d, cb) => {
      capturedCallback = cb;
      return { kill: vi.fn() } as any;
    });

    render(IngestDashboard);
    await waitFor(() => screen.getByRole("button", { name: /start ingest/i }));
    fireEvent.click(screen.getByRole("button", { name: /start ingest/i }));

    await waitFor(() => expect(capturedCallback).not.toBeNull());
    capturedCallback!({ type: "progress", step: "copy", current: 10, total: 50, message: "" });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
    });
  });

  it("Shows summary card after done event", async () => {
    setDeviceState([mockCartridge], [mockSd]);

    vi.mocked(runIngest).mockImplementation(async (_s, _o, _d, cb) => {
      setTimeout(() => cb({
        type: "done",
        summary: { total: 150, duplicates_skipped: 8, scored: 142, named: 142, xmp_written: 142, db_upserted: 142, elapsed_seconds: 47.2 },
      }), 0);
      return { kill: vi.fn() } as any;
    });

    render(IngestDashboard);
    await waitFor(() => screen.getByRole("button", { name: /start ingest/i }));
    fireEvent.click(screen.getByRole("button", { name: /start ingest/i }));

    await waitFor(() => {
      expect(screen.getByText("150")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /new ingest/i })).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: Run to verify tests fail**

```bash
ssh alex@10.27.27.10 'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && npx vitest run src/panels/IngestDashboard.test.ts 2>&1 | tail -20'
```

Expected: FAIL

- [ ] **Step 3: Update the `<script>` block of `IngestDashboard.svelte`**

Read `photonforge-gui/src/panels/IngestDashboard.svelte`. Replace the `<script lang="ts">` block with:

```svelte
<script lang="ts">
  import { deviceState } from "../stores/devices";
  import type { SdCandidate } from "../stores/devices";
  import { ingestState, resetIngest } from "../stores/ingest";
  import { pipelineSettings } from "../stores/pipeline";
  import { runIngest, type SidecarEvent, type StageDoneEvent } from "../lib/sidecar";

  $: cartridge = $deviceState.cartridges[0] ?? null;
  $: sdCandidates = $deviceState.sd_candidates;

  // Auto-select SD if only one candidate
  let selectedSdMount: string | null = null;
  $: {
    if (sdCandidates.length === 1) {
      selectedSdMount = sdCandidates[0].mount_point;
    } else if (sdCandidates.length === 0) {
      selectedSdMount = null;
    }
  }

  $: selectedSd = sdCandidates.find(s => s.mount_point === selectedSdMount) ?? null;
  $: canStart = cartridge !== null && selectedSd !== null;

  $: sourceLabel = selectedSd
    ? (selectedSd.label ?? selectedSd.mount_point)
    : "No SD card";
  $: destLabel = cartridge ? cartridge.cartridge_id : "No cartridge mounted";

  const STAGE_DEFS = [
    { key: "copy",      label: "Copy",           required: true  },
    { key: "dedup",     label: "Deduplication",  required: false },
    { key: "scoring",   label: "Scoring",        required: false },
    { key: "naming",    label: "AI Naming",      required: false },
    { key: "darktable", label: "Darktable sync", required: false },
  ] as const;

  type StageKey = typeof STAGE_DEFS[number]["key"];
  type StageStatus = "pending" | "active" | "done" | "skipped";

  interface StageEntry {
    key: StageKey;
    label: string;
    required: boolean;
    status: StageStatus;
    current: number;
    total: number;
    meta: Record<string, unknown> | undefined;
  }

  function isEnabled(key: StageKey): boolean {
    if (key === "copy") return true;
    return $pipelineSettings[key as keyof typeof $pipelineSettings] as boolean;
  }

  function stageStatus(key: StageKey): StageStatus {
    if (!isEnabled(key)) return "skipped";
    if ($ingestState.stageDone[key]) return "done";
    if ($ingestState.step === key) return "active";
    return "pending";
  }

  $: stageList = STAGE_DEFS.map((s): StageEntry => ({
    ...s,
    status: stageStatus(s.key),
    current: $ingestState.step === s.key ? $ingestState.current : 0,
    total: $ingestState.step === s.key ? $ingestState.total : 0,
    meta: $ingestState.stageDone[s.key],
  }));

  function stageMeta(entry: StageEntry): string {
    if (!entry.meta) return "";
    const m = entry.meta;
    if (entry.key === "copy")      return `${m.copied ?? 0} files`;
    if (entry.key === "dedup")     return `${m.dupes_found ?? 0} dupes removed`;
    if (entry.key === "scoring")   return `${m.scored ?? 0} scored`;
    if (entry.key === "naming")    return `${m.named ?? 0} named`;
    if (entry.key === "darktable") return `${m.xmp_written ?? 0} XMP, ${m.db_upserted ?? 0} DB rows`;
    return "";
  }

  function stageIcon(status: StageStatus): string {
    if (status === "done")    return "✓";
    if (status === "active")  return "▶";
    if (status === "skipped") return "—";
    return "○";
  }

  async function startIngest() {
    if (!canStart || !selectedSd || !cartridge) return;
    const sd  = selectedSd.mount_point;
    const ssd = cartridge.mount_point;
    const db  = `${ssd}/library.db`;

    ingestState.update(s => ({
      ...s,
      phase: "running",
      step: "copy",
      current: 0,
      total: 0,
      errorMsg: "",
      summary: null,
      activeCmd: null,
      stageDone: {},
      sdEjected: false,
    }));

    try {
      const cmd = await runIngest(sd, ssd, db, (event: SidecarEvent) => {
        if (event.type === "progress") {
          ingestState.update(s => ({ ...s, step: event.step, current: event.current, total: event.total }));
        } else if (event.type === "stage_done") {
          const e = event as StageDoneEvent;
          ingestState.update(s => ({
            ...s,
            stageDone: { ...s.stageDone, [e.stage]: e as unknown as Record<string, unknown> },
          }));
        } else if (event.type === "sd_ejected") {
          ingestState.update(s => ({ ...s, sdEjected: true }));
        } else if (event.type === "done") {
          ingestState.update(s => ({ ...s, phase: "done", summary: event.summary, activeCmd: null }));
        } else if (event.type === "error") {
          ingestState.update(s => ({ ...s, phase: "idle", errorMsg: event.message, activeCmd: null }));
        }
      }, {
        skipDedup:     !$pipelineSettings.dedup,
        skipScoring:   !$pipelineSettings.scoring,
        skipNaming:    !$pipelineSettings.naming,
        skipDarktable: !$pipelineSettings.darktable,
      });
      ingestState.update(s => ({ ...s, activeCmd: cmd }));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      ingestState.update(s => ({ ...s, phase: "idle", errorMsg: `Failed to start: ${msg}`, activeCmd: null }));
    }
  }

  function cancelIngest() {
    $ingestState.activeCmd?.kill().catch(() => {});
    ingestState.update(s => ({ ...s, phase: "idle", activeCmd: null }));
  }
</script>
```

Update the **idle view HTML** section to add the SD picker. Replace the existing `<div class="device-row">` block for Source with:

```svelte
      {#if sdCandidates.length > 1}
        <div class="sd-picker">
          <span class="label">Source</span>
          <div class="drive-picker">
            {#each sdCandidates as sd}
              <button
                class="drive-option"
                class:selected={selectedSdMount === sd.mount_point}
                on:click={() => (selectedSdMount = sd.mount_point)}
              >
                <span class="drive-model">{sd.label ?? sd.mount_point}</span>
                <span class="drive-meta">{sd.device} · {sd.mount_point}</span>
              </button>
            {/each}
          </div>
        </div>
      {:else}
        <div class="device-row">
          <span class="label">Source</span>
          <span class="value" class:missing={!selectedSd}>
            {sdCandidates.length === 0 ? "Insert SD card" : sourceLabel}
          </span>
        </div>
      {/if}
      <div class="device-row">
        <span class="label">Destination</span>
        <span class="value" class:missing={!cartridge}>
          {cartridge ? destLabel : "No cartridge mounted"}
        </span>
      </div>
```

Add these CSS rules to the `<style>` block:
```svelte
  .sd-picker { width: 100%; display: flex; flex-direction: column; gap: 0.5rem; }
  .drive-picker { display: flex; flex-direction: column; gap: 0.4rem; }
  .drive-option { display: flex; flex-direction: column; gap: 0.15rem; padding: 0.6rem 0.75rem; background: var(--surface, #1a1a1a); border: 1px solid var(--border, #333); border-radius: 0.375rem; cursor: pointer; text-align: left; width: 100%; }
  .drive-option:hover { border-color: var(--accent, #6366f1); }
  .drive-option.selected { border-color: var(--accent, #6366f1); background: rgba(99,102,241,0.1); }
  .drive-model { color: var(--text-primary, #fff); font-size: 0.9rem; }
  .drive-meta { color: var(--text-muted, #888); font-size: 0.75rem; font-family: monospace; }
```

- [ ] **Step 4: Run IngestDashboard tests on Yoga**

```bash
ssh alex@10.27.27.10 'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && npx vitest run src/panels/IngestDashboard.test.ts 2>&1 | tail -20'
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add photonforge-gui/src/panels/IngestDashboard.svelte photonforge-gui/src/panels/IngestDashboard.test.ts
git commit -m "feat: IngestDashboard uses sd_candidates picker; source from deviceState"
```

---

### Task 8: `install_polkit.sh` — remove udevadm from sudoers + update Yoga

**Files:**
- Modify: `scripts/install_polkit.sh`

- [ ] **Step 1: Remove `udevadm` from the sudoers line in `install_polkit.sh`**

Read `scripts/install_polkit.sh`. Find the `echo` line that writes the sudoers rule. Replace:

```bash
echo "${SUDOERS_USER} ALL=(ALL) NOPASSWD: /usr/sbin/parted *, /usr/sbin/wipefs *, /usr/sbin/mkfs.ext4 *, /usr/bin/udevadm *, /usr/bin/umount *" \
```

with:

```bash
echo "${SUDOERS_USER} ALL=(ALL) NOPASSWD: /usr/sbin/parted *, /usr/sbin/wipefs *, /usr/sbin/mkfs.ext4 *, /usr/bin/umount *" \
```

- [ ] **Step 2: Commit and push**

```bash
git add scripts/install_polkit.sh
git commit -m "chore: remove udevadm from sudoers — sidecar no longer calls it"
git push origin main
```

- [ ] **Step 3: Update the live sudoers file on Yoga**

Run in your PowerShell terminal (needs password prompt via `-t`):

```
ssh -t alex@10.27.27.10 "echo 'alex ALL=(ALL) NOPASSWD: /usr/sbin/parted *, /usr/sbin/wipefs *, /usr/sbin/mkfs.ext4 *, /usr/bin/umount *' | sudo tee /etc/sudoers.d/photonforge && sudo chmod 440 /etc/sudoers.d/photonforge && sudo visudo -c && echo OK"
```

Expected: `OK`

---

### Task 9: Yoga filesystem cleanup

No code changes — removes stale directories from Yoga.

- [ ] **Step 1: Pull latest on Yoga**

```bash
ssh alex@10.27.27.10 'cd ~/PHOTONFORGE_Photo-Workflow && git pull --ff-only && echo OK'
```

- [ ] **Step 2: Remove stale mount directories**

Run in PowerShell terminal:

```
ssh -t alex@10.27.27.10 "sudo rm -rf /mnt/photon_sd /mnt/photon_ssd && echo OK"
```

- [ ] **Step 3: Rebuild sidecar binary**

```bash
ssh alex@10.27.27.10 'cd ~/PHOTONFORGE_Photo-Workflow && source .venv/bin/activate && bash scripts/build_sidecar.sh 2>&1 | tail -5'
```

Expected: `Binary written to: ...` and `File size: 131M`

- [ ] **Step 4: Restart the app**

```bash
ssh alex@10.27.27.10 'bash ~/PHOTONFORGE_Photo-Workflow/scripts/launch_app.sh --bg 2>&1'
```

Expected: `App is ready!`

- [ ] **Step 5: Smoke test — verify cartridge detected**

```bash
ssh alex@10.27.27.10 '~/PHOTONFORGE_Photo-Workflow/photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu cartridge-list 2>&1'
```

Expected: JSON with `type: "cartridges"` and one item containing `cartridge_id`, `provisioned_by`, `est_raw_capacity` fields.

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| Metadata file `.photonforge/cartridge.json` written at provision | Task 1 |
| `est_raw_capacity = size_bytes / (25 MB)` | Task 1 |
| `provisioned_by` = hostname | Task 1 |
| `next_available_cartridge_id` scans metadata files | Task 1 |
| `cartridge-list` reads metadata files | Task 2 |
| `reformat_done` event has no `mount_point` | Task 2 |
| New `cartridge-update-meta` command | Task 2 |
| `mount_monitor.rs` uses closure-based detection | Task 3 |
| `DeviceState.cartridges: Vec<CartridgeMeta>` | Task 3 |
| `DeviceState.sd_candidates: Vec<SdCandidate>` | Task 3 |
| `SdCandidate.label: Option<String>` | Task 3 |
| `CartridgeMeta.device` field populated from `/proc/mounts` | Task 3 |
| `sidecar.ts` `CartridgeInfo` gains all metadata fields | Task 4 |
| `MetaUpdatedEvent` added | Task 4 |
| `updateCartridgeMeta()` function | Task 4 |
| `devices.ts` shape updated | Task 5 |
| CartridgeManager reads from `deviceState.cartridges` | Task 6 |
| CartridgeManager shows metadata (ID, date, machine, capacity) | Task 6 |
| CartridgeManager editable description field | Task 6 |
| Reformat uses `cartridge.device` not `/dev/disk/by-label/` | Task 6 |
| IngestDashboard SD source picker from `sd_candidates` | Task 7 |
| `canStart` requires both cartridge and SD | Task 7 |
| Remove `udevadm` from sudoers | Task 8 |
| Yoga stale dir cleanup | Task 9 |
| Yoga sidecar rebuild + smoke test | Task 9 |

All requirements covered. No gaps found.
