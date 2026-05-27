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
    assert sessions.aesthetic_head is None


def test_build_subject_context_no_models(tmp_path: Path) -> None:
    """With no models available, build_subject_context returns degraded context."""
    from PIL import Image
    img_path = tmp_path / "test.jpg"
    img = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
    img.save(img_path)

    sessions = ModelSessions(tmp_path / "models")
    ctx = build_subject_context(img_path, sessions)

    assert isinstance(ctx, SubjectContext)
    assert ctx.image_bgr.shape == (100, 100, 3)
    assert ctx.image_gray.shape == (100, 100)
    assert ctx.subject_mask.shape == (100, 100)
    assert ctx.subject_mask.all()
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

    assert isinstance(ctx.exif, dict)


def test_build_subject_context_sharpness_contrast(tmp_path: Path) -> None:
    """sharpness_contrast should be computed during build_subject_context."""
    from PIL import Image
    img_path = tmp_path / "test.jpg"
    img = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
    img.save(img_path)

    sessions = ModelSessions(tmp_path / "models")
    ctx = build_subject_context(img_path, sessions)

    assert hasattr(ctx, "sharpness_contrast")
    assert isinstance(ctx.sharpness_contrast, (int, float))
    assert ctx.sharpness_contrast >= 0.0


def test_model_sessions_training_db_override(tmp_path: Path) -> None:
    """ModelSessions should load active prototypes from training_weights.db if configured."""
    from photo_workflow.training_weights_db import open_training_db, ensure_schema, upsert_prototype
    from photo_workflow.genre_router import ALL_LABELS, SUBJECTS, PHOTO_TYPES

    training_db_path = tmp_path / "training_weights.db"
    conn = open_training_db(training_db_path)
    ensure_schema(conn)

    for i, label in enumerate(ALL_LABELS):
        proto = np.random.randn(512).astype(np.float32)
        proto /= np.linalg.norm(proto)
        upsert_prototype(conn, 1, label, proto.tobytes(), i * 5, 0.8)

    conn.close()

    sessions = ModelSessions(tmp_path / "models", training_db_path=training_db_path)
    protos = sessions.genre_prototypes

    assert protos is not None
    # Shape is (len(SUBJECTS) + len(PHOTO_TYPES), 512) = (14, 512)
    # because "general" appears in both halves
    assert protos.shape == (len(SUBJECTS) + len(PHOTO_TYPES), 512)
    for i in range(protos.shape[0]):
        assert not np.allclose(protos[i], 0.0)


def test_model_sessions_training_db_fallback(tmp_path: Path) -> None:
    """ModelSessions should fallback to hardcoded file if training_db missing."""
    model_dir = tmp_path / "models"
    model_dir.mkdir()

    n_rows = 14  # len(SUBJECTS) + len(PHOTO_TYPES)
    hardcoded_protos = np.random.randn(n_rows, 512).astype(np.float32)
    np.save(model_dir / "genre_prototypes.npy", hardcoded_protos)

    training_db_path = tmp_path / "nonexistent.db"

    sessions = ModelSessions(model_dir, training_db_path=training_db_path)
    protos = sessions.genre_prototypes

    assert protos is not None
    assert np.allclose(protos, hardcoded_protos)
