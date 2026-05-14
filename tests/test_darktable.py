"""Tests for darktable_bridge: XMP writing and color label computation."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from photo_workflow.darktable_bridge import (
    compute_color_label,
    sync_to_darktable,
    validate_xmp,
    _write_xmp,
)
from photo_workflow.pipeline import PhotoRecord


def _make_record(tmp_path: Path, name: str = "test", duplicate: bool = False) -> PhotoRecord:
    img_path = tmp_path / f"{name}.jpg"
    img_path.touch()
    rec = PhotoRecord(path=img_path)
    rec.session_id = "session_0001"
    rec.is_duplicate = duplicate
    rec.sharpness_score = 0.85
    rec.composition_score = 0.72
    rec.exposure_score = 0.91
    rec.semantic_name = "golden_hour_landscape"
    return rec


# ---------------------------------------------------------------------------
# XMP tests
# ---------------------------------------------------------------------------

def test_xmp_written_for_non_duplicate(tmp_path: Path) -> None:
    rec = _make_record(tmp_path)
    _write_xmp(rec)
    xmp_path = rec.path.with_suffix(".xmp")
    assert xmp_path.exists()
    content = xmp_path.read_text()
    assert "0.85" in content
    assert "golden_hour_landscape" in content


def test_xmp_not_written_for_duplicate(tmp_path: Path) -> None:
    rec = _make_record(tmp_path, duplicate=True)
    count = sync_to_darktable([rec])
    xmp_path = rec.path.with_suffix(".xmp")
    assert not xmp_path.exists()
    assert count == 0


def test_validate_xmp_passes_for_valid_sidecar(tmp_path: Path) -> None:
    rec = _make_record(tmp_path)
    _write_xmp(rec)
    assert validate_xmp(rec.path.with_suffix(".xmp")) is True


def test_validate_xmp_fails_for_malformed(tmp_path: Path) -> None:
    bad_xmp = tmp_path / "bad.xmp"
    bad_xmp.write_text("<not-valid-xmp>garbage</not-valid-xmp>", encoding="utf-8")
    assert validate_xmp(bad_xmp) is False


# ---------------------------------------------------------------------------
# sync_to_darktable tests
# ---------------------------------------------------------------------------

def test_sync_to_darktable_xmp_only(tmp_path: Path) -> None:
    img = tmp_path / "00001.ARW"
    img.write_bytes(b"fake")
    record = PhotoRecord(
        path=img, session_id="s1",
        sharpness_score=0.7, composition_score=0.6, exposure_score=0.7,
        semantic_name="a-blue-waterfall",
        metadata={"original_filename": "DSC001.ARW"},
    )
    count = sync_to_darktable([record])
    assert (tmp_path / "00001.xmp").exists()
    assert count == 1


def test_sync_to_darktable_no_db_param() -> None:
    sig = inspect.signature(sync_to_darktable)
    assert "db_path" not in sig.parameters


def test_sync_to_darktable_skips_duplicates(tmp_path: Path) -> None:
    keeper = _make_record(tmp_path, name="keeper")
    dup = _make_record(tmp_path, name="dup", duplicate=True)
    count = sync_to_darktable([keeper, dup])
    assert count == 1
    assert keeper.path.with_suffix(".xmp").exists()
    assert not dup.path.with_suffix(".xmp").exists()


# ---------------------------------------------------------------------------
# compute_color_label tests
# ---------------------------------------------------------------------------

def test_compute_color_label_green_mean_above_half() -> None:
    assert compute_color_label(0.7, 0.6, 0.7) == 2


def test_compute_color_label_yellow_low_sharpness() -> None:
    assert compute_color_label(0.2, 0.6, 0.7) == 1


def test_compute_color_label_blue_low_exposure() -> None:
    assert compute_color_label(0.7, 0.6, 0.4) == 3


def test_compute_color_label_purple_low_composition() -> None:
    assert compute_color_label(0.7, 0.1, 0.7) == 4


def test_compute_color_label_no_label_below_mean() -> None:
    label = compute_color_label(0.4, 0.4, 0.6)
    assert label == -1


def test_compute_color_label_yellow_takes_priority_over_blue() -> None:
    # sharpness < 0.3 AND exposure < 0.5 → yellow wins
    assert compute_color_label(0.2, 0.6, 0.3) == 1
