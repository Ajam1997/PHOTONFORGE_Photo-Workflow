"""Tests for raw_loader — the single source of truth for extension sets."""

from __future__ import annotations

from pathlib import Path

from photo_workflow import ingest, pipeline, raw_loader
from photo_workflow.sharpness import _SUPPORTED_EXTS


def test_extension_sets_are_unified():
    """Regression: modules kept disagreeing copies — a .RAF passed pipeline
    scanning but is_raw() said False, so Fuji RAFs fell to cv2.imread and
    errored in scoring."""
    assert raw_loader.is_raw(Path("x.RAF"))
    assert raw_loader.is_raw(Path("x.raf"))
    assert pipeline.PHOTO_EXTS is raw_loader.IMAGE_EXTENSIONS
    assert ingest.SUPPORTED_EXTENSIONS is raw_loader.IMAGE_EXTENSIONS
    assert ingest.RAW_EXTENSIONS is raw_loader.RAW_EXTENSIONS
    assert _SUPPORTED_EXTS is raw_loader.IMAGE_EXTENSIONS
    # Every scannable RAW extension routes through rawpy, not cv2
    for ext in raw_loader.RAW_EXTENSIONS:
        assert raw_loader.is_raw(Path(f"photo{ext}"))


def test_is_raw_rejects_non_raw():
    assert not raw_loader.is_raw(Path("x.jpg"))
    assert not raw_loader.is_raw(Path("x.xmp"))
