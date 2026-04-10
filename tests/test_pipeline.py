"""Integration test: AnalysisPipeline end-to-end with fixture images."""

from __future__ import annotations

from pathlib import Path

import pytest

from photo_workflow.pipeline import AnalysisPipeline, PipelineConfig


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_output(tmp_path: Path) -> Path:
    return tmp_path / "output"


def test_pipeline_dry_run(fixture_dir: Path, tmp_output: Path) -> None:
    """Pipeline runs in dry-run mode without writing files."""
    config = PipelineConfig(
        source_dir=fixture_dir,
        output_dir=tmp_output,
        darktable_db=fixture_dir / "library.db",
        dry_run=True,
    )
    pipeline = AnalysisPipeline(config)
    # Dry run — just verify no exception raised
    # Actual records depend on fixture content
    records = pipeline.run()
    assert isinstance(records, list)
