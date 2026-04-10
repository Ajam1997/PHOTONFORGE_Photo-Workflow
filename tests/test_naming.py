"""Tests for FR-1.7: Florence-2-base-ft INT8 semantic naming (naming.py)."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from photo_workflow.naming import generate_name


def test_missing_model_falls_back_to_stem(tmp_path: Path) -> None:
    """When model weights are absent, returns the original filename stem."""
    img_path = tmp_path / "sunset_beach.jpg"
    img_path.touch()

    result = generate_name(img_path, model_dir=tmp_path / "no_models")
    assert result == "sunset_beach"


def test_unloadable_image_falls_back_to_stem(tmp_path: Path) -> None:
    """If cv2 cannot load the image, return the filename stem."""
    model_dir = tmp_path / "models"
    (model_dir / "florence2_int8").mkdir(parents=True)
    (model_dir / "florence2_int8" / "model.onnx").touch()

    img_path = tmp_path / "photo.jpg"
    img_path.touch()

    import photo_workflow.naming as nm
    nm._session_cache.clear()

    with patch("photo_workflow.naming._load_session", return_value=MagicMock()), \
         patch("cv2.imread", return_value=None):
        result = generate_name(img_path, model_dir=model_dir)

    assert result == "photo"


def test_caption_is_slugified(tmp_path: Path) -> None:
    """Model caption is lowercased, punctuation removed, first 5 words joined by underscores."""
    fake_img = np.zeros((224, 224, 3), dtype=np.uint8)
    session = MagicMock()
    session.run.return_value = ["A golden sunset over the ocean!"]

    img_path = tmp_path / "img.jpg"
    img_path.touch()

    with patch("photo_workflow.naming._load_session", return_value=session), \
         patch("cv2.imread", return_value=fake_img), \
         patch("cv2.cvtColor", return_value=fake_img), \
         patch("cv2.resize", return_value=fake_img.astype(np.float32)):
        import photo_workflow.naming as nm
        nm._session_cache.clear()
        result = generate_name(img_path, model_dir=tmp_path / "models")

    assert " " not in result
    assert "!" not in result
    assert result == result.lower()
    assert result == "a_golden_sunset_over_the"


def test_slug_max_length(tmp_path: Path) -> None:
    """Slug is capped at 64 characters."""
    very_long = "a " * 100  # 200 chars before slug, but 5-word cap applies first
    fake_img = np.zeros((224, 224, 3), dtype=np.uint8)
    session = MagicMock()
    session.run.return_value = [very_long]

    img_path = tmp_path / "img.jpg"
    img_path.touch()

    with patch("photo_workflow.naming._load_session", return_value=session), \
         patch("cv2.imread", return_value=fake_img), \
         patch("cv2.cvtColor", return_value=fake_img), \
         patch("cv2.resize", return_value=fake_img.astype(np.float32)):
        import photo_workflow.naming as nm
        nm._session_cache.clear()
        result = generate_name(img_path, model_dir=tmp_path / "models")

    assert len(result) <= 64


def test_five_word_slug(tmp_path: Path) -> None:
    """Caption is truncated to the first 5 words."""
    fake_img = np.zeros((224, 224, 3), dtype=np.uint8)
    session = MagicMock()
    session.run.return_value = ["red fox jumps over lazy brown dog"]

    img_path = tmp_path / "img.jpg"
    img_path.touch()

    with patch("photo_workflow.naming._load_session", return_value=session), \
         patch("cv2.imread", return_value=fake_img), \
         patch("cv2.cvtColor", return_value=fake_img), \
         patch("cv2.resize", return_value=fake_img.astype(np.float32)):
        import photo_workflow.naming as nm
        nm._session_cache.clear()
        result = generate_name(img_path, model_dir=tmp_path / "models")

    assert result == "red_fox_jumps_over_lazy"


def test_slow_inference_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Inference exceeding 1.5s emits a KPM-1.2 warning."""
    fake_img = np.zeros((224, 224, 3), dtype=np.uint8)
    session = MagicMock()
    session.run.return_value = ["mountain lake reflection dawn sky"]

    img_path = tmp_path / "img.jpg"
    img_path.touch()

    call_count = 0

    def fake_counter() -> float:
        nonlocal call_count
        call_count += 1
        return 0.0 if call_count == 1 else 2.0  # simulates 2s elapsed

    with patch("photo_workflow.naming._load_session", return_value=session), \
         patch("cv2.imread", return_value=fake_img), \
         patch("cv2.cvtColor", return_value=fake_img), \
         patch("cv2.resize", return_value=fake_img.astype(np.float32)), \
         patch("photo_workflow.naming.time.perf_counter", side_effect=fake_counter), \
         caplog.at_level(logging.WARNING, logger="photo_workflow.naming"):
        import photo_workflow.naming as nm
        nm._session_cache.clear()
        generate_name(img_path, model_dir=tmp_path / "models")

    assert any("KPM-1.2" in r.message for r in caplog.records)
