# IF-1.1 — Darktable Lua Plugin ↔ CLI Orchestrator

**Side A:** Darktable Lua Plugin (`lua/photonforge/*`)
**Side B:** `photo-workflow` CLI Orchestrator (`src/photo_workflow/pipeline.py`)
**Status:** living
**Owner:** @software_lead

> The one genuinely cross-language boundary in the system: Lua (inside
> Darktable) drives Python (the pipeline) over subprocess IPC. Four
> sub-contracts must stay in agreement.

## What crosses

1. **Command invocation** — Lua spawns the CLI as a subprocess.
2. **Progress stream** — Python emits machine-readable progress on stdout.
3. **Stop signal** — Lua tracks each launched step's own process PID and sends a scoped kill (no shared sentinel).
4. **Result store** — Python writes results; Lua reads them back.

## Contract

### 1. Command invocation (A → B)

Lua invokes the installed `photo-workflow` console script:

```
photo-workflow <stage> [--json-progress] [stage-specific flags]
```

Stages the plugin may invoke: `ingest`, `scan`, `dedup`, `score`,
`name`, `sync-tags`, `suggest-training-set`, `refresh-review`,
rescore (`score --only-files --skip-genre`), `training recalibrate`,
`training collect-corrections`. The command name and stage names are
the contract — renaming a CLI stage breaks the plugin.

### 2. Progress stream (B → A)

When `--json-progress` is set, Python emits **one JSON object per
line** on stdout (`pipeline.emit()`):

```json
{"stage": "score", "item": "DSC_0042.NEF", "status": "ok", "done": 12, "total": 50}
```

Required keys: `stage`, `item`, `status` (`ok` | `error` | `skip`).
Optional: `done`, `total`, `dest`, plus stage-specific extras. The
Lua `json` parser consumes these for the progress bar. Adding keys is
backward-compatible; renaming/removing `stage`/`item`/`status` is not.

### 3. Stop signal (A → B)

Lua launches each step **detached** and captures the process-tree PID
itself — no PID sentinel from Python is read. On Windows,
`Start-Process -FilePath 'cmd.exe' ... -PassThru` returns the launched
process's PID, written to `photonforge_<step>.pid`; on Linux, the step
runs under `setsid sh <script>.sh`, and `$!` (the group leader's PID,
since `setsid` starts a new session/process group) is written to the
same per-step pidfile. Liveness is checked by PID (`tasklist /FI "PID
eq <pid>" /FI "IMAGENAME eq cmd.exe"` on Windows — filtered to the
tracked `cmd.exe` image so a reused PID belonging to some other
process isn't mistaken for ours; `kill -0` on Linux). To stop, Lua
iterates its tracked steps and sends a **scoped kill** to only the
live, tracked PIDs — never a wildcard: `taskkill /F /T /PID <pid>` on
Windows, `kill -TERM -<pgid>` on Linux (negative PID targets the whole
process group; the PID equals the group ID because the step was
started under `setsid`). The pidfile is removed once the step
completes (or is force-cleared at the start of its next run). Contract:
the per-step pidfile path/format (`photonforge_<step>.pid`, PID as
plain text) and the process-group semantics (`setsid` on Linux,
`cmd.exe` as the tracked Windows image name).

### 4. Result store (B → A)

Python writes results to two stores the plugin reads:
- **XMP sidecars** next to each image (scores + `photon|subject|*` /
  `photon|type|*` hierarchical tags) — see IF-3.2.
- **Darktable `library.db`** rows via the sync-tags stage.

The Lua `applicator.lua` + `tag_manager.lua` apply these into Darktable's tag
UI. The XMP namespace + tag hierarchy is the contract (detailed in
IF-3.2).

## Verified By (Side A — Lua)

- (none yet) — manual: plugin run from Darktable drives a full pipeline; progress bar advances; Stop halts mid-stage

## Verified By (Side B — Python)

- pytest: tests/test_pid_sentinel.py
- pytest: tests/test_cli_v2.py

## Validated By

- (none yet) — e2e: Stage 3 milestone — plugin-driven end-to-end run on the Yoga 910

## Notes

- This is the highest-risk interface in the system: a silent schema
  drift between the Python `emit()` keys and the Lua `json` consumer
  produces a frozen progress bar with no error (historically Issues
  #20, #21 — sentinel/progress bugs).
- The stop path is OS-specific by necessity; keep the Windows and
  Linux branches (`pid_alive`, `M.kill`) in sync.
