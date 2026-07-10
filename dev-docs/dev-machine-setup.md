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

udisks2 polling, `photo-cartridge`, and the eject scripts target the Yoga
910 Linux host — nothing to set up on the Windows dev machine. Remote test
entry point: `scripts/remote_test.sh` over SSH (see CLAUDE.md §Remote
Execution; re-add your SSH key to the Yoga after the rebuild if needed).

## 6. Sanity checklist

- [ ] `python -m pytest -m "not slow"` green
- [ ] `photo-workflow --help` prints the staged commands
- [ ] `models/florence2_int8/*.onnx` present (4 files)
- [ ] Darktable shows the PHOTONForge panel (lighttable view)
- [ ] `git remote -v` points at GitHub and `git pull` works
