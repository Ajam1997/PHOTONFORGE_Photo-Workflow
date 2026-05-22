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


_SAMPLE_SUB_SCORES = {
    "eye_sharpness": 0.85,
    "subject_sharpness": 0.78,
    "subject_isolation": 0.64,
    "blur_type": "bokeh",
    "composition_rot": 0.71,
    "symmetry": 0.32,
    "leading_lines": 0.45,
    "negative_space": 0.68,
    "zone_entropy": 0.82,
    "dynamic_range": 0.91,
    "exposure_style": "normal",
    "face_exposure": 0.88,
    "aesthetic_clip": 0.65,
}


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
    rec.genre = "wildlife"
    rec.genre_confidence = 0.87
    rec.master_score = 0.72
    rec.sub_scores = dict(_SAMPLE_SUB_SCORES)
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


def test_xmp_contains_genre_fields(tmp_path: Path) -> None:
    rec = _make_record(tmp_path)
    _write_xmp(rec)
    content = rec.path.with_suffix(".xmp").read_text()
    assert "<photon:Genre>wildlife</photon:Genre>" in content
    assert "<photon:GenreConfidence>0.87</photon:GenreConfidence>" in content
    assert "<photon:MasterScore>0.72</photon:MasterScore>" in content


def test_xmp_contains_all_sub_scores(tmp_path: Path) -> None:
    rec = _make_record(tmp_path)
    _write_xmp(rec)
    content = rec.path.with_suffix(".xmp").read_text()
    assert "<photon:EyeSharpness>0.85</photon:EyeSharpness>" in content
    assert "<photon:SubjectSharpness>0.78</photon:SubjectSharpness>" in content
    assert "<photon:SubjectIsolation>0.64</photon:SubjectIsolation>" in content
    assert "<photon:BlurType>bokeh</photon:BlurType>" in content
    assert "<photon:CompositionRoT>0.71</photon:CompositionRoT>" in content
    assert "<photon:Symmetry>0.32</photon:Symmetry>" in content
    assert "<photon:LeadingLines>0.45</photon:LeadingLines>" in content
    assert "<photon:NegativeSpace>0.68</photon:NegativeSpace>" in content
    assert "<photon:ZoneEntropy>0.82</photon:ZoneEntropy>" in content
    assert "<photon:DynamicRange>0.91</photon:DynamicRange>" in content
    assert "<photon:ExposureStyle>normal</photon:ExposureStyle>" in content
    assert "<photon:FaceExposure>0.88</photon:FaceExposure>" in content
    assert "<photon:AestheticScore>0.65</photon:AestheticScore>" in content


def test_xmp_defaults_when_no_sub_scores(tmp_path: Path) -> None:
    img = tmp_path / "bare.jpg"
    img.touch()
    rec = PhotoRecord(path=img, semantic_name="test")
    _write_xmp(rec)
    content = img.with_suffix(".xmp").read_text()
    assert "<photon:Genre></photon:Genre>" in content
    assert "<photon:MasterScore>0.0</photon:MasterScore>" in content
    assert "<photon:EyeSharpness>0.0</photon:EyeSharpness>" in content
    assert "<photon:BlurType></photon:BlurType>" in content
    assert "<photon:ExposureStyle></photon:ExposureStyle>" in content


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


# ---------------------------------------------------------------------------
# compute_color_label master_score mode tests
# ---------------------------------------------------------------------------

def test_compute_color_label_master_score_yellow() -> None:
    assert compute_color_label(0.0, master_score=0.2) == 1  # < 0.3


def test_compute_color_label_master_score_none_average() -> None:
    assert compute_color_label(0.0, master_score=0.4) == -1  # 0.3-0.5


def test_compute_color_label_master_score_green() -> None:
    assert compute_color_label(0.0, master_score=0.6) == 2  # 0.5-0.75


def test_compute_color_label_master_score_blue_excellent() -> None:
    assert compute_color_label(0.0, master_score=0.8) == 3  # > 0.75


def test_compute_color_label_hard_reject_returns_none() -> None:
    assert compute_color_label(0.0, master_score=0.9, hard_reject=True) == -1


def test_compute_color_label_sharpness_only_fallback() -> None:
    assert compute_color_label(0.8) == 3  # > 0.75 → blue
