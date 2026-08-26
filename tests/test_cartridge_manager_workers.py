"""Tests for the QThread worker wrapper."""

from __future__ import annotations

import pytest

# Skip this entire module if PySide6 is not installed
pytest.importorskip("PySide6")

from cartridge_manager.workers import Worker


def simple_function(*, progress=None):
    """A function that calls progress twice and returns a value."""
    if progress is not None:
        progress(1, 3, "First step")
        progress(2, 3, "Second step")
    return {"result": "success", "count": 42}


def string_progress_function(*, progress=None):
    """A function that calls progress with a single string argument."""
    if progress is not None:
        progress("processing...")
    return {"status": "done"}


def failing_function(*, progress=None):
    """A function that raises an exception."""
    raise RuntimeError("boom")


def no_progress_function(snapshot, target, *, force=False):
    """A function with no `progress` parameter at all (like restore_snapshot)."""
    return f"restored {snapshot} into {target} (force={force})"


def test_worker_calls_progress_twice_and_returns(qtbot):
    """Worker wraps a function, calls progress twice, returns result."""
    worker = Worker(simple_function)

    # Record progress signals
    progress_signals = []
    worker.signals.progress.connect(lambda i, t, l: progress_signals.append((i, t, l)))

    # Wait for finished signal
    with qtbot.waitSignal(worker.signals.finished, timeout=2000) as blocker:
        worker.start()

    # Assert result (blocker.args is a tuple of the emitted arguments)
    result = blocker.args[0]
    assert result["result"] == "success"
    assert result["count"] == 42

    # Assert progress signals were emitted in order
    assert len(progress_signals) == 2
    assert progress_signals[0] == (1, 3, "First step")
    assert progress_signals[1] == (2, 3, "Second step")


def test_worker_catches_exception_and_emits_failed(qtbot):
    """Worker wraps a function that raises; emits failed signal with message."""
    worker = Worker(failing_function)

    with qtbot.waitSignal(worker.signals.failed, timeout=2000) as blocker:
        worker.start()

    message = blocker.args[0]
    assert message == "boom"


def test_worker_normalizes_single_string_progress(qtbot):
    """Worker normalizes single-string progress into (0, 0, str)."""
    worker = Worker(string_progress_function)

    progress_signals = []
    worker.signals.progress.connect(lambda i, t, l: progress_signals.append((i, t, l)))

    with qtbot.waitSignal(worker.signals.finished, timeout=2000):
        worker.start()

    assert len(progress_signals) == 1
    assert progress_signals[0] == (0, 0, "processing...")


def test_worker_does_not_pass_progress_to_a_function_without_it(qtbot):
    """A function with no `progress` parameter must not raise TypeError."""
    worker = Worker(no_progress_function, "snap.tar", "target/", force=True)

    with qtbot.waitSignal(worker.signals.finished, timeout=2000) as blocker:
        worker.start()

    assert blocker.args[0] == "restored snap.tar into target/ (force=True)"
