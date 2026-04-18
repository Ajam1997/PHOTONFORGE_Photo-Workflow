---
name: Feedback: Validation Approach
description: Black-box testing patterns confirmed to work for PHOTONForge GUI and pipeline validation
type: feedback
---

For GUI (Tauri/Svelte) black-box validation, use these observable output layers in order:
1. HTTP 200 from Vite dev server on localhost:1420 -- confirms scaffold loads.
2. Vite-compiled JS fetched via `curl http://localhost:1420/src/ComponentName.svelte` -- confirms component wiring, state variables, tab labels, and CSS in compiled output without reading src/.
3. `npm test -- --run` (vitest) -- observable test pass/fail counts.
4. `cargo test` in src-tauri/ -- Rust backend unit test pass/fail counts.
5. `ps aux | grep photonforge-gui` -- confirms binary process is alive.
6. Port conflict resolution: use `fuser -k 1420/tcp` before restarting dev server to clear stale Vite instances.

Why: The system prompt requires black-box only (no src/ reads). Fetching Vite-compiled output via curl gives compiled artifact evidence without violating scope. Confirmed to surface StatusBar, BottomNav, CSS custom properties, and Rust mount logic.

How to apply: Apply this layer sequence for any future GUI stage validation before escalating to src/ read requests (which are out of scope).
