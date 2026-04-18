---
name: Project Overview
description: PHOTONForge stage history, UN-ID coverage gaps, and key findings from validation runs
type: project
---

PHOTONForge is an offline photo ingest-to-edit pipeline running on a Lenovo Yoga 910 (i7-7500U, 8GB RAM). The GUI layer is a Tauri + Svelte app (`photonforge-gui`) in the repo root.

**Living User Need Document** is at `/home/alex/PHOTONFORGE_Photo-Workflow/docs/living-user-needs.md` on the Yoga 910. As of 2026-04-18 it contains UN-001 through UN-041 (94 lines, no GUI-specific UN-IDs).

**Stage 7.1 (GUI scaffold) gap**: Features delivered -- status bar with SSD/SD indicators, 6-tab nav (Ingest, Library, Darktable, Export, Cartridge, Settings), panel switching, dark theme with CSS custom properties, /proc/mounts polling via Rust mount_monitor -- have NO UN-IDs in the Living User Need Document. @architect must define UN-050+ before Stage 7.x validation can be fully traceable.

**UN-041 status**: PARTIAL. Notification display pathway is scaffolded (StatusBar shows "No SD card" on unmount). Active eject command (`safe_eject.sh` invocation) and explicit completion notification (dialog/toast) are not yet wired in the GUI.

**Toolchain on Yoga 910**: Node 20.20.2 via NVM, cargo 1.95.0, tauri-cli 2.10.1.

**ValidationReports path on Yoga 910**: `/home/alex/PHOTONFORGE_Photo-Workflow/docs/ValidationReports/`

Why: Needed to avoid re-discovering coverage gaps and toolchain details on every run.
How to apply: Check UN-ID coverage before pulling requirements; expect gap at UN-041 for GUI stage runs until @architect defines UN-050+.
