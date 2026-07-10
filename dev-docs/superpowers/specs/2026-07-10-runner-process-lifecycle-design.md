# Runner Process-Lifecycle Fix — Design

**Status:** design
**Owner:** @software_lead
**Date:** 2026-07-10
**Scope:** `lua/photonforge/runner.lua` (+ small touch to `lua/photonforge/panel.lua` for the run guard)

## Problem

Running the pipeline from the Darktable panel reports the `score` step as
`failed (exit nil)` after ~20 images and halts, even though the score CLI
actually runs to completion (verified on disk: `photonforge_score.exit` = `0`,
progress `308/308`). The `name` step separately exits `1` after 5 images with no
Python traceback — i.e. it was killed, not crashed.

### Root cause

The runner tracks whether a step's detached process is still alive with a single
**shared** sentinel file, `photonforge.running`
([runner.lua](../../../lua/photonforge/runner.lua) `is_process_alive`). Any
step's `.bat` — or a straggler process from an earlier run — deleting that file
makes the watch loop believe a *live* step has ended. The loop then breaks while
the process is still running, so `read_exit_code` finds no `.exit` file yet and
returns `nil`; the exit-code check reports `failed (exit nil)` and `run_all`
halts.

Because it looks failed, the operator re-runs. `M.kill()` matches
`%photo-workflow%` (a wildcard over **all** such processes), so each new run
kills the previous run's still-running `score`/`name` — that is `name`'s
`exit 1`. Overlapping runs also interleave writes to the single SQLite DB.

One defect (liveness inferred from a shared file) → false failure → re-run
cascade → cross-run kills.

The exit-code propagation added earlier is correct in intent, but it converts
the pre-existing silent early-abandonment into a hard halt, which is what
surfaces the re-run cascade. The real fix is to make liveness tracking correct.

## Design

### 1. PID-recording launcher (per step)

Each step still runs **detached** — Darktable Lua's `os.execute` is blocking, so
the CLI must run in the background while the loop polls its log. The launcher
records the launched process-tree's **PID** to a per-step
`photonforge_<step>.pid` file. The child continues to write its exit code to
`photonforge_<step>.exit`. The shared `photonforge.running` sentinel is
**removed** from the design entirely.

- **Windows:** launch the step `.bat` via a small `Start-Process -PassThru` so
  the launched process's PID is captured and written to the pidfile, while the
  launch itself returns immediately (async). The `.bat` keeps the
  `photo-workflow … > log 2>&1` redirect and the `.exit` write.
- **Linux:** `( cmd > log 2>&1; echo $? > exit ) & echo $! > pidfile` captures
  the background subshell PID.

### 2. PID-based liveness

`is_process_alive(step)` becomes "is *this PID* still running":
- **Windows:** `tasklist /FI "PID eq <pid>"` reports the image name if alive.
- **Linux:** `kill -0 <pid>` succeeds iff alive.

The watch loop terminates **only** when the PID is gone. At that point the
`.exit` file is guaranteed to have been written, so the success/failure verdict
is always based on a real exit code — never `nil` for a live process. A slow
step (score ≈ 25 min, name ≈ 13 min for this shoot) is followed to completion.

### 3. Scoped kill

`M.kill()` targets the **tracked** PID only:
- **Windows:** `taskkill /F /T /PID <pid>` (the `/T` kills the process tree, so
  the `photo-workflow` child under the launched `cmd` dies with it).
- **Linux:** kill the process (group) for the recorded PID.

The `wmic … call terminate` / `pkill -f 'photo-workflow'` wildcards are
**deleted** — a Stop or a new run can never kill an unrelated or prior-run
process.

### 4. Single-active-run guard

Before launching a run, if a tracked PID is still alive, refuse:
`[BUSY] a run is already in progress` and do not launch. This is the backstop
against overlap even if Lua UI state is lost (e.g. Darktable config reload)
while a detached process persists. It lives at the run entry point in
`panel.lua`'s Run handler (and the standalone-action handlers that dispatch a
step), checking liveness across the known step pidfiles.

### 5. Behavior after the fix

- A long step runs to completion; the panel shows steady progress and a correct
  `✓`/`✗` with the real exit code.
- Stop kills only the current run's process tree.
- Clicking Run (or a training action) while a run is active is refused, not
  layered on top.

## Interfaces / contract

Per-step temp files in the OS temp dir (names unchanged except the new pidfile;
the sentinel is gone):

| File | Writer | Reader | Meaning |
|---|---|---|---|
| `photonforge_<step>.log` | child (`> log 2>&1`) | runner loop | streamed JSON progress + records |
| `photonforge_<step>.pid` | launcher | `is_process_alive`, `M.kill`, run guard | PID of the launched process tree |
| `photonforge_<step>.exit` | child `.bat`/subshell | `read_exit_code` | integer exit code, written before the process ends |

Liveness is derived from the pidfile PID, never from file existence alone
(an absent/stale pidfile ⇒ treat as not alive).

## Testing / verification

This is Lua that only executes inside Darktable, so there is no unit harness.

1. **Mechanism simulation (scratch):** reproduce the launcher → pidfile → exit
   contract with a scratch script in both Windows (`.bat` + `tasklist`/`taskkill`)
   and Linux (`& echo $!` + `kill -0`) form, asserting: a long-running child is
   reported *alive* until it truly exits; the `.exit` value is read correctly
   for success (0) and failure (non-zero); killing the tracked PID stops the
   child and leaves unrelated processes untouched.
2. **Small-folder E2E:** a throwaway folder of ~10 images so a full
   dedup→score→name run completes in ~2 min inside Darktable, confirming the
   run reports correct success/halt and no false failure — before committing to
   a full ~30–40 min run on the real 463-image cartridge.
3. **Deploy** via `deploy_lua.ps1` through Task Scheduler (AppData overlay), and
   confirm on the real disk, per the established procedure.

## Out of scope

- Per-run unique temp filenames (unnecessary once the single-run guard makes
  concurrent runs impossible).
- Any change to scoring/naming logic, the raw+jpg import question, or long-step
  progress UX.
- The stale `color_labels` orphan rows found during diagnosis (harmless DB
  cruft; separate minor-bug-roundup candidate if worth cleaning).
