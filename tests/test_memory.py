"""KPM-1.3: RSS memory budget monitoring for the analysis pipeline."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

RSS_LIMIT_MB = 1536  # KPM-1.3: analyzer container <= 1.5 GB RSS


def _current_rss_mb() -> float:
    """Return current process RSS in megabytes."""
    try:
        import resource
        rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux returns KB, macOS returns bytes
        if os.uname().sysname == "Darwin":
            return rss_kb / (1024 * 1024)
        return rss_kb / 1024
    except Exception:
        # Fallback: read /proc/self/status
        try:
            status = Path("/proc/self/status").read_text()
            for line in status.splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
        except Exception:
            pass
        return 0.0


@pytest.mark.slow
def test_pipeline_rss_within_budget(tmp_path: Path) -> None:
    """
    Run a minimal pipeline pass and verify RSS stays under KPM-1.3 budget.
    Mark as slow — run explicitly with pytest -m slow.
    """
    from photo_workflow.pipeline import AnalysisPipeline, PipelineConfig

    config = PipelineConfig(
        source_dir=tmp_path,
        output_dir=tmp_path / "out",
        darktable_db=tmp_path / "library.db",
        dry_run=True,
    )
    pipeline = AnalysisPipeline(config)
    pipeline.run()

    rss_mb = _current_rss_mb()
    assert rss_mb < RSS_LIMIT_MB, (
        f"RSS {rss_mb:.1f} MB exceeds KPM-1.3 budget of {RSS_LIMIT_MB} MB"
    )


def test_rss_baseline_reasonable() -> None:
    """Sanity check: baseline RSS measurement returns a plausible value."""
    rss = _current_rss_mb()
    # Should be at least 1 MB (we're running Python) and less than the limit at baseline
    assert 0 < rss < RSS_LIMIT_MB
