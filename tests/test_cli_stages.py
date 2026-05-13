"""Integration tests for the staged CLI subcommands."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

from photo_workflow.manifest import load_manifest
from photo_workflow.pipeline import cli


@pytest.fixture()
def photo_dir(tmp_path: Path) -> Path:
    """Create 4 synthetic JPEG images in a flat directory."""
    d = tmp_path / "photos"
    d.mkdir()

    def save_jpg(arr: np.ndarray, name: str, dt_str: str) -> None:
        p = d / name
        img = Image.fromarray(arr.astype(np.uint8))
        exif = img.getexif()
        exif[0x0132] = dt_str
        img.save(p, "JPEG", quality=95, exif=exif.tobytes())

    checker = (np.indices((64, 64)).sum(axis=0) % 2 * 255).astype(np.uint8)
    checker_rgb = np.stack([checker] * 3, axis=2)
    save_jpg(checker_rgb, "IMG_0001.jpg", "2026:04:01 10:00:00")

    # Duplicate of IMG_0001
    shutil.copy2(d / "IMG_0001.jpg", d / "IMG_0002.jpg")

    gray = np.full((64, 64, 3), 128, dtype=np.uint8)
    save_jpg(gray, "IMG_0003.jpg", "2026:04:01 10:05:00")

    rng = np.random.default_rng(42)
    noise = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
    save_jpg(noise, "IMG_0004.jpg", "2026:04:01 14:00:00")

    return d


@pytest.fixture()
def manifest_path(tmp_path: Path) -> Path:
    return tmp_path / "manifest.jsonl"


def test_scan_creates_manifest(photo_dir: Path, manifest_path: Path) -> None:
    """scan subcommand discovers JPEGs and writes a manifest."""
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", "--source", str(photo_dir), "--manifest", str(manifest_path)])
    assert result.exit_code == 0, result.output
    assert manifest_path.exists()

    entries = load_manifest(manifest_path)
    assert len(entries) == 4
    assert all("scan" in e.stages_completed for e in entries)
    assert "Scanned 4" in result.output


def test_scan_recursive(photo_dir: Path, manifest_path: Path) -> None:
    """scan --recursive finds images in subdirectories."""
    sub = photo_dir / "subdir"
    sub.mkdir()
    shutil.copy2(photo_dir / "IMG_0001.jpg", sub / "IMG_0005.jpg")

    runner = CliRunner()
    result = runner.invoke(cli, [
        "scan", "--source", str(photo_dir), "--manifest", str(manifest_path), "--recursive",
    ])
    assert result.exit_code == 0
    entries = load_manifest(manifest_path)
    assert len(entries) == 5  # 4 original + 1 in subdir
