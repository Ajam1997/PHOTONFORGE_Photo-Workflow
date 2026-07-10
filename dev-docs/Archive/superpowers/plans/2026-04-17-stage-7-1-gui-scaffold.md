# Stage 7.1 GUI Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `photonforge-gui/` Tauri + Svelte application scaffold with bottom tab navigation, dark theme, six panel stubs, and a live status bar driven by a Rust backend watching `/proc/mounts`.

**Architecture:** Plain Svelte 5 + Vite frontend compiled by Tauri 2. Rust backend runs a `std::thread` that watches `/proc/mounts` via the `notify` crate and emits `device-state-changed` Tauri events. Svelte reads those events through a writable store. No Tauri commands in this stage — event-only.

**Tech Stack:** Tauri 2, Svelte 5, Vite 6, TypeScript, Rust 2021 edition, `notify = "6"`, `serde`, Vitest + @testing-library/svelte (frontend tests), `cargo test` (Rust unit tests).

---

## File Map

| File | Purpose |
|------|---------|
| `photonforge-gui/package.json` | JS deps + scripts |
| `photonforge-gui/index.html` | HTML entry point |
| `photonforge-gui/vite.config.ts` | Vite + Vitest config |
| `photonforge-gui/svelte.config.js` | Svelte preprocessor |
| `photonforge-gui/src/main.ts` | Svelte mount point |
| `photonforge-gui/src/app.css` | Dark theme CSS tokens |
| `photonforge-gui/src/test-setup.ts` | Vitest + jest-dom setup |
| `photonforge-gui/src/App.svelte` | Root layout: StatusBar + panel area + BottomNav |
| `photonforge-gui/src/stores/devices.ts` | Writable DeviceState store |
| `photonforge-gui/src/stores/devices.test.ts` | Store unit tests |
| `photonforge-gui/src/components/StatusBar.svelte` | Top status bar |
| `photonforge-gui/src/components/StatusBar.test.ts` | StatusBar tests |
| `photonforge-gui/src/components/BottomNav.svelte` | Bottom 6-tab nav |
| `photonforge-gui/src/components/BottomNav.test.ts` | BottomNav tests |
| `photonforge-gui/src/panels/IngestDashboard.svelte` | Stub |
| `photonforge-gui/src/panels/LibraryBrowser.svelte` | Stub |
| `photonforge-gui/src/panels/DarktableLauncher.svelte` | Stub |
| `photonforge-gui/src/panels/ExportShare.svelte` | Stub |
| `photonforge-gui/src/panels/CartridgeManager.svelte` | Stub |
| `photonforge-gui/src/panels/Settings.svelte` | Stub |
| `photonforge-gui/src-tauri/Cargo.toml` | Rust deps |
| `photonforge-gui/src-tauri/build.rs` | Tauri build script |
| `photonforge-gui/src-tauri/tauri.conf.json` | Window + bundle config |
| `photonforge-gui/src-tauri/src/main.rs` | Tauri entry point |
| `photonforge-gui/src-tauri/src/mount_monitor.rs` | `/proc/mounts` watcher + DeviceState |

---

### Task 1: Project skeleton — config files

**Files:**
- Create: `photonforge-gui/package.json`
- Create: `photonforge-gui/index.html`
- Create: `photonforge-gui/vite.config.ts`
- Create: `photonforge-gui/svelte.config.js`
- Create: `photonforge-gui/src-tauri/Cargo.toml`
- Create: `photonforge-gui/src-tauri/build.rs`
- Create: `photonforge-gui/src-tauri/tauri.conf.json`
- Modify: `.gitignore`

- [ ] **Step 1: Create `photonforge-gui/package.json`**

```json
{
  "name": "photonforge-gui",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "tauri": "tauri",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@tauri-apps/api": "^2.0.0"
  },
  "devDependencies": {
    "@sveltejs/vite-plugin-svelte": "^4.0.0",
    "@testing-library/jest-dom": "^6.0.0",
    "@testing-library/svelte": "^5.0.0",
    "jsdom": "^24.0.0",
    "svelte": "^5.0.0",
    "tslib": "^2.6.0",
    "typescript": "^5.0.0",
    "vite": "^6.0.0",
    "vitest": "^2.0.0"
  }
}
```

- [ ] **Step 2: Create `photonforge-gui/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>PhotonForge</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

- [ ] **Step 3: Create `photonforge-gui/vite.config.ts`**

```typescript
import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

export default defineConfig({
  plugins: [svelte()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
  },
  build: {
    target: "chrome105",
    minify: "esbuild",
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test-setup.ts"],
  },
});
```

- [ ] **Step 4: Create `photonforge-gui/svelte.config.js`**

```javascript
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";
export default { preprocess: vitePreprocess() };
```

- [ ] **Step 5: Create `photonforge-gui/src-tauri/Cargo.toml`**

```toml
[package]
name = "photonforge-gui"
version = "0.1.0"
edition = "2021"

[build-dependencies]
tauri-build = { version = "2", features = [] }

[dependencies]
tauri = { version = "2", features = [] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
notify = "6"

[profile.release]
codegen-units = 1
lto = true
opt-level = "s"
panic = "abort"
strip = true
```

- [ ] **Step 6: Create `photonforge-gui/src-tauri/build.rs`**

```rust
fn main() {
    tauri_build::build()
}
```

- [ ] **Step 7: Create `photonforge-gui/src-tauri/tauri.conf.json`**

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
    "icon": []
  }
}
```

- [ ] **Step 8: Add `photonforge-gui` entries to root `.gitignore`**

Append to `E:/PHOTONForge/photo-workflow/.gitignore`:

```
photonforge-gui/node_modules/
photonforge-gui/dist/
photonforge-gui/src-tauri/target/
photonforge-gui/.superpowers/
```

- [ ] **Step 9: Commit**

```bash
git add photonforge-gui/ .gitignore
git commit -m "feat: scaffold photonforge-gui project config files"
```

---

### Task 2: Test infrastructure + dark theme

**Files:**
- Create: `photonforge-gui/src/test-setup.ts`
- Create: `photonforge-gui/src/app.css`
- Create: `photonforge-gui/src/main.ts`

- [ ] **Step 1: Create `photonforge-gui/src/test-setup.ts`**

```typescript
import "@testing-library/jest-dom";
```

- [ ] **Step 2: Create `photonforge-gui/src/app.css`**

```css
*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

:root {
  --bg:         #111111;
  --surface:    #1c1c1c;
  --border:     #2a2a2a;
  --accent:     #4a9eff;
  --text:       #e0e0e0;
  --text-muted: #666666;
  --ok:         #4caf50;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, sans-serif;
  overflow: hidden;
}
```

- [ ] **Step 3: Create `photonforge-gui/src/main.ts`**

```typescript
import { mount } from "svelte";
import App from "./App.svelte";
import "./app.css";

const app = mount(App, { target: document.getElementById("app")! });
export default app;
```

- [ ] **Step 4: Commit**

```bash
git add photonforge-gui/src/
git commit -m "feat: add dark theme tokens and test setup"
```

---

### Task 3: DeviceState store (TDD)

**Files:**
- Create: `photonforge-gui/src/stores/devices.test.ts`
- Create: `photonforge-gui/src/stores/devices.ts`

- [ ] **Step 1: Write failing tests**

Create `photonforge-gui/src/stores/devices.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { get } from "svelte/store";

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn().mockResolvedValue(() => {}),
}));

Object.defineProperty(window, "__TAURI_INTERNALS__", {
  value: {},
  writable: true,
  configurable: true,
});

describe("deviceState store", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("initialises with SSD absent", async () => {
    const { deviceState } = await import("./devices");
    expect(get(deviceState).ssd_mounted).toBe(false);
  });

  it("initialises with ssd_label null", async () => {
    const { deviceState } = await import("./devices");
    expect(get(deviceState).ssd_label).toBeNull();
  });

  it("initialises with SD absent", async () => {
    const { deviceState } = await import("./devices");
    expect(get(deviceState).sd_mounted).toBe(false);
  });

  it("can be set to mounted state", async () => {
    const { deviceState } = await import("./devices");
    deviceState.set({ ssd_mounted: true, ssd_label: "PHOTON-001", sd_mounted: true });
    const state = get(deviceState);
    expect(state.ssd_mounted).toBe(true);
    expect(state.ssd_label).toBe("PHOTON-001");
    expect(state.sd_mounted).toBe(true);
  });
});
```

- [ ] **Step 2: Run tests — verify they fail**

Run on Yoga 910:
```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && npm test -- stores/devices'
```

Expected: FAIL — `Cannot find module './devices'`

- [ ] **Step 3: Implement `photonforge-gui/src/stores/devices.ts`**

```typescript
import { writable } from "svelte/store";
import { listen } from "@tauri-apps/api/event";

export interface DeviceState {
  ssd_mounted: boolean;
  ssd_label: string | null;
  sd_mounted: boolean;
}

const initial: DeviceState = {
  ssd_mounted: false,
  ssd_label: null,
  sd_mounted: false,
};

export const deviceState = writable<DeviceState>(initial);

if (typeof window !== "undefined" && (window as any).__TAURI_INTERNALS__) {
  listen<DeviceState>("device-state-changed", (event) => {
    deviceState.set(event.payload);
  });
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && npm test -- stores/devices'
```

Expected: PASS — 4 tests

- [ ] **Step 5: Commit**

```bash
git add photonforge-gui/src/stores/
git commit -m "feat: add DeviceState Svelte store with Tauri event listener"
```

---

### Task 4: StatusBar component (TDD)

**Files:**
- Create: `photonforge-gui/src/components/StatusBar.test.ts`
- Create: `photonforge-gui/src/components/StatusBar.svelte`

- [ ] **Step 1: Write failing tests**

Create `photonforge-gui/src/components/StatusBar.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/svelte";
import { writable } from "svelte/store";

const mockDeviceState = writable({
  ssd_mounted: false,
  ssd_label: null,
  sd_mounted: false,
});

vi.mock("../stores/devices", () => ({
  deviceState: mockDeviceState,
}));

// Import after mock
const { default: StatusBar } = await import("./StatusBar.svelte");

describe("StatusBar", () => {
  beforeEach(() => {
    mockDeviceState.set({ ssd_mounted: false, ssd_label: null, sd_mounted: false });
  });

  it("shows 'No cartridge' when SSD absent", () => {
    const { getByText } = render(StatusBar);
    expect(getByText(/No cartridge/)).toBeInTheDocument();
  });

  it("shows 'No SD card' when SD absent", () => {
    const { getByText } = render(StatusBar);
    expect(getByText(/No SD card/)).toBeInTheDocument();
  });

  it("shows SSD label when mounted", async () => {
    mockDeviceState.set({ ssd_mounted: true, ssd_label: "PHOTON-001", sd_mounted: false });
    const { getByText } = render(StatusBar);
    expect(getByText(/PHOTON-001/)).toBeInTheDocument();
  });

  it("shows 'SD ready' when SD mounted", async () => {
    mockDeviceState.set({ ssd_mounted: false, ssd_label: null, sd_mounted: true });
    const { getByText } = render(StatusBar);
    expect(getByText(/SD ready/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && npm test -- StatusBar'
```

Expected: FAIL — `Cannot find module './StatusBar.svelte'`

- [ ] **Step 3: Implement `photonforge-gui/src/components/StatusBar.svelte`**

```svelte
<script lang="ts">
  import { deviceState } from "../stores/devices";
</script>

<div class="status-bar">
  <span class="indicator" class:ok={$deviceState.ssd_mounted}>
    SSD: {$deviceState.ssd_mounted
      ? ($deviceState.ssd_label ?? "mounted")
      : "No cartridge"}
  </span>
  <span class="indicator" class:ok={$deviceState.sd_mounted}>
    SD: {$deviceState.sd_mounted ? "SD ready" : "No SD card"}
  </span>
</div>

<style>
  .status-bar {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    height: 40px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 2rem;
    padding: 0 1rem;
    z-index: 100;
  }
  .indicator {
    color: var(--text-muted);
    font-size: 0.875rem;
  }
  .indicator.ok {
    color: var(--ok);
  }
</style>
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && npm test -- StatusBar'
```

Expected: PASS — 4 tests

- [ ] **Step 5: Commit**

```bash
git add photonforge-gui/src/components/
git commit -m "feat: add StatusBar component with live device state"
```

---

### Task 5: BottomNav component (TDD)

**Files:**
- Create: `photonforge-gui/src/components/BottomNav.test.ts`
- Create: `photonforge-gui/src/components/BottomNav.svelte`

- [ ] **Step 1: Write failing tests**

Create `photonforge-gui/src/components/BottomNav.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { render, fireEvent } from "@testing-library/svelte";
import BottomNav from "./BottomNav.svelte";

describe("BottomNav", () => {
  it("renders all six tab buttons", () => {
    const { getAllByRole } = render(BottomNav, { props: { activeIdx: 0 } });
    expect(getAllByRole("button")).toHaveLength(6);
  });

  it("renders each tab by aria-label", () => {
    const { getByLabelText } = render(BottomNav, { props: { activeIdx: 0 } });
    expect(getByLabelText("Ingest")).toBeInTheDocument();
    expect(getByLabelText("Library")).toBeInTheDocument();
    expect(getByLabelText("Darktable")).toBeInTheDocument();
    expect(getByLabelText("Export")).toBeInTheDocument();
    expect(getByLabelText("Cartridge")).toBeInTheDocument();
    expect(getByLabelText("Settings")).toBeInTheDocument();
  });

  it("applies active class to the active tab only", () => {
    const { getByLabelText } = render(BottomNav, { props: { activeIdx: 2 } });
    expect(getByLabelText("Darktable").className).toContain("active");
    expect(getByLabelText("Ingest").className).not.toContain("active");
  });

  it("dispatches select event with tab index on click", async () => {
    const results: number[] = [];
    const { getByLabelText, component } = render(BottomNav, { props: { activeIdx: 0 } });
    component.$on("select", (e: CustomEvent<number>) => results.push(e.detail));
    await fireEvent.click(getByLabelText("Library"));
    expect(results).toEqual([1]);
  });
});
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && npm test -- BottomNav'
```

Expected: FAIL — `Cannot find module './BottomNav.svelte'`

- [ ] **Step 3: Implement `photonforge-gui/src/components/BottomNav.svelte`**

```svelte
<script lang="ts">
  import { createEventDispatcher } from "svelte";

  export let activeIdx: number = 0;

  const dispatch = createEventDispatcher<{ select: number }>();

  const TABS = [
    { label: "Ingest",     icon: "⬇" },
    { label: "Library",    icon: "◼" },
    { label: "Darktable",  icon: "●" },
    { label: "Export",     icon: "↑" },
    { label: "Cartridge",  icon: "▣" },
    { label: "Settings",   icon: "⚙" },
  ];
</script>

<nav class="bottom-nav">
  {#each TABS as tab, i}
    <button
      class="tab"
      class:active={i === activeIdx}
      on:click={() => dispatch("select", i)}
      aria-label={tab.label}
    >
      <span class="tab-icon" aria-hidden="true">{tab.icon}</span>
      <span class="tab-label">{tab.label}</span>
    </button>
  {/each}
</nav>

<style>
  .bottom-nav {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    height: 56px;
    background: var(--surface);
    border-top: 1px solid var(--border);
    display: flex;
    z-index: 100;
  }
  .tab {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--text-muted);
    cursor: pointer;
    gap: 2px;
    min-height: 44px;
    padding: 0;
  }
  .tab.active {
    color: var(--accent);
    border-bottom-color: var(--accent);
  }
  .tab-icon { font-size: 1.2rem; }
  .tab-label { font-size: 0.7rem; }
</style>
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && npm test -- BottomNav'
```

Expected: PASS — 4 tests

- [ ] **Step 5: Commit**

```bash
git add photonforge-gui/src/components/
git commit -m "feat: add BottomNav component with 6 tabs and active state"
```

---

### Task 6: Panel stubs + App.svelte

**Files:**
- Create: `photonforge-gui/src/panels/IngestDashboard.svelte`
- Create: `photonforge-gui/src/panels/LibraryBrowser.svelte`
- Create: `photonforge-gui/src/panels/DarktableLauncher.svelte`
- Create: `photonforge-gui/src/panels/ExportShare.svelte`
- Create: `photonforge-gui/src/panels/CartridgeManager.svelte`
- Create: `photonforge-gui/src/panels/Settings.svelte`
- Create: `photonforge-gui/src/App.svelte`

- [ ] **Step 1: Create all six panel stubs**

Each file follows the same pattern. Create all six:

`photonforge-gui/src/panels/IngestDashboard.svelte`:
```svelte
<div class="panel-stub">
  <h2>Ingest Dashboard</h2>
  <p>Coming in Stage 7.2</p>
</div>

<style>
  .panel-stub {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 1rem;
    color: var(--text-muted);
  }
</style>
```

`photonforge-gui/src/panels/LibraryBrowser.svelte`:
```svelte
<div class="panel-stub">
  <h2>Library Browser</h2>
  <p>Coming in Stage 7.3</p>
</div>

<style>
  .panel-stub {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 1rem;
    color: var(--text-muted);
  }
</style>
```

`photonforge-gui/src/panels/DarktableLauncher.svelte`:
```svelte
<div class="panel-stub">
  <h2>Darktable Launcher</h2>
  <p>Coming in Stage 7.4</p>
</div>

<style>
  .panel-stub {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 1rem;
    color: var(--text-muted);
  }
</style>
```

`photonforge-gui/src/panels/ExportShare.svelte`:
```svelte
<div class="panel-stub">
  <h2>Export / Share</h2>
  <p>Coming in Stage 7.5</p>
</div>

<style>
  .panel-stub {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 1rem;
    color: var(--text-muted);
  }
</style>
```

`photonforge-gui/src/panels/CartridgeManager.svelte`:
```svelte
<div class="panel-stub">
  <h2>Cartridge Manager</h2>
  <p>Coming in Stage 7.2</p>
</div>

<style>
  .panel-stub {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 1rem;
    color: var(--text-muted);
  }
</style>
```

`photonforge-gui/src/panels/Settings.svelte`:
```svelte
<div class="panel-stub">
  <h2>Settings</h2>
  <p>Coming in Stage 7.7</p>
</div>

<style>
  .panel-stub {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 1rem;
    color: var(--text-muted);
  }
</style>
```

- [ ] **Step 2: Create `photonforge-gui/src/App.svelte`**

```svelte
<script lang="ts">
  import StatusBar from "./components/StatusBar.svelte";
  import BottomNav from "./components/BottomNav.svelte";
  import IngestDashboard from "./panels/IngestDashboard.svelte";
  import LibraryBrowser from "./panels/LibraryBrowser.svelte";
  import DarktableLauncher from "./panels/DarktableLauncher.svelte";
  import ExportShare from "./panels/ExportShare.svelte";
  import CartridgeManager from "./panels/CartridgeManager.svelte";
  import Settings from "./panels/Settings.svelte";

  let activeIdx = 0;
</script>

<StatusBar />

<main class="panel-area">
  {#if activeIdx === 0}
    <IngestDashboard />
  {:else if activeIdx === 1}
    <LibraryBrowser />
  {:else if activeIdx === 2}
    <DarktableLauncher />
  {:else if activeIdx === 3}
    <ExportShare />
  {:else if activeIdx === 4}
    <CartridgeManager />
  {:else}
    <Settings />
  {/if}
</main>

<BottomNav {activeIdx} on:select={(e) => (activeIdx = e.detail)} />

<style>
  .panel-area {
    position: fixed;
    top: 40px;
    bottom: 56px;
    left: 0;
    right: 0;
    overflow-y: auto;
    background: var(--bg);
  }
</style>
```

- [ ] **Step 3: Run full Vitest suite — all tests should pass**

```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && npm test'
```

Expected: PASS — 12 tests across 3 suites (devices, StatusBar, BottomNav)

- [ ] **Step 4: Commit**

```bash
git add photonforge-gui/src/panels/ photonforge-gui/src/App.svelte
git commit -m "feat: add six panel stubs and App.svelte root layout"
```

---

### Task 7: Rust mount_monitor (TDD)

**Files:**
- Create: `photonforge-gui/src-tauri/src/mount_monitor.rs`

- [ ] **Step 1: Write failing Rust tests first**

Create `photonforge-gui/src-tauri/src/mount_monitor.rs` with tests only (no `run` function yet):

```rust
use serde::Serialize;

#[derive(Clone, Serialize, Debug, PartialEq)]
pub struct DeviceState {
    pub ssd_mounted: bool,
    pub ssd_label: Option<String>,
    pub sd_mounted: bool,
}

pub fn parse_proc_mounts(content: &str) -> DeviceState {
    todo!("implement")
}

pub fn run(_app: tauri::AppHandle) {
    todo!("implement")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_mounts_all_absent() {
        let state = parse_proc_mounts("");
        assert!(!state.ssd_mounted);
        assert!(state.ssd_label.is_none());
        assert!(!state.sd_mounted);
    }

    #[test]
    fn sd_mount_detected() {
        let content = "/dev/sda1 /mnt/photon_sd ext4 rw 0 0\n";
        let state = parse_proc_mounts(content);
        assert!(state.sd_mounted);
        assert!(!state.ssd_mounted);
    }

    #[test]
    fn ssd_mount_detected() {
        let content = "/dev/sdb1 /mnt/photon_ssd/001 ext4 rw 0 0\n";
        let state = parse_proc_mounts(content);
        assert!(state.ssd_mounted);
        assert!(!state.sd_mounted);
    }

    #[test]
    fn both_mounted() {
        let content = "/dev/sda1 /mnt/photon_sd ext4 rw 0 0\n\
                       /dev/sdb1 /mnt/photon_ssd/001 ext4 rw 0 0\n";
        let state = parse_proc_mounts(content);
        assert!(state.sd_mounted);
        assert!(state.ssd_mounted);
    }

    #[test]
    fn unrelated_mounts_ignored() {
        let content = "tmpfs /tmp tmpfs rw 0 0\n/dev/sda2 / ext4 rw 0 0\n";
        let state = parse_proc_mounts(content);
        assert!(!state.ssd_mounted);
        assert!(!state.sd_mounted);
    }

    #[test]
    fn malformed_line_ignored() {
        let content = "incomplete_line\n/dev/sdb1 /mnt/photon_ssd/001 ext4 rw 0 0\n";
        let state = parse_proc_mounts(content);
        assert!(state.ssd_mounted);
    }
}
```

- [ ] **Step 2: Run Rust tests — verify they fail**

```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui/src-tauri && cargo test mount_monitor 2>&1'
```

Expected: FAIL — `not yet implemented: implement`

- [ ] **Step 3: Implement `parse_proc_mounts` and `run`**

Replace the entire `mount_monitor.rs` with:

```rust
use notify::{Config, Event, RecommendedWatcher, RecursiveMode, Watcher};
use serde::Serialize;
use std::path::Path;
use std::sync::mpsc;
use tauri::{AppHandle, Emitter};

#[derive(Clone, Serialize, Debug, PartialEq)]
pub struct DeviceState {
    pub ssd_mounted: bool,
    pub ssd_label: Option<String>,
    pub sd_mounted: bool,
}

pub fn parse_proc_mounts(content: &str) -> DeviceState {
    let mut ssd_mounted = false;
    let mut sd_mounted = false;

    for line in content.lines() {
        let parts: Vec<&str> = line.split_whitespace().collect();
        if parts.len() < 2 {
            continue;
        }
        let mount_point = parts[1];
        if mount_point == "/mnt/photon_sd" {
            sd_mounted = true;
        } else if mount_point.starts_with("/mnt/photon_ssd/") {
            ssd_mounted = true;
        }
    }

    DeviceState {
        ssd_mounted,
        ssd_label: if ssd_mounted { read_ssd_label() } else { None },
        sd_mounted,
    }
}

fn read_ssd_label() -> Option<String> {
    let by_label = Path::new("/dev/disk/by-label");
    if !by_label.exists() {
        return None;
    }
    std::fs::read_dir(by_label).ok()?.find_map(|entry| {
        let name = entry.ok()?.file_name().to_string_lossy().into_owned();
        if name.starts_with("PHOTON-") {
            Some(name)
        } else {
            None
        }
    })
}

fn read_mounts() -> DeviceState {
    let content = std::fs::read_to_string("/proc/mounts").unwrap_or_default();
    parse_proc_mounts(&content)
}

pub fn run(app: AppHandle) {
    let initial = read_mounts();
    let _ = app.emit("device-state-changed", initial.clone());

    let (tx, rx) = mpsc::channel::<notify::Result<Event>>();
    let mut watcher = match RecommendedWatcher::new(tx, Config::default()) {
        Ok(w) => w,
        Err(_) => return,
    };

    #[cfg(target_os = "linux")]
    if watcher
        .watch(Path::new("/proc/mounts"), RecursiveMode::NonRecursive)
        .is_err()
    {
        return;
    }

    let mut prev = initial;
    for result in rx {
        if result.is_ok() {
            let next = read_mounts();
            if next != prev {
                let _ = app.emit("device-state-changed", next.clone());
                prev = next;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_mounts_all_absent() {
        let state = parse_proc_mounts("");
        assert!(!state.ssd_mounted);
        assert!(state.ssd_label.is_none());
        assert!(!state.sd_mounted);
    }

    #[test]
    fn sd_mount_detected() {
        let content = "/dev/sda1 /mnt/photon_sd ext4 rw 0 0\n";
        let state = parse_proc_mounts(content);
        assert!(state.sd_mounted);
        assert!(!state.ssd_mounted);
    }

    #[test]
    fn ssd_mount_detected() {
        let content = "/dev/sdb1 /mnt/photon_ssd/001 ext4 rw 0 0\n";
        let state = parse_proc_mounts(content);
        assert!(state.ssd_mounted);
        assert!(!state.sd_mounted);
    }

    #[test]
    fn both_mounted() {
        let content = "/dev/sda1 /mnt/photon_sd ext4 rw 0 0\n\
                       /dev/sdb1 /mnt/photon_ssd/001 ext4 rw 0 0\n";
        let state = parse_proc_mounts(content);
        assert!(state.sd_mounted);
        assert!(state.ssd_mounted);
    }

    #[test]
    fn unrelated_mounts_ignored() {
        let content = "tmpfs /tmp tmpfs rw 0 0\n/dev/sda2 / ext4 rw 0 0\n";
        let state = parse_proc_mounts(content);
        assert!(!state.ssd_mounted);
        assert!(!state.sd_mounted);
    }

    #[test]
    fn malformed_line_ignored() {
        let content = "incomplete_line\n/dev/sdb1 /mnt/photon_ssd/001 ext4 rw 0 0\n";
        let state = parse_proc_mounts(content);
        assert!(state.ssd_mounted);
    }
}
```

- [ ] **Step 4: Run Rust tests — verify they pass**

```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui/src-tauri && cargo test mount_monitor 2>&1'
```

Expected:
```
running 6 tests
test mount_monitor::tests::empty_mounts_all_absent ... ok
test mount_monitor::tests::sd_mount_detected ... ok
test mount_monitor::tests::ssd_mount_detected ... ok
test mount_monitor::tests::both_mounted ... ok
test mount_monitor::tests::unrelated_mounts_ignored ... ok
test mount_monitor::tests::malformed_line_ignored ... ok
test result: ok. 6 passed; 0 failed
```

- [ ] **Step 5: Commit**

```bash
git add photonforge-gui/src-tauri/src/mount_monitor.rs
git commit -m "feat: add mount_monitor Rust module with /proc/mounts parser"
```

---

### Task 8: Wire main.rs

**Files:**
- Create: `photonforge-gui/src-tauri/src/main.rs`

- [ ] **Step 1: Create `photonforge-gui/src-tauri/src/main.rs`**

```rust
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod mount_monitor;

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || mount_monitor::run(handle));
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error running PhotonForge");
}
```

- [ ] **Step 2: Verify Rust compiles**

```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui/src-tauri && cargo check 2>&1'
```

Expected: no errors. Warnings about unused imports are acceptable.

- [ ] **Step 3: Commit**

```bash
git add photonforge-gui/src-tauri/src/main.rs
git commit -m "feat: wire Tauri main.rs with mount_monitor thread"
```

---

### Task 9: Install dependencies and first dev build

All commands run on Yoga 910 via SSH. Prereqs: Node.js ≥ 18, npm, Rust stable, `cargo-tauri` CLI (`cargo install tauri-cli`), and Tauri system deps (`sudo apt install -y libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf`).

- [ ] **Step 1: Install Tauri system dependencies on Yoga 910**

```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'sudo apt install -y libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf 2>&1 | tail -5'
```

Expected: `0 upgraded, N newly installed` or already installed.

- [ ] **Step 2: Install cargo-tauri CLI if not present**

```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'cargo tauri --version 2>/dev/null || cargo install tauri-cli --locked 2>&1 | tail -5'
```

Expected: `tauri-cli X.Y.Z` or install completes.

- [ ] **Step 3: Install npm dependencies**

```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && npm install 2>&1 | tail -10'
```

Expected: `added NNN packages` with no errors.

- [ ] **Step 4: Run full test suite**

```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && npm test 2>&1'
```

Expected: all 12 Vitest tests pass, 0 failures.

- [ ] **Step 5: Run all Rust tests**

```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui/src-tauri && cargo test 2>&1'
```

Expected: 6 tests pass, 0 failures.

- [ ] **Step 6: Launch `cargo tauri dev`**

```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && DISPLAY=:0 cargo tauri dev 2>&1 &'
```

Expected: Vite dev server starts on port 1420, Rust compiles, window opens on the Yoga 910 display.

Note: this runs in the background. Monitor the output with:
```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 'tail -20 /tmp/tauri-dev.log'
```

Or run it in a tmux session on the Yoga 910 for persistent output.

- [ ] **Step 7: Commit lock files**

```bash
git add photonforge-gui/package-lock.json photonforge-gui/src-tauri/Cargo.lock
git commit -m "chore: add package-lock.json and Cargo.lock for photonforge-gui"
```

---

### Task 10: Acceptance criteria verification

Verify all five acceptance criteria from the spec. Run on the Yoga 910 with the app running from Task 9 Step 6.

- [ ] **Step 1: Verify all six tabs navigate without crash**

With the app open on the Yoga 910 display, click each of the six bottom tabs in order. Each panel stub should render its heading. No errors in the Tauri dev console.

Check the Tauri console for errors:
```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'DISPLAY=:0 cargo tauri dev 2>&1 | grep -i error | head -20'
```

Expected: no JS errors, no Rust panics.

- [ ] **Step 2: Verify status bar updates on SSD plug**

With the app open, insert the PHOTON-001 SSD cartridge into the Yoga 910 USB-C port.

Observe: the status bar should change from "SSD: No cartridge" to "SSD: PHOTON-001" within 1–2 seconds.

- [ ] **Step 3: Verify status bar updates on SD plug**

Insert an SD card into the Yoga 910 SD reader.

Observe: the status bar should change from "SD: No SD card" to "SD: SD ready".

- [ ] **Step 4: Measure idle RSS**

With the app open and no pipeline running:

```bash
ssh -i ~/.ssh/photonforge_yoga alex@10.27.27.10 \
  'ps aux | grep photonforge | grep -v grep'
```

Note the RSS column (in KB). Convert: divide by 1024 for MB.

Expected: RSS ≤ 51200 KB (50 MB). If exceeded, check for memory leaks in the Svelte store listener.

- [ ] **Step 5: Verify touch targets ≥ 44px**

The `.tab` CSS class sets `min-height: 44px` and `.bottom-nav` sets `height: 56px`. Verify in the Tauri devtools (right-click → Inspect if enabled in dev mode):

```bash
# In Tauri dev, right-click the app → Inspect → Elements
# Select any .tab button and check computed height
```

Expected: computed height ≥ 44px for all tab buttons.

- [ ] **Step 6: Final commit**

```bash
git add photonforge-gui/
git commit -m "feat: complete Stage 7.1 GUI scaffold — all acceptance criteria met"
```
