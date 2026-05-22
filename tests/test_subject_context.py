"""Tests for the subject context builder (mocked ONNX sessions)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

from photo_workflow.subject_context import ModelSessions, build_subject_context
from photo_workflow.scoring_types import SubjectContext


def test_model_sessions_lazy_loading(tmp_path: Path) -> None:
    """ModelSessions should not load models until accessed."""
    sessions = ModelSessions(tmp_path)
    # No sessions loaded yet
    assert sessions._sessions == {}


def test_model_sessions_missing_model_returns_none(tmp_path: Path) -> None:
    """Missing model files should return None, not crash."""
    sessions = ModelSessions(tmp_path)
    assert sessions.clip_vision is None
    assert sessions.rmbg is None
    assert sessions.yunet is None
    assert sessions.yolo is None
    assert sessions.clip_aesthetic_head is None


def test_build_subject_context_no_models(tmp_path: Path) -> None:
    """With no models available, build_subject_context returns degraded context."""
    # Create a simple test image
    from PIL import Image
    img_path = tmp_path / "test.jpg"
    img = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
    img.save(img_path)

    sessions = ModelSessions(tmp_path / "models")
    ctx = build_subject_context(img_path, sessions)

    assert isinstance(ctx, SubjectContext)
    assert ctx.image_bgr.shape == (100, 100, 3)
    assert ctx.image_gray.shape == (100, 100)
    # Degraded: full-image mask, no faces, no detections, zero embedding
    assert ctx.subject_mask.shape == (100, 100)
    assert ctx.subject_mask.all()  # Full image is "subject" when no model
    assert ctx.subject_area_ratio == 1.0
    assert ctx.faces == []
    assert ctx.detections == []
    assert ctx.clip_embedding.shape == (512,)
    assert np.allclose(ctx.clip_embedding, 0.0)


def test_build_subject_context_with_mocked_clip(tmp_path: Path) -> None:
    """CLIP embedding should be populated when session is available."""
    from PIL import Image
    img_path = tmp_path / "test.jpg"
    img = Image.fromarray(np.random.randint(0, 255, (200, 200, 3), dtype=np.uint8))
    img.save(img_path)

    fake_embedding = np.random.randn(512).astype(np.float32)
    mock_session = MagicMock()
    mock_session.run.return_value = [fake_embedding.reshape(1, 512)]
    mock_session.get_inputs.return_value = [MagicMock(name="pixel_values", shape=[1, 3, 224, 224])]

    sessions = ModelSessions(tmp_path / "models")
    sessions._sessions["clip_vision"] = mock_session

    ctx = build_subject_context(img_path, sessions)

    assert ctx.clip_embedding.shape == (512,)
    assert not np.allclose(ctx.clip_embedding, 0.0)


def test_build_subject_context_exif_extraction(tmp_path: Path) -> None:
    """EXIF data should be extracted when available."""
    from PIL import Image
    img_path = tmp_path / "test.jpg"
    img = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
    img.save(img_path)

    sessions = ModelSessions(tmp_path / "models")
    ctx = build_subject_context(img_path, sessions)

    # EXIF dict exists (may be empty for synthetic images)
    assert isinstance(ctx.exif, dict)
