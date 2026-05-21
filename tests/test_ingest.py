"""Tests for FR-1.1: volume ingestion with cartridge-prefix renaming (ingest.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from photo_workflow.ingest import ingest_volume, SUPPORTED_EXTENSIONS


def _make_jpg(path: Path, dt_str: str = "2026:05:10 14:32:01") -> None:
    """Create a tiny JPEG with EXIF DateTimeOriginal."""
    arr = np.full((8, 8, 3), 128, dtype=np.uint8)
    img = Image.fromarray(arr)
    exif = img.getexif()
    exif[0x9003] = dt_str  # DateTimeOriginal
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", exif=exif.tobytes())


def test_supported_extensions_not_empty() -> None:
    """Sanity check: supported extension set is populated."""
    assert len(SUPPORTED_EXTENSIONS) > 0
    assert ".jpg" in SUPPORTED_EXTENSIONS
    assert ".raw" in SUPPORTED_EXTENSIONS
    assert ".arw" in SUPPORTED_EXTENSIONS


def test_ingest_volume_creates_output_dir(tmp_path: Path) -> None:
    """Output directory is created if it does not exist."""
    src = tmp_path / "src"
    src.mkdir()
    output = tmp_path / "does" / "not" / "exist"

    with patch("photo_workflow.ingest.get_volume_label", return_value="PHOTONFORGE-001"):
        ingest_volume(src, output)

    assert output.is_dir()


def test_ingest_volume_skips_non_image_files(tmp_path: Path) -> None:
    """Non-image files in source are ignored."""
    src = tmp_path / "src"
    src.mkdir()
    output = tmp_path / "output"
    output.mkdir()

    # Create various files
    _make_jpg(src / "photo.jpg", "2026:05:10 12:00:00")
    (src / "readme.txt").touch()
    (src / "data.csv").touch()

    with patch("photo_workflow.ingest.get_volume_label", return_value="PHOTONFORGE-001"):
        result = ingest_volume(src, output)

    # Only the JPEG should be ingested
    assert len(result) == 1
    assert result[0].name.endswith(".jpg")
