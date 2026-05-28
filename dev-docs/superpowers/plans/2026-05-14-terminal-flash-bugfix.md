# Terminal Flash Elimination & Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate console window flashing in the Darktable Lua plugin on Windows and fix related process management bugs.

**Architecture:** Python pipeline writes PID + sentinel files for Lua to detect process state without spawning subprocesses. Entry point changed to gui_scripts (pythonw.exe) to prevent console allocation. Runner.lua rewritten to use file-based detection, PID-targeted kill, and temp batch file for safe command construction.

**Tech Stack:** Lua 5.4 (Darktable API), Python 3.11+ (click CLI), Windows batch scripting

---

## File Structure

| File | Role |
|------|------|
| `src/photo_workflow/pipeline.py` | Add PID/sentinel lifecycle to `main()` |
| `pyproject.toml` | Move `photo-workflow` to `gui-scripts` |
| `lua/photonforge/runner.lua` | Rewrite process management (polling, kill, launch) |
| `lua/photonforge/config.lua` | Fix model_dir default |
| `tests/test_pipeline.py` | Test PID/sentinel file behavior |

---

### Task 1: Config Default Fix

**Files:**
- Modify: `lua/photonforge/config.lua:9`

- [ ] **Step 1: Fix the model_dir default**

In `lua/photonforge/config.lua`, change line 9 from:

```lua
  { name = "model_dir",    type = "string",  default = "models/blip_base", label = "Model directory" },
```

To:

```lua
  { name = "model_dir",    type = "string",  default = "models/florence2_int8", label = "Model directory" },
```

- [ ] **Step 2: Commit**

```bash
git add lua/photonforge/config.lua
git commit -m "fix: correct model_dir default from blip_base to florence2_int8"
```

---

### Task 2: PID and Sentinel File Lifecycle in Python

**Files:**
- Modify: `src/photo_workflow/pipeline.py:679-680`
- Create: `tests/test_pid_sentinel.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_pid_sentinel.py`:

```python
"""Test PID and sentinel file lifecycle for Lua plugin integration."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


def test_sentinel_created_on_start(tmp_path, monkeypatch):
    """Pipeline main() creates sentinel and PID files in TEMP."""
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))

    from photo_workflow.pipeline import _write_sentinel, _cleanup_sentinel

    _write_sentinel(tmp_path)

    pid_file = tmp_path / "photonforge.pid"
    sentinel = tmp_path / "photonforge.running"

    assert pid_file.exists()
    assert sentinel.exists()
    assert pid_file.read_text().strip() == str(os.getpid())

    _cleanup_sentinel(tmp_path)

    assert not sentinel.exists()
    # PID file stays (Lua may still need to read it for kill)
    assert pid_file.exists()


def test_sentinel_cleanup_is_idempotent(tmp_path):
    """Calling cleanup when sentinel doesn't exist doesn't raise."""
    from photo_workflow.pipeline import _cleanup_sentinel

    # Should not raise even if files don't exist
    _cleanup_sentinel(tmp_path)


def test_stale_sentinel_overwritten(tmp_path):
    """If a stale sentinel exists from a crash, it gets overwritten."""
    from photo_workflow.pipeline import _write_sentinel

    sentinel = tmp_path / "photonforge.running"
    sentinel.write_text("stale")

    pid_file = tmp_path / "photonforge.pid"
    pid_file.write_text("99999")

    _write_sentinel(tmp_path)

    assert pid_file.read_text().strip() == str(os.getpid())
    assert sentinel.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pid_sentinel.py -v`

Expected: FAIL with `ImportError` or `cannot import name '_write_sentinel'`

- [ ] **Step 3: Implement sentinel functions in pipeline.py**

Add these functions before the `main()` function in `src/photo_workflow/pipeline.py` (above line 679):

```python
def _get_temp_dir() -> Path:
    """Return the platform temp directory."""
    import tempfile
    return Path(tempfile.gettempdir())


def _write_sentinel(temp_dir: Path | None = None) -> None:
    """Write PID file and sentinel for Lua plugin process detection."""
    if temp_dir is None:
        temp_dir = _get_temp_dir()
    pid_file = temp_dir / "photonforge.pid"
    sentinel = temp_dir / "photonforge.running"
    pid_file.write_text(str(os.getpid()))
    sentinel.write_text("")


def _cleanup_sentinel(temp_dir: Path | None = None) -> None:
    """Remove sentinel file on clean exit. PID file is left for kill reference."""
    if temp_dir is None:
        temp_dir = _get_temp_dir()
    sentinel = temp_dir / "photonforge.running"
    try:
        sentinel.unlink()
    except FileNotFoundError:
        pass
```

- [ ] **Step 4: Wire sentinel into main()**

Replace the `main()` function in `src/photo_workflow/pipeline.py`:

```python
def main() -> None:
    import atexit
    _write_sentinel()
    atexit.register(_cleanup_sentinel)
    cli()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pid_sentinel.py -v`

Expected: All 3 tests PASS

- [ ] **Step 6: Run full test suite to check for regressions**

Run: `pytest tests/ -v --tb=short`

Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/photo_workflow/pipeline.py tests/test_pid_sentinel.py
git commit -m "feat: add PID and sentinel file lifecycle for Lua process detection"
```

---

### Task 3: Change Entry Point to gui_scripts

**Files:**
- Modify: `pyproject.toml:33-34`

- [ ] **Step 1: Move photo-workflow to gui-scripts**

In `pyproject.toml`, replace:

```toml
[project.scripts]
photo-workflow = "photo_workflow.pipeline:main"
photo-cartridge = "photo_workflow.cartridge:main"
```

With:

```toml
[project.scripts]
photo-cartridge = "photo_workflow.cartridge:main"

[project.gui-scripts]
photo-workflow = "photo_workflow.pipeline:main"
```

- [ ] **Step 2: Reinstall the package**

Run: `pip install -e .`

Expected: Successful install. The `photo-workflow` executable in the Scripts directory is now a `pythonw.exe`-based wrapper.

- [ ] **Step 3: Verify the executable still works from terminal**

Run: `photo-workflow --help`

Expected: Prints help text (gui_scripts executables still work from terminal on Windows).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "fix: change photo-workflow to gui_scripts for windowless execution"
```

---

### Task 4: Rewrite runner.lua Process Management

**Files:**
- Modify: `lua/photonforge/runner.lua` (full rewrite of process management sections)

- [ ] **Step 1: Add sentinel/PID file path helpers**

Replace lines 57-62 of `runner.lua` (the `get_log_path` function) with expanded helper functions:

```lua
local function get_temp_dir()
  if IS_WINDOWS then
    return os.getenv("TEMP") or os.getenv("TMP") or "C:\\Temp"
  end
  return os.getenv("TMPDIR") or "/tmp"
end

local function get_log_path()
  return get_temp_dir() .. (IS_WINDOWS and "\\" or "/") .. "photonforge_step.log"
end

local function get_sentinel_path()
  return get_temp_dir() .. (IS_WINDOWS and "\\" or "/") .. "photonforge.running"
end

local function get_pid_path()
  return get_temp_dir() .. (IS_WINDOWS and "\\" or "/") .. "photonforge.pid"
end

local function read_pid_file()
  local fh = io.open(get_pid_path(), "r")
  if not fh then return nil end
  local pid = fh:read("*l")
  fh:close()
  if pid then pid = pid:match("^%s*(%d+)%s*$") end
  return pid
end

local function is_process_alive()
  local sentinel = get_sentinel_path()
  local fh = io.open(sentinel, "r")
  if fh then
    fh:close()
    return true
  end
  return false
end
```

- [ ] **Step 2: Rewrite M.kill() to use PID-based kill**

Replace the existing `M.kill()` function (lines 47-55) with:

```lua
function M.kill()
  M.abort = true
  local pid = read_pid_file()
  if IS_WINDOWS then
    if pid then
      os.execute('taskkill /F /PID ' .. pid .. ' >nul 2>&1')
    end
  else
    if pid then
      os.execute("kill -9 " .. pid .. " 2>/dev/null")
    else
      os.execute("pkill -f 'photo-workflow' 2>/dev/null")
    end
  end
  -- Clean up sentinel in case atexit didn't fire
  local sentinel = get_sentinel_path()
  os.remove(sentinel)
end
```

- [ ] **Step 3: Rewrite run_step() launch to use temp batch file**

Replace the command construction and launch section (lines 64-77 of original) in `M.run_step`:

```lua
function M.run_step(step, log_fn, job)
  local cmd = build_cmd(step)
  local log_path = get_log_path()
  log_fn(string.format("[%s] Running: %s", os.date("%H:%M:%S"), cmd))

  -- Clear log file
  local f = io.open(log_path, "w")
  if f then f:close() end

  if IS_WINDOWS then
    -- Write command to temp batch file to avoid nested quoting issues
    local bat_path = get_temp_dir() .. "\\photonforge_run.bat"
    local bf = io.open(bat_path, "w")
    if bf then
      bf:write("@echo off\r\n")
      bf:write(cmd .. ' >"' .. log_path .. '" 2>&1\r\n')
      bf:close()
    end
    os.execute('start /B "" "' .. bat_path .. '"')
  else
    cmd = cmd .. " > " .. shell_quote(log_path) .. " 2>&1 &"
    os.execute(cmd)
  end
```

- [ ] **Step 4: Rewrite the polling loop to use file-based alive detection**

Replace the process-alive check section (lines 100-121 of original) within the `while not M.abort` loop:

```lua
    if new_data == nil or new_data == "" then
      if not is_process_alive() then
        break
      end

      idle_count = idle_count + 1
      if idle_count > MAX_IDLE then break end
      goto continue
    end
```

This replaces the entire `io.popen('tasklist ...')` / `os.execute("pgrep ...")` block with a single file existence check.

- [ ] **Step 5: Assemble the complete rewritten runner.lua**

Write the full file `lua/photonforge/runner.lua`:

```lua
local dt = require "darktable"
local json = require "photonforge/json"
local config = require "photonforge/config"
local applicator = require "photonforge/applicator"

local M = {}

M.abort = false

local IS_WINDOWS = package.config:sub(1,1) == "\\"

local function shell_quote(s)
  if IS_WINDOWS then
    s = s:gsub("\\$", "")
    return '"' .. s .. '"'
  end
  return "'" .. s:gsub("'", "'\\''") .. "'"
end

local function build_cmd(step)
  local manifest = config.read("manifest")
  local model_dir = config.read("model_dir")
  local tz = tostring(config.read("tz_offset"))
  local dest = config.read("dest_path")
  local sd = config.read("sd_path")

  local base = "photo-workflow " .. step .. " --json-progress"

  if step == "ingest" then
    return base .. " --source " .. shell_quote(sd) .. " --dest " .. shell_quote(dest)
  elseif step == "scan" then
    return base .. " --source " .. shell_quote(dest) .. " --manifest " .. shell_quote(manifest)
  elseif step == "dedup" then
    return base .. " --manifest " .. shell_quote(manifest)
  elseif step == "score" then
    return base .. " --manifest " .. shell_quote(manifest)
  elseif step == "name" then
    return base .. " --manifest " .. shell_quote(manifest)
              .. " --model-dir " .. shell_quote(model_dir)
              .. " --tz-offset " .. tz
  elseif step == "sync" then
    return base .. " --manifest " .. shell_quote(manifest)
  end
  error("Unknown step: " .. step)
end

local function get_temp_dir()
  if IS_WINDOWS then
    return os.getenv("TEMP") or os.getenv("TMP") or "C:\\Temp"
  end
  return os.getenv("TMPDIR") or "/tmp"
end

local function get_log_path()
  return get_temp_dir() .. (IS_WINDOWS and "\\" or "/") .. "photonforge_step.log"
end

local function get_sentinel_path()
  return get_temp_dir() .. (IS_WINDOWS and "\\" or "/") .. "photonforge.running"
end

local function get_pid_path()
  return get_temp_dir() .. (IS_WINDOWS and "\\" or "/") .. "photonforge.pid"
end

local function read_pid_file()
  local fh = io.open(get_pid_path(), "r")
  if not fh then return nil end
  local pid = fh:read("*l")
  fh:close()
  if pid then pid = pid:match("^%s*(%d+)%s*$") end
  return pid
end

local function is_process_alive()
  local fh = io.open(get_sentinel_path(), "r")
  if fh then
    fh:close()
    return true
  end
  return false
end

function M.kill()
  M.abort = true
  local pid = read_pid_file()
  if IS_WINDOWS then
    if pid then
      os.execute('taskkill /F /PID ' .. pid .. ' >nul 2>&1')
    end
  else
    if pid then
      os.execute("kill -9 " .. pid .. " 2>/dev/null")
    else
      os.execute("pkill -f 'photo-workflow' 2>/dev/null")
    end
  end
  os.remove(get_sentinel_path())
end

function M.run_step(step, log_fn, job)
  local cmd = build_cmd(step)
  local log_path = get_log_path()
  log_fn(string.format("[%s] Running: %s", os.date("%H:%M:%S"), cmd))

  local f = io.open(log_path, "w")
  if f then f:close() end

  if IS_WINDOWS then
    local bat_path = get_temp_dir() .. "\\photonforge_run.bat"
    local bf = io.open(bat_path, "w")
    if bf then
      bf:write("@echo off\r\n")
      bf:write(cmd .. ' >"' .. log_path .. '" 2>&1\r\n')
      bf:close()
    end
    os.execute('start /B "" "' .. bat_path .. '"')
  else
    cmd = cmd .. " > " .. shell_quote(log_path) .. " 2>&1 &"
    os.execute(cmd)
  end

  local dest = config.read("dest_path")
  local done, total = 0, 0
  local last_pos = 0
  local idle_count = 0
  local MAX_IDLE = 600

  while not M.abort do
    dt.control.sleep(500)

    local fh = io.open(log_path, "r")
    if fh == nil then
      idle_count = idle_count + 1
      if idle_count > MAX_IDLE then break end
      goto continue
    end

    fh:seek("set", last_pos)
    local new_data = fh:read("*a")
    last_pos = fh:seek()
    fh:close()

    if new_data == nil or new_data == "" then
      if not is_process_alive() then
        break
      end

      idle_count = idle_count + 1
      if idle_count > MAX_IDLE then break end
      goto continue
    end

    idle_count = 0
    for line in new_data:gmatch("[^\r\n]+") do
      local ok, rec = pcall(json.decode, line)
      if ok and type(rec) == "table" then
        if rec.step == "_progress" then
          done  = rec.done  or done
          total = rec.total or total
          if job ~= nil and total > 0 then
            job.percent = done / total
          end
        else
          local msg = string.format("[%s] %s %s [%s]",
            os.date("%H:%M:%S"), rec.step or "?", rec.file or "", rec.status or "")
          log_fn(msg)
          applicator.apply(rec, dest)
        end
      else
        log_fn(line)
      end
    end

    ::continue::
  end

  if M.abort then
    M.kill()
    log_fn("[STOPPED] Run aborted by user.")
    return false
  end

  local fh = io.open(log_path, "r")
  if fh then
    fh:seek("set", last_pos)
    local remaining = fh:read("*a")
    fh:close()
    if remaining and remaining ~= "" then
      for line in remaining:gmatch("[^\r\n]+") do
        local ok, rec = pcall(json.decode, line)
        if ok and type(rec) == "table" and rec.step ~= "_progress" then
          local msg = string.format("[%s] %s %s [%s]",
            os.date("%H:%M:%S"), rec.step or "?", rec.file or "", rec.status or "")
          log_fn(msg)
          applicator.apply(rec, dest)
        elseif not ok then
          log_fn(line)
        end
      end
    end
  end

  return true
end

function M.run_all(step_list, log_fn, status_fn)
  M.abort = false
  local total_steps = #step_list
  local job = dt.gui.create_job(
    "PHOTONForge (" .. total_steps .. " steps)", true,
    function() M.kill() end
  )
  job.percent = 0.0

  for i, step in ipairs(step_list) do
    if M.abort then break end
    log_fn(string.format("--- Step %d/%d: %s ---", i, total_steps, step))
    local ok = M.run_step(step, log_fn, job)

    if step == "ingest" and ok then
      local dest = config.read("dest_path")
      local film = dt.films.new(dest)
      if film then
        log_fn("[ingest] Library rescanned: " .. dest)
      else
        log_fn("[ingest] Could not import folder: " .. dest)
      end
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

  pcall(function() job.valid = false end)
  pcall(function() job:destroy() end)
end

return M
```

- [ ] **Step 6: Commit**

```bash
git add lua/photonforge/runner.lua
git commit -m "fix: eliminate terminal flashing with file-based process detection and batch launcher"
```

---

### Task 5: Integration Verification

- [ ] **Step 1: Run full pytest suite**

Run: `pytest tests/ -v --tb=short`

Expected: All tests PASS

- [ ] **Step 2: Verify photo-workflow still produces help output**

Run: `photo-workflow --help`

Expected: Prints the CLI help with all subcommands (ingest, scan, dedup, score, name, sync, status, run)

- [ ] **Step 3: Verify sentinel file behavior manually**

Run:
```powershell
photo-workflow scan --source . --manifest test_manifest.jsonl --json-progress
```

Then check:
```powershell
Test-Path "$env:TEMP\photonforge.running"
Get-Content "$env:TEMP\photonforge.pid"
```

Expected: During execution, both files exist. After completion, `photonforge.running` is deleted, `photonforge.pid` remains with the PID that was used.

- [ ] **Step 4: Clean up test artifact**

```powershell
Remove-Item test_manifest.jsonl -ErrorAction SilentlyContinue
```

- [ ] **Step 5: Final commit if any cleanup needed**

If any test revealed issues that required fixes, commit them:

```bash
git add -u
git commit -m "fix: address integration test findings"
```
