# Dev Machine Setup (Windows) — post-OS-rebuild checklist

Written 2026-07-09 after the dev machine OS rebuild. Repo location assumed:
`F:\Files\50-59-software-and-dev\51-code-and-repos\PHOTONForge\photo-workflow`
Darktable install: `F:\Files\50-59-software-and-dev\54-creative\Darktable`

Run everything from a PowerShell prompt in the repo root unless noted.

## 1. Python environment

```powershell
# Python 3.11+ required (py -0 to list installed versions)
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,docs]"
python -m pytest -m "not slow"     # expect: all green
```

## 2. Models (one-time download; runtime stays offline per NFR-2.1)

```powershell
# Florence-2 naming model -> models/florence2_int8/
# provision_models.sh is bash; on Windows run it from Git Bash or WSL:
bash scripts/provision_models.sh

# Scoring models (CLIP / YOLO / YuNet / RMBG / aesthetic head):
python scripts/provision_scoring_models.py
```

## 3. Darktable Lua plugin

**Updating an existing install** — one command, from the repo or anywhere:

```powershell
# Close Darktable first. Refreshes the venv package, deploys the plugin,
# then VERIFIES the result and exits non-zero if anything is off.
.\scripts\update_install.ps1

# Did it actually take effect? (changes nothing)
.\scripts\update_install.ps1 -VerifyOnly

# Portable install with its own config dir:
.\scripts\update_install.ps1 -DarktableDir "<darktable config dir>"
```

It deploys **whatever is checked out** and never runs git, so it cannot move
your working tree. Useful switches: `-SkipPip` (plugin only — the install is
editable, so new modules and CLI subcommands are normally picked up without
reinstalling), `-Force` (proceed with Darktable running; see the warning
below about `darktablerc`).

The verification is the point: it hashes every deployed `.lua` against the
repo and flags **STALE** copies, runs `photo-cartridge --help` and checks each
subcommand the panel can press actually exists, and confirms `luarc` and
`cli_path`. A silently-stale plugin is the failure this catches.

**Plugin only** (what `update_install.ps1` calls internally):

```powershell
# Copies lua/photonforge/*.lua into the Darktable config dir and adds the
# require line to luarc. Re-run after every .lua change.
.\scripts\deploy_lua.ps1
# Non-default config dir (portable installs):
#   .\scripts\deploy_lua.ps1 -DarktableDir "<darktable config dir>"
```

Note: the plugin lives in Darktable's **config** directory
(`%LOCALAPPDATA%\darktable` by default), not the install directory. A
portable install at `F:\...\54-creative\Darktable` keeps its config where
its launcher's `--configdir` points — pass that to `-DarktableDir`.

> **⚠ Deploy this yourself, not through an AI agent** — this applies to
> `update_install.ps1` exactly as it does to `deploy_lua.ps1`. Claude Code's tools
> on this machine run behind a **copy-on-write filesystem overlay** for
> `%LOCALAPPDATA%` (and other user-profile paths). When an agent runs
> `deploy_lua.ps1`, the files land in the overlay at the *same path string*
> `C:\Users\Alexa\AppData\Local\darktable` but a **different backing store**
> than your real Darktable reads — so the agent sees the plugin load in its
> own test launches while your Start-Menu launch shows nothing. `dangerously`
> disabling the sandbox does **not** escape it for AppData paths.
>
> Symptom: PHOTONForge is missing from the lighttable left panel even though
> every check "passes". Confirm the *real* state from your own session with a
> scheduled-task probe (Task Scheduler runs under your interactive token,
> outside the overlay):
>
> ```powershell
> schtasks /Create /TN pf_probe /SC ONCE /ST 23:59 /F /TR "cmd /c (type %LOCALAPPDATA%\darktable\luarc & dir %LOCALAPPDATA%\darktable\lua\photonforge) > %USERPROFILE%\pf_realview.txt 2>&1"
> schtasks /Run /TN pf_probe; Start-Sleep 3; type %USERPROFILE%\pf_realview.txt
> schtasks /Delete /TN pf_probe /F
> ```
>
> Fix: run `deploy_lua.ps1` in a **normal PowerShell window** (or, if an agent
> must do it, via a scheduled task). Diagnosed 2026-07-10 — the tell-tale in
> Darktable's log was `g_rename() ... Improper link` (EXDEV cross-device
> rename), a signature of AppData virtualization.

**CLI path:** Darktable launches as a GUI, so its subprocess `PATH` does not
include `.venv\Scripts` — the plugin's `photo-workflow` calls would fail with
"not recognized". `deploy_lua.ps1` therefore writes the resolved
`.venv\Scripts\photo-workflow.exe` into the `lua/photonforge/cli_path`
preference (in `darktablerc`). **Close Darktable before deploying**, or it
overwrites `darktablerc` on exit and drops the setting. To point at a
different interpreter, set *photo-workflow CLI path* under Darktable →
Preferences → Lua options. Leave it blank on Linux/container installs where
`photo-workflow` is on `PATH`.

## 4. MCP server (`.mcp.json`)

The recovered `.mcp.json` registers a `darktable` MCP server run as
`python -m darktable_mcp` from the repo venv. That module lived only in the
pre-rebuild venv and is **not** in this repo — reinstall it into `.venv`
(or remove the entry if it is no longer used). The command path in
`.mcp.json` now points at the new F: repo location.

## 5. Cartridge / SSD tooling (Linux target only)

udisks2 polling, cartridge detection/provisioning, and the eject scripts
target the Yoga 910 Linux host — nothing to set up on the Windows dev
machine. Remote test entry point: `scripts/remote_test.sh` over SSH (see
CLAUDE.md §Remote Execution; re-add your SSH key to the Yoga after the
rebuild if needed).

**Exception — the backup subcommands run on Windows too.** `photo-cartridge
snapshot`, `backup`, `verify-backup` and `restore-backup` are pure Python with
no udisks2/lsblk dependency, and the panel's Snapshot/Backup/Verify buttons
invoke them here. They work against any mounted cartridge (`E:\`, or a
portable drive) with a backup destination on a second drive. The Linux-only
pieces are `detect_cartridges` (lsblk) and provisioning. See the
[backup runbook](backup-and-restore-guide.md).

## 6. Sanity checklist

- [ ] `python -m pytest -m "not slow"` green
- [ ] `.\scripts\update_install.ps1 -VerifyOnly` reports "Install is up to date"
- [ ] `photo-workflow --help` prints the staged commands
- [ ] `models/florence2_int8/*.onnx` present (4 files)
- [ ] Darktable shows the PHOTONForge panel (lighttable view)
- [ ] `git remote -v` points at GitHub and `git pull` works
