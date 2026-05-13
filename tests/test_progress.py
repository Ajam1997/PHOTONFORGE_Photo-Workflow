"""Tests for the terminal progress tracker."""

from __future__ import annotations

from photo_workflow.progress import ProgressTracker


def test_progress_format_line() -> None:
    """format_line() produces the expected counter string."""
    tracker = ProgressTracker(stage="score", total=100)
    line = tracker.format_line(current=25, elapsed_seconds=12.5, rss_mb=512)
    assert "[score]" in line
    assert "25/100" in line
    assert "25.0%" in line
    assert "img/s" in line
    assert "RSS" in line


def test_progress_eta_calculation() -> None:
    """ETA decreases as more items complete."""
    tracker = ProgressTracker(stage="name", total=1000)
    line_early = tracker.format_line(current=100, elapsed_seconds=250.0)
    line_late = tracker.format_line(current=900, elapsed_seconds=2250.0)
    assert "ETA" in line_early
    assert "ETA" in line_late
    # At 0.4 img/s, 900 remaining = 2250s = 37m; 100 remaining = 250s = 4m
    assert "37m" in line_early
    assert "4m" in line_late


def test_progress_zero_total() -> None:
    """Zero total doesn't crash — shows 0.0%."""
    tracker = ProgressTracker(stage="scan", total=0)
    line = tracker.format_line(current=0, elapsed_seconds=1.0)
    assert "0.0%" in line
