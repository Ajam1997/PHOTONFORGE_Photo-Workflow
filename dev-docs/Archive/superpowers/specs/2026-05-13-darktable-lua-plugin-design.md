# PHOTONForge Darktable Lua Plugin — Design Spec

**Date:** 2026-05-13
**Status:** Approved
**Author:** Alex Meyer
**Scope:** Darktable left-sidebar plugin + Python engine changes (sequence numbering, `--json-progress`, DB-write removal)

---

## 1. Goal

Embed the PHOTONForge photo analysis pipeline directly into Darktable's lighttable as a collapsible left-sidebar panel. The user selects photos (or an SD card source), toggles individual pipeline steps, clicks Run, and watches progress in real time — without leaving Darktable.

---

## 2. Architecture

### Approach: Thin Lua Shell

Lua is pure UI glue. It builds the panel, launches `photo-workflow` subcommands as subprocesses, reads their stdout JSON line-by-line, and applies results to Darktable images via the native Lua API. All computation — ONNX inference, dedup, scoring, naming — stays in Python.

```
Darktable GUI (Lua plugin)
├── Left sidebar panel: "PHOTONForge"
│   ├── Configuration fields
│   ├── Step toggles with last-run status
│   ├── [Run] / [Stop] buttons
│   ├── Progress bar
│   └── Live log viewer
│
└── On Run → for each enabled step:
        subprocess: photo-workflow <step> --json-progress [args]
        stdout → JSON lines → parsed by Lua
        results → darktable.image API (rating, color label, description, tags)

Python engine (photo-workflow CLI, installed via pip)
├── ingest   → copy from SD, print JSON per file
├── scan     → build manifest, print JSON per file
├── dedup    → flag near-duplicates, print JSON per file
├── score    → sharpness/composition/exposure, print JSON per file
├── name     → sequence rename + BLIP semantic name, print JSON per file
└── sync     → XMP sidecar write only (DB writes removed)
```

**Python engine location:** installed system-wide via `pip install -e .`. The `photo-workflow` entry point is on PATH. No path configuration required.

---

## 3. Lua Plugin File Layout

Installed into Darktable's Lua directory:

```
%APPDATA%\darktable\lua\
└── photonforge\
    ├── main.lua          -- entry point; registers panel with darktable
    ├── panel.lua         -- sidebar widget tree and event handlers
    ├── runner.lua        -- subprocess launch + stdout JSON parsing
    ├── applicator.lua    -- JSON result → darktable.image API calls
    └── config.lua        -- load/save settings via darktable.preferences
```

One line added to `luarc`:

```lua
require "photonforge/main"
```

---

## 4. Panel UI

Left sidebar, collapsible section labelled **PHOTONForge**.

```
▼ PHOTONForge
  ┌─ Configuration ──────────────────┐
  │ SD card path:    [____________]  │
  │ Destination:     [____________]  │
  │ Model dir:       [____________]  │
  │ Manifest:        [____________]  │
  │ TZ offset (hrs): [____]          │
  └──────────────────────────────────┘
  ┌─ Steps ──────────────────────────┐
  │ ☑ Ingest    last: 2026-05-13 ✓  │
  │ ☑ Dedup     last: —             │
  │ ☑ Score     last: 2026-05-13 ✓  │
  │ ☑ Name      last: 2026-05-13 ✓  │
  │ ☐ Sync      last: —             │
  └──────────────────────────────────┘
  [▶ Run PHOTONForge]  [■ Stop]
  ████████░░░░  Score 847/2300
  ┌─ Log ────────────────────────────┐
  │ [14:32:01] score DSC09979 0.87  │
  │ [14:32:02] score DSC09980 0.61  │
  └──────────────────────────────────┘
```

**Config persistence:** All fields saved via `darktable.preferences.register()` under namespace `photonforge`. Stored in `darktablerc`, survive restarts.

**Stop:** Sets a Lua-side abort flag; the running subprocess is killed. The JSONL manifest checkpoint means the next Run resumes from where it stopped.

**Per-step status chips:** Each step row shows last-run timestamp and image count on success, or an error indicator on failure. Stored in preferences.

---

## 5. JSON Progress Protocol

Each Python subcommand gains a `--json-progress` flag. When set, all stdout output is newline-delimited JSON. Human-readable output is unchanged without the flag.

### Line formats

```json
{"step": "ingest",     "file": "DSC09979.ARW", "status": "ok", "dest": "H:\\ICELAND\\20260511_DSC09979.ARW"}
{"step": "dedup",      "file": "00848.ARW",    "status": "duplicate", "keeper": "00847.ARW"}
{"step": "score",      "file": "00847.ARW",    "status": "ok", "sharpness": 0.82, "composition": 0.54, "exposure": 0.71, "stars": 3, "color_label": 2}
{"step": "name",       "file": "00847.ARW",    "status": "ok", "semantic_name": "a-waterfall-in-reykjavik-in-the-morning"}
{"step": "sync",       "file": "00847.ARW",    "status": "ok", "xmp": "00847.xmp"}
{"step": "_progress",  "done": 847, "total": 2300}
{"step": "score",      "file": "00849.ARW",    "status": "error", "message": "failed to decode RAW"}
```

- `status: ok` → applicator writes results to Darktable API
- `status: duplicate` → applicator sets red color label, rating 0
- `status: error` → logged to panel log viewer, image skipped, step continues
- `step: _progress` → updates progress bar; may interleave with image lines

---

## 6. Applicator — JSON → Darktable API Mapping

`applicator.lua` receives parsed JSON and looks up the Darktable image object by matching `file` against `darktable.database`.

| JSON field | Darktable API call |
|---|---|
| `stars` | `image.rating = value` |
| `color_label` (int 0–4) | `darktable.colorlabels` table assignment |
| `semantic_name` | `image:set_metadata("description", value)` |
| `status = "duplicate"` | `image.rating = 0` + red color label (0) |
| `step = "ingest", all files done` | `darktable.films.scan(dest_dir)` called once after ingest subprocess exits — adds all new files to library before subsequent steps run |
| `step = "name", dest` | `image:move(dest_dir, new_filename)` |

The image lookup iterates `darktable.database` filtering by filename. If not found (not yet imported), the result is queued and retried after a brief delay — ingest + scan may add the image to the library moments before name/score results arrive.

---

## 7. Python Engine Changes

### 7.1 `--json-progress` flag

Added to: `ingest`, `scan`, `dedup`, `score`, `name`, `sync` subcommands in `pipeline.py`.

Implementation: a `json_progress` boolean passed through each stage's processing loop. Where `click.echo(...)` currently prints human-readable lines, a helper `emit(record, **fields)` is called instead — prints JSON when flag is set, human text otherwise.

### 7.2 Sequence numbering (`name` subcommand)

New behaviour in the `name` subcommand:

1. Scan destination folder for files matching the source extension (`.ARW`, `.JPG`, etc.)
2. Parse any leading digits from existing filenames; find the maximum
3. If none found, start counter at 1
4. For each record in manifest order:
   - `new_filename = f"{counter:05d}{record.path.suffix}"` → e.g. `00847.ARW`
   - Rename `record.path` → `record.path.parent / new_filename`
   - Store original filename in manifest entry and XMP sidecar (already done)
   - Semantic slug written to manifest `semantic_name` field only — not the filename
   - Increment counter
5. JSON progress line emitted per file with `dest` = new path

Zero-padded to 5 digits (supports up to 99,999 per folder). Extension preserved. Safe against overwrites because the scan happens before any renames.

### 7.3 `darktable_bridge.py` scope reduction

`sync_to_darktable()` DB-write path (`_upsert_to_darktable`, `_set_color_label`, `_apply_quality_labels`, `_upsert_tags`, `_get_or_create_film_id`) is removed. The function retains only XMP sidecar writing (`_write_xmp`). The `sync` subcommand continues to exist for XMP-only use. All Darktable DB/API writes are handled by `applicator.lua`.

### 7.4 Green threshold change (option B)

Switch from per-score thresholds to mean-score green: if no individual score flags the image yellow/blue/purple, and the mean score ≥ 0.5, assign green. Emitted as `color_label: 2` in the score JSON line.

---

## 8. Error Handling

| Scenario | Behaviour |
|---|---|
| `photo-workflow` not on PATH | Panel shows error on Run: "photo-workflow not found. Run: pip install -e ." |
| Subprocess exits non-zero | Step marked failed in status chip; subsequent steps do not run |
| JSON parse error on a line | Line logged as raw text; processing continues |
| Image not found in `darktable.database` | Queued for retry (3 attempts, 500ms apart); if still not found, logged and skipped |
| Stop button pressed | Subprocess killed; manifest checkpoint preserved; next Run resumes |
| Darktable closed mid-run | Subprocess is orphaned; manifest checkpoint preserves progress |

---

## 9. Out of Scope

- Lua plugin packaging / auto-installer (manual install for now)
- Windows tray icon or system notifications
- Tethered shooting / auto-trigger on SD insertion (future: Approach 3 daemon)
- Multi-folder / multi-session in a single run
- Undo support for renames (original filename preserved in XMP)

---

## 10. Files Changed

| File | Change |
|---|---|
| `src/photo_workflow/pipeline.py` | Add `--json-progress` to all subcommands; add sequence numbering to `name` |
| `src/photo_workflow/darktable_bridge.py` | Remove DB-write functions; retain `_write_xmp` only |
| `lua/photonforge/main.lua` | New — plugin entry point |
| `lua/photonforge/panel.lua` | New — sidebar UI |
| `lua/photonforge/runner.lua` | New — subprocess + JSON parsing |
| `lua/photonforge/applicator.lua` | New — JSON → Darktable API |
| `lua/photonforge/config.lua` | New — preferences persistence |
| `luarc` | Add `require "photonforge/main"` |
| `tests/test_naming.py` | Add sequence numbering tests |
| `tests/test_darktable.py` | Remove DB-write tests; add XMP-only tests |
