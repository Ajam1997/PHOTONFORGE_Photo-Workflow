"""Tests for FR-1.2: spatio-temporal session clustering (grouping.py)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch


from photo_workflow.grouping import cluster_sessions, SESSION_GAP_MINUTES
from photo_workflow.pipeline import PhotoRecord


def _rec(name: str) -> PhotoRecord:
    return PhotoRecord(path=Path(f"/fake/{name}.jpg"))


def test_single_record_gets_session_id() -> None:
    """A lone record is assigned a non-empty session_id."""
    records = [_rec("solo")]
    dt = datetime(2026, 4, 10, 12, 0, 0)
    with patch("photo_workflow.grouping.read_exif_datetime", return_value=dt):
        result = cluster_sessions(records)
    assert result[0].session_id != ""


def test_records_within_gap_share_session() -> None:
    """Two records < SESSION_GAP_MINUTES apart share the same session."""
    records = [_rec("a"), _rec("b")]
    dts = [datetime(2026, 4, 10, 10, 0, 0), datetime(2026, 4, 10, 10, 5, 0)]
    with patch("photo_workflow.grouping.read_exif_datetime", side_effect=dts):
        result = cluster_sessions(records)
    assert result[0].session_id == result[1].session_id


def test_records_across_gap_get_different_sessions() -> None:
    """Two records > SESSION_GAP_MINUTES apart get different session IDs."""
    from datetime import timedelta

    records = [_rec("morning"), _rec("evening")]
    base = datetime(2026, 4, 10, 9, 0, 0)
    dts = [base, base + timedelta(minutes=SESSION_GAP_MINUTES + 1)]
    with patch("photo_workflow.grouping.read_exif_datetime", side_effect=dts):
        result = cluster_sessions(records)
    assert result[0].session_id != result[1].session_id


def test_no_exif_falls_back_to_session_zero() -> None:
    """Records without EXIF timestamps are assigned to session_0000."""
    records = [_rec("no_exif")]
    with patch("photo_workflow.grouping.read_exif_datetime", return_value=None):
        result = cluster_sessions(records)
    assert result[0].session_id == "session_0000"
