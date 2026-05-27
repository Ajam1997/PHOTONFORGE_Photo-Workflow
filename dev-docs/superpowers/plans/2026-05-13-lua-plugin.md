# PHOTONForge Darktable Lua Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Darktable left-sidebar plugin that runs the `photo-workflow` CLI subcommands as subprocesses, reads their `--json-progress` stdout, and applies results (ratings, color labels, description) to Darktable images via the native Lua API.

**Architecture:** Five Lua files installed under `%APPDATA%\darktable\lua\photonforge\`. `main.lua` registers with Darktable and wires the other modules. `config.lua` persists settings via `darktable.preferences`. `panel.lua` builds the sidebar widget tree. `runner.lua` launches subprocesses and parses JSON stdout line by line. `applicator.lua` maps parsed JSON fields to `darktable.image` API calls.

**Tech Stack:** Darktable 5.x Lua API, `darktable.preferences`, `darktable.gui.libs`, `darktable.control.execute()`, `darktable.films.scan()`, `io.popen()` for subprocess I/O

**Prerequisites:** Plan 1 (Python engine changes) must be complete — the Lua plugin depends on `--json-progress` output from `photo-workflow`.

---

## Darktable Lua API Reference

Key APIs used in this plan:

```lua
-- Preferences
darktable.preferences.register(script, name, type, label, tooltip, default)
darktable.preferences.read(script, name, type)
darktable.preferences.write(script, name, type, value)

-- GUI
darktable.gui.libs.register(name, label, expandable, reset_callback, widget, position)
dt_lua_widget.new("box")    -- container
dt_lua_widget.new("label")
dt_lua_widget.new("entry")  -- text input
dt_lua_widget.new("check_button")
dt_lua_widget.new("button")
dt_lua_widget.new("slider")
dt_lua_widget.new("text_view")  -- log viewer

-- Database / images
darktable.database           -- array-like, all images in library
image.filename               -- bare filename e.g. "00001.ARW"
image.path                   -- folder path
image.rating                 -- integer 0-5
image:set_metadata("description", value)
darktable.colorlabels        -- table; set via image.red/yellow/green/blue/purple booleans

-- Films / import
darktable.films.scan(path)   -- rescan a folder into the library

-- Job progress
local job = darktable.gui.create_job("PHOTONForge", true, cancel_callback)
job.percent = 0.5   -- 0.0-1.0
job:destroy()

-- Subprocess
local handle = io.popen(cmd, "r")
local line = handle:read("*l")
handle:close()
```

---

## File Map

| File | Responsibility |
|---|---|
| `lua/photonforge/main.lua` | Entry point; requires other modules; registers panel |
| `lua/photonforge/config.lua` | Load/save all preferences; expose as `config` table |
| `lua/photonforge/panel.lua` | Build sidebar widget tree; expose `panel.widget` |
| `lua/photonforge/runner.lua` | Launch subprocess; yield JSON lines; call applicator |
| `lua/photonforge/applicator.lua` | Map JSON → `darktable.image` API calls |

Installation target: `%APPDATA%\darktable\lua\photonforge\`  
`luarc` addition: `require "photonforge/main"`

---

## Task 1: Project scaffold + `config.lua`

**Files:**
- Create: `lua/photonforge/config.lua`
- Create: `lua/photonforge/main.lua` (stub only)

- [ ] **Step 1: Create the `lua/photonforge/` directory**

```
mkdir lua\photonforge
```

- [ ] **Step 2: Create `config.lua`**

Create `lua/photonforge/config.lua`:

```lua
-- config.lua: load and save PHOTONForge preferences via darktable.preferences
local dt = require "darktable"
local M = {}

local SCRIPT = "photonforge"

local DEFS = {
  { name = "sd_path",      type = "string",  default = "",   label = "SD card path" },
  { name = "dest_path",    type = "string",  default = "",   label = "Destination path" },
  { name = "model_dir",    type = "string",  default = "models/blip_base", label = "Model directory" },
  { name = "manifest",     type = "string",  default = "manifest.jsonl",   label = "Manifest path" },
  { name = "tz_offset",    type = "integer", default = 0,    label = "TZ offset (hours)" },
  { name = "step_ingest",  type = "bool",    default = true, label = "Ingest" },
  { name = "step_dedup",   type = "bool",    default = true, label = "Dedup" },
  { name = "step_score",   type = "bool",    default = true, label = "Score" },
  { name = "step_name",    type = "bool",    default = true, label = "Name" },
  { name = "step_sync",    type = "bool",    default = false, label = "Sync (XMP)" },
  { name = "last_run_ingest",  type = "string",  default = "", label = "" },
  { name = "last_run_dedup",   type = "string",  default = "", label = "" },
  { name = "last_run_score",   type = "string",  default = "", label = "" },
  { name = "last_run_name",    type = "string",  default = "", label = "" },
  { name = "last_run_sync",    type = "string",  default = "", label = "" },
}

-- Register all preferences with Darktable on first load
for _, d in ipairs(DEFS) do
  darktable.preferences.register(
    SCRIPT, d.name, d.type, d.label, "PHOTONForge: " .. d.label, d.default
  )
end

function M.read(name)
  for _, d in ipairs(DEFS) do
    if d.name == name then
      return darktable.preferences.read(SCRIPT, name, d.type)
    end
  end
  error("Unknown config key: " .. name)
end

function M.write(name, value)
  for _, d in ipairs(DEFS) do
    if d.name == name then
      darktable.preferences.write(SCRIPT, name, d.type, value)
      return
    end
  end
  error("Unknown config key: " .. name)
end

return M
```

- [ ] **Step 3: Create stub `main.lua`**

Create `lua/photonforge/main.lua`:

```lua
-- main.lua: PHOTONForge plugin entry point
local dt = require "darktable"
local config = require "photonforge/config"

dt.print_log("PHOTONForge: loaded (stub)")
```

- [ ] **Step 4: Install and verify Darktable loads without errors**

Copy files to Darktable's Lua dir:
```
xcopy /E /Y lua\photonforge "%APPDATA%\darktable\lua\photonforge\"
```

Add to `%APPDATA%\darktable\luarc`:
```
require "photonforge/main"
```

Start Darktable, open Help > Lua console, run:
```lua
return "PHOTONForge config sd_path=" .. require("photonforge/config").read("sd_path")
```
Expected: no error, returns `"PHOTONForge config sd_path="`

- [ ] **Step 5: Commit**

```
git add lua/
git commit -m "feat: scaffold photonforge Lua plugin with config module"
```

---

## Task 2: `applicator.lua` — JSON → Darktable image API

**Files:**
- Create: `lua/photonforge/applicator.lua`

- [ ] **Step 1: Create `applicator.lua`**

Create `lua/photonforge/applicator.lua`:

```lua
-- applicator.lua: map JSON progress records → darktable.image API calls
local dt = require "darktable"
local M = {}

-- Find a darktable image by bare filename and folder path.
-- Returns the image object or nil.
local function find_image(filename, folder)
  for _, img in ipairs(dt.database) do
    if img.filename == filename and img.path == folder then
      return img
    end
  end
  return nil
end

-- Apply a parsed JSON record to the matching darktable image.
-- rec is a table with at minimum: step, file, status
-- folder is the destination directory string (used for image lookup)
function M.apply(rec, folder)
  if rec.step == "_progress" then
    return  -- handled by runner, not applicator
  end

  if rec.status == "error" then
    dt.print_log(string.format("PHOTONForge error [%s] %s: %s",
      rec.step, rec.file or "?", rec.message or "unknown"))
    return
  end

  -- ingest: just log; darktable.films.scan() called by runner after step completes
  if rec.step == "ingest" then
    dt.print_log(string.format("PHOTONForge ingested: %s", rec.file or ""))
    return
  end

  local img = find_image(rec.file, folder)
  if img == nil then
    dt.print_log(string.format("PHOTONForge: image not found in library: %s", rec.file or ""))
    return
  end

  if rec.step == "dedup" then
    if rec.status == "duplicate" then
      img.rating = 0
      img.red = true
    end

  elseif rec.step == "score" then
    if rec.stars ~= nil then
      img.rating = math.min(5, math.max(0, math.floor(rec.stars + 0.5)))
    end
    -- color_label: -1=none, 0=red, 1=yellow, 2=green, 3=blue, 4=purple
    local cl = rec.color_label
    if cl ~= nil and cl >= 0 then
      img.red    = (cl == 0)
      img.yellow = (cl == 1)
      img.green  = (cl == 2)
      img.blue   = (cl == 3)
      img.purple = (cl == 4)
    end

  elseif rec.step == "name" then
    if rec.semantic_name ~= nil then
      img:set_metadata("description", rec.semantic_name)
    end

  elseif rec.step == "sync" then
    -- XMP written by Python; nothing to apply via API
    dt.print_log(string.format("PHOTONForge XMP written: %s", rec.xmp or ""))
  end
end

return M
```

- [ ] **Step 2: Verify in Lua console**

Copy updated files to Darktable Lua dir, restart Darktable, then in Lua console:
```lua
local a = require "photonforge/applicator"
-- Should load without error
return type(a.apply)
```
Expected: `"function"`

- [ ] **Step 3: Commit**

```
git add lua/photonforge/applicator.lua
git commit -m "feat: add applicator.lua - JSON result → darktable image API"
```

---

## Task 3: `runner.lua` — subprocess launch + JSON parsing

**Files:**
- Create: `lua/photonforge/runner.lua`

- [ ] **Step 1: Create `runner.lua`**

Create `lua/photonforge/runner.lua`:

```lua
-- runner.lua: launch photo-workflow subprocesses and parse JSON stdout
local dt = require "darktable"
local json = require "darktable.json"   -- built-in since Darktable 4.x
local config = require "photonforge/config"
local applicator = require "photonforge/applicator"

local M = {}

-- Shared abort flag — set by Stop button
M.abort = false

-- Build the command string for a given step
local function build_cmd(step)
  local manifest = config.read("manifest")
  local model_dir = config.read("model_dir")
  local tz = tostring(config.read("tz_offset"))
  local dest = config.read("dest_path")
  local sd = config.read("sd_path")

  local base = "photo-workflow " .. step .. " --json-progress"

  if step == "ingest" then
    return base .. ' --source "' .. sd .. '" --dest "' .. dest .. '"'
  elseif step == "scan" then
    return base .. ' --source "' .. dest .. '" --manifest "' .. manifest .. '"'
  elseif step == "dedup" then
    return base .. ' --manifest "' .. manifest .. '" --resume'
  elseif step == "score" then
    return base .. ' --manifest "' .. manifest .. '" --resume'
  elseif step == "name" then
    return base .. ' --manifest "' .. manifest .. '" --resume'
              .. ' --model-dir "' .. model_dir .. '"'
              .. ' --tz-offset ' .. tz
  elseif step == "sync" then
    return base .. ' --manifest "' .. manifest .. '"'
  end
  error("Unknown step: " .. step)
end

-- Run a single step. log_fn(msg) is called for each log line.
-- job is a darktable job object for progress bar updates.
-- Returns true on success, false on failure.
function M.run_step(step, log_fn, job)
  M.abort = false
  local cmd = build_cmd(step)
  log_fn(string.format("[%s] Running: %s", os.date("%H:%M:%S"), cmd))

  local handle = io.popen(cmd, "r")
  if handle == nil then
    log_fn("[ERROR] Failed to launch photo-workflow. Is it installed?")
    return false
  end

  local dest = config.read("dest_path")
  local done, total = 0, 0

  for line in handle:lines() do
    if M.abort then
      handle:close()
      log_fn("[STOPPED] Run aborted by user.")
      return false
    end

    -- Try to parse as JSON
    local ok, rec = pcall(json.decode, line)
    if ok and type(rec) == "table" then
      if rec.step == "_progress" then
        done  = rec.done  or done
        total = rec.total or total
        if job ~= nil and total > 0 then
          job.percent = done / total
        end
      else
        -- Log to panel
        local msg = string.format("[%s] %s %s [%s]",
          os.date("%H:%M:%S"), rec.step or "?", rec.file or "", rec.status or "")
        log_fn(msg)
        -- Apply to Darktable
        applicator.apply(rec, dest)
      end
    else
      -- Not JSON — log as-is (human-readable fallback or stderr bleed)
      log_fn(line)
    end
  end

  local ok_close = handle:close()
  return ok_close ~= false
end

-- Run all enabled steps in sequence.
-- step_list: array of step name strings e.g. {"ingest","scan","dedup","score","name"}
-- log_fn: function(msg) called for each log line
-- status_fn: function(step, result, count_str) updates per-step chips
function M.run_all(step_list, log_fn, status_fn)
  local total_steps = #step_list
  local job = darktable.gui.create_job(
    "PHOTONForge (" .. total_steps .. " steps)", true,
    function() M.abort = true end
  )
  job.percent = 0.0

  for i, step in ipairs(step_list) do
    log_fn(string.format("--- Step %d/%d: %s ---", i, total_steps, step))
    local ok = M.run_step(step, log_fn, job)

    if step == "ingest" and ok then
      -- Trigger Darktable library rescan so new files appear before score/name
      local dest = config.read("dest_path")
      darktable.films.scan(dest)
      log_fn("[ingest] Library rescanned: " .. dest)
    end

    local result = ok and "ok" or "error"
    if status_fn ~= nil then
      status_fn(step, result, os.date("%Y-%m-%d %H:%M"))
    end

    if not ok then
      log_fn("[STOPPED] Step failed: " .. step .. ". Remaining steps skipped.")
      break
    end

    job.percent = i / total_steps
  end

  job:destroy()
end

return M
```

- [ ] **Step 2: Verify module loads in Lua console**

```lua
local r = require "photonforge/runner"
return type(r.run_step)
```
Expected: `"function"`

- [ ] **Step 3: Commit**

```
git add lua/photonforge/runner.lua
git commit -m "feat: add runner.lua - subprocess launch and JSON stdout parsing"
```

---

## Task 4: `panel.lua` — sidebar widget tree

**Files:**
- Create: `lua/photonforge/panel.lua`

- [ ] **Step 1: Create `panel.lua`**

Create `lua/photonforge/panel.lua`:

```lua
-- panel.lua: PHOTONForge left-sidebar widget tree
local dt = require "darktable"
local config = require "photonforge/config"
local runner = require "photonforge/runner"

local M = {}

local LOG_MAX_LINES = 200

-- Build and return the root widget for the sidebar panel
function M.build()
  -- ── Configuration section ──────────────────────────────────────────────

  local function make_path_entry(label_text, config_key)
    local lbl = dt.new_widget("label") { label = label_text }
    local entry = dt.new_widget("entry") {
      text = config.read(config_key),
      tooltip = label_text,
      changed_callback = function(w)
        config.write(config_key, w.text)
      end,
    }
    return dt.new_widget("box") {
      orientation = "horizontal",
      lbl, entry,
    }
  end

  local config_box = dt.new_widget("box") {
    orientation = "vertical",
    make_path_entry("SD card path:",  "sd_path"),
    make_path_entry("Destination:",   "dest_path"),
    make_path_entry("Model dir:",     "model_dir"),
    make_path_entry("Manifest:",      "manifest"),
  }

  local tz_label = dt.new_widget("label") { label = "TZ offset (hrs):" }
  local tz_entry = dt.new_widget("entry") {
    text = tostring(config.read("tz_offset")),
    tooltip = "Hours to add to EXIF timestamp",
    changed_callback = function(w)
      local n = tonumber(w.text) or 0
      config.write("tz_offset", n)
    end,
  }
  local tz_box = dt.new_widget("box") {
    orientation = "horizontal", tz_label, tz_entry,
  }

  -- ── Step toggles ────────────────────────────────────────────────────────

  local steps = {"ingest", "dedup", "score", "name", "sync"}
  local step_checks = {}
  local last_run_labels = {}

  local steps_box = dt.new_widget("box") { orientation = "vertical" }

  for _, step in ipairs(steps) do
    local check = dt.new_widget("check_button") {
      label = step,
      value = config.read("step_" .. step),
      tooltip = "Enable " .. step .. " step",
      clicked_callback = function(w)
        config.write("step_" .. step, w.value)
      end,
    }
    local last_lbl = dt.new_widget("label") {
      label = "last: " .. (config.read("last_run_" .. step) ~= "" and config.read("last_run_" .. step) or "—"),
    }
    step_checks[step] = check
    last_run_labels[step] = last_lbl

    local row = dt.new_widget("box") {
      orientation = "horizontal", check, last_lbl,
    }
    steps_box[#steps_box + 1] = row
  end

  -- ── Run / Stop buttons ───────────────────────────────────────────────────

  local log_lines = {}
  local log_view = dt.new_widget("text_view") {
    editable = false,
    text = "",
  }

  local function append_log(msg)
    table.insert(log_lines, msg)
    if #log_lines > LOG_MAX_LINES then
      table.remove(log_lines, 1)
    end
    log_view.text = table.concat(log_lines, "\n")
  end

  local function update_status(step, result, timestamp)
    local mark = result == "ok" and "✓" or "✗"
    local text = string.format("last: %s %s", timestamp, mark)
    last_run_labels[step].label = text
    config.write("last_run_" .. step, timestamp .. " " .. mark)
  end

  local stop_btn = dt.new_widget("button") {
    label = "■ Stop",
    tooltip = "Abort current run",
    clicked_callback = function()
      runner.abort = true
    end,
  }

  local run_btn = dt.new_widget("button") {
    label = "▶ Run PHOTONForge",
    tooltip = "Run enabled pipeline steps",
    clicked_callback = function()
      local enabled = {}
      for _, step in ipairs(steps) do
        if config.read("step_" .. step) then
          table.insert(enabled, step)
        end
      end
      if #enabled == 0 then
        append_log("[WARN] No steps enabled.")
        return
      end

      -- Run in a Darktable background job so the GUI stays responsive
      darktable.control.dispatch(function()
        runner.run_all(enabled, append_log, update_status)
      end)
    end,
  }

  local btn_box = dt.new_widget("box") {
    orientation = "horizontal", run_btn, stop_btn,
  }

  -- ── Root container ────────────────────────────────────────────────────────

  local root = dt.new_widget("box") {
    orientation = "vertical",
    config_box,
    tz_box,
    steps_box,
    btn_box,
    log_view,
  }

  M.widget = root
  return root
end

return M
```

- [ ] **Step 2: Verify module loads without error**

```lua
local p = require "photonforge/panel"
return type(p.build)
```
Expected: `"function"`

- [ ] **Step 3: Commit**

```
git add lua/photonforge/panel.lua
git commit -m "feat: add panel.lua - left-sidebar widget tree"
```

---

## Task 5: `main.lua` — register panel with Darktable

**Files:**
- Modify: `lua/photonforge/main.lua`

- [ ] **Step 1: Replace stub `main.lua` with full registration**

Replace `lua/photonforge/main.lua` with:

```lua
-- main.lua: PHOTONForge Darktable plugin entry point
local dt = require "darktable"

-- Guard against double-loading
if dt.preferences.read("photonforge", "_loaded", "bool") then
  return
end
dt.preferences.register("photonforge", "_loaded", "bool", "", "", false)
dt.preferences.write("photonforge", "_loaded", "bool", true)

local config = require "photonforge/config"
local panel  = require "photonforge/panel"

-- Build the sidebar widget once
local widget = panel.build()

-- Register as a Darktable lighttable left-panel lib
dt.gui.libs.register(
  "photonforge",         -- unique name
  "PHOTONForge",         -- display label
  true,                  -- expandable
  function() end,        -- reset callback (no-op)
  widget,                -- root widget
  dt.gui.views.lighttable,  -- visible in lighttable only
  {"DT_UI_CONTAINER_PANEL_LEFT_CENTER", 99}  -- position
)

dt.print_log("PHOTONForge: plugin registered")
```

- [ ] **Step 2: Install and verify panel appears**

```
xcopy /E /Y lua\photonforge "%APPDATA%\darktable\lua\photonforge\"
```

Restart Darktable. Open the lighttable view. Verify "PHOTONForge" appears as a collapsible panel in the left sidebar. Expand it — all configuration fields and step checkboxes should be visible.

- [ ] **Step 3: Verify preferences persist across restart**

1. Type a path in the "Destination" field
2. Close Darktable
3. Reopen Darktable
4. Expand the PHOTONForge panel
5. Verify the path is still there

- [ ] **Step 4: Commit**

```
git add lua/photonforge/main.lua
git commit -m "feat: register PHOTONForge panel in Darktable lighttable"
```

---

## Task 6: End-to-end smoke test

**Files:**
- No code changes — manual verification only

- [ ] **Step 1: Prepare test conditions**

1. Have at least 3 `.ARW` or `.JPG` files in a test folder
2. `photo-workflow` must be installed and on PATH: `photo-workflow --help` should print usage
3. In the PHOTONForge panel, set Destination to your test folder and Manifest to a temp path

- [ ] **Step 2: Run scan step only**

1. Uncheck all steps except "scan"
2. Click "▶ Run PHOTONForge"
3. Verify log shows one JSON line per photo with `"step": "scan", "status": "ok"`
4. Verify manifest file was created at configured path

- [ ] **Step 3: Run score step**

1. Check "score", uncheck all others
2. Click Run
3. Verify log shows score lines with sharpness/composition/exposure values
4. Open one photo in Darktable lighttable — verify star rating was applied

- [ ] **Step 4: Run name step**

1. Check "name" only
2. Click Run
3. Verify log shows `"step": "name"` lines with semantic names
4. Verify files on disk were renamed to `00001.ARW`, `00002.ARW` etc.
5. Open one photo — verify description field shows the semantic name

- [ ] **Step 5: Test Stop button**

1. Enable score + name on a large folder (100+ photos)
2. Click Run, then immediately click Stop
3. Verify run halts mid-progress and log shows "[STOPPED] Run aborted by user."
4. Verify manifest checkpoint preserved — re-running with resume picks up where it stopped

- [ ] **Step 6: Commit final installation docs**

Create `lua/photonforge/README.md`:

```markdown
# PHOTONForge Darktable Plugin

## Installation

1. Install the Python engine: `pip install -e .` from the repo root
2. Copy the plugin: `xcopy /E /Y lua\photonforge "%APPDATA%\darktable\lua\photonforge\"`
3. Add to `%APPDATA%\darktable\luarc`: `require "photonforge/main"`
4. Restart Darktable

## Usage

Open the lighttable view. Expand the "PHOTONForge" panel in the left sidebar.
Configure paths, toggle steps, click Run.
```

```
git add lua/photonforge/README.md
git commit -m "docs: add PHOTONForge Lua plugin installation README"
```
