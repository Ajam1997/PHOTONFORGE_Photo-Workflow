"""Terminal progress display for long-running pipeline stages."""

from __future__ import annotations

import sys
import time


def _get_rss_mb() -> int:
    """Return current process RSS in MB (Linux/Windows)."""
    try:
        import psutil

        return psutil.Process().memory_info().rss // (1024 * 1024)
    except ImportError:
        pass
    # Fallback for Linux: read /proc/self/status
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except (FileNotFoundError, ValueError):
        pass
    return 0


class ProgressTracker:
    """In-place terminal progress counter with throughput and ETA."""

    def __init__(self, stage: str, total: int) -> None:
        self.stage = stage
        self.total = total
        self._start_time = time.monotonic()
        self._current = 0

    def format_line(
        self,
        current: int,
        elapsed_seconds: float | None = None,
        rss_mb: int | None = None,
    ) -> str:
        """Build the progress string without printing it."""
        if elapsed_seconds is None:
            elapsed_seconds = time.monotonic() - self._start_time
        if rss_mb is None:
            rss_mb = _get_rss_mb()

        pct = (current / self.total * 100) if self.total > 0 else 0.0
        rate = current / elapsed_seconds if elapsed_seconds > 0 else 0.0
        remaining = self.total - current
        eta_seconds = remaining / rate if rate > 0 else 0
        eta_min = int(eta_seconds // 60)

        return (
            f"[{self.stage}] {current}/{self.total} ({pct:.1f}%) "
            f"| {rate:.1f} img/s | ETA {eta_min}m | RSS {rss_mb}MB"
        )

    def update(self, current: int) -> None:
        """Print an in-place progress line to stderr."""
        self._current = current
        line = self.format_line(current)
        sys.stderr.write(f"\r{line}")
        sys.stderr.flush()

    def finish(self) -> None:
        """Print final newline so the summary line doesn't overwrite progress."""
        sys.stderr.write("\n")
        sys.stderr.flush()
