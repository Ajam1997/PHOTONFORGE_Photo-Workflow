# Handoff: PHOTONForge Darktable Panel — Release-1 Redesign

## Overview
Information-architecture and visual polish for the **PHOTONForge** Darktable
left-dock lib panel (`lua/photonforge/panel.lua`). The redesign establishes a
clear primary path (configure → enable steps → **Run**), separates the two
workflows (ingest→name **Pipeline** vs. the **Training**/correction loop) into a
tabbed `stack`, adds a shared **cartridge manager** strip (archive / restore /
provision / safe-eject), a **training-weights inspector**, a developer mode, and
a tweakable accent color (default **dark maroon**).

## About the Design Files
The file in this bundle (`PHOTONForge Panel.dc.html`) is a **design reference
created in HTML** — a picture of the intended look, hierarchy, and states. It is
**not** production code and must **not** be shipped as HTML.

⚠️ **Critical constraint — this is NOT a web UI.** The target is the Darktable
Lua plugin. There is no HTML/DOM/flexbox/grid/React in the real product. The
task is to recreate the design using **only**:
- **`dt.new_widget("<type>"){…}`** calls in `lua/photonforge/panel.lua`
  (nested horizontal/vertical `box`es for all layout), and
- a **GTK3-CSS theme** (subset only) targeting each widget by its `name`
  attribute, using darktable theme variables.

Every region in the mock is annotated in the HTML with the DT widget type it
maps to. Treat the HTML flex/grid/SVG purely as a rendering of the end result;
the implementation is GTK boxes + theme CSS. Anything the mock does that the
widget palette can't (see **Buildability** below) is explicitly flagged.

## Fidelity
**High-fidelity** for layout, grouping, hierarchy, states, copy, iconography,
and color intent — but realized through the GTK widget set and theme variables,
not pixel-for-pixel CSS. Match the *structure and semantics*; let darktable's
active theme own the exact pixel rendering of native widgets (combobox/slider
chrome, entry insets, focus rings).

---

## The buildable widget palette (the only components available)

Created via `dt.new_widget("<type>"){…}`. This is the complete set:

| Widget | Use for | Key attributes |
|---|---|---|
| `box` | layout only (h or v) | `orientation`, children |
| `label` | static text | `label`, `ellipsize`, `halign` |
| `section_label` | titled divider (rule/border) | `label` |
| `separator` | thin divider | — |
| `button` | action | `label`, `tooltip`, `clicked_callback`, `sensitive` |
| `check_button` | boolean toggle | `label`, `value` |
| `combobox` | pick-one dropdown | `label`, `value`, items, `changed_callback` |
| `entry` | single-line text | `text`, `tooltip`, `is_password` |
| `file_chooser_button` | native folder/file picker | `title`, `value`, `is_directory` |
| `slider` | numeric value | `soft/hard_min/max`, `step`, `digits`, `label` |
| `stack` | **show ONE child at a time** (tabs/wizard) | `active` child |
| `text_view` | multi-line text (log/dump) | `text`, `editable` |

Shared by all: `name` (the CSS hook — the only per-widget styling handle),
`sensitive`, `visible`, `tooltip`, `reset_callback`.

Structural levers: **`stack`** = tabs (switch active child via a row of
buttons); **nested boxes** = rows/columns; **`section_label`+`separator`** =
grouping; **`sensitive`/`visible`** = progressive disclosure.

---

## Screens / Views

The panel is one tall, narrow vertical column (~332 px) in
`DT_UI_CONTAINER_PANEL_LEFT_CENTER`. The HTML board shows it in five buildable
states plus one out-of-scope concept. **Build the single panel; the "states"
are the same widget tree under different `value`/`sensitive`/`visible`/`label`
conditions.**

### Shared chrome (always present, above the tab `stack`)

1. **Title bar** — h-`box`: a status `label` ("PHOTONFORGE") + a state `label`
   on the right (`IDLE` / `RUNNING` / `SETUP` / `DEV`). The leading status dot is
   conveyed by the state `label`'s color via its `name` (green idle / accent
   running / grey unconfigured).

2. **Cartridge strip** — h-`box`, `name=pf_cartridge`:
   - Left: two `label`s — identity (`PHOTON-001 · ICELAND`) and a `.dt_monospace`
     sub-line (`412 GB free · /mnt/ssd`; becomes `writing · do not eject` while
     running).
   - Right: four icon `button`s in an h-`box` — **Archive**, **Restore**
     (backup), **Provision**, **Safe Eject**. Each spawns its CLI job:
     - Archive / Restore → backup of the cartridge library
     - Provision → `photo-cartridge provision --label <NAME> /mnt/ssd` (FR-1.9)
     - Eject → safe-eject (WAL flush + sync + unmount) `safe_eject.sh` (FR-1.10)
   - All four go `sensitive=false` mid-run.

3. **Configuration** — collapsible (`section_label` + `box` toggled with
   `visible`). When configured, show a one-line `.dt_monospace` summary
   (`/media/SD · ~/Photos/2026 · resume · both`). When unconfigured (first run),
   expand it: three path rows (`label` + `entry` + `file_chooser_button`), the
   two required entries get `name=pf_entry_required`. Corpus JSONL is optional
   (training only).

4. **Tab switch** — h-`box` of two `button`s ("Pipeline" / "Training") driving a
   `stack`. Active button `name=pf_tab_active`, inactive `name=pf_tab_idle`.

### Tab A — Pipeline (`stack` child 1)

- `section_label` "PIPELINE STEPS".
- Five step rows, each an h-`box`: a `check_button` (`label` = step name) + a
  right-aligned status `label` (`name=pf_step_ok` / `pf_step_fail`) reading the
  last-run timestamp + ✓/✗ (or `—`). `ingest` and `import` carry a small "ONCE"
  hint `label` and are unchecked by default (run once per photo set); `dedup`,
  `score`, `name` are the repeatable steps, checked by default.
- Two compact `combobox`es side by side in an h-`box`: **Run mode**
  (resume/force/fresh) and **File type** (both/raw/jpg). Use the `.dt_bauhaus`
  native look.
- Primary action row (h-`box`): **Run** `button` `name=pf_run` (accent fill,
  bold) + **Stop** `button` `name=pf_stop` (`sensitive=false` when idle). When
  running: Run greys out, Stop enables, and a live status block appears —
  current step `label`, a **pseudo-progress bar** (see Buildability), and
  `elapsed` / `ETA` `.dt_monospace` `label`s.

### Tab B — Training / Correction loop (`stack` child 2)

- `section_label` "CORRECTION LOOP" + a helper `label` (instructions).
- Ordered steps as rows (`box` + number `label` + icon + name `label`):
  **1 Collect Corrections**, **2 Recalibrate**.
- Two secondary utility `button`s in an h-`box`: **Sync Tags**, **Refresh Flags**.
- Primary **Full Correction Loop** `button` (`name=pf_run`, accent).
- **Training Weights inspector** (`section_label` "TRAINING WEIGHTS"):
  - Header right: a `.dt_monospace` `label` `v14 · F1 0.82` read from
    `training_weights.db`.
  - "SUBJECT PROTOTYPES" mini-`label` then per-axis value rows (wildlife 0.91,
    person 0.88, building 0.74); "PHOTO-TYPE WEIGHTS" then rows (portrait 0.84,
    landscape 0.79, street 0.61). Each row = name `label` + weight bar
    (approximation) + value `label`.
  - **View full weights table** `button` → opens the full dump in a read-only
    `text_view`.

### Activity log (below the `stack`, always present)

- `section_label` "ACTIVITY LOG" + a `.dt_monospace` read-only `text_view`
  (200-line ring buffer). Prefix lines with `[OK]` / `[ERROR]` / `[RUN]` for
  scannability (per-line color is an approximation — see below).

### Developer mode (gated by one `visible` flag — clean mode hides it entirely)

A `DEV` `label` in the title bar plus an extra `section_label`+`box` block:
- Two toggles (`check_button`): **verbose**, **dry-run**.
- **Resolved command** preview in a `.dt_monospace` `text_view`.
- **Last run · timing** rows (`label`s): `dedup exit 0 · 4.2s`,
  `score exit 1 · 812ms`, `name skipped` (colored ok/fail).
- Two `button`s: **Reload module**, **Open log file**.

### Out of scope — "Dream dashboard" concept (frame F in the HTML)
A north-star concept (progress ring, stat cards, photo thumbnails, filter
chips, per-line colored log). **Do not implement** — it exceeds the widget set
and is included only to show the hierarchy the buildable panel borrows. Build
frames A–E only.

---

## Interactions & Behavior
- **Run** (`run_btn`): saves config, collects enabled steps, dispatches
  `runner.run_all(enabled, append_log, update_status, update_progress)` on a
  background thread (`dt.control.dispatch`) so the UI never freezes. Warn if no
  steps enabled.
- **Stop** (`stop_btn`): `runner.kill()`. Enabled only while a run is active.
- **Tab switch**: set the `stack`'s active child; restyle the two tab buttons.
- **Cartridge buttons**: each spawns its CLI command via the runner and surfaces
  stdout/exit code into the log; disabled while a run is active.
- **Training buttons**: Collect Corrections / Recalibrate / Sync Tags / Full
  Correction Loop each dispatch the corresponding `runner.run_step` /
  `run_all`; long jobs report progress, never block the UI.
- **View full weights table**: load `training_weights.db` dump into the
  `text_view`.
- **Progress**: `update_progress(step, done, total)` updates the current-step
  `label` and the pseudo-bar cells; cleared on completion.
- **State clarity**: Stop/cartridge `sensitive` follows run state; required
  entries flagged until paths resolve; Run `sensitive=false` until the two
  required paths are set.
- **Motion**: any pulse/shimmer is decorative only — never load-bearing (GTK
  transition support is limited; the status dot can simply toggle).

## State Management
Mirrors the existing `config.read/write` model plus run state:
- Per-path config: `sd_path`, `dest_path`, `corpus_path`, `tz_offset`,
  `run_mode`, `file_type` (already in `config.lua`).
- Per-step enable flags `step_<name>` and last-run strings `last_run_<name>`.
- Transient: `is_running`, current step + done/total, elapsed/ETA, dev-mode
  toggles (verbose/dry-run), `dev_visible`, active tab.
- Cartridge identity / free space read from the mounted volume + manifest.
- Training: model version + held-out F1 + per-axis weights from
  `training_weights.db`.

---

## Design Tokens

**Color** — drive accent from theme variables so the panel re-tints with the
active darktable theme; the mock additionally exposes a single tweakable accent.
- **Accent (primary):** `@bauhaus_fill`. Mock default = **dark maroon `#7d2733`**
  (tweakable; alternates shown: `#5a1a22`, `#9b2c3a`, `#6e2438`, amber `#d8a24a`).
- **On-accent text/icon:** light on dark accents (`#f6e7ea`); the mock derives
  it from accent luminance (use light text when the accent is dark).
- **Panel bg:** `@plugin_bg_color` (mock `#1b1b1b`); **inset/entry/log bg:**
  `@grey_10` (mock `#121212`); **section bg:** mock `#181818`–`#202020`.
- **Text:** `@fg_color` primary (mock `#d7d7d7`), muted `#8a8a8a`, dim `#5f5f5f`.
- **Borders/dividers:** `@grey_25` (mock `#2e2e2e`/`#313131`).
- **Semantic status (only hard-coded hex):** success green `#6f9f5f`,
  fail red `#c05a4f`.

**Typography** — system sans (darktable default) for UI; `.dt_monospace`
helper for log, paths, timestamps, weights values, command preview.
Section labels: ~10 px, 700, letter-spacing ~1.2 px, uppercase, muted.
Body: ~11–13 px. Run button label ~13.5 px bold.

**Spacing/radius** — panel padding ~11–13 px; row gaps ~5–7 px; control radius
4–5 px; section dividers via `section_label`/`separator`.

### Proposed CSS hooks (`name` → GTK3-CSS)
```
#pf_run            background:@bauhaus_fill; color:@grey_05; font-weight:bold; border-radius:5px; min-height:34px;
#pf_run:disabled   background:@grey_15; color:@grey_40;
#pf_stop           color:@grey_60; border:1px solid @grey_25;  (red tint on :hover)
#pf_tab_active     background:@bauhaus_fill; color:@grey_05;
#pf_tab_idle       background:@grey_15; color:@grey_60;
#pf_step_ok        color:#6f9f5f;
#pf_step_fail      color:#c05a4f;
#pf_entry_required border-color:@bauhaus_fill;
#pf_log            .dt_monospace; background:@grey_10; font-size:10px;
#pf_section        .dt_section_label; letter-spacing:1px;
#pf_cartridge      background:@grey_10; .dt_monospace free-space sub-label;
#pf_eject          color:@bauhaus_fill on :hover; :disabled while running;
```
Supported CSS subset: selectors by `name`/node/class + `:hover :disabled
:checked :focus`; `color`, `background-color/image` (SVG icons), font props,
border/radius, padding/margin/min-width/min-height, box-shadow/opacity, and the
theme vars (`@bg_color @fg_color @plugin_bg_color @bauhaus_fill @grey_00…100`)
and helpers (`dt_section_label dt_monospace dt_bauhaus dt_dimmed
dt_transparent_background dt_no_hover`). **No** flex/grid/absolute, transitions
the design depends on, tables, or thumbnails.

## Assets — Symbolic icons
Replace all inline emoji with 24×24 monochrome **symbolic SVGs** set as
`background-image` on each button's `name`; `color` drives the glyph so it
follows theme + `:hover`. Needed glyphs:
`run` (play), `stop` (square), `sync` (up-arrow), `collect` (box), `recalibrate`
(star), `loop` (refresh-cycle), `refresh`, `folder` (browse), `eject`,
`cartridge` (hard-drive), `archive`, `restore` (rotate-ccw). Reference shapes
are in the HTML (feather-style strokes).

## Buildability notes (approximations & exclusions)
- ✓ **Tabs, sections, progressive disclosure, cartridge strip, dev block,
  weights values** — all real (`stack`+buttons, `section_label`, `visible`/
  `sensitive`, `button`/`label`).
- ✓ **Accent + status colors** — real via `@bauhaus_fill` + per-`name` CSS.
- ≈ **Progress bar** — *approximation*. No bar widget; build from a row of fixed
  `box` cells recolored per step + a `label` count. Updates discretely.
- ≈ **Weight bars** in the inspector — same fixed-`box` approximation; the
  values themselves are real `label`s.
- ≈ **Per-line log color** — *approximation*. `text_view` is one flat color;
  fall back to `[OK]/[ERR]/[RUN]` text prefixes.
- ✗ **Thumbnails, progress ring, stat cards, filter chips** — dream-only, omit.
- ✗ **Animated pulse/shimmer** — decorative; the status dot can just toggle.

## Files
- `PHOTONForge Panel.dc.html` — the design reference (open in a browser to view
  all five buildable states + the concept; each region is annotated with its DT
  widget mapping).
- `screenshots/` — PNG renders of the design board:
  - `01-idle-and-running.png`, `02-training-firstrun-dev.png`,
    `03-dream-dashboard-top.png`, `04-dream-and-spec-cards.png`.
- Target implementation files in the real repo:
  - `lua/photonforge/panel.lua` — the panel to rebuild.
  - `lua/photonforge/config.lua` — existing config read/write.
  - a bundled `photonforge.css` (or merged into `~/.config/darktable/user.css`)
    for the `name`-targeted theme rules above.
