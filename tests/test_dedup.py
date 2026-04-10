"""Unit tests for FR-1.3: dHash deduplication."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from photo_workflow.dedup import deduplicate, DHASH_THRESHOLD
from photo_workflow.pipeline import PhotoRecord


def _make_record(name: str, session: str = "session_0001") -> PhotoRecord:
    rec = PhotoRecord(path=Path(f"/fake/{name}.jpg"))
    rec.session_id = session
    return rec


def test_no_duplicates_when_hashes_differ() -> None:
    """Records with very different hashes are not marked as duplicates."""
    records = [_make_record("a"), _make_record("b"), _make_record("c")]

    # Hashes far apart (Hamming distance >> threshold)
    hashes = [0x0000000000000000, 0xFFFFFFFFFFFFFFFF, 0x00FF00FF00FF00FF]

    with patch("photo_workflow.dedup._dhash", side_effect=hashes):
        result = deduplicate(records)

    assert not any(r.is_duplicate for r in result)


def test_duplicate_flagged_within_session() -> None:
    """Near-identical hashes in the same session → second is a duplicate."""
    records = [_make_record("orig"), _make_record("dup")]
    base_hash = 0xABCDABCDABCDABCD
    near_hash = base_hash ^ 0b11  # Hamming distance = 2 <= DHASH_THRESHOLD

    with patch("photo_workflow.dedup._dhash", side_effect=[base_hash, near_hash]):
        result = deduplicate(records)

    assert not result[0].is_duplicate
    assert result[1].is_duplicate


def test_no_cross_session_dedup() -> None:
    """Near-identical hashes in different sessions are NOT duplicates of each other."""
    r1 = _make_record("a", session="session_0001")
    r2 = _make_record("b", session="session_0002")
    base_hash = 0xABCDABCDABCDABCD
    near_hash = base_hash ^ 0b111

    with patch("photo_workflow.dedup._dhash", side_effect=[base_hash, near_hash]):
        result = deduplicate([r1, r2])

    assert not any(r.is_duplicate for r in result)


def test_dhash_failure_skips_record() -> None:
    """Records where dHash fails are not marked as duplicates."""
    records = [_make_record("bad")]
    with patch("photo_workflow.dedup._dhash", return_value=None):
        result = deduplicate(records)
    assert not result[0].is_duplicate
