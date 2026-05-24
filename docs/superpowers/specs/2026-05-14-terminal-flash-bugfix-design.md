# Terminal Flash Elimination & Codebase Bug Fixes

**Date**: 2026-05-14
**Status**: Approved
**Author**: Alex Meyer
**Scope**: lua/photonforge/runner.lua, lua/photonforge/config.lua, pyproject.toml, src/photo_workflow/pipeline.py

## Problem Statement

When Darktable is launched from the Windows Start Menu (GUI subsystem, no parent console), every `os.execute()` and `io.popen()` call in the Lua plugin allocates a new visible console window. The worst offender is the `io.popen('tasklist ...')` polling loop which runs every 500ms, causing rapid repeated terminal flashing. Additional latent bugs were identified during code review.

## Environment

- Windows 11, Darktable 5.4.1 native (GUI launch, no parent console)
- Python 3.11+ with `photo-workflow` installed via pip editable mode
- Florence-2-base-ft INT8 ONNX model at `models/florence2_int8/`

## Fixes

### Fix 1: File-Based Process Alive Detection

**Files**: `runner.lua`, `pipeline.py`

Replace `io.popen('tasklist /FI "IMAGENAME eq photo-workflow.exe" /NH 2>nul')` with file-based detection:

1. Python pipeline writes `%TEMP%\photonforge.pid` containing its PID on startup
2. Python pipeline writes `%TEMP%\photonforge.running` sentinel file on startup, deleted via `atexit` handler on exit
3. Lua polling loop checks sentinel file existence (`io.open(path, "r")` then close) instead of spawning `tasklist`
4. Fallback: if sentinel exists but log file hasn't updated in MAX_IDLE cycles, consider process dead (handles crash without clean exit)

**Why sentinel + PID file (not just PID)**:
- Sentinel existence = fast "is it running?" check with zero subprocess overhead
- PID file = needed for targeted kill (Fix 3)
- atexit deletion handles normal exit; crash leaves sentinel which triggers fallback timeout

### Fix 2: Windowless Python Entry Point

**File**: `pyproject.toml`

Change:
```toml
[project.scripts]
photo-workflow = "photo_workflow.pipeline:main"
```

To:
```toml
[project.gui-scripts]
photo-workflow = "photo_workflow.pipeline:main"
```

This makes pip generate a wrapper using `pythonw.exe` (GUI subsystem) instead of `python.exe` (console subsystem). Since all pipeline output is redirected to the log file by the Lua runner, no console is needed.

The `photo-cartridge` entry stays as `console_scripts` since it's a user-facing CLI tool run from terminals.

### Fix 3: Targeted PID-Based Kill

**File**: `runner.lua`

Replace:
```lua
os.execute('taskkill /F /IM photo-workflow.exe >nul 2>&1')
os.execute('taskkill /F /IM python.exe /FI "WINDOWTITLE eq photo-workflow*" >nul 2>&1')
```

With:
```lua
local pid = read_pid_file()
if pid then
  os.execute('taskkill /F /PID ' .. pid .. ' >nul 2>&1')
end
```

Benefits:
- Cannot accidentally kill unrelated Python processes
- Single call instead of two
- More reliable termination

### Fix 4: Correct Config Default

**File**: `config.lua`

Change line 9 model_dir default from `"models/blip_base"` to `"models/florence2_int8"`.

### Fix 5: Shell Quoting Safety

**File**: `runner.lua`

Replace the fragile nested-quote command construction:
```lua
cmd = 'start /B cmd /c "' .. cmd .. ' >' .. shell_quote(log_path) .. ' 2>&1"'
```

With a temp batch file approach:
1. Write the full command (with redirect) to `%TEMP%\photonforge_run.bat`
2. Execute: `start /B "" "%TEMP%\photonforge_run.bat"`

This avoids nested double-quote escaping issues with paths containing `%`, `"`, `&`, or `^`.

## Files Changed

| File | Change |
|------|--------|
| `lua/photonforge/runner.lua` | Fixes 1, 3, 5 — rewrite process management |
| `lua/photonforge/config.lua` | Fix 4 — correct model_dir default |
| `src/photo_workflow/pipeline.py` | Fix 1 — write PID + sentinel files on start |
| `pyproject.toml` | Fix 2 — gui_scripts entry point |

## Testing

- Manual: Launch Darktable from Start Menu, run pipeline, confirm zero terminal flashes during polling
- Manual: Click Stop, confirm process terminates (one brief flash acceptable)
- Manual: Verify `photo-workflow` command still works when called from terminal (gui_scripts executables still work from cmd/PowerShell)
- Unit: Existing pytest suite passes unchanged (pipeline logic unaffected)

## Risks

- `gui_scripts` on Windows: `pythonw.exe` suppresses stdout/stderr — if the log file redirect fails, errors are silently lost. Mitigated by the sentinel file approach (Lua detects process death via missing sentinel).
- `atexit` not called on SIGKILL/taskkill: sentinel file may persist after crash. Mitigated by the idle timeout fallback already in the polling loop.
