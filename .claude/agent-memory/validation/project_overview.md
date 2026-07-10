---
name: Project Overview
description: PHOTONForge stage history, UN-ID coverage gaps, and key findings from validation runs
type: project
---

PHOTONForge is an offline photo ingest-to-edit pipeline running on a Lenovo Yoga 910 (i7-7500U, 8GB RAM). The operator UI is a **Darktable Lua plugin** (`lua/photonforge/`) that renders a PHOTONForge panel in the lighttable left sidebar; `runner.lua` invokes the `photo-workflow` CLI as a subprocess (IF-1.1). The earlier Tauri + Svelte GUI (`photonforge-gui`) is fully retired and no longer exists in the repo.

**Living User Need Document** is at `/home/alex/PHOTONFORGE_Photo-Workflow/dev-docs/living-user-needs.md` on the Yoga 910 (auto-generated; UN-001 through UN-054).

**UN-041 status**: PARTIAL. Notification pathway exists via zenity/desktop notification after transfer; verify active eject (`safe_eject.sh`) and the completion notification end-to-end on hardware.

**Toolchain on Yoga 910**: Python 3.11 venv + Darktable with the Lua plugin installed (one `luarc` line: `require "photonforge/main"`). No Node/cargo/tauri toolchain is needed anymore.

Why: Needed to avoid re-discovering coverage gaps and toolchain details on every run.
How to apply: Check UN-ID coverage before pulling requirements; validate UI behavior through the Darktable Lua panel (black-box: panel buttons → CLI subprocess → XMP/library.db outputs), not through any web/Tauri layer.
