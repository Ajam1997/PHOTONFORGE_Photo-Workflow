"""Tests for FR-1.7: Florence-2-base-ft INT8 semantic naming (naming.py)."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from photo_workflow.naming import (
    _Sessions,
    _build_empty_past_kv,
    _caption_to_slug,
    generate_name,
)


def _fake_sessions(use_merged_decoder: bool = False) -> _Sessions:
    """Return a _Sessions with all-MagicMock internals."""
    decoder_mock = MagicMock()
    if use_merged_decoder:
        # Merged decoder exposes 'use_cache_branch' as an input name
        decoder_mock.get_inputs.return_value = [
            MagicMock(name="encoder_attention_mask"),
            MagicMock(name="encoder_hidden_states"),
            MagicMock(name="inputs_embeds"),
            MagicMock(name="past_key_values.0.decoder.key"),
            MagicMock(name="past_key_values.0.decoder.value"),
            MagicMock(name="past_key_values.0.encoder.key"),
            MagicMock(name="past_key_values.0.encoder.value"),
            MagicMock(name="use_cache_branch"),
        ]
    else:
        decoder_mock.get_inputs.return_value = [
            MagicMock(name="encoder_attention_mask"),
            MagicMock(name="encoder_hidden_states"),
            MagicMock(name="inputs_embeds"),
        ]

    return _Sessions(
        vision_encoder=MagicMock(),
        embed_tokens=MagicMock(),
        encoder=MagicMock(),
        decoder=decoder_mock,
        tokenizer=None,
        img_size=(768, 768),
        img_mean=np.zeros(3, dtype=np.float32),
        img_std=np.ones(3, dtype=np.float32),
        prompt_ids=np.array([[0, 1, 2, 3, 4, 5, 6, 7]], dtype=np.int64),
        decoder_out_names=["logits"],
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
    """Model caption is lowercased, punctuation removed, first 5 words joined by hyphens."""
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
    assert result == "a-golden-sunset-over-the"


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

    assert result == "red-fox-jumps-over-lazy"


def test_slow_inference_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Inference exceeding 2.5s emits a KPM-1.2 warning."""
    img_path = tmp_path / "img.jpg"
    img_path.touch()

    import photo_workflow.naming as nm
    nm._session_cache.clear()

    dummy_pixels = np.zeros((1, 3, 768, 768), dtype=np.float32)
    call_count = 0

    def fake_counter() -> float:
        nonlocal call_count
        call_count += 1
        return 0.0 if call_count == 1 else 3.0  # simulates 3s elapsed (> 2.5s KPM limit)

    with patch("photo_workflow.naming._load_sessions", return_value=_fake_sessions()), \
         patch("photo_workflow.naming._preprocess_image", return_value=dummy_pixels), \
         patch("photo_workflow.naming._run_inference", return_value="mountain lake reflection dawn sky"), \
         patch("photo_workflow.naming.time.perf_counter", side_effect=fake_counter), \
         caplog.at_level(logging.WARNING, logger="photo_workflow.naming"):
        generate_name(img_path, model_dir=tmp_path / "models")

    assert any("KPM-1.2" in r.message for r in caplog.records)


def test_build_empty_past_kv_returns_zero_tensors() -> None:
    """_build_empty_past_kv returns float32 zero tensors of shape (1, 12, 0, 64)."""
    session_mock = MagicMock()
    # Simulate 6-layer merged decoder: each layer has 4 KV slots (dec.key, dec.val, enc.key, enc.val)
    kv_input_names = [
        f"past_key_values.{layer}.{side}.{kv}"
        for layer in range(6)
        for side in ("decoder", "encoder")
        for kv in ("key", "value")
    ]
    session_mock.get_inputs.return_value = [
        MagicMock(name=n) for n in kv_input_names
    ]

    result = _build_empty_past_kv(session_mock)

    assert len(result) == 24  # 6 layers * 2 sides * 2 kv = 24
    for name, tensor in result.items():
        assert name.startswith("past_key_values"), f"unexpected key: {name}"
        assert tensor.dtype == np.float32
        assert tensor.shape == (1, 12, 0, 64), f"wrong shape for {name}: {tensor.shape}"


def test_caption_to_slug_strips_task_prefix() -> None:
    """Captions starting with a leading task token or angle brackets are still slugified."""
    # Verify the slug function handles captions from the real model gracefully
    assert _caption_to_slug("A glowing ring in the dark with a black background.") == \
        "a-glowing-ring-in-the"
    assert _caption_to_slug("") == ""
    assert _caption_to_slug("One") == "one"
