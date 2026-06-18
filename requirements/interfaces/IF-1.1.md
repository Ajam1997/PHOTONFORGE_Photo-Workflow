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
3. **Stop signal** — Lua terminates a running pipeline via a PID sentinel.
4. **Result store** — Python writes results; Lua reads them back.

## Contract

### 1. Command invocation (A → B)

Lua invokes the installed `photo-workflow` console script:

```
photo-workflow <stage> [--json-progress] [stage-specific flags]
```

Stages the plugin may invoke: `ingest`, `scan`, `dedup`, `score`,
`name`, `sync-tags`, `training collect-corrections`. The command name
and stage names are the contract — renaming a CLI stage breaks the
plugin.

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

Python writes a **PID sentinel file** at run start (location from
`_get_temp_dir()`). To stop, Lua reads the PID and terminates the
process tree (`taskkill /F /T` on Windows, `kill -9` / `pkill -f
'photo-workflow'` on POSIX), then removes the sentinel. Contract: the
sentinel path + format (PID as text) and the `photo-workflow`
command-line signature that `pkill -f` matches.

### 4. Result store (B → A)

Python writes results to two stores the plugin reads:
- **XMP sidecars** next to each image (scores + `photon|subject|*` /
  `photon|type|*` hierarchical tags) — see IF-3.2.
- **Darktable `library.db`** rows via the sync-tags stage.

The Lua `applicator.lua` + `tags.lua` apply these into Darktable's tag
UI. The XMP namespace + tag hierarchy is the contract (detailed in
IF-3.2).

## Verified By (Side A — Lua)

- (none yet) — manual: plugin run from Darktable drives a full pipeline; progress bar advances; Stop halts mid-stage

## Verified By (Side B — Python)

- pytest: tests/test_pid_sentinel.py
- pytest: tests/test_progress.py

## Validated By

- (none yet) — e2e: Stage 3 milestone — plugin-driven end-to-end run on the Yoga 910

## Notes

- This is the highest-risk interface in the system: a silent schema
  drift between the Python `emit()` keys and the Lua `json` consumer
  produces a frozen progress bar with no error (historically Issues
  #20, #21 — sentinel/progress bugs).
- The stop path is OS-specific by necessity; keep the three platform
  branches in sync.
