"""Tests for FR-1.1: rsync-triggered volume ingestion (ingest.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from photo_workflow.ingest import ingest_volume, SUPPORTED_EXTENSIONS


def test_supported_extensions_not_empty() -> None:
    """Sanity check: supported extension set is populated."""
    assert len(SUPPORTED_EXTENSIONS) > 0
    assert ".jpg" in SUPPORTED_EXTENSIONS
    assert ".raw" in SUPPORTED_EXTENSIONS


def test_ingest_volume_raises_on_rsync_failure(tmp_path: Path) -> None:
    """rsync non-zero exit code raises RuntimeError."""
    failed = MagicMock(returncode=1, stderr="rsync: error")
    with patch("subprocess.run", return_value=failed):
        with pytest.raises(RuntimeError, match="rsync exited"):
            ingest_volume(tmp_path / "src", tmp_path / "dst")


def test_ingest_volume_dry_run_returns_existing_files(tmp_path: Path) -> None:
    """Dry-run returns files already present in output dir (no rsync write)."""
    output = tmp_path / "output"
    output.mkdir()
    (output / "photo.jpg").touch()
    (output / "ignore.txt").touch()

    ok = MagicMock(returncode=0, stderr="")
    with patch("subprocess.run", return_value=ok):
        result = ingest_volume(tmp_path / "src", output, dry_run=True)

    names = {p.name for p in result}
    assert "photo.jpg" in names
    assert "ignore.txt" not in names


def test_ingest_volume_creates_output_dir(tmp_path: Path) -> None:
    """Output directory is created if it does not exist."""
    output = tmp_path / "does" / "not" / "exist"
    ok = MagicMock(returncode=0, stderr="")
    with patch("subprocess.run", return_value=ok):
        ingest_volume(tmp_path / "src", output)
    assert output.is_dir()
