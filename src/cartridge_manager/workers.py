"""QThread wrapper for blocking photo_workflow operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal


class WorkerSignals(QObject):
    """Owned by the main thread (created in Worker.__init__, not run()) so
    Qt auto-queues these signal emissions from the worker thread back onto
    the main thread's event loop — this is the standard, correct pattern;
    creating a QObject inside run() instead is the classic mistake that
    breaks this.
    """

    progress = Signal(int, int, str)  # (index, total, label) — always this shape
    finished = Signal(object)  # the wrapped call's return value
    failed = Signal(str)  # str(exception)


class Worker(QThread):
    """Runs one blocking photo_workflow call off the GUI thread.

    Call as Worker(relocate.move_photos, photo_paths, dest_dir, cart_id,
    trip_code, ungroup=..., force=...) — do NOT pass `dry_run=True` calls
    through this (those are fast, synchronous, and belong on the GUI
    thread directly, not threaded).
    """

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self) -> None:
        def _progress(*cb_args: Any) -> None:
            # Normalize whatever shape the wrapped function's progress
            # callback receives into (index, total, str-label). relocate.py
            # calls progress(index, total, Path) — 3 args. Some other
            # photo_workflow modules use a single-string progress(msg) —
            # handle that too so this worker isn't relocate-specific.
            if len(cb_args) >= 3:
                index, total, label = cb_args[0], cb_args[1], cb_args[2]
            elif len(cb_args) == 1:
                index, total, label = 0, 0, cb_args[0]
            else:
                index, total, label = 0, 0, ""
            self.signals.progress.emit(int(index), int(total), str(label))

        try:
            result = self._fn(*self._args, progress=_progress, **self._kwargs)
            self.signals.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - must convert to a signal, not crash the worker thread silently
            self.signals.failed.emit(str(exc))
