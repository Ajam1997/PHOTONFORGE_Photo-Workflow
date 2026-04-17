# Stage 7.1 GUI Scaffold — Design Spec

**Date:** 2026-04-17
**Status:** Approved
**Roadmap stage:** 7.1 (GUI Scaffold)

---

## Goal

Create the `photonforge-gui/` Tauri application scaffold: dark-themed shell with bottom tab navigation across six panels and a live status bar that reflects real SSD cartridge and SD card mount state via inotify on `/proc/mounts`.

---

## Acceptance Criteria

- `cargo tauri dev` (on Yoga 910) launches a full-screen decorated-less dark window
- All six tabs navigate without crash
- Status bar updates live when SSD cartridge or SD card is plugged/unplugged
- Idle RSS ≤ 50 MB (GUI-2.1)
- All interactive elements ≥ 44px touch target (NFR-3.3)

---

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Frontend framework | Svelte + Vite (plain, not SvelteKit) | No SSR/routing overhead; compiles to vanilla JS; minimal runtime footprint |
| Navigation | Bottom tab bar, 56px height | Touch-friendly; easy reach on 13.9" kiosk; ≥44px satisfied |
| Mount monitoring | inotify on `/proc/mounts` | No native C deps; builds on Windows dev machine; reliable for mount/unmount detection |
| Theming | CSS custom properties only | No theming library; dark mode only per NFR-3.4 |
| Tauri commands | None in 7.1 | Status bar is read-only, event-driven; commands added in 7.2+ |

---

## Project Structure

```
photonforge-gui/
  package.json              # svelte, @sveltejs/vite-plugin-svelte, @tauri-apps/api
  vite.config.ts
  svelte.config.js
  src-tauri/
    Cargo.toml              # tauri, notify = "6", serde
    tauri.conf.json         # fullscreen, no decorations, dark, 1920x1080
    src/
      main.rs               # Tauri builder; spawns mount_monitor thread pre-run
      mount_monitor.rs      # inotify watcher → DeviceState → Tauri events
  src/
    app.css                 # CSS custom properties: dark theme tokens
    main.ts                 # Svelte mount point
    App.svelte              # Root: StatusBar (top) + panel area + BottomNav (bottom)
    stores/
      devices.ts            # Svelte writable store; listens for device-state-changed
    components/
      StatusBar.svelte      # 40px top bar: SSD label + SD status indicators
      BottomNav.svelte      # 56px bottom bar: 6 tabs with icon + label
    panels/
      IngestDashboard.svelte
      LibraryBrowser.svelte
      DarktableLauncher.svelte
      ExportShare.svelte
      CartridgeManager.svelte
      Settings.svelte       # all stubs: heading + placeholder text only
```

---

## Rust Backend

### `mount_monitor.rs`

Runs in a `std::thread` (not Tokio) to avoid blocking the async runtime.

**Startup sequence:**
1. Read `/proc/mounts` once; parse into initial `DeviceState`; emit `device-state-changed`
2. Open inotify watch on `/proc/mounts` for `IN_MODIFY`
3. On each event: re-read and re-parse `/proc/mounts`; diff against previous state; emit only on change

**Mount detection rules:**
- SSD: any line whose mount point matches `/mnt/photon_ssd/` and filesystem label matches `PHOTON-*` (read via `/dev/disk/by-label/`)
- SD: mount point is `/mnt/photon_sd`

**Tauri event payload:**

```rust
#[derive(Clone, serde::Serialize)]
struct DeviceState {
    ssd_mounted: bool,
    ssd_label: Option<String>,  // e.g. "PHOTON-001", None when absent
    sd_mounted: bool,
}
```

Event name: `device-state-changed`

**Cross-platform:** The `notify` crate uses inotify on Linux and compiles cleanly on Windows (using ReadDirectoryChangesW under the hood). On Windows the watch on `/proc/mounts` finds no file and silently does nothing — status bar stays in "absent" state, which is acceptable for UI layout work on the dev machine.

### `main.rs`

```rust
fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle();
            std::thread::spawn(move || mount_monitor::run(handle));
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error running PhotonForge");
}
```

No Tauri `#[tauri::command]` functions in 7.1.

### `tauri.conf.json` (key fields)

```json
{
  "tauri": {
    "windows": [{
      "fullscreen": true,
      "decorations": false,
      "theme": "Dark",
      "width": 1920,
      "height": 1080,
      "title": "PhotonForge"
    }]
  }
}
```

---

## Svelte Frontend

### Dark Theme (`app.css`)

```css
:root {
  --bg:        #111111;
  --surface:   #1c1c1c;
  --border:    #2a2a2a;
  --accent:    #4a9eff;
  --text:      #e0e0e0;
  --text-muted:#666666;
  --ok:        #4caf50;
}
```

### `stores/devices.ts`

```typescript
import { writable } from 'svelte/store';
import { listen } from '@tauri-apps/api/event';

export interface DeviceState {
  ssd_mounted: boolean;
  ssd_label: string | null;
  sd_mounted: boolean;
}

const initial: DeviceState = { ssd_mounted: false, ssd_label: null, sd_mounted: false };
export const deviceState = writable<DeviceState>(initial);

listen<DeviceState>('device-state-changed', e => deviceState.set(e.payload));
```

### `App.svelte` layout

```
┌─────────────────────────────┐  ← StatusBar (40px, position: fixed top)
│  SSD: PHOTON-001  SD: ready │
├─────────────────────────────┤
│                             │
│   Active panel (flex-grow)  │
│                             │
├─────────────────────────────┤
│  Ingest Library Dtable …    │  ← BottomNav (56px, position: fixed bottom)
└─────────────────────────────┘
```

Panel area height: `calc(100vh - 40px - 56px)`, padded top/bottom to avoid overlap.

### `StatusBar.svelte`

- Subscribes to `$deviceState`
- SSD indicator: shows `ssd_label` in `--ok` green when `ssd_mounted`, "No cartridge" in `--text-muted` when absent
- SD indicator: "SD ready" in `--ok` when `sd_mounted`, "No SD card" in `--text-muted` when absent
- Background: `--surface`; 1px bottom border `--border`

### `BottomNav.svelte`

- Six tabs: Ingest · Library · Darktable · Export · Cartridge · Settings
- Each tab: icon (SVG or Unicode placeholder) + text label; minimum 44px height (actual 56px)
- `activePanelIdx` prop; active tab gets `--accent` bottom border + text colour
- Emits `on:select` event with panel index; `App.svelte` owns the active index

### Panel stubs

Each panel file:
```svelte
<div class="panel-stub">
  <h2>[Panel Name]</h2>
  <p>Coming in Stage 7.x</p>
</div>
```

---

## Out of Scope for 7.1

- Pipeline invocation from UI (7.2)
- Real thumbnail generation (7.3)
- Darktable subprocess launch (7.4)
- Export functionality (7.5)
- Kiosk auto-login / crash recovery (7.6)
- Touch rotation / tablet mode (7.7)
- Any Tauri `#[tauri::command]` beyond event emission

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `tauri` | 2.x | Desktop app runtime |
| `notify` | 6.x | `/proc/mounts` watch (inotify on Linux, compiles on Windows) |
| `serde` | 1.x | DeviceState serialization |
| `svelte` | 5.x | Frontend framework |
| `@sveltejs/vite-plugin-svelte` | latest | Vite integration |
| `@tauri-apps/api` | 2.x | Frontend event listener |

---

## Build Notes

- Development on Yoga 910: `cd photonforge-gui && cargo tauri dev`
- Development on Windows dev machine: `cargo tauri dev` compiles (inotify no-ops); status bar stays in "absent" state — sufficient for UI layout work
- Production build on Yoga 910: `cargo tauri build`
- Add `photonforge-gui/.superpowers/` to `.gitignore`
