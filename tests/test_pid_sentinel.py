"""Test PID and sentinel file lifecycle for Lua plugin integration."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


def test_sentinel_created_on_start(tmp_path, monkeypatch):
    """Pipeline main() creates sentinel and PID files in TEMP."""
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))

    from photo_workflow.pipeline import _write_sentinel, _cleanup_sentinel

    _write_sentinel(tmp_path)

    pid_file = tmp_path / "photonforge.pid"
    sentinel = tmp_path / "photonforge.running"

    assert pid_file.exists()
    assert sentinel.exists()
    assert pid_file.read_text().strip() == str(os.getpid())

    _cleanup_sentinel(tmp_path)

    assert not sentinel.exists()
    # PID file stays (Lua may still need to read it for kill)
    assert pid_file.exists()


def test_sentinel_cleanup_is_idempotent(tmp_path):
    """Calling cleanup when sentinel doesn't exist doesn't raise."""
    from photo_workflow.pipeline import _cleanup_sentinel

    # Should not raise even if files don't exist
    _cleanup_sentinel(tmp_path)


def test_stale_sentinel_overwritten(tmp_path):
    """If a stale sentinel exists from a crash, it gets overwritten."""
    from photo_workflow.pipeline import _write_sentinel

    sentinel = tmp_path / "photonforge.running"
    sentinel.write_text("stale")

    pid_file = tmp_path / "photonforge.pid"
    pid_file.write_text("99999")

    _write_sentinel(tmp_path)

    assert pid_file.read_text().strip() == str(os.getpid())
    assert sentinel.exists()
