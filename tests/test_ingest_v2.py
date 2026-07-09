"""Tests for v2 ingest — cartridge-prefix renaming."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from photo_workflow.ingest import ingest_volume


def _make_jpg(path: Path, dt_str: str = "2026:05:10 14:32:01") -> None:
    """Create a tiny JPEG with EXIF DateTimeOriginal."""
    arr = np.full((8, 8, 3), 128, dtype=np.uint8)
    img = Image.fromarray(arr)
    exif = img.getexif()
    exif[0x9003] = dt_str  # DateTimeOriginal
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", exif=exif.tobytes())


@pytest.fixture()
def sd_dir(tmp_path: Path) -> Path:
    d = tmp_path / "SD"
    d.mkdir()
    _make_jpg(d / "DSC03056.jpg", "2026:05:10 14:00:00")
    _make_jpg(d / "DSC03057.jpg", "2026:05:10 14:01:00")
    _make_jpg(d / "DSC03058.jpg", "2026:05:10 13:00:00")
    return d


@pytest.fixture()
def dest_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ICELAND"
    d.mkdir()
    return d


@patch("photo_workflow.ingest.get_volume_label", return_value="PHOTONFORGE-003")
def test_ingest_renames_to_sequence(mock_label, sd_dir: Path, dest_dir: Path):
    copied = ingest_volume(sd_dir, dest_dir)
    names = sorted(p.name for p in copied)
    assert names == ["P003ICE0000001.jpg", "P003ICE0000002.jpg", "P003ICE0000003.jpg"]


@patch("photo_workflow.ingest.get_volume_label", return_value="PHOTONFORGE-003")
def test_ingest_sorts_by_exif_timestamp(mock_label, sd_dir: Path, dest_dir: Path):
    copied = ingest_volume(sd_dir, dest_dir)
    # DSC03058 (13:00) should be first, DSC03056 (14:00) second, DSC03057 (14:01) third
    assert copied[0].name == "P003ICE0000001.jpg"
    assert copied[2].name == "P003ICE0000003.jpg"


@patch("photo_workflow.ingest.get_volume_label", return_value="PHOTONFORGE-003")
def test_ingest_continues_sequence(mock_label, sd_dir: Path, dest_dir: Path):
    (dest_dir / "P003ICE0000005.jpg").touch()
    copied = ingest_volume(sd_dir, dest_dir)
    names = sorted(p.name for p in copied)
    assert names[0] == "P003ICE0000006.jpg"


@patch("photo_workflow.ingest.get_volume_label", return_value="MYUSB")
def test_ingest_fallback_cartridge_id(mock_label, sd_dir: Path, dest_dir: Path):
    copied = ingest_volume(sd_dir, dest_dir)
    assert all(p.name.startswith("P000") for p in copied)


@patch("photo_workflow.ingest.get_volume_label", return_value="PHOTONFORGE-003")
def test_ingest_skip_existing(mock_label, sd_dir: Path, dest_dir: Path):
    copied1 = ingest_volume(sd_dir, dest_dir)
    assert len(copied1) == 3
    copied2 = ingest_volume(sd_dir, dest_dir)
    assert len(copied2) == 0


@patch("photo_workflow.ingest.get_volume_label", return_value="PHOTONFORGE-003")
def test_ingest_dry_run(mock_label, sd_dir: Path, dest_dir: Path):
    copied = ingest_volume(sd_dir, dest_dir, dry_run=True)
    assert len(copied) == 3
    actual_files = list(dest_dir.iterdir())
    assert len(actual_files) == 0


@patch("photo_workflow.ingest.get_volume_label", return_value="PHOTONFORGE-003")
def test_ingest_crash_during_copy_does_not_lose_photo(mock_label, tmp_path: Path):
    """A crash mid-copy must not leave the DB claiming the photo was ingested."""
    sd = tmp_path / "SD"
    sd.mkdir()
    _make_jpg(sd / "DSC09999.jpg", "2026:05:10 15:00:00")
    dest = tmp_path / "ICELAND"
    dest.mkdir()

    with patch("photo_workflow.ingest.shutil.copy2", side_effect=OSError("card yanked")):
        with pytest.raises(OSError):
            ingest_volume(sd, dest)

    from photo_workflow.ingest import _get_already_ingested

    assert not any(orig == "DSC09999.jpg" for orig, _ in _get_already_ingested(dest))

    # Resume run must still ingest the photo
    copied = ingest_volume(sd, dest)
    assert [p.name for p in copied] == ["P003ICE0000001.jpg"]
    assert copied[0].exists()


@patch("photo_workflow.ingest.get_volume_label", return_value="PHOTONFORGE-003")
def test_ingest_name_collision_retries_same_source(mock_label, tmp_path: Path):
    """A pre-existing file at the computed name must not skip the source photo."""
    sd = tmp_path / "SD"
    sd.mkdir()
    _make_jpg(sd / "DSC00001.jpg", "2026:05:10 15:00:00")
    dest = tmp_path / "ICELAND"
    dest.mkdir()
    (dest / "P003ICE0000001.jpg").write_bytes(b"leftover")

    with patch("photo_workflow.volume.get_next_sequence", return_value=1):
        copied = ingest_volume(sd, dest)

    assert [p.name for p in copied] == ["P003ICE0000002.jpg"]
    assert copied[0].exists()
    assert (dest / "P003ICE0000001.jpg").read_bytes() == b"leftover"
