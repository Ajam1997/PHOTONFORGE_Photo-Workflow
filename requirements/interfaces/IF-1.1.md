# IF-1.1 — Darktable Lua Plugin ↔ CLI Orchestrator

**Side A:** Darktable Lua Plugin (`lua/photonforge/*`)
**Side B:** `photo-workflow` CLI Orchestrator (`src/photo_workflow/pipeline.py`)
**Status:** living
**Owner:** @software_lead

> The one genuinely cross-language boundary in the system: Lua (inside
> Darktable) drives Python (the pipeline) over subprocess IPC. Five
> sub-contracts must stay in agreement.

## What crosses

1. **Command invocation** — Lua spawns the CLI as a subprocess.
2. **Progress stream** — Python emits machine-readable progress on stdout.
3. **Stop signal** — Lua tracks each launched step's own process PID and sends a scoped kill (no shared sentinel).
4. **Cartridge commands** — Lua launches the separate `photo-cartridge` script into a terminal.
5. **Result store** — Python writes results; Lua reads them back.

## Contract

### 1. Command invocation (A → B)

Lua invokes the installed `photo-workflow` console script:

```
photo-workflow <stage> [--json-progress] [stage-specific flags]
```

**How the program is located** (both console scripts): an explicitly
configured path wins (`cli_path` / `cartridge_path`), then `photo-cartridge`
may be derived as a sibling of `cli_path`, then `<drive>/runtime/{win,linux}/`
when running from a portable cartridge, then the bare name on `PATH`. A
GUI-launched Darktable's subprocess `PATH` excludes a project venv, so the bare
name fails there — resolution is not cosmetic. The portable root is recomputed
from `dt.configuration.config_dir` on every call rather than stored, because
Darktable rewrites `darktablerc` on exit and the drive letter changes between
machines. A configured path is used only if it opens as a file.

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

### 4. Cartridge commands (A → B, `photo-cartridge`)

The CARTRIDGE strip launches the **separate** `photo-cartridge` console
script fire-and-forget into a visible terminal. It is outside the
progress/stop contract above: no `--json-progress`, no pidfile, no
liveness tracking — the user watches the terminal.

Subcommands the plugin may invoke, and the flags it passes verbatim:

| Button | Command | Gate |
|---|---|---|
| Snapshot | `photo-cartridge snapshot <root> --keep N` | implemented |
| Backup | `photo-cartridge backup <root> --dest <dir> --keep N` | implemented |
| Verify | `photo-cartridge verify-backup --dest <dir> [--root <root>]` | implemented |
| Provision | `photo-cartridge provision <root> [--id NNN]` | **not implemented** |
| Archive | `photo-cartridge archive <root> -r <repo> …` | **not implemented** (restic tier) |
| Restore | `photo-cartridge restore -r <repo> --to <root>` | **not implemented** (restic tier) |

**The contract is the subcommand names and flag spellings.** Lua builds
these strings by hand, so a renamed flag surfaces as `No such option` in
a terminal window the user cannot scroll back — not as a test failure.
Two things keep them honest:

- `runner.lua`'s `CARTRIDGE_IMPLEMENTED` table gates **per command**, so
  a tier can ship without exposing buttons for one that has not. A gated
  button logs and refuses instead of shelling out.
- `tests/lua/test_runner_cartridge.lua` loads `runner.lua` against a
  stubbed `darktable`, captures what it would execute, and asserts the
  command strings — including that gated commands execute nothing.

Adding a subcommand means: implement it, flip its `CARTRIDGE_IMPLEMENTED`
entry, add its row here, and assert its string in the Lua test.

### 5. Result store (B → A)

Python writes results to two stores the plugin reads:
- **XMP sidecars** next to each image (scores + `photon|subject|*` /
  `photon|type|*` hierarchical tags) — see IF-3.2.
- **Darktable `library.db`** rows via the sync-tags stage.

The Lua `applicator.lua` + `tag_manager.lua` apply these into Darktable's tag
UI. The XMP namespace + tag hierarchy is the contract (detailed in
IF-3.2).

## Verified By (Side A — Lua)

- lua: tests/lua/test_runner_cartridge.lua (sub-contract 4 — cartridge command strings + per-command gating)
- manual: plugin run from Darktable drives a full pipeline; progress bar advances; Stop halts mid-stage

## Verified By (Side B — Python)

- pytest: tests/test_cli_v2.py, tests/test_cartridge_cli.py

## Validated By

- (none yet) — e2e: Stage 3 milestone — plugin-driven end-to-end run on the Yoga 910

## Notes

- This is the highest-risk interface in the system: a silent schema
  drift between the Python `emit()` keys and the Lua `json` consumer
  produces a frozen progress bar with no error (historically Issues
  #20, #21 — sentinel/progress bugs).
- The stop path is OS-specific by necessity; keep the Windows and
  Linux branches (`pid_alive`, `M.kill`) in sync.
