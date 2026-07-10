---
name: Feedback: Validation Approach
description: Black-box testing patterns confirmed to work for PHOTONForge pipeline and Darktable Lua plugin validation
type: feedback
---

The GUI is the Darktable Lua plugin (`lua/photonforge/`) — validate it black-box through its observable outputs, in order:

1. `photo-workflow <stage> --json-progress` run directly — one JSON object per line on stdout confirms the CLI side of IF-1.1 (stage names, `stage`/`item`/`status` keys).
2. XMP sidecars next to each image — `IMG_0001.ARW` → `IMG_0001.ARW.xmp`, containing `photon:*` fields (`SemanticName`, scores) and `photon|subject|*` / `photon|type|*` tags.
3. Darktable `library.db` — ratings, tags, and description rows written by sync-tags (sqlite3 queries; never write to it).
4. `pytest -m "not slow"` — observable pass/fail counts for the Python side.
5. Panel behavior on the Yoga 910 — plugin loads via `luarc`, buttons launch subprocesses, progress bar advances, Stop kills via PID sentinel (requires Darktable session; prompt-and-wait).

Why: The system prompt requires black-box only (no src/ reads). CLI stdout, sidecar files, and library.db rows are compiled-artifact evidence without violating scope. The old Vite/cargo layer sequence is obsolete — the Tauri GUI was retired.

How to apply: Apply this layer sequence for plugin/pipeline validation before escalating to src/ read requests (which are out of scope).
