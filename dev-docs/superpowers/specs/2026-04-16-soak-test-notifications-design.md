# Design: soak_cycle.py Physical Action Notifications

**Date:** 2026-04-16
**Status:** Approved
**Author:** Alex Meyer
**Scope:** `scripts/soak_cycle.py` only

---

## Problem

`soak_cycle.py` runs on the Yoga 910 via SSH from the operator's desktop PC through Claude Code. The script's unplug/replug prompts are emitted as stdout via `log()`. Because the operator watches Claude Code on the desktop (not the SSH terminal directly), these prompts are not reliably visible in real time, causing missed cues and stalled soak cycles.

The Yoga 910 sits physically on the desk next to the operator, so its display is accessible.

---

## Solution

Add a `_notify_physical(message, blocking)` helper to `soak_cycle.py` that delivers action prompts to the Yoga 910's own display. All existing `log()` calls are kept — SSH stdout output is unchanged.

---

## Helper: `_notify_physical(message, blocking)`

Tries notification methods in priority order. Each method is wrapped in `try/except`; failures are silently skipped so a missing binary never aborts the soak test.

| Priority | Method | When used | Behaviour |
|----------|--------|-----------|-----------|
| 1 | `DISPLAY=:0 zenity --info` | `blocking=True` | Blocks until operator clicks OK on Yoga 910 display |
| 1 | `DISPLAY=:0 notify-send` | `blocking=False` | Fires desktop toast on Yoga 910 display; returns immediately |
| 2 | `wall` | Either (fallback) | Broadcasts to all open TTYs on the Yoga 910 |

The `DISPLAY=:0` environment variable is set on the subprocess call, not assumed from the SSH environment. `zenity` window title is `"PHOTONForge Soak Test"`.

---

## Call Sites

### Unplug prompt (blocking)

**Location:** `wait_for_replug_and_mount()`, immediately before the UUID-disappear poll loop (currently line 128).

```
_notify_physical(f"Cycle {cycle} — Unplug the SSD now, then click OK", blocking=True)
log(f"Unplug the SSD now — waiting for UUID {PHOTON_SSD_UUID} to disappear...")
```

Rationale: the operator confirms readiness before polling begins. Prevents a race where the UUID disappears before the operator is ready to replug.

### Replug prompt (non-blocking)

**Location:** `wait_for_replug_and_mount()`, immediately before the UUID-reappear poll loop (currently line 141).

```
_notify_physical(f"Cycle {cycle} — Plug the SSD back in", blocking=False)
log(f"Plug the SSD back in — waiting for UUID {PHOTON_SSD_UUID} to reappear...")
```

Rationale: polling must start immediately after the prompt so the UUID reappearance is not missed. A non-blocking toast is sufficient — the operator sees it and plugs in.

### Cycle number

`wait_for_replug_and_mount()` receives a new `cycle: int` parameter passed from `main()`.

---

## Dependencies

| Tool | Package | Already required? |
|------|---------|-------------------|
| `zenity` | `zenity` | Yes — NFR-2.4 mandates zenity for hardware prompts |
| `notify-send` | `libnotify-bin` | Ships with Ubuntu 24.04 default install |
| `wall` | `util-linux` | Core Unix utility, always present |

No new packages need to be installed.

---

## Error Handling

- All `subprocess.run()` calls in `_notify_physical` use `check=False` and are wrapped in `try/except Exception`.
- If every method fails (e.g. no display, no zenity, no wall), the function returns silently. The existing `log()` stdout message is the last-resort notification.
- A failed notification never raises, never sets a FAIL result on the cycle.

---

## Testing

- Unit test in `tests/test_cartridge.py` or a new `tests/test_soak_cycle.py`:
  - Patch `subprocess.run` to assert `_notify_physical` calls zenity with `blocking=True` for unplug and notify-send for replug.
  - Assert silent fallback when subprocess raises `FileNotFoundError`.
- No hardware required for unit tests.

---

## Out of Scope

- Validation pass (UN-XXX status updates) — separate workstream.
- Automating the full 50-cycle run in a single invocation — the prompt-and-wait pattern is intentional per CLAUDE.md.
- Any changes to `remote_test.sh`, `safe_eject.sh`, or other scripts.
