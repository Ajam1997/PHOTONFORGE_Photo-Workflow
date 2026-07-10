# Runner Process-Lifecycle Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Darktable panel runner track each step's process by real PID so long steps (score ≈ 25 min, name ≈ 13 min) run to completion, are reported success/failure correctly, and Stop/new-run never kill unrelated processes.

**Architecture:** Each step's background CLI is launched so its process-tree PID is written to a per-step `.pid` file. The watch loop's completion signal becomes the per-step `.exit` file (a plain file check — never deleted by another run, unlike the old shared `photonforge.running` sentinel). PID + `tasklist`/`kill -0` are used only for scoped kill and a single-active-run guard, never in the 500 ms poll loop.

**Tech Stack:** Lua (Darktable plugin API), Windows `cmd`/PowerShell/`wscript`, POSIX `sh`/`setsid`. No Python changes.

## Global Constraints

- Target files: `lua/photonforge/runner.lua` (core) and `lua/photonforge/panel.lua` (run guard wiring). No other modules.
- No console-window flashes during a run: nothing may spawn a subprocess inside the 500 ms poll loop. Launch uses `wscript … Run(…,0,False)` (hidden/async) as today.
- Preserve the existing per-step temp-file naming: `photonforge_<step>.{log,exit}` in the OS temp dir; add `photonforge_<step>.pid`. Remove `photonforge.running`.
- Lua version portability: `os.execute` returns differ between 5.1 (number) and 5.2+ (boolean). Treat success as `res == true or res == 0`.
- This branch (`fix/runner-process-lifecycle`) is based on `main` which already has `cli()` resolution and `read_exit_code`/`get_result_path` (merged via #129). Build on them; do not re-add.

---

## File Structure

- `lua/photonforge/runner.lua` — all lifecycle logic: temp-path helpers, `pid_alive`, launcher, watch loop, `M.kill`, new `M.is_busy`.
- `lua/photonforge/panel.lua` — call `runner.is_busy()` at the two launch entry points (main Run handler and `dispatch_step`).

---

## Task 1: Per-step PID helpers; remove sentinel helpers

**Files:**
- Modify: `lua/photonforge/runner.lua` (helper block, currently `get_sentinel_path`/`get_pid_path`/`read_pid_file`/`is_process_alive` ≈ lines 253–275)

**Interfaces:**
- Produces: `get_pid_path(step) -> string`, `read_pid(step) -> string|nil`, `pid_alive(pid) -> bool`, and module-local `PROC_STEPS` (list of step names that spawn a process). Consumed by Tasks 2–4.
- Removes: `get_sentinel_path`, `is_process_alive`, `read_pid_file` (no longer referenced after this plan).

- [ ] **Step 1: Replace the sentinel/pid helper block**

Delete `get_sentinel_path`, the old shared `get_pid_path`, `read_pid_file`, and `is_process_alive`. Replace with:

```lua
local function get_pid_path(step)
  return get_temp_dir() .. (IS_WINDOWS and "\\" or "/") .. "photonforge_" .. step .. ".pid"
end

local function read_pid(step)
  local fh = io.open(get_pid_path(step), "r")
  if not fh then return nil end
  local data = fh:read("*a")
  fh:close()
  return data and data:match("%d+") or nil
end

-- Steps that launch a background CLI process. Used by the run guard and scoped
-- kill to find a still-running step from ANY run (including a prior Darktable
-- session whose pid file survived).
local PROC_STEPS = {
  "dedup", "score", "name", "ingest",
  "sync-tags", "suggest-training-set", "refresh-review",
  "recalibrate", "rescore", "collect-corrections",
}

-- True iff the given PID is a live process. Called only at run start (guard) and
-- on Stop (kill) -- never inside the poll loop -- so its io.popen/os.execute is
-- infrequent.
local function pid_alive(pid)
  if not pid then return false end
  if IS_WINDOWS then
    local p = io.popen('tasklist /NH /FI "PID eq ' .. pid .. '" 2>NUL', "r")
    if not p then return false end
    local out = p:read("*a") or ""
    p:close()
    -- Alive: the row contains the PID. Not alive: "INFO: No tasks are running...".
    return out:find(pid, 1, true) ~= nil
  else
    local res = os.execute("kill -0 " .. pid .. " 2>/dev/null")
    return res == true or res == 0
  end
end
```

- [ ] **Step 2: Verify no dangling references**

Run:
```bash
grep -n "is_process_alive\|get_sentinel_path\|read_pid_file\|get_pid_path()" lua/photonforge/runner.lua
```
Expected: no matches for `is_process_alive`, `get_sentinel_path`, `read_pid_file`, or the no-arg `get_pid_path()`. (Remaining `get_pid_path(step)` / `read_pid(step)` calls are fine.) Any hit is fixed in Task 2/4.

- [ ] **Step 3: Commit**

```bash
git add lua/photonforge/runner.lua
git commit -m "refactor(runner): per-step PID helpers; drop shared sentinel/is_process_alive"
```

---

## Task 2: PID-capturing launcher; drop the sentinel in run_step

**Files:**
- Modify: `lua/photonforge/runner.lua` `M.run_step` launch section (≈ lines 432–474)

**Interfaces:**
- Consumes: `get_pid_path(step)` (Task 1), existing `get_log_path`, `get_result_path`, `build_cmd`, `shell_quote`.
- Produces: on launch, `photonforge_<step>.pid` holds the launched process-tree PID; `photonforge_<step>.exit` holds the exit code when done. No sentinel is written.

- [ ] **Step 1: Remove the sentinel write and rewrite the launch block**

Replace the current launch section — from the `local sentinel = get_sentinel_path()` line and the `sf`/sentinel write, through the end of the `if IS_WINDOWS then … else … end` launch block — with:

```lua
  local cmd = build_cmd(step)
  local log_path = get_log_path(step)
  local result_path = get_result_path(step)
  local pid_path = get_pid_path(step)
  log_fn(string.format("[%s] Running: %s", os.date("%H:%M:%S"), cmd))

  -- Fresh log; drop any exit code / pid from a previous run of this step.
  local f = io.open(log_path, "w"); if f then f:close() end
  os.remove(result_path)
  os.remove(pid_path)

  if IS_WINDOWS then
    local base     = get_temp_dir() .. "\\photonforge_" .. step
    local bat_path = base .. ".bat"
    local ps_path  = base .. ".launch.ps1"
    local vbs_path = base .. ".vbs"

    local bat = io.open(bat_path, "w")
    if bat then
      bat:write('@echo off\r\n')
      bat:write(cmd .. ' > "' .. log_path .. '" 2>&1\r\n')
      -- Redirect-first form avoids cmd's single-digit-before-`>` handle gotcha
      -- (`echo 1>file` would redirect stdout instead of writing "1").
      bat:write('>"' .. result_path .. '" echo %errorlevel%\r\n')
      bat:close()
    end

    -- Launch the .bat via Start-Process -PassThru so we capture the PID of the
    -- cmd process tree; taskkill /T on it later takes the photo-workflow child.
    local ps = io.open(ps_path, "w")
    if ps then
      ps:write("$ErrorActionPreference='SilentlyContinue'\r\n")
      ps:write("$p = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','"
        .. bat_path .. "' -WindowStyle Hidden -PassThru\r\n")
      ps:write("Set-Content -LiteralPath '" .. pid_path .. "' -Value $p.Id\r\n")
      ps:close()
    end

    -- wscript Run(...,0,False): PowerShell runs hidden and async (no flash).
    local vbs = io.open(vbs_path, "w")
    if vbs then
      vbs:write('CreateObject("Wscript.Shell").Run '
        .. '"powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""'
        .. ps_path .. '""", 0, False\r\n')
      vbs:close()
    end

    local p = io.popen('wscript "' .. vbs_path .. '"', "r")
    if p then p:read("*a") p:close() end
  else
    -- Write the step to a .sh so quoting stays sane, run it in its own process
    -- group (setsid) so kill can take the whole tree; $! is the group leader.
    local sh_path = get_temp_dir() .. "/photonforge_" .. step .. ".sh"
    local sh = io.open(sh_path, "w")
    if sh then
      sh:write("#!/bin/sh\n")
      sh:write(cmd .. " > " .. shell_quote(log_path) .. " 2>&1\n")
      sh:write("echo $? > " .. shell_quote(result_path) .. "\n")
      sh:close()
    end
    os.execute("setsid sh " .. shell_quote(sh_path)
      .. " & echo $! > " .. shell_quote(pid_path))
  end
```

- [ ] **Step 2: Mechanism-simulation (Windows) — prove pid + exit capture**

Write and run this scratch script (adjust the scratch dir path). It reproduces the launcher contract with a 6-second stand-in child:

```powershell
$d = "$env:TEMP\pf_sim"; ni $d -ItemType Directory -Force | Out-Null
$bat="$d\s.bat"; $ps="$d\s.ps1"; $vbs="$d\s.vbs"; $pidf="$d\s.pid"; $exit="$d\s.exit"; $log="$d\s.log"
Remove-Item $pidf,$exit,$log -ErrorAction SilentlyContinue
"@echo off","ping -n 6 127.0.0.1 > `"$log`" 2>&1",">`"$exit`" echo %errorlevel%" | Set-Content $bat -Encoding ascii
"`$p = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','$bat' -WindowStyle Hidden -PassThru","Set-Content -LiteralPath '$pidf' -Value `$p.Id" | Set-Content $ps -Encoding ascii
"CreateObject(""Wscript.Shell"").Run ""powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """"$ps"""""", 0, False" | Set-Content $vbs -Encoding ascii
wscript $vbs; Start-Sleep -Milliseconds 1500
$capturedPid = (Get-Content $pidf).Trim()
"pid=$capturedPid"
"alive_midrun=$([bool](tasklist /NH /FI "PID eq $capturedPid" | Select-String $capturedPid))  (expect True)"
"exit_midrun_absent=$(-not (Test-Path $exit))  (expect True)"
Start-Sleep -Seconds 6
"exit_after=$(Get-Content $exit)  (expect 0)"
"alive_after=$([bool](tasklist /NH /FI "PID eq $capturedPid" | Select-String $capturedPid))  (expect False)"
```
Expected: `alive_midrun=True`, `exit_midrun_absent=True`, `exit_after=0`, `alive_after=False`. This proves: PID captured, process reported alive mid-run, `.exit` appears only at completion.

- [ ] **Step 3: Commit**

```bash
git add lua/photonforge/runner.lua
git commit -m "feat(runner): capture per-step PID at launch; remove shared sentinel"
```

---

## Task 3: Watch loop completes on the exit file

**Files:**
- Modify: `lua/photonforge/runner.lua` `M.run_step` poll loop (the `while not M.abort do` block, empty-data branch ≈ lines 487–510)

**Interfaces:**
- Consumes: `read_exit_code(step)` (existing).
- Produces: the loop now terminates when the per-step `.exit` file appears (or `MAX_IDLE`), never on a shared-file signal.

- [ ] **Step 1: Replace the empty-data branch's break condition**

Find the empty-data branch inside the loop:

```lua
    if new_data == nil or new_data == "" then
      if startup_grace > 0 then
        startup_grace = startup_grace - 1
      elseif not is_process_alive() then
        break
      end

      idle_count = idle_count + 1
      if idle_count > MAX_IDLE then break end
      goto continue
    end
```

Replace it with (drop `is_process_alive`; complete on the exit file):

```lua
    if new_data == nil or new_data == "" then
      -- Completion is signalled by the per-step .exit file, written by the child
      -- right before it ends. It is per-step, so no other run can delete it --
      -- this is what fixes the false "exit nil" abandonment.
      if read_exit_code(step) ~= nil then break end
      if startup_grace > 0 then startup_grace = startup_grace - 1 end
      idle_count = idle_count + 1
      if idle_count > MAX_IDLE then break end
      goto continue
    end
```

- [ ] **Step 2: Verify the abort/exit-code tail is intact**

Read the code immediately after the loop. Confirm it still: (a) returns `false` on `M.abort`; (b) drains remaining log output; (c) `local exit_code = read_exit_code(step); local ok = (exit_code == 0)`; (d) logs a failure line when `not ok`; (e) `return ok`. No change needed there — just confirm the loop edit didn't disturb it.

Run:
```bash
grep -n "is_process_alive\|get_sentinel_path\|\.running" lua/photonforge/runner.lua
```
Expected: **no matches** (the sentinel is fully gone).

- [ ] **Step 3: Commit**

```bash
git add lua/photonforge/runner.lua
git commit -m "fix(runner): complete watch loop on per-step exit file, not shared sentinel"
```

---

## Task 4: Scoped kill + single-active-run guard

**Files:**
- Modify: `lua/photonforge/runner.lua` `M.kill` (≈ lines 277–294); add `M.is_busy`

**Interfaces:**
- Consumes: `PROC_STEPS`, `read_pid`, `pid_alive` (Task 1).
- Produces: `M.kill()` kills only tracked live step PIDs; `M.is_busy() -> bool` for the panel guard (Task 5).

- [ ] **Step 1: Replace M.kill and add M.is_busy**

Replace the whole `function M.kill() … end` with:

```lua
-- Kill only PIDs this plugin launched and that are still alive. No wildcard --
-- a Stop or new run can never touch an unrelated (or prior-run) process.
function M.kill()
  M.abort = true
  for _, step in ipairs(PROC_STEPS) do
    local pid = read_pid(step)
    if pid and pid_alive(pid) then
      if IS_WINDOWS then
        os.execute('taskkill /F /T /PID ' .. pid .. ' >nul 2>&1')
      else
        os.execute("kill -TERM -" .. pid .. " 2>/dev/null")  -- negative = group
      end
    end
  end
end

-- True if any launched step process is still running (from this or a prior
-- Darktable session). Backstop against overlapping runs.
function M.is_busy()
  for _, step in ipairs(PROC_STEPS) do
    if pid_alive(read_pid(step)) then return true end
  end
  return false
end
```

- [ ] **Step 2: Mechanism-simulation — scoped kill only hits the tracked PID**

Scratch check (Windows): start two `ping -n 30` stand-ins, record one PID as "tracked", `taskkill /F /T /PID <tracked>`, confirm the tracked one dies and the other survives, then clean up the survivor.

```powershell
$a = Start-Process cmd -ArgumentList '/c','ping -n 30 127.0.0.1' -WindowStyle Hidden -PassThru
$b = Start-Process cmd -ArgumentList '/c','ping -n 30 127.0.0.1' -WindowStyle Hidden -PassThru
Start-Sleep 1
taskkill /F /T /PID $($a.Id) | Out-Null
Start-Sleep 1
"tracked_dead=$(-not [bool](tasklist /NH /FI "PID eq $($a.Id)" | Select-String "$($a.Id)"))  (expect True)"
"other_alive=$([bool](tasklist /NH /FI "PID eq $($b.Id)" | Select-String "$($b.Id)"))  (expect True)"
taskkill /F /T /PID $($b.Id) | Out-Null   # cleanup
```
Expected: `tracked_dead=True`, `other_alive=True`.

- [ ] **Step 3: Commit**

```bash
git add lua/photonforge/runner.lua
git commit -m "feat(runner): scoped PID kill + is_busy guard; drop wmic/pkill wildcard"
```

---

## Task 5: Wire the single-run guard into the panel

**Files:**
- Modify: `lua/photonforge/panel.lua` — the `run_btn` `clicked_callback` and the `dispatch_step` helper (both launch a run)

**Interfaces:**
- Consumes: `runner.is_busy()` (Task 4), existing `append_log`.

- [ ] **Step 1: Guard the main Run handler**

In `run_btn`'s `clicked_callback`, inside the `pcall`, immediately after `save_entries()` and the existing empty-destination check, add:

```lua
        if runner.is_busy() then
          append_log("[BUSY] A PHOTONForge run is already in progress. "
                  .. "Wait for it to finish, or press Stop.")
          return
        end
```

- [ ] **Step 2: Guard dispatch_step**

Find `dispatch_step` (used by the training/correction action buttons). At its start, after any `save_entries()` it already performs, add the same guard:

```lua
    if runner.is_busy() then
      append_log("[BUSY] A PHOTONForge run is already in progress. "
              .. "Wait for it to finish, or press Stop.")
      return
    end
```
(If `dispatch_step` wraps work in a `pcall`, place the guard as the first statement inside it, consistent with Step 1.)

- [ ] **Step 3: Confirm `runner` is in scope**

Run:
```bash
grep -n 'require "photonforge/runner"\|local runner' lua/photonforge/panel.lua
```
Expected: a `runner` module handle exists at file scope. If not, add `local runner = require "photonforge/runner"` near the other requires.

- [ ] **Step 4: Commit**

```bash
git add lua/photonforge/panel.lua
git commit -m "feat(panel): refuse to launch while a run is already active (is_busy guard)"
```

---

## Task 6: Deploy + small-folder Darktable E2E

**Files:** none (verification only)

- [ ] **Step 1: Make the worktree deployable**

The worktree has no `.venv` (it lives in the main checkout), and `deploy_lua.ps1` derives `cli_path` from its own repo root. Create a junction so the worktree resolves to the real venv:

```powershell
cmd /c mklink /J "F:\Files\50-59-software-and-dev\51-code-and-repos\PHOTONForge\photo-workflow\.worktrees\runner-fix\.venv" "F:\Files\50-59-software-and-dev\51-code-and-repos\PHOTONForge\photo-workflow\.venv"
```

- [ ] **Step 2: Deploy the worktree's Lua via Task Scheduler**

Per the AppData-overlay procedure, run the worktree's `deploy_lua.ps1` through a scheduled task (so it lands on the real disk and sets `cli_path`), then confirm on disk. Close Darktable first.

- [ ] **Step 3: Build a ~10-image throwaway folder**

Copy ~10 RAWs into a temp folder on the cartridge (e.g. `H:\PFTest`), set Destination to it in the panel. This keeps a full dedup→score→name run to ~2 minutes.

- [ ] **Step 4: Run and observe**

Enable dedup + score + name, click Run. Confirm:
- No console-window flashes during the run.
- Score/name run to completion; each step ends with `✓` and the correct item count (no `failed (exit nil)`).
- Clicking Run again mid-run logs `[BUSY]` and does not start a second run.
- Stop cancels the active run and leaves any other process untouched.

Expected: green `✓ dedup / ✓ score / ✓ name` summary, no false failure.

- [ ] **Step 5: Full-run confirmation (optional, user-paced)**

Point Destination back at `H:\ZooPueblo2026` and run the full pipeline (~30–40 min). Confirm it completes without a false failure. This is the acceptance gate for the real shoot.

---

## Self-Review notes

- **Spec coverage:** §1 launcher → Task 2; §2 exit-file watch + PID-for-kill/guard → Tasks 1, 3, 4; §3 scoped kill → Task 4; §4 single-run guard → Tasks 4–5; §5 verification → Tasks 2/4 sims + Task 6 E2E. All covered.
- **No shared sentinel anywhere:** Tasks 1–3 grep-assert `is_process_alive`/`.running` are gone.
- **Type/name consistency:** `get_pid_path(step)`, `read_pid(step)`, `pid_alive(pid)`, `PROC_STEPS`, `M.is_busy` used identically across tasks.
