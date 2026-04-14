"""Tests for FR-1.7: Florence-2-base-ft INT8 semantic naming (naming.py)."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from photo_workflow.naming import _Sessions, generate_name


def _fake_sessions() -> _Sessions:
    """Return a _Sessions with all-MagicMock internals (never actually called in slug tests)."""
    return _Sessions(
        embed_tokens=MagicMock(),
        encoder=MagicMock(),
        decoder=MagicMock(),
        tokenizer=None,
    )


def test_missing_model_falls_back_to_stem(tmp_path: Path) -> None:
    """When model weights are absent, returns the original filename stem."""
    img_path = tmp_path / "sunset_beach.jpg"
    img_path.touch()

    result = generate_name(img_path, model_dir=tmp_path / "no_models")
    assert result == "sunset_beach"


def test_unloadable_image_falls_back_to_stem(tmp_path: Path) -> None:
    """If cv2 cannot load the image, return the filename stem."""
    img_path = tmp_path / "photo.jpg"
    img_path.touch()

    import photo_workflow.naming as nm
    nm._session_cache.clear()

    with patch("photo_workflow.naming._load_sessions", return_value=_fake_sessions()), \
         patch("photo_workflow.naming._preprocess_image", side_effect=ValueError("unreadable")):
        result = generate_name(img_path, model_dir=tmp_path / "models")

    assert result == "photo"


def test_caption_is_slugified(tmp_path: Path) -> None:
    """Model caption is lowercased, punctuation removed, first 5 words joined by underscores."""
    img_path = tmp_path / "img.jpg"
    img_path.touch()

    import photo_workflow.naming as nm
    nm._session_cache.clear()

    dummy_pixels = np.zeros((1, 3, 768, 768), dtype=np.float32)

    with patch("photo_workflow.naming._load_sessions", return_value=_fake_sessions()), \
         patch("photo_workflow.naming._preprocess_image", return_value=dummy_pixels), \
         patch("photo_workflow.naming._run_inference", return_value="A golden sunset over the ocean!"):
        result = generate_name(img_path, model_dir=tmp_path / "models")

    assert " " not in result
    assert "!" not in result
    assert result == result.lower()
    assert result == "a_golden_sunset_over_the"


def test_slug_max_length(tmp_path: Path) -> None:
    """Slug is capped at 64 characters."""
    very_long = "a " * 100  # 200 chars before slug, but 5-word cap applies first
    img_path = tmp_path / "img.jpg"
    img_path.touch()

    import photo_workflow.naming as nm
    nm._session_cache.clear()

    dummy_pixels = np.zeros((1, 3, 768, 768), dtype=np.float32)

    with patch("photo_workflow.naming._load_sessions", return_value=_fake_sessions()), \
         patch("photo_workflow.naming._preprocess_image", return_value=dummy_pixels), \
         patch("photo_workflow.naming._run_inference", return_value=very_long):
        result = generate_name(img_path, model_dir=tmp_path / "models")

    assert len(result) <= 64


def test_five_word_slug(tmp_path: Path) -> None:
    """Caption is truncated to the first 5 words."""
    img_path = tmp_path / "img.jpg"
    img_path.touch()

    import photo_workflow.naming as nm
    nm._session_cache.clear()

    dummy_pixels = np.zeros((1, 3, 768, 768), dtype=np.float32)

    with patch("photo_workflow.naming._load_sessions", return_value=_fake_sessions()), \
         patch("photo_workflow.naming._preprocess_image", return_value=dummy_pixels), \
         patch("photo_workflow.naming._run_inference", return_value="red fox jumps over lazy brown dog"):
        result = generate_name(img_path, model_dir=tmp_path / "models")

    assert result == "red_fox_jumps_over_lazy"


def test_slow_inference_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Inference exceeding 1.5s emits a KPM-1.2 warning."""
    img_path = tmp_path / "img.jpg"
    img_path.touch()

    import photo_workflow.naming as nm
    nm._session_cache.clear()

    dummy_pixels = np.zeros((1, 3, 768, 768), dtype=np.float32)
    call_count = 0

    def fake_counter() -> float:
        nonlocal call_count
        call_count += 1
        return 0.0 if call_count == 1 else 2.0  # simulates 2s elapsed

    with patch("photo_workflow.naming._load_sessions", return_value=_fake_sessions()), \
         patch("photo_workflow.naming._preprocess_image", return_value=dummy_pixels), \
         patch("photo_workflow.naming._run_inference", return_value="mountain lake reflection dawn sky"), \
         patch("photo_workflow.naming.time.perf_counter", side_effect=fake_counter), \
         caplog.at_level(logging.WARNING, logger="photo_workflow.naming"):
        generate_name(img_path, model_dir=tmp_path / "models")

    assert any("KPM-1.2" in r.message for r in caplog.records)
