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
    _physical_core_count,
    _read_shooting_info,
    generate_name,
    warm_sessions,
)


def _fake_sessions(use_merged_decoder: bool = False) -> _Sessions:
    """Return a _Sessions with all-MagicMock internals."""
    decoder_mock = MagicMock()
    if use_merged_decoder:
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
    """If image cannot be loaded and no EXIF, return the filename stem."""
    img_path = tmp_path / "photo.jpg"
    img_path.touch()

    import photo_workflow.naming as nm
    nm._session_cache.clear()

    with patch("photo_workflow.naming._load_sessions", return_value=_fake_sessions()), \
         patch("photo_workflow.naming._preprocess_image", side_effect=ValueError("unreadable")):
        result = generate_name(img_path, model_dir=tmp_path / "models")

    assert result == "photo"


def test_caption_is_full_sentence(tmp_path: Path) -> None:
    """Model caption is preserved as a capitalized full sentence."""
    img_path = tmp_path / "img.jpg"
    img_path.touch()

    import photo_workflow.naming as nm
    nm._session_cache.clear()

    dummy_pixels = np.zeros((1, 3, 768, 768), dtype=np.float32)

    with patch("photo_workflow.naming._load_sessions", return_value=_fake_sessions()), \
         patch("photo_workflow.naming._preprocess_image", return_value=dummy_pixels), \
         patch("photo_workflow.naming._run_inference", return_value="a golden sunset over the ocean"):
        result = generate_name(img_path, model_dir=tmp_path / "models")

    assert result.startswith("A golden sunset over the ocean")


def test_caption_trailing_period_stripped(tmp_path: Path) -> None:
    """Trailing period from model output is removed."""
    img_path = tmp_path / "img.jpg"
    img_path.touch()

    import photo_workflow.naming as nm
    nm._session_cache.clear()

    dummy_pixels = np.zeros((1, 3, 768, 768), dtype=np.float32)

    with patch("photo_workflow.naming._load_sessions", return_value=_fake_sessions()), \
         patch("photo_workflow.naming._preprocess_image", return_value=dummy_pixels), \
         patch("photo_workflow.naming._run_inference", return_value="a red fox in a field."):
        result = generate_name(img_path, model_dir=tmp_path / "models")

    assert not result.endswith(".")
    assert result.startswith("A red fox in a field")


def test_caption_combined_with_exif(tmp_path: Path) -> None:
    """Caption and EXIF shooting info are combined on separate lines."""
    img_path = tmp_path / "img.jpg"
    img_path.touch()

    import photo_workflow.naming as nm
    nm._session_cache.clear()

    dummy_pixels = np.zeros((1, 3, 768, 768), dtype=np.float32)

    with patch("photo_workflow.naming._load_sessions", return_value=_fake_sessions()), \
         patch("photo_workflow.naming._preprocess_image", return_value=dummy_pixels), \
         patch("photo_workflow.naming._run_inference", return_value="mountain lake at dawn"), \
         patch("photo_workflow.naming._read_shooting_info", return_value="35mm | f/2.8 | 1/250s | ISO 400"):
        result = generate_name(img_path, model_dir=tmp_path / "models")

    lines = result.split("\n")
    assert len(lines) == 2
    assert lines[0] == "Mountain lake at dawn"
    assert "35mm" in lines[1]
    assert "ISO 400" in lines[1]


def test_exif_only_when_model_unavailable(tmp_path: Path) -> None:
    """When model can't load but EXIF is available, return EXIF info."""
    img_path = tmp_path / "img.jpg"
    img_path.touch()

    import photo_workflow.naming as nm
    nm._session_cache.clear()

    with patch("photo_workflow.naming._load_sessions", side_effect=FileNotFoundError("no model")), \
         patch("photo_workflow.naming._read_shooting_info", return_value="50mm | f/1.8 | ISO 200"):
        result = generate_name(img_path, model_dir=tmp_path / "models")

    assert "50mm" in result
    assert "ISO 200" in result


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
        return 0.0 if call_count == 1 else 3.0

    with patch("photo_workflow.naming._load_sessions", return_value=_fake_sessions()), \
         patch("photo_workflow.naming._preprocess_image", return_value=dummy_pixels), \
         patch("photo_workflow.naming._run_inference", return_value="mountain lake reflection dawn sky"), \
         patch("photo_workflow.naming.time.perf_counter", side_effect=fake_counter), \
         caplog.at_level(logging.WARNING, logger="photo_workflow.naming"):
        generate_name(img_path, model_dir=tmp_path / "models")

    assert any("KPM-1.2" in r.message for r in caplog.records)


def test_physical_core_count_positive_and_even() -> None:
    """_physical_core_count returns a positive integer >= 2."""
    count = _physical_core_count()
    assert isinstance(count, int)
    assert count >= 2


def test_warm_sessions_returns_true_when_model_loads(tmp_path: Path) -> None:
    """warm_sessions returns True and populates the cache when load succeeds."""
    import photo_workflow.naming as nm
    nm._session_cache.clear()

    with patch("photo_workflow.naming._load_sessions", return_value=_fake_sessions()), \
         patch("photo_workflow.naming._warm_up"):
        ok = warm_sessions(model_dir=tmp_path / "models")

    assert ok is True
    cache_key = str((tmp_path / "models").resolve())
    assert cache_key in nm._session_cache


def test_warm_sessions_returns_false_when_model_missing(tmp_path: Path) -> None:
    """warm_sessions returns False when model directory doesn't contain ONNX files."""
    import photo_workflow.naming as nm
    nm._session_cache.clear()

    ok = warm_sessions(model_dir=tmp_path / "no_model_here")
    assert ok is False


def test_relative_and_absolute_paths_share_cache_entry(tmp_path: Path) -> None:
    """Relative and absolute forms of the same model_dir map to the same cache key."""
    import os
    import photo_workflow.naming as nm
    nm._session_cache.clear()

    abs_model_dir = tmp_path / "models"
    # Compute a relative path from cwd to the model dir
    try:
        rel_model_dir = Path(os.path.relpath(abs_model_dir))
    except ValueError:
        pytest.skip("Cannot compute relative path on this OS")

    sessions_obj = _fake_sessions()
    load_calls = []

    def fake_load(d: Path) -> _Sessions:
        load_calls.append(d)
        return sessions_obj

    with patch("photo_workflow.naming._load_sessions", side_effect=fake_load), \
         patch("photo_workflow.naming._warm_up"):
        warm_sessions(model_dir=abs_model_dir)
        warm_sessions(model_dir=rel_model_dir)

    # _load_sessions should have been called exactly once despite two warm_sessions calls
    assert len(load_calls) == 1, (
        f"Sessions loaded {len(load_calls)} times — path normalisation not working"
    )


def test_build_empty_past_kv_returns_zero_tensors() -> None:
    """_build_empty_past_kv returns float32 zero tensors of shape (1, 12, 0, 64)."""
    session_mock = MagicMock()
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

    assert len(result) == 24
    for name, tensor in result.items():
        assert name.startswith("past_key_values"), f"unexpected key: {name}"
        assert tensor.dtype == np.float32
        assert tensor.shape == (1, 12, 0, 64), f"wrong shape for {name}: {tensor.shape}"
