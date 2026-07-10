# Soak Test Physical Action Notifications — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Yoga 910 display notifications to `soak_cycle.py` so the operator sees zenity/notify-send popups when physical plug/unplug actions are needed during KPM-1.4 soak testing.

**Architecture:** Add `_notify_physical(message, blocking)` helper that tries zenity (blocking) or notify-send (non-blocking) with `DISPLAY=:0`, falling back to `wall`. Add `cycle` parameter to `wait_for_replug_and_mount()` and insert two notify calls inside it.

**Tech Stack:** Python 3.11, subprocess, unittest.mock, pytest, zenity, notify-send, wall

---

## File Map

| File | Action | What changes |
|------|--------|-------------|
| `scripts/soak_cycle.py` | Modify | Add `_notify_physical()`, add `cycle` param to `wait_for_replug_and_mount()`, two new notify call sites |
| `tests/test_soak_cycle.py` | Create | Unit tests for `_notify_physical` (3 scenarios) + call-site tests for `wait_for_replug_and_mount` |

---

### Task 1: Create test file with failing tests for `_notify_physical`

**Files:**
- Create: `tests/test_soak_cycle.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_soak_cycle.py` with this exact content:

```python
"""Unit tests for soak_cycle._notify_physical and wait_for_replug_and_mount."""
import sys
from pathlib import Path
from unittest.mock import patch, call, MagicMock

import pytest

# soak_cycle.py lives in scripts/, not a package — import via sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import soak_cycle


# ---------------------------------------------------------------------------
# _notify_physical — blocking=True (zenity path)
# ---------------------------------------------------------------------------

def test_notify_physical_blocking_calls_zenity():
    """blocking=True must call zenity with DISPLAY=:0."""
    with patch("soak_cycle.subprocess.run") as mock_run:
        soak_cycle._notify_physical("Unplug the SSD now", blocking=True)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "zenity"
        assert "--info" in cmd
        assert any("PHOTONForge Soak Test" in arg for arg in cmd)
        env = mock_run.call_args[1]["env"]
        assert env["DISPLAY"] == ":0"


def test_notify_physical_blocking_does_not_call_wall_on_success():
    """If zenity succeeds, wall must NOT be called."""
    with patch("soak_cycle.subprocess.run") as mock_run:
        soak_cycle._notify_physical("msg", blocking=True)
        for c in mock_run.call_args_list:
            assert c[0][0][0] != "wall"


# ---------------------------------------------------------------------------
# _notify_physical — blocking=False (notify-send path)
# ---------------------------------------------------------------------------

def test_notify_physical_nonblocking_calls_notify_send():
    """blocking=False must call notify-send with DISPLAY=:0."""
    with patch("soak_cycle.subprocess.run") as mock_run:
        soak_cycle._notify_physical("Plug the SSD back in", blocking=False)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "notify-send"
        assert cmd[1] == "PHOTONForge"
        assert "Plug the SSD back in" in cmd
        env = mock_run.call_args[1]["env"]
        assert env["DISPLAY"] == ":0"


def test_notify_physical_nonblocking_does_not_call_wall_on_success():
    """If notify-send succeeds, wall must NOT be called."""
    with patch("soak_cycle.subprocess.run") as mock_run:
        soak_cycle._notify_physical("msg", blocking=False)
        for c in mock_run.call_args_list:
            assert c[0][0][0] != "wall"


# ---------------------------------------------------------------------------
# _notify_physical — wall fallback
# ---------------------------------------------------------------------------

def test_notify_physical_falls_back_to_wall_when_primary_missing():
    """FileNotFoundError on primary binary must trigger wall fallback."""
    def raise_fnf_for_primary(cmd, **kwargs):
        if cmd[0] in ("zenity", "notify-send"):
            raise FileNotFoundError(f"{cmd[0]} not found")

    with patch("soak_cycle.subprocess.run", side_effect=raise_fnf_for_primary) as mock_run:
        soak_cycle._notify_physical("test message", blocking=True)
        wall_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "wall"]
        assert len(wall_calls) == 1
        assert "test message" in wall_calls[0][0][0]


def test_notify_physical_silent_when_all_methods_fail():
    """If every subprocess call raises, _notify_physical must not propagate the exception."""
    with patch("soak_cycle.subprocess.run", side_effect=FileNotFoundError):
        soak_cycle._notify_physical("test", blocking=True)   # must not raise
        soak_cycle._notify_physical("test", blocking=False)  # must not raise
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd E:/PHOTONForge/photo-workflow
pytest tests/test_soak_cycle.py -v
```

Expected: `AttributeError: module 'soak_cycle' has no attribute '_notify_physical'` (or similar) for all tests — confirms the tests are wired correctly and the implementation is missing.

---

### Task 2: Implement `_notify_physical` in `soak_cycle.py`

**Files:**
- Modify: `scripts/soak_cycle.py` — add helper after the existing `shutil_which` function (around line 91)

- [ ] **Step 1: Insert `_notify_physical` after `shutil_which`**

Open `scripts/soak_cycle.py`. After the `shutil_which` function (ends around line 91), insert:

```python
def _notify_physical(message: str, blocking: bool) -> None:
    """Send an action prompt to the Yoga 910 display.

    blocking=True  → zenity dialog (operator must click OK before polling starts)
    blocking=False → notify-send toast (script polls immediately)
    Falls back to wall broadcast if the primary binary is missing.
    """
    env = {**os.environ, "DISPLAY": ":0"}
    primary_ok = False

    if blocking:
        try:
            subprocess.run(
                [
                    "zenity", "--info",
                    "--title=PHOTONForge Soak Test",
                    f"--text={message}",
                ],
                env=env,
                check=False,
                timeout=300,
            )
            primary_ok = True
        except Exception:
            pass
    else:
        try:
            subprocess.run(
                ["notify-send", "PHOTONForge", message],
                env=env,
                check=False,
                timeout=10,
            )
            primary_ok = True
        except Exception:
            pass

    if not primary_ok:
        try:
            subprocess.run(["wall", message], check=False, timeout=10)
        except Exception:
            pass
```

- [ ] **Step 2: Run Task 1 tests to confirm they all pass**

```
pytest tests/test_soak_cycle.py -v -k "notify_physical"
```

Expected: 6 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add scripts/soak_cycle.py tests/test_soak_cycle.py
git commit -m "feat: add _notify_physical helper to soak_cycle.py"
```

---

### Task 3: Write failing call-site tests for `wait_for_replug_and_mount`

**Files:**
- Modify: `tests/test_soak_cycle.py` — append new tests at the bottom

- [ ] **Step 1: Append call-site tests to `tests/test_soak_cycle.py`**

```python
# ---------------------------------------------------------------------------
# wait_for_replug_and_mount — _notify_physical call sites
# ---------------------------------------------------------------------------

def test_wait_for_replug_calls_blocking_notify_for_unplug():
    """First _notify_physical call must be blocking=True and include cycle number."""
    # UUID sequence: None (disappear detected) → "/dev/sda1" (replug) → "/dev/sda1" (settle re-resolve)
    uuid_seq = iter([None, "/dev/sda1", "/dev/sda1"])

    with patch.object(soak_cycle, "_notify_physical") as mock_notify, \
         patch.object(soak_cycle, "_uuid_device", side_effect=lambda: next(uuid_seq)), \
         patch.object(soak_cycle, "is_mounted", return_value=True), \
         patch("soak_cycle.time.sleep"):
        soak_cycle.wait_for_replug_and_mount(Path("/mnt/test"), timeout=10, cycle=7)

    assert mock_notify.call_count >= 2
    first_call_kwargs = mock_notify.call_args_list[0]
    # Accept positional or keyword arg for blocking
    blocking_val = (
        first_call_kwargs[1].get("blocking")
        if first_call_kwargs[1]
        else first_call_kwargs[0][1]
    )
    assert blocking_val is True
    message = first_call_kwargs[0][0]
    assert "7" in message  # cycle number present


def test_wait_for_replug_calls_nonblocking_notify_for_replug():
    """Second _notify_physical call must be blocking=False."""
    uuid_seq = iter([None, "/dev/sda1", "/dev/sda1"])

    with patch.object(soak_cycle, "_notify_physical") as mock_notify, \
         patch.object(soak_cycle, "_uuid_device", side_effect=lambda: next(uuid_seq)), \
         patch.object(soak_cycle, "is_mounted", return_value=True), \
         patch("soak_cycle.time.sleep"):
        soak_cycle.wait_for_replug_and_mount(Path("/mnt/test"), timeout=10, cycle=7)

    second_call_kwargs = mock_notify.call_args_list[1]
    blocking_val = (
        second_call_kwargs[1].get("blocking")
        if second_call_kwargs[1]
        else second_call_kwargs[0][1]
    )
    assert blocking_val is False
```

- [ ] **Step 2: Run new tests to confirm they fail**

```
pytest tests/test_soak_cycle.py -v -k "wait_for_replug"
```

Expected: `TypeError: wait_for_replug_and_mount() got an unexpected keyword argument 'cycle'` — confirms the signature change is needed.

---

### Task 4: Wire `_notify_physical` into `wait_for_replug_and_mount`

**Files:**
- Modify: `scripts/soak_cycle.py` — update `wait_for_replug_and_mount` signature and body, update call in `main()`

- [ ] **Step 1: Update `wait_for_replug_and_mount` signature**

Change the existing function signature from:
```python
def wait_for_replug_and_mount(mount_point: Path, timeout: int) -> bool:
```
to:
```python
def wait_for_replug_and_mount(mount_point: Path, timeout: int, cycle: int = 0) -> bool:
```

- [ ] **Step 2: Add blocking notify call before the UUID-disappear poll**

Inside `wait_for_replug_and_mount`, find:
```python
    # Step 1: wait for UUID link to disappear (confirms physical unplug)
    log(f"Unplug the SSD now — waiting for UUID {PHOTON_SSD_UUID} to disappear...")
```

Insert `_notify_physical` immediately before the `log()` call:
```python
    # Step 1: wait for UUID link to disappear (confirms physical unplug)
    _notify_physical(f"Cycle {cycle} — Unplug the SSD now, then click OK", blocking=True)
    log(f"Unplug the SSD now — waiting for UUID {PHOTON_SSD_UUID} to disappear...")
```

- [ ] **Step 3: Add non-blocking notify call before the UUID-reappear poll**

Find:
```python
    # Step 2: wait for UUID link to reappear (confirms physical replug)
    log(f"Plug the SSD back in — waiting for UUID {PHOTON_SSD_UUID} to reappear...")
```

Insert immediately before the `log()` call:
```python
    # Step 2: wait for UUID link to reappear (confirms physical replug)
    _notify_physical(f"Cycle {cycle} — Plug the SSD back in", blocking=False)
    log(f"Plug the SSD back in — waiting for UUID {PHOTON_SSD_UUID} to reappear...")
```

- [ ] **Step 4: Pass `cycle` from `main()` to `wait_for_replug_and_mount`**

In `main()`, find:
```python
    if not wait_for_replug_and_mount(mount, args.timeout):
```

Change to:
```python
    if not wait_for_replug_and_mount(mount, args.timeout, cycle=cycle):
```

- [ ] **Step 5: Run all soak_cycle tests**

```
pytest tests/test_soak_cycle.py -v
```

Expected: all tests PASS (6 notify_physical + 2 call-site = 8 total).

- [ ] **Step 6: Run the full test suite to check for regressions**

```
pytest --tb=short -q
```

Expected: all previously passing tests still PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/soak_cycle.py tests/test_soak_cycle.py
git commit -m "feat: notify operator on Yoga 910 display during soak cycle plug/unplug"
```

---

## Self-Review

**Spec coverage:**
- ✅ `_notify_physical(message, blocking)` helper added
- ✅ `DISPLAY=:0` set on subprocess env
- ✅ zenity for `blocking=True`, notify-send for `blocking=False`
- ✅ `wall` fallback for both
- ✅ Silent error handling — no exception propagated
- ✅ `cycle` param added to `wait_for_replug_and_mount`
- ✅ Blocking unplug call + non-blocking replug call wired in
- ✅ Existing `log()` calls preserved
- ✅ Unit tests covering all 3 notification scenarios + both call sites
- ✅ No hardware required for unit tests

**Placeholder scan:** None found.

**Type consistency:** `_notify_physical(message: str, blocking: bool)` used identically across all tasks. `wait_for_replug_and_mount(mount_point, timeout, cycle=0)` signature matches all call sites.
