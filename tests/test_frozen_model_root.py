"""portable-drive plan Task 5 — frozen-aware model root.

A PyInstaller onedir freeze has no src/photo_workflow/*.py on disk to climb
from via __file__, so the models/ fallback must switch to resolving from
sys.executable when frozen. Covers both copies of _default_model_root()
(pipeline.py and naming.py) and that the 4 CLI fallback sites + the 2
naming.py function defaults actually call it.
"""

from __future__ import annotations

import sys
from pathlib import Path

from photo_workflow import naming, pipeline


def test_pipeline_default_model_root_unfrozen_is_repo_root_models():
    assert pipeline._default_model_root() == pipeline._REPO_ROOT / "models"


def test_pipeline_default_model_root_frozen_climbs_from_executable(monkeypatch):
    fake_exe = "/mnt/PHOTON-001/runtime/linux/photo-workflow"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", fake_exe, raising=False)
    result = pipeline._default_model_root()
    assert result == Path("/mnt/PHOTON-001/models")


def test_naming_default_model_root_unfrozen_is_repo_root_models():
    repo_root = Path(naming.__file__).resolve().parent.parent.parent
    assert naming._default_model_root() == repo_root / "models"


def test_naming_default_model_root_frozen_climbs_from_executable(monkeypatch):
    fake_exe = "/mnt/PHOTON-001/runtime/linux/photo-cartridge"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", fake_exe, raising=False)
    result = naming._default_model_root()
    assert result == Path("/mnt/PHOTON-001/models")


def test_naming_generate_name_none_model_dir_uses_default_root(monkeypatch, tmp_path):
    monkeypatch.setattr(naming, "_default_model_root", lambda: tmp_path)
    img = tmp_path / "photo.jpg"
    from PIL import Image
    Image.new("RGB", (8, 8)).save(img)
    # no models/florence2_int8 present under tmp_path -> falls back to EXIF/stem,
    # but the cache key proves _default_model_root() / "florence2_int8" was used.
    naming.generate_name(img, model_dir=None)
    assert str((tmp_path / "florence2_int8").resolve()) in naming._session_cache


def test_naming_warm_sessions_none_model_dir_uses_default_root(monkeypatch, tmp_path):
    monkeypatch.setattr(naming, "_default_model_root", lambda: tmp_path)
    naming.warm_sessions(model_dir=None)
    assert str((tmp_path / "florence2_int8").resolve()) in naming._session_cache


def test_pipeline_cli_fallback_sites_all_call_default_model_root():
    """The 4 `if model_dir is None:` sites in pipeline.py resolve via the
    shared helper rather than re-deriving Path(__file__)... inline — a
    regression guard for the frozen-build bug the helper exists to fix."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(pipeline))
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "_default_model_root"
    ]
    assert len(calls) == 4, f"expected 4 call sites, found {len(calls)}"
