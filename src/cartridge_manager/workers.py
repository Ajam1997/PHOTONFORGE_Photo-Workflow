"""QThread wrapper for blocking photo_workflow operations."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal


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

    Not every wrapped function accepts a `progress` kwarg (e.g.
    `backup.restore_snapshot` doesn't) — `progress` is only forwarded when
    `fn`'s signature actually declares it (or accepts **kwargs), so wrapping
    a progress-less function doesn't raise a TypeError.

    Call `.settle()` (not bare `.wait()`) in your `finished`/`failed` slot
    before dropping the last Python reference — see `settle()` below for
    why a plain `wait()` is not quite enough on its own.
    """

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = WorkerSignals()
        # QThread's own native `finished` signal (distinct from
        # `self.signals.finished` above) is guaranteed by Qt itself to fire
        # only once the OS thread has genuinely, fully terminated — unlike
        # our custom signal, which is emitted from inside run() just before
        # it returns. Connecting it to deleteLater() lets Qt's own event
        # loop delete the underlying C++ object at a Qt-determined safe
        # point, independent of Python's reference counting/GC timing
        # entirely, which is the standard, most robust fix for QThread
        # lifetime bugs (the __del__ safety net above and callers' own
        # `.wait()` calls remain as defense in depth, not the primary fix).
        self.finished.connect(self.deleteLater)
        try:
            params = inspect.signature(fn).parameters
            self._accepts_progress = "progress" in params or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            )
        except (TypeError, ValueError):
            # Signature couldn't be introspected (e.g. some builtins/C
            # callables) — assume it doesn't take progress rather than risk
            # a TypeError from an unexpected kwarg.
            self._accepts_progress = False

    def __del__(self) -> None:
        # `finished`/`failed` are emitted from inside run(), on the worker
        # thread itself, via a queued connection — by the time a receiver on
        # the main thread acts on one, run() is *about* to return, but there
        # is a real race where the underlying OS thread has not fully
        # joined yet. Garbage-collecting (or otherwise deleting) a QThread
        # while it is still technically running is a fatal error in
        # PySide6 ("QThread: Destroyed while thread is still running"),
        # which aborts the whole process — not a Python exception any
        # caller could catch. Guaranteeing that here, in the one place
        # every caller's reference eventually funnels through, means no
        # caller (view code, tests, anything future) has to remember a
        # wait()-before-drop contract to be safe. wait() is a documented
        # no-op if the thread has already finished.
        try:
            if self.isRunning():
                self.wait()
        except RuntimeError:
            pass  # underlying C++ object already gone; nothing to wait on

    def settle(self) -> None:
        """Block until this worker's thread and Qt-level teardown are both
        fully done — call this, not bare `.wait()`, before dropping your
        reference or reusing this worker's slot for something else.

        `wait()` alone only guarantees the OS thread has joined; it does not
        guarantee that Qt has finished *processing* the native `finished`
        signal this class connects to `deleteLater()` in `__init__` (see
        there for why that connection exists). If that queued deletion is
        still sitting unprocessed when this method returns, it lingers in
        the event queue and can end up being processed much later — inside
        a completely unrelated later `QEventLoop.exec()` (e.g. some other
        widget's next `qtbot.waitSignal()`), by which point the surrounding
        conditions are no longer whatever they were when the deletion was
        scheduled. That "stale queued event fires at an unrelated later
        moment" pattern is exactly what made this class of bug so hard to
        pin down empirically — a race reproduced this way only rarely,
        never on the same test twice. Pumping the event loop here, right
        after wait(), forces that queued deletion to actually happen now,
        while conditions are still exactly what this method's caller
        expects, rather than deferring it to an unpredictable later moment.
        """
        self.wait()
        QCoreApplication.processEvents()
        QCoreApplication.processEvents()

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
            kwargs = dict(self._kwargs)
            if self._accepts_progress:
                kwargs["progress"] = _progress
            result = self._fn(*self._args, **kwargs)
            self.signals.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 - must convert to a signal, not crash the worker thread silently
            self.signals.failed.emit(str(exc))
