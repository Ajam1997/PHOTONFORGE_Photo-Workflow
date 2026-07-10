# Stage 7.2 — IngestDashboard & CartridgeManager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire IngestDashboard and CartridgeManager panel stubs to the Python backend via a PyInstaller sidecar, giving the operator a touch-friendly UI for ingesting photos and managing SSD cartridges.

**Architecture:** A thin Python CLI (`sidecar_cli.py`) exposes three subcommands (`ingest`, `cartridge-list`, `cartridge-reformat`) that stream JSON-lines to stdout. Tauri's `tauri-plugin-shell` spawns the compiled binary once per command. A TypeScript module (`sidecar.ts`) wraps each command into typed callbacks. Both panels consume `sidecar.ts` — no panel talks to Rust or the binary directly.

**Tech Stack:** Rust/Tauri 2, Svelte 5 (legacy compat), `tauri-plugin-shell`, Python 3.11 + Click, PyInstaller, pytest, vitest

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `photonforge-gui/src-tauri/src/mount_monitor.rs` | Add `ssd_mount_point`, `sd_path` fields |
| Modify | `photonforge-gui/src/stores/devices.ts` | Extend TypeScript `DeviceState` interface |
| Modify | `photonforge-gui/src-tauri/Cargo.toml` | Add `tauri-plugin-shell` dependency |
| Modify | `photonforge-gui/src-tauri/src/main.rs` | Register shell plugin |
| Modify | `photonforge-gui/package.json` | Add `@tauri-apps/plugin-shell` npm dep |
| Modify | `photonforge-gui/src-tauri/capabilities/default.json` | Add shell permissions |
| Modify | `photonforge-gui/src-tauri/tauri.conf.json` | Add `externalBin` entry |
| Create | `photonforge-gui/src-tauri/src/sidecar.rs` | Protocol types + `parse_event` |
| Modify | `photonforge-gui/src-tauri/src/main.rs` | `mod sidecar;` |
| Create | `src/photo_workflow/sidecar_cli.py` | Python CLI with three subcommands |
| Create | `tests/test_sidecar_cli.py` | Python unit tests |
| Create | `photonforge-gui/src/lib/sidecar.ts` | TypeScript sidecar wrapper |
| Modify | `photonforge-gui/src/panels/IngestDashboard.svelte` | Replace stub with full UI |
| Create | `photonforge-gui/src/panels/IngestDashboard.test.ts` | Vitest frontend tests |
| Modify | `photonforge-gui/src/panels/CartridgeManager.svelte` | Replace stub with full UI |
| Create | `photonforge-gui/src/panels/CartridgeManager.test.ts` | Vitest frontend tests |
| Create | `scripts/build_sidecar.sh` | PyInstaller build script (runs on Yoga) |
| Create | `scripts/install_polkit.sh` | One-time polkit rule installer |
| Create | `photonforge-gui/src-tauri/binaries/.gitkeep` | Placeholder for binary directory |

---

### Task 1: Extend DeviceState in Rust

**Files:**
- Modify: `photonforge-gui/src-tauri/src/mount_monitor.rs`

- [ ] **Step 1: Write failing tests for the new fields**

Add these tests at the bottom of the `#[cfg(test)]` block in `mount_monitor.rs`:

```rust
#[test]
fn ssd_mount_point_populated() {
    let content = "/dev/sdb1 /mnt/photon_ssd/001 ext4 rw 0 0\n";
    let state = parse_proc_mounts(content);
    assert_eq!(state.ssd_mount_point, Some("/mnt/photon_ssd/001".to_string()));
}

#[test]
fn sd_path_populated_canonical() {
    let content = "/dev/sda1 /mnt/photon_sd ext4 rw 0 0\n";
    let state = parse_proc_mounts(content);
    assert_eq!(state.sd_path, Some("/mnt/photon_sd".to_string()));
}

#[test]
fn sd_path_absent_when_not_mounted() {
    let state = parse_proc_mounts("");
    assert!(state.sd_path.is_none());
    assert!(state.ssd_mount_point.is_none());
}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd photonforge-gui && cargo test --no-default-features -- mount_monitor 2>&1 | tail -20
```

Expected: compile error — `ssd_mount_point` and `sd_path` fields don't exist yet.

- [ ] **Step 3: Extend the DeviceState struct and parser**

In `mount_monitor.rs`, replace the struct and `parse_proc_mounts` function:

```rust
#[derive(Clone, Serialize, Debug, PartialEq)]
pub struct DeviceState {
    pub ssd_mounted: bool,
    pub ssd_label: Option<String>,
    pub ssd_mount_point: Option<String>,
    pub sd_mounted: bool,
    pub sd_path: Option<String>,
}

pub fn parse_proc_mounts(content: &str) -> DeviceState {
    let mut ssd_mounted = false;
    let mut ssd_mount_point: Option<String> = None;
    let mut sd_mounted = false;
    let mut sd_path: Option<String> = None;

    for line in content.lines() {
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() < 2 {
            continue;
        }
        let device = parts[0];
        let mount_point = parts[1];
        if mount_point == "/mnt/photon_sd" {
            sd_mounted = true;
            sd_path = Some(mount_point.to_string());
        } else if mount_point.starts_with("/mnt/photon_ssd/") {
            ssd_mounted = true;
            ssd_mount_point = Some(mount_point.to_string());
        } else if mount_point.starts_with("/media/") && is_removable_block_device(device) {
            sd_mounted = true;
            sd_path = Some(mount_point.to_string());
        }
    }

    DeviceState {
        ssd_mounted,
        ssd_label: if ssd_mounted { read_ssd_label() } else { None },
        ssd_mount_point,
        sd_mounted,
        sd_path,
    }
}
```

- [ ] **Step 4: Run all mount_monitor tests**

```bash
cd photonforge-gui && cargo test --no-default-features -- mount_monitor 2>&1 | tail -20
```

Expected: all 10 tests pass (7 existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add photonforge-gui/src-tauri/src/mount_monitor.rs
git commit -m "feat: extend DeviceState with ssd_mount_point and sd_path"
```

---

### Task 2: Extend DeviceState in TypeScript

**Files:**
- Modify: `photonforge-gui/src/stores/devices.ts`

- [ ] **Step 1: Update the interface and initial value**

Replace the contents of `photonforge-gui/src/stores/devices.ts`:

```typescript
import { writable } from "svelte/store";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";

export interface DeviceState {
  ssd_mounted: boolean;
  ssd_label: string | null;
  ssd_mount_point: string | null;
  sd_mounted: boolean;
  sd_path: string | null;
}

const initial: DeviceState = {
  ssd_mounted: false,
  ssd_label: null,
  ssd_mount_point: null,
  sd_mounted: false,
  sd_path: null,
};

export const deviceState = writable<DeviceState>(initial);

if (typeof window !== "undefined") {
  invoke<DeviceState>("get_device_state")
    .then((state) => deviceState.set(state))
    .catch(() => {});

  listen<DeviceState>("device-state-changed", (event) => {
    deviceState.set(event.payload);
  }).catch(() => {});
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd photonforge-gui && npm run check 2>&1 | tail -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add photonforge-gui/src/stores/devices.ts
git commit -m "feat: extend TypeScript DeviceState with ssd_mount_point and sd_path"
```

---

### Task 3: Add tauri-plugin-shell

**Files:**
- Modify: `photonforge-gui/src-tauri/Cargo.toml`
- Modify: `photonforge-gui/src-tauri/src/main.rs`
- Modify: `photonforge-gui/package.json`
- Modify: `photonforge-gui/src-tauri/capabilities/default.json`
- Modify: `photonforge-gui/src-tauri/tauri.conf.json`
- Create: `photonforge-gui/src-tauri/binaries/.gitkeep`

- [ ] **Step 1: Add Rust dependency**

In `photonforge-gui/src-tauri/Cargo.toml`, add to `[dependencies]`:

```toml
tauri-plugin-shell = "2"
```

Full `[dependencies]` section after edit:
```toml
[dependencies]
tauri = { version = "2", features = [], optional = true }
tauri-plugin-shell = "2"
serde = { version = "1", features = ["derive"] }
```

- [ ] **Step 2: Register plugin in main.rs**

Replace `photonforge-gui/src-tauri/src/main.rs`:

```rust
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod mount_monitor;
mod sidecar;

#[cfg(feature = "tauri")]
fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![mount_monitor::get_device_state])
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || mount_monitor::run(handle));
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error running PhotonForge");
}

#[cfg(not(feature = "tauri"))]
fn main() {}
```

- [ ] **Step 3: Add npm package**

```bash
cd photonforge-gui && npm install @tauri-apps/plugin-shell
```

- [ ] **Step 4: Add shell permissions to capabilities**

Replace `photonforge-gui/src-tauri/capabilities/default.json`:

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "identifier": "default",
  "description": "Default capabilities for PhotonForge",
  "windows": ["main"],
  "permissions": [
    "core:default",
    "shell:allow-execute",
    "shell:allow-kill"
  ]
}
```

- [ ] **Step 5: Add externalBin to tauri.conf.json**

In `photonforge-gui/src-tauri/tauri.conf.json`, add `externalBin` inside the `bundle` object:

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "PhotonForge",
  "version": "0.1.0",
  "identifier": "com.photonforge.app",
  "build": {
    "frontendDist": "../dist",
    "devUrl": "http://localhost:1420",
    "beforeDevCommand": "npm run dev",
    "beforeBuildCommand": "npm run build"
  },
  "app": {
    "windows": [
      {
        "label": "main",
        "title": "PhotonForge",
        "width": 1920,
        "height": 1080,
        "fullscreen": true,
        "decorations": false,
        "theme": "Dark"
      }
    ],
    "security": { "csp": null }
  },
  "bundle": {
    "active": true,
    "targets": "all",
    "icon": ["icons/icon.png"],
    "externalBin": ["binaries/photo-workflow-sidecar"]
  }
}
```

- [ ] **Step 6: Create binaries placeholder**

```bash
mkdir -p photonforge-gui/src-tauri/binaries
touch photonforge-gui/src-tauri/binaries/.gitkeep
```

- [ ] **Step 7: Verify Rust compiles**

```bash
cd photonforge-gui && cargo build 2>&1 | tail -20
```

Expected: compiles without errors (sidecar.rs module stub needed — create empty file `src-tauri/src/sidecar.rs` containing just `// sidecar protocol types` if the compiler errors on the mod declaration).

- [ ] **Step 8: Commit**

```bash
git add photonforge-gui/src-tauri/Cargo.toml \
        photonforge-gui/src-tauri/Cargo.lock \
        photonforge-gui/src-tauri/src/main.rs \
        photonforge-gui/package.json \
        photonforge-gui/package-lock.json \
        photonforge-gui/src-tauri/capabilities/default.json \
        photonforge-gui/src-tauri/tauri.conf.json \
        photonforge-gui/src-tauri/binaries/.gitkeep
git commit -m "feat: add tauri-plugin-shell and sidecar binary configuration"
```

---

### Task 4: sidecar.rs — Protocol Types and parse_event

**Files:**
- Create: `photonforge-gui/src-tauri/src/sidecar.rs`

- [ ] **Step 1: Write failing tests**

Create `photonforge-gui/src-tauri/src/sidecar.rs` with only the tests (no implementation yet):

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_progress_event() {
        let line = r#"{"type":"progress","step":"copying","current":42,"total":150,"message":"DSC_0042.ARW"}"#;
        let event = parse_event(line).unwrap();
        match event {
            SidecarEvent::Progress { step, current, total, message } => {
                assert_eq!(step, "copying");
                assert_eq!(current, 42);
                assert_eq!(total, 150);
                assert_eq!(message, "DSC_0042.ARW");
            }
            _ => panic!("unexpected variant"),
        }
    }

    #[test]
    fn parses_done_event() {
        let line = r#"{"type":"done","summary":{"total":150,"duplicates_skipped":8,"scored":142,"xmp_written":142,"db_upserted":142,"elapsed_seconds":47.2}}"#;
        let event = parse_event(line).unwrap();
        match event {
            SidecarEvent::Done { summary } => {
                assert_eq!(summary.total, 150);
                assert_eq!(summary.duplicates_skipped, 8);
            }
            _ => panic!("unexpected variant"),
        }
    }

    #[test]
    fn malformed_json_returns_none() {
        assert!(parse_event("not json {{{").is_none());
    }

    #[test]
    fn parses_error_event() {
        let line = r#"{"type":"error","message":"SD card not mounted"}"#;
        let event = parse_event(line).unwrap();
        match event {
            SidecarEvent::Error { message } => assert_eq!(message, "SD card not mounted"),
            _ => panic!("unexpected variant"),
        }
    }

    #[test]
    fn parses_cartridges_event() {
        let line = r#"{"type":"cartridges","items":[{"label":"PHOTON-001","mount_point":"/mnt/photon_ssd/001","free_bytes":100,"size_bytes":200}]}"#;
        let event = parse_event(line).unwrap();
        match event {
            SidecarEvent::Cartridges { items } => {
                assert_eq!(items.len(), 1);
                assert_eq!(items[0].label, "PHOTON-001");
            }
            _ => panic!("unexpected variant"),
        }
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd photonforge-gui && cargo test --no-default-features -- sidecar 2>&1 | tail -20
```

Expected: compile errors — `parse_event`, `SidecarEvent` not defined yet.

- [ ] **Step 3: Implement the types and parser**

Replace `sidecar.rs` with the full implementation:

```rust
use serde::Deserialize;

#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum SidecarEvent {
    Progress {
        step: String,
        current: u64,
        total: u64,
        message: String,
    },
    Done {
        summary: IngestSummary,
    },
    Error {
        message: String,
    },
    Cartridges {
        items: Vec<CartridgeInfo>,
    },
    ReformatDone {
        label: String,
        mount_point: String,
    },
}

#[derive(Debug, Deserialize)]
pub struct IngestSummary {
    pub total: u64,
    pub duplicates_skipped: u64,
    pub scored: u64,
    pub xmp_written: u64,
    pub db_upserted: u64,
    pub elapsed_seconds: f64,
}

#[derive(Debug, Deserialize)]
pub struct CartridgeInfo {
    pub label: String,
    pub mount_point: String,
    pub free_bytes: u64,
    pub size_bytes: u64,
}

pub fn parse_event(line: &str) -> Option<SidecarEvent> {
    serde_json::from_str(line).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_progress_event() {
        let line = r#"{"type":"progress","step":"copying","current":42,"total":150,"message":"DSC_0042.ARW"}"#;
        let event = parse_event(line).unwrap();
        match event {
            SidecarEvent::Progress { step, current, total, message } => {
                assert_eq!(step, "copying");
                assert_eq!(current, 42);
                assert_eq!(total, 150);
                assert_eq!(message, "DSC_0042.ARW");
            }
            _ => panic!("unexpected variant"),
        }
    }

    #[test]
    fn parses_done_event() {
        let line = r#"{"type":"done","summary":{"total":150,"duplicates_skipped":8,"scored":142,"xmp_written":142,"db_upserted":142,"elapsed_seconds":47.2}}"#;
        let event = parse_event(line).unwrap();
        match event {
            SidecarEvent::Done { summary } => {
                assert_eq!(summary.total, 150);
                assert_eq!(summary.duplicates_skipped, 8);
            }
            _ => panic!("unexpected variant"),
        }
    }

    #[test]
    fn malformed_json_returns_none() {
        assert!(parse_event("not json {{{").is_none());
    }

    #[test]
    fn parses_error_event() {
        let line = r#"{"type":"error","message":"SD card not mounted"}"#;
        let event = parse_event(line).unwrap();
        match event {
            SidecarEvent::Error { message } => assert_eq!(message, "SD card not mounted"),
            _ => panic!("unexpected variant"),
        }
    }

    #[test]
    fn parses_cartridges_event() {
        let line = r#"{"type":"cartridges","items":[{"label":"PHOTON-001","mount_point":"/mnt/photon_ssd/001","free_bytes":100,"size_bytes":200}]}"#;
        let event = parse_event(line).unwrap();
        match event {
            SidecarEvent::Cartridges { items } => {
                assert_eq!(items.len(), 1);
                assert_eq!(items[0].label, "PHOTON-001");
            }
            _ => panic!("unexpected variant"),
        }
    }
}
```

Also add `serde_json` to `Cargo.toml` `[dependencies]`:
```toml
serde_json = "1"
```

- [ ] **Step 4: Run all sidecar tests**

```bash
cd photonforge-gui && cargo test --no-default-features -- sidecar 2>&1 | tail -20
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add photonforge-gui/src-tauri/src/sidecar.rs \
        photonforge-gui/src-tauri/Cargo.toml \
        photonforge-gui/src-tauri/Cargo.lock
git commit -m "feat: add sidecar.rs protocol types and parse_event"
```

---

### Task 5: sidecar_cli.py — Python CLI

**Files:**
- Create: `src/photo_workflow/sidecar_cli.py`

- [ ] **Step 1: Write the CLI**

Create `src/photo_workflow/sidecar_cli.py`:

```python
"""Sidecar CLI: streams JSON-lines for Tauri shell plugin consumption."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import click

from photo_workflow.ingest import ingest_sd_card
from photo_workflow.cartridge import list_cartridges


def emit(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.option("--source", required=True, help="Source mount path (SD card)")
@click.option("--output", required=True, help="Destination mount path (SSD)")
@click.option("--db", required=True, help="Path to library.db on SSD")
def ingest(source: str, output: str, db: str) -> None:
    """Ingest photos from SD to SSD, streaming progress events."""
    def on_progress(step: str, current: int, total: int, message: str = "") -> None:
        emit({"type": "progress", "step": step, "current": current, "total": total, "message": message})

    try:
        summary = ingest_sd_card(
            source_path=source,
            output_path=output,
            db_path=db,
            progress_callback=on_progress,
        )
        emit({
            "type": "done",
            "summary": {
                "total": summary.total,
                "duplicates_skipped": summary.duplicates_skipped,
                "scored": summary.scored,
                "xmp_written": summary.xmp_written,
                "db_upserted": summary.db_upserted,
                "elapsed_seconds": summary.elapsed_seconds,
            },
        })
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "message": str(exc)})
        sys.exit(1)


@cli.command("cartridge-list")
def cartridge_list() -> None:
    """List all mounted PHOTON cartridges."""
    try:
        items = list_cartridges()
        emit({
            "type": "cartridges",
            "items": [
                {
                    "label": c.label,
                    "mount_point": c.mount_point,
                    "free_bytes": c.free_bytes,
                    "size_bytes": c.size_bytes,
                }
                for c in items
            ],
        })
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "message": str(exc)})
        sys.exit(1)


@cli.command("cartridge-reformat")
@click.option("--device", required=True, help="Block device path, e.g. /dev/sdb")
@click.option("--label", required=True, help="New filesystem label, e.g. PHOTON-002")
@click.option("--dry-run", is_flag=True, default=False, help="Simulate without touching disk")
def cartridge_reformat(device: str, label: str, dry_run: bool) -> None:
    """Reformat a cartridge as ext4 with the given label."""
    try:
        emit({"type": "progress", "step": "formatting", "current": 0, "total": 1, "message": device})
        if not dry_run:
            result = subprocess.run(
                ["mkfs.ext4", "-L", label, "-F", device],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "mkfs.ext4 failed")
            mount_point = f"/mnt/photon_ssd/{label.replace('PHOTON-', '').zfill(3)}"
        else:
            mount_point = f"/mnt/photon_ssd/dry-run"

        emit({"type": "progress", "step": "formatting", "current": 1, "total": 1, "message": ""})
        emit({"type": "reformat_done", "label": label, "mount_point": mount_point})
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "message": str(exc)})
        sys.exit(1)


if __name__ == "__main__":
    cli()
```

- [ ] **Step 2: Add `list_cartridges` to cartridge.py if not present**

Check `src/photo_workflow/cartridge.py`. If `list_cartridges` doesn't exist, add:

```python
from __future__ import annotations
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CartridgeInfo:
    label: str
    mount_point: str
    free_bytes: int
    size_bytes: int


def list_cartridges() -> list[CartridgeInfo]:
    """Return all mounted PHOTON-* cartridges under /mnt/photon_ssd/."""
    base = Path("/mnt/photon_ssd")
    if not base.exists():
        return []
    results: list[CartridgeInfo] = []
    by_label = Path("/dev/disk/by-label")
    for entry in sorted(base.iterdir()):
        if not entry.is_dir():
            continue
        try:
            usage = shutil.disk_usage(str(entry))
        except OSError:
            continue
        # Derive label from /dev/disk/by-label symlinks
        label = _label_for_mount(str(entry), by_label)
        results.append(CartridgeInfo(
            label=label or entry.name,
            mount_point=str(entry),
            free_bytes=usage.free,
            size_bytes=usage.total,
        ))
    return results


def _label_for_mount(mount_point: str, by_label: Path) -> str | None:
    if not by_label.exists():
        return None
    for entry in by_label.iterdir():
        if not entry.name.startswith("PHOTON-"):
            continue
        try:
            target = os.path.realpath(str(entry))
            # Check if this label's device is mounted at our mount_point
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] == mount_point:
                        dev = os.path.realpath(parts[0])
                        if dev == target:
                            return entry.name
        except OSError:
            continue
    return None
```

Also add `IngestSummary` dataclass and `ingest_sd_card` stub to `src/photo_workflow/ingest.py` if it doesn't exist (check first). The ingest function must accept a `progress_callback` parameter.

- [ ] **Step 3: Add progress_callback to ingest_sd_card**

Read `src/photo_workflow/ingest.py`. Find the `ingest_sd_card` function signature. Add `progress_callback` parameter with a default of `None`:

```python
from typing import Callable, Optional
from dataclasses import dataclass

@dataclass
class IngestSummary:
    total: int
    duplicates_skipped: int
    scored: int
    xmp_written: int
    db_upserted: int
    elapsed_seconds: float

def ingest_sd_card(
    source_path: str,
    output_path: str,
    db_path: str,
    progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
) -> IngestSummary:
    ...
```

Where callbacks already exist in the function body, wire them to `progress_callback` if it's not None. If `ingest_sd_card` doesn't call a callback, add the calls at each logical step.

- [ ] **Step 4: Commit**

```bash
git add src/photo_workflow/sidecar_cli.py \
        src/photo_workflow/cartridge.py \
        src/photo_workflow/ingest.py
git commit -m "feat: add sidecar_cli.py with ingest, cartridge-list, cartridge-reformat subcommands"
```

---

### Task 6: Python Tests for sidecar_cli

**Files:**
- Create: `tests/test_sidecar_cli.py`

- [ ] **Step 1: Write the tests**

Create `tests/test_sidecar_cli.py`:

```python
"""Tests for sidecar_cli subcommands via subprocess to test stdout JSON-lines."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def run_sidecar(*args: str) -> tuple[list[dict], int]:
    """Run sidecar_cli and return (parsed_events, returncode)."""
    result = subprocess.run(
        [sys.executable, "-m", "photo_workflow.sidecar_cli", *args],
        capture_output=True,
        text=True,
    )
    events = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events, result.returncode


def test_cartridge_list_exits_zero_and_emits_cartridges_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """cartridge-list prints a cartridges event and exits 0."""
    monkeypatch.setattr(
        "photo_workflow.cartridge.list_cartridges",
        lambda: [],
    )
    events, rc = run_sidecar("cartridge-list")
    assert rc == 0
    assert len(events) == 1
    assert events[0]["type"] == "cartridges"
    assert "items" in events[0]


def test_ingest_streams_progress_and_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ingest streams at least one progress event and one done event, exits 0."""
    from photo_workflow.ingest import IngestSummary
    import photo_workflow.sidecar_cli as cli_module

    def fake_ingest(source_path, output_path, db_path, progress_callback=None):
        if progress_callback:
            progress_callback("copying", 1, 1, "test.ARW")
        return IngestSummary(
            total=1,
            duplicates_skipped=0,
            scored=1,
            xmp_written=1,
            db_upserted=1,
            elapsed_seconds=0.1,
        )

    monkeypatch.setattr("photo_workflow.sidecar_cli.ingest_sd_card", fake_ingest)

    events, rc = run_sidecar(
        "ingest",
        "--source", str(tmp_path),
        "--output", str(tmp_path),
        "--db", str(tmp_path / "library.db"),
    )
    assert rc == 0
    types = [e["type"] for e in events]
    assert "progress" in types
    assert "done" in types


def test_cartridge_reformat_dry_run_no_disk_touch(tmp_path: Path) -> None:
    """cartridge-reformat --dry-run streams events without touching disk, exits 0."""
    events, rc = run_sidecar(
        "cartridge-reformat",
        "--device", "/dev/null",
        "--label", "PHOTON-TEST",
        "--dry-run",
    )
    assert rc == 0
    types = [e["type"] for e in events]
    assert "reformat_done" in types
    done = next(e for e in events if e["type"] == "reformat_done")
    assert done["label"] == "PHOTON-TEST"
```

- [ ] **Step 2: Run the tests**

```bash
pytest tests/test_sidecar_cli.py -v 2>&1 | tail -30
```

Expected: 3 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_sidecar_cli.py
git commit -m "test: add test_sidecar_cli.py for JSON-lines CLI output"
```

---

### Task 7: sidecar.ts — TypeScript Wrapper Module

**Files:**
- Create: `photonforge-gui/src/lib/sidecar.ts`

- [ ] **Step 1: Write sidecar.ts**

Create `photonforge-gui/src/lib/sidecar.ts`:

```typescript
import { Command } from "@tauri-apps/plugin-shell";

export interface ProgressEvent {
  type: "progress";
  step: string;
  current: number;
  total: number;
  message: string;
}

export interface DoneEvent {
  type: "done";
  summary: {
    total: number;
    duplicates_skipped: number;
    scored: number;
    xmp_written: number;
    db_upserted: number;
    elapsed_seconds: number;
  };
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export interface CartridgesEvent {
  type: "cartridges";
  items: CartridgeInfo[];
}

export interface ReformatDoneEvent {
  type: "reformat_done";
  label: string;
  mount_point: string;
}

export interface CartridgeInfo {
  label: string;
  mount_point: string;
  free_bytes: number;
  size_bytes: number;
}

export type SidecarEvent =
  | ProgressEvent
  | DoneEvent
  | ErrorEvent
  | CartridgesEvent
  | ReformatDoneEvent;

function parseLine(line: string): SidecarEvent | null {
  try {
    return JSON.parse(line) as SidecarEvent;
  } catch {
    return null;
  }
}

export async function runIngest(
  source: string,
  output: string,
  db: string,
  onEvent: (event: SidecarEvent) => void,
): Promise<Command<string>> {
  const cmd = Command.sidecar("binaries/photo-workflow-sidecar", [
    "ingest",
    "--source", source,
    "--output", output,
    "--db", db,
  ]);

  let buffer = "";
  cmd.stdout.on("data", (chunk: string) => {
    buffer += chunk;
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const event = parseLine(line.trim());
      if (event) onEvent(event);
    }
  });

  await cmd.spawn();
  return cmd;
}

export async function listCartridges(): Promise<CartridgeInfo[]> {
  const cmd = Command.sidecar("binaries/photo-workflow-sidecar", [
    "cartridge-list",
  ]);

  return new Promise((resolve, reject) => {
    let output = "";
    cmd.stdout.on("data", (chunk: string) => { output += chunk; });
    cmd.on("close", () => {
      for (const line of output.split("\n")) {
        const event = parseLine(line.trim());
        if (event?.type === "cartridges") {
          resolve(event.items);
          return;
        }
      }
      resolve([]);
    });
    cmd.on("error", reject);
    cmd.spawn().catch(reject);
  });
}

export async function reformatCartridge(
  device: string,
  label: string,
  onEvent: (event: SidecarEvent) => void,
  dryRun = false,
): Promise<Command<string>> {
  const args = [
    "cartridge-reformat",
    "--device", device,
    "--label", label,
  ];
  if (dryRun) args.push("--dry-run");

  const cmd = Command.sidecar("binaries/photo-workflow-sidecar", args);

  let buffer = "";
  cmd.stdout.on("data", (chunk: string) => {
    buffer += chunk;
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const event = parseLine(line.trim());
      if (event) onEvent(event);
    }
  });

  await cmd.spawn();
  return cmd;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd photonforge-gui && npm run check 2>&1 | tail -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add photonforge-gui/src/lib/sidecar.ts
git commit -m "feat: add sidecar.ts TypeScript wrapper for sidecar commands"
```

---

### Task 8: build_sidecar.sh and Yoga Build

**Files:**
- Create: `scripts/build_sidecar.sh`
- Create: `photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu` (built on Yoga, then committed)

- [ ] **Step 1: Write build_sidecar.sh**

Create `scripts/build_sidecar.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Build the photo-workflow sidecar binary using PyInstaller.
# Must be run on the Yoga 910 (Linux x86_64).
# Output: photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$REPO_ROOT/photonforge-gui/src-tauri/binaries"
BINARY_NAME="photo-workflow-sidecar-x86_64-unknown-linux-gnu"

cd "$REPO_ROOT"

echo "Installing build dependencies..."
pip install pyinstaller --quiet

echo "Building sidecar binary..."
pyinstaller \
  --onefile \
  --name "photo-workflow-sidecar" \
  --distpath "$OUTPUT_DIR" \
  --workpath /tmp/pyinstaller-build \
  --specpath /tmp/pyinstaller-build \
  src/photo_workflow/sidecar_cli.py

# Rename to Tauri's required target-triple format
mv "$OUTPUT_DIR/photo-workflow-sidecar" "$OUTPUT_DIR/$BINARY_NAME"
chmod +x "$OUTPUT_DIR/$BINARY_NAME"

echo "Binary written to: $OUTPUT_DIR/$BINARY_NAME"
echo "File size: $(du -h "$OUTPUT_DIR/$BINARY_NAME" | cut -f1)"
```

- [ ] **Step 2: Run build on Yoga via SSH**

```bash
ssh alex@$(cat scripts/yoga_ip.txt 2>/dev/null || echo "yoga") \
  "cd ~/photo-workflow && bash scripts/build_sidecar.sh"
```

If `yoga_ip.txt` doesn't exist, substitute the actual IP.

- [ ] **Step 3: Retrieve the binary**

```bash
scp alex@yoga:~/photo-workflow/photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu \
    photonforge-gui/src-tauri/binaries/
```

- [ ] **Step 4: Verify the binary runs**

```bash
ssh alex@yoga "~/photo-workflow/photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu cartridge-list"
```

Expected: prints a JSON line with `{"type":"cartridges","items":[...]}` and exits 0.

- [ ] **Step 5: Commit the binary and script**

```bash
git add scripts/build_sidecar.sh \
        photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu
git commit -m "feat: add build_sidecar.sh and commit pre-built sidecar binary"
```

---

### Task 9: IngestDashboard.svelte

**Files:**
- Modify: `photonforge-gui/src/panels/IngestDashboard.svelte`

- [ ] **Step 1: Implement the three-state panel**

Replace `photonforge-gui/src/panels/IngestDashboard.svelte`:

```svelte
<script lang="ts">
  import { deviceState } from "../stores/devices";
  import { runIngest, type SidecarEvent, type DoneEvent } from "../lib/sidecar";
  import type { Command } from "@tauri-apps/plugin-shell";

  type IngestState = "idle" | "running" | "done";

  let state: IngestState = "idle";
  let step = "";
  let current = 0;
  let total = 0;
  let summary: DoneEvent["summary"] | null = null;
  let activeCmd: Command<string> | null = null;
  let errorMsg = "";

  const STEP_LABELS: Record<string, string> = {
    copying: "Copying files",
    scoring: "Scoring images",
    naming: "Generating names",
    darktable: "Syncing to Darktable",
    formatting: "Formatting cartridge",
  };

  $: canStart = $deviceState.sd_mounted && $deviceState.ssd_mounted;
  $: sourceLabel = $deviceState.sd_path ?? "No SD card";
  $: destLabel = $deviceState.ssd_label ?? "No cartridge";

  async function startIngest() {
    if (!canStart) return;
    const sd = $deviceState.sd_path!;
    const ssd = $deviceState.ssd_mount_point!;
    const db = `${ssd}/library.db`;

    state = "running";
    step = "copying";
    current = 0;
    total = 0;
    errorMsg = "";
    summary = null;

    activeCmd = await runIngest(sd, ssd, db, (event: SidecarEvent) => {
      if (event.type === "progress") {
        step = event.step;
        current = event.current;
        total = event.total;
      } else if (event.type === "done") {
        summary = event.summary;
        state = "done";
        activeCmd = null;
      } else if (event.type === "error") {
        errorMsg = event.message;
        state = "idle";
        activeCmd = null;
      }
    });
  }

  function cancelIngest() {
    activeCmd?.kill().catch(() => {});
    activeCmd = null;
    state = "idle";
  }

  function reset() {
    state = "idle";
    summary = null;
    errorMsg = "";
  }
</script>

<div class="ingest-panel">
  {#if state === "idle"}
    <div class="idle-view">
      <h2>Ingest Photos</h2>
      <div class="device-row">
        <span class="label">Source</span>
        <span class="value" class:missing={!$deviceState.sd_mounted}>
          {$deviceState.sd_mounted ? sourceLabel : "Insert SD card"}
        </span>
      </div>
      <div class="device-row">
        <span class="label">Destination</span>
        <span class="value" class:missing={!$deviceState.ssd_mounted}>
          {$deviceState.ssd_mounted ? destLabel : "No cartridge mounted"}
        </span>
      </div>
      {#if errorMsg}
        <p class="error">{errorMsg}</p>
      {/if}
      <button class="primary-btn" disabled={!canStart} on:click={startIngest}>
        Start Ingest
      </button>
    </div>

  {:else if state === "running"}
    <div class="running-view">
      <h2>{STEP_LABELS[step] ?? step}…</h2>
      <p class="progress-numbers">{current} / {total}</p>
      <div class="progress-bar">
        <div
          class="progress-fill"
          style="width: {total > 0 ? (current / total) * 100 : 0}%"
        ></div>
      </div>
      <button class="cancel-btn" on:click={cancelIngest}>Cancel</button>
    </div>

  {:else if state === "done" && summary}
    <div class="done-view">
      <h2>Ingest Complete</h2>
      <div class="summary-card">
        <div class="summary-row"><span>Total files</span><strong>{summary.total}</strong></div>
        <div class="summary-row"><span>Duplicates skipped</span><strong>{summary.duplicates_skipped}</strong></div>
        <div class="summary-row"><span>Images scored</span><strong>{summary.scored}</strong></div>
        <div class="summary-row"><span>Elapsed</span><strong>{summary.elapsed_seconds.toFixed(1)}s</strong></div>
      </div>
      <button class="primary-btn" on:click={reset}>New Ingest</button>
    </div>
  {/if}
</div>

<style>
  .ingest-panel {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 1.5rem;
    padding: 2rem;
  }
  .idle-view, .running-view, .done-view {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1rem;
    width: 100%;
    max-width: 480px;
  }
  h2 { color: var(--text-primary, #fff); font-size: 1.5rem; margin: 0; }
  .device-row {
    display: flex;
    justify-content: space-between;
    width: 100%;
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--border, #333);
  }
  .label { color: var(--text-muted, #888); }
  .value { color: var(--text-primary, #fff); }
  .value.missing { color: var(--warning, #f59e0b); }
  .primary-btn {
    padding: 0.75rem 2rem;
    background: var(--accent, #6366f1);
    color: #fff;
    border: none;
    border-radius: 0.5rem;
    font-size: 1rem;
    cursor: pointer;
    width: 100%;
  }
  .primary-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .cancel-btn {
    padding: 0.75rem 2rem;
    background: transparent;
    color: var(--warning, #f59e0b);
    border: 1px solid var(--warning, #f59e0b);
    border-radius: 0.5rem;
    font-size: 1rem;
    cursor: pointer;
    width: 100%;
  }
  .progress-bar {
    width: 100%;
    height: 8px;
    background: var(--border, #333);
    border-radius: 4px;
    overflow: hidden;
  }
  .progress-fill {
    height: 100%;
    background: var(--accent, #6366f1);
    transition: width 0.2s ease;
  }
  .progress-numbers { color: var(--text-muted, #888); }
  .summary-card {
    width: 100%;
    background: var(--surface, #1a1a1a);
    border-radius: 0.5rem;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .summary-row {
    display: flex;
    justify-content: space-between;
    color: var(--text-muted, #888);
  }
  .summary-row strong { color: var(--text-primary, #fff); }
  .error { color: var(--error, #ef4444); }
</style>
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd photonforge-gui && npm run check 2>&1 | tail -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add photonforge-gui/src/panels/IngestDashboard.svelte
git commit -m "feat: implement IngestDashboard three-state UI (idle/running/done)"
```

---

### Task 10: IngestDashboard.test.ts

**Files:**
- Create: `photonforge-gui/src/panels/IngestDashboard.test.ts`

- [ ] **Step 1: Write the vitest tests**

Create `photonforge-gui/src/panels/IngestDashboard.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import IngestDashboard from "./IngestDashboard.svelte";
import { deviceState } from "../stores/devices";
import type { DeviceState } from "../stores/devices";

// Mock the sidecar module
vi.mock("../lib/sidecar", () => ({
  runIngest: vi.fn(),
}));

import { runIngest } from "../lib/sidecar";

function setDeviceState(state: Partial<DeviceState>) {
  deviceState.set({
    ssd_mounted: false,
    ssd_label: null,
    ssd_mount_point: null,
    sd_mounted: false,
    sd_path: null,
    ...state,
  });
}

describe("IngestDashboard", () => {
  beforeEach(() => {
    setDeviceState({});
    vi.clearAllMocks();
  });

  it("Start Ingest disabled when ssd_mounted is false", () => {
    setDeviceState({ sd_mounted: true, sd_path: "/media/alex/SD", ssd_mounted: false });
    render(IngestDashboard);
    const btn = screen.getByRole("button", { name: /start ingest/i });
    expect(btn).toBeDisabled();
  });

  it("Start Ingest disabled when sd_mounted is false", () => {
    setDeviceState({ ssd_mounted: true, ssd_mount_point: "/mnt/photon_ssd/001", sd_mounted: false });
    render(IngestDashboard);
    const btn = screen.getByRole("button", { name: /start ingest/i });
    expect(btn).toBeDisabled();
  });

  it("Start Ingest enabled when both SD and SSD present", () => {
    setDeviceState({
      sd_mounted: true, sd_path: "/media/alex/SD",
      ssd_mounted: true, ssd_mount_point: "/mnt/photon_ssd/001", ssd_label: "PHOTON-001",
    });
    render(IngestDashboard);
    const btn = screen.getByRole("button", { name: /start ingest/i });
    expect(btn).not.toBeDisabled();
  });

  it("Shows warning when SD absent", () => {
    setDeviceState({ ssd_mounted: true });
    render(IngestDashboard);
    expect(screen.getByText(/insert sd card/i)).toBeInTheDocument();
  });

  it("Shows warning when SSD absent", () => {
    setDeviceState({ sd_mounted: true });
    render(IngestDashboard);
    expect(screen.getByText(/no cartridge mounted/i)).toBeInTheDocument();
  });

  it("Shows progress bar and cancel button while running", async () => {
    setDeviceState({
      sd_mounted: true, sd_path: "/media/alex/SD",
      ssd_mounted: true, ssd_mount_point: "/mnt/photon_ssd/001",
    });

    let capturedCallback: ((e: any) => void) | null = null;
    vi.mocked(runIngest).mockImplementation(async (_s, _o, _d, cb) => {
      capturedCallback = cb;
      return { kill: vi.fn() } as any;
    });

    render(IngestDashboard);
    fireEvent.click(screen.getByRole("button", { name: /start ingest/i }));

    await waitFor(() => {
      capturedCallback?.({ type: "progress", step: "copying", current: 42, total: 150, message: "" });
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
    });
  });

  it("Shows summary card after done event", async () => {
    setDeviceState({
      sd_mounted: true, sd_path: "/media/alex/SD",
      ssd_mounted: true, ssd_mount_point: "/mnt/photon_ssd/001",
    });

    vi.mocked(runIngest).mockImplementation(async (_s, _o, _d, cb) => {
      setTimeout(() => cb({
        type: "done",
        summary: { total: 150, duplicates_skipped: 8, scored: 142, xmp_written: 142, db_upserted: 142, elapsed_seconds: 47.2 },
      }), 0);
      return { kill: vi.fn() } as any;
    });

    render(IngestDashboard);
    fireEvent.click(screen.getByRole("button", { name: /start ingest/i }));

    await waitFor(() => {
      expect(screen.getByText("150")).toBeInTheDocument();
      expect(screen.getByText("8")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /new ingest/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests**

```bash
cd photonforge-gui && npx vitest run src/panels/IngestDashboard.test.ts 2>&1 | tail -30
```

Expected: all 7 tests pass.

- [ ] **Step 3: Commit**

```bash
git add photonforge-gui/src/panels/IngestDashboard.test.ts
git commit -m "test: add IngestDashboard.test.ts vitest coverage"
```

---

### Task 11: CartridgeManager.svelte

**Files:**
- Modify: `photonforge-gui/src/panels/CartridgeManager.svelte`

- [ ] **Step 1: Implement the cartridge list and reformat flow**

Replace `photonforge-gui/src/panels/CartridgeManager.svelte`:

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import { deviceState } from "../stores/devices";
  import { listCartridges, reformatCartridge, type CartridgeInfo, type SidecarEvent } from "../lib/sidecar";

  let cartridges: CartridgeInfo[] = [];
  let loading = false;

  // Reformat state
  let reformatTarget: CartridgeInfo | null = null;
  let confirmLabel = "";
  let reformatRunning = false;
  let reformatStep = "";
  let reformatError = "";

  async function fetchCartridges() {
    loading = true;
    try {
      cartridges = await listCartridges();
    } finally {
      loading = false;
    }
  }

  onMount(fetchCartridges);

  // Re-fetch when devices change
  $: if ($deviceState) fetchCartridges();

  function formatBytes(bytes: number): string {
    if (bytes >= 1e12) return `${(bytes / 1e12).toFixed(1)} TB`;
    if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
    return `${(bytes / 1e6).toFixed(0)} MB`;
  }

  function usedPercent(c: CartridgeInfo): number {
    return ((c.size_bytes - c.free_bytes) / c.size_bytes) * 100;
  }

  function openReformat(c: CartridgeInfo) {
    reformatTarget = c;
    confirmLabel = "";
    reformatError = "";
  }

  function closeReformat() {
    reformatTarget = null;
    reformatRunning = false;
    reformatStep = "";
    reformatError = "";
  }

  async function confirmReformat() {
    if (!reformatTarget || confirmLabel !== reformatTarget.label) return;
    reformatRunning = true;
    reformatError = "";
    const target = reformatTarget;

    // Derive block device from mount_point — in prod the backend resolves it
    // For now pass the label; cartridge-reformat expects --device
    // The actual /dev path comes from the sidecar resolving by label
    await reformatCartridge(
      `/dev/disk/by-label/${target.label}`,
      target.label,
      (event: SidecarEvent) => {
        if (event.type === "progress") {
          reformatStep = event.step;
        } else if (event.type === "reformat_done") {
          reformatRunning = false;
          closeReformat();
          fetchCartridges();
        } else if (event.type === "error") {
          reformatError = event.message;
          reformatRunning = false;
        }
      },
    );
  }
</script>

<div class="cartridge-panel">
  <h2>Cartridge Manager</h2>

  {#if loading}
    <p class="muted">Loading cartridges…</p>
  {:else if cartridges.length === 0}
    <p class="muted">No PHOTON cartridges mounted.</p>
  {:else}
    <div class="cartridge-list">
      {#each cartridges as c (c.label)}
        <div class="cartridge-card">
          <div class="card-header">
            <span class="cartridge-label">{c.label}</span>
            <span class="mount-point">{c.mount_point}</span>
          </div>
          <div class="space-bar-row">
            <div class="space-bar">
              <div class="space-fill" style="width: {usedPercent(c)}%"></div>
            </div>
            <span class="space-text">
              {formatBytes(c.free_bytes)} free of {formatBytes(c.size_bytes)}
            </span>
          </div>
          <button class="reformat-btn" on:click={() => openReformat(c)}>
            Reformat
          </button>
        </div>
      {/each}
    </div>
  {/if}

  {#if reformatTarget}
    <div class="sheet-overlay" role="dialog" aria-modal="true">
      <div class="sheet">
        {#if reformatRunning}
          <h3>Reformatting {reformatTarget.label}…</h3>
          <p class="muted">{reformatStep}</p>
        {:else}
          <h3>Reformat {reformatTarget.label}?</h3>
          <p class="warning">All data will be erased. This cannot be undone.</p>
          {#if reformatError}
            <p class="error">{reformatError}</p>
          {/if}
          <label for="confirm-label">Type the cartridge label to confirm:</label>
          <input
            id="confirm-label"
            bind:value={confirmLabel}
            placeholder={reformatTarget.label}
            autocomplete="off"
          />
          <div class="sheet-actions">
            <button class="cancel-btn" on:click={closeReformat}>Cancel</button>
            <button
              class="danger-btn"
              disabled={confirmLabel !== reformatTarget.label}
              on:click={confirmReformat}
            >
              Confirm Reformat
            </button>
          </div>
        {/if}
      </div>
    </div>
  {/if}
</div>

<style>
  .cartridge-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    padding: 2rem;
    gap: 1rem;
  }
  h2 { color: var(--text-primary, #fff); margin: 0; }
  .muted { color: var(--text-muted, #888); }
  .cartridge-list { display: flex; flex-direction: column; gap: 1rem; }
  .cartridge-card {
    background: var(--surface, #1a1a1a);
    border-radius: 0.5rem;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }
  .card-header { display: flex; justify-content: space-between; align-items: baseline; }
  .cartridge-label { color: var(--text-primary, #fff); font-weight: 600; }
  .mount-point { color: var(--text-muted, #888); font-size: 0.85rem; }
  .space-bar-row { display: flex; align-items: center; gap: 0.75rem; }
  .space-bar { flex: 1; height: 6px; background: var(--border, #333); border-radius: 3px; overflow: hidden; }
  .space-fill { height: 100%; background: var(--accent, #6366f1); }
  .space-text { color: var(--text-muted, #888); font-size: 0.8rem; white-space: nowrap; }
  .reformat-btn {
    padding: 0.5rem 1rem;
    background: transparent;
    color: var(--error, #ef4444);
    border: 1px solid var(--error, #ef4444);
    border-radius: 0.375rem;
    cursor: pointer;
    align-self: flex-end;
  }
  .sheet-overlay {
    position: fixed; inset: 0;
    background: rgba(0,0,0,0.7);
    display: flex; align-items: flex-end; justify-content: center;
    z-index: 100;
  }
  .sheet {
    background: var(--surface-elevated, #222);
    border-radius: 1rem 1rem 0 0;
    padding: 2rem;
    width: 100%;
    max-width: 600px;
    display: flex; flex-direction: column; gap: 1rem;
  }
  h3 { color: var(--text-primary, #fff); margin: 0; }
  .warning { color: var(--warning, #f59e0b); }
  .error { color: var(--error, #ef4444); }
  label { color: var(--text-muted, #888); font-size: 0.9rem; }
  input {
    padding: 0.6rem;
    background: var(--surface, #1a1a1a);
    border: 1px solid var(--border, #333);
    border-radius: 0.375rem;
    color: var(--text-primary, #fff);
    font-size: 1rem;
  }
  .sheet-actions { display: flex; gap: 0.75rem; }
  .cancel-btn {
    flex: 1; padding: 0.75rem;
    background: transparent; color: var(--text-muted, #888);
    border: 1px solid var(--border, #333); border-radius: 0.375rem; cursor: pointer;
  }
  .danger-btn {
    flex: 1; padding: 0.75rem;
    background: var(--error, #ef4444); color: #fff;
    border: none; border-radius: 0.375rem; cursor: pointer;
  }
  .danger-btn:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd photonforge-gui && npm run check 2>&1 | tail -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add photonforge-gui/src/panels/CartridgeManager.svelte
git commit -m "feat: implement CartridgeManager with cartridge list and reformat flow"
```

---

### Task 12: CartridgeManager.test.ts

**Files:**
- Create: `photonforge-gui/src/panels/CartridgeManager.test.ts`

- [ ] **Step 1: Write the vitest tests**

Create `photonforge-gui/src/panels/CartridgeManager.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import CartridgeManager from "./CartridgeManager.svelte";

vi.mock("../lib/sidecar", () => ({
  listCartridges: vi.fn(),
  reformatCartridge: vi.fn(),
}));

import { listCartridges, reformatCartridge } from "../lib/sidecar";

const mockCartridges = [
  {
    label: "PHOTON-001",
    mount_point: "/mnt/photon_ssd/001",
    free_bytes: 214_748_364_800,
    size_bytes: 500_107_862_016,
  },
];

describe("CartridgeManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listCartridges).mockResolvedValue(mockCartridges);
  });

  it("renders cartridge card from mock sidecar cartridges event", async () => {
    render(CartridgeManager);
    await waitFor(() => {
      expect(screen.getByText("PHOTON-001")).toBeInTheDocument();
      expect(screen.getByText("/mnt/photon_ssd/001")).toBeInTheDocument();
    });
  });

  it("reformat confirm button disabled until label typed correctly", async () => {
    render(CartridgeManager);
    await waitFor(() => screen.getByText("PHOTON-001"));

    fireEvent.click(screen.getByRole("button", { name: /reformat/i }));

    await waitFor(() => {
      const btn = screen.getByRole("button", { name: /confirm reformat/i });
      expect(btn).toBeDisabled();
    });
  });

  it("reformat confirm button enabled when label matches", async () => {
    render(CartridgeManager);
    await waitFor(() => screen.getByText("PHOTON-001"));

    fireEvent.click(screen.getByRole("button", { name: /reformat/i }));
    await waitFor(() => screen.getByLabelText(/type the cartridge label/i));

    const input = screen.getByLabelText(/type the cartridge label/i);
    fireEvent.input(input, { target: { value: "PHOTON-001" } });

    await waitFor(() => {
      const btn = screen.getByRole("button", { name: /confirm reformat/i });
      expect(btn).not.toBeDisabled();
    });
  });

  it("shows empty state when no cartridges mounted", async () => {
    vi.mocked(listCartridges).mockResolvedValue([]);
    render(CartridgeManager);
    await waitFor(() => {
      expect(screen.getByText(/no photon cartridges mounted/i)).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 2: Run the tests**

```bash
cd photonforge-gui && npx vitest run src/panels/CartridgeManager.test.ts 2>&1 | tail -30
```

Expected: all 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add photonforge-gui/src/panels/CartridgeManager.test.ts
git commit -m "test: add CartridgeManager.test.ts vitest coverage"
```

---

### Task 13: install_polkit.sh

**Files:**
- Create: `scripts/install_polkit.sh`

- [ ] **Step 1: Write install_polkit.sh**

Create `scripts/install_polkit.sh`:

```bash
#!/usr/bin/env bash
# One-time install: grant the sidecar binary passwordless permission to run mkfs.ext4.
# Must be run as root (or via sudo) on the Yoga 910.
set -euo pipefail

BINARY_NAME="photo-workflow-sidecar-x86_64-unknown-linux-gnu"
POLKIT_RULE="/etc/polkit-1/rules.d/50-photonforge-reformat.rules"

if [[ $EUID -ne 0 ]]; then
  echo "Run this script as root: sudo bash scripts/install_polkit.sh" >&2
  exit 1
fi

cat > "$POLKIT_RULE" << 'EOF'
// Allow photo-workflow-sidecar to run mkfs.ext4 without a password.
polkit.addRule(function(action, subject) {
    if (action.id === "org.freedesktop.policykit.exec" &&
        action.lookup("program") === "/sbin/mkfs.ext4" &&
        subject.user === "alex") {
        return polkit.Result.YES;
    }
});
EOF

chmod 644 "$POLKIT_RULE"
echo "Polkit rule installed at $POLKIT_RULE"
echo "Restart polkit to apply: systemctl restart polkit"
```

- [ ] **Step 2: Verify ShellCheck**

```bash
shellcheck scripts/install_polkit.sh
```

Expected: no warnings.

- [ ] **Step 3: Commit**

```bash
git add scripts/install_polkit.sh
git commit -m "feat: add install_polkit.sh for passwordless cartridge-reformat"
```

---

## Post-Plan Self-Review

### Spec Coverage Check

| Spec Requirement | Task |
|---|---|
| DeviceState: add ssd_mount_point, sd_path (Rust) | Task 1 |
| DeviceState: add ssd_mount_point, sd_path (TypeScript) | Task 2 |
| tauri-plugin-shell dependency + capabilities | Task 3 |
| sidecar.rs protocol types + parse_event + 4 unit tests | Task 4 |
| sidecar_cli.py: ingest, cartridge-list, cartridge-reformat | Task 5 |
| Python tests: cartridge-list, ingest, --dry-run | Task 6 |
| sidecar.ts typed async wrapper | Task 7 |
| build_sidecar.sh + PyInstaller binary | Task 8 |
| IngestDashboard: idle/running/done states | Task 9 |
| IngestDashboard tests: 4 spec cases | Task 10 |
| CartridgeManager: list + reformat confirmation | Task 11 |
| CartridgeManager tests: 3 spec cases | Task 12 |
| install_polkit.sh | Task 13 |
| binaries/.gitkeep | Task 3 |

All spec requirements covered. No gaps found.
