# ADR-004 — Darktable Lua Plugin as the GUI, Tauri Chain and Tk Manager Retired

**Status:** Accepted (PR #117, 2026-07-08)

## Context

Three GUI surfaces accumulated: a planned/prototyped **Tauri + Svelte**
desktop app (design mockups and a handoff brief), a **Tkinter Cartridge
Manager** (PyInstaller-packaged, with its own file-ops/DB layer), and the
**Darktable Lua plugin** (`lua/photonforge/`). Only the plugin was actually
used: the operator's workflow lives inside Darktable (review, ratings, tags,
corrections), so a separate app duplicated state and drifted — the 2026-07-08
review found the Tk manager's DB layer used an incompatible schema and its
delete path was unsafe.

## Decision

The **Darktable Lua plugin is the single GUI** (panel + runner + applicator +
tag_manager over the `photo-workflow` CLI's JSON-progress protocol, IF-1.1).
PR #117 deleted the Tk Cartridge Manager and the Tauri chain; the Tauri-era
design intent is archived in
[gui-layer-handoff-brief.md](../../Archive/architecture/gui-layer-handoff-brief.md).
Cartridge provision/archive/restore became plugin buttons that launch
elevated terminal commands (guarded until `photo-cartridge` implements them).

## Consequences

- One GUI codebase; plugin deploy is a scripted copy
  (`scripts/deploy_lua.ps1` on Windows; manual copy on Linux — see
  [docs/install-yoga-linux.md](../../../docs/install-yoga-linux.md)).
- No GUI outside Darktable: headless/CLI use remains fully supported
  (`sync-tags` covers the no-plugin path).
- A future standalone culling app (2026-07-08 review "Architecture B") would
  be a new decision, not a revival of the retired code.
