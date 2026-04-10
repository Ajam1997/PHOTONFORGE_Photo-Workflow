"""Tests for FR-1.7: Florence-2-base-ft INT8 semantic naming (naming.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

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

    with patch("photo_workflow.naming._load_session", return_value=MagicMock()), \
         patch("cv2.imread", return_value=None):
        result = generate_name(img_path, model_dir=model_dir)

    assert result == "photo"


def test_caption_is_slugified(tmp_path: Path) -> None:
    """Model caption is lowercased and non-alphanumeric chars become underscores."""
    fake_img = np.zeros((224, 224, 3), dtype=np.uint8)
    session = MagicMock()
    session.run.return_value = ["A golden sunset over the ocean!"]

    img_path = tmp_path / "img.jpg"
    img_path.touch()

    with patch("photo_workflow.naming._load_session", return_value=session), \
         patch("cv2.imread", return_value=fake_img), \
         patch("cv2.cvtColor", return_value=fake_img), \
         patch("cv2.resize", return_value=fake_img.astype(np.float32)):
        # Clear cache to force session load
        import photo_workflow.naming as nm
        nm._session_cache.clear()
        result = generate_name(img_path, model_dir=tmp_path / "models")

    assert " " not in result
    assert "!" not in result
    assert result == result.lower()


def test_slug_max_length(tmp_path: Path) -> None:
    """Slug is capped at 64 characters."""
    very_long = "a " * 100  # 200 chars before slug
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
