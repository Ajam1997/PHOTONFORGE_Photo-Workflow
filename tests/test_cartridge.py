"""Tests for FR-1.9: SSD volume detection and management (cartridge.py)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from photo_workflow.cartridge import detect_cartridges, manage_cartridge, Cartridge


def _fake_lsblk(devices: list) -> MagicMock:
    result = MagicMock()
    result.returncode = 0
    result.stdout = json.dumps({"blockdevices": devices})
    return result


def test_no_photon_label_returns_empty() -> None:
    """Devices without PHOTON label are not returned."""
    devices = [{"name": "sdb", "label": "BACKUP", "mountpoint": "/mnt/backup",
                "size": "500G", "fsavail": "100G", "children": None}]
    with patch("subprocess.run", return_value=_fake_lsblk(devices)):
        result = detect_cartridges()
    assert result == []


def test_lsblk_unavailable_returns_empty() -> None:
    """FileNotFoundError from lsblk → returns empty list, no exception."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = detect_cartridges()
    assert result == []


def test_photon_labeled_device_detected(tmp_path: Path) -> None:
    """Devices with PHOTON prefix label and a valid mount point are returned."""
    devices = [{"name": "sdc", "label": "PHOTON-001", "mountpoint": str(tmp_path),
                "size": "1T", "fsavail": "800G", "children": None}]

    import shutil
    usage = shutil.disk_usage(tmp_path)

    with patch("subprocess.run", return_value=_fake_lsblk(devices)):
        result = detect_cartridges()

    assert len(result) == 1
    assert result[0].label == "PHOTON-001"
    assert result[0].device == "/dev/sdc"
    assert result[0].mount_point == tmp_path


def test_manage_cartridge_calls_pipeline(tmp_path: Path) -> None:
    """manage_cartridge invokes the pipeline function with the mount point."""
    cartridge = Cartridge(
        device="/dev/sdc",
        mount_point=tmp_path,
        label="PHOTON-001",
        size_bytes=1_000_000_000,
        free_bytes=500_000_000,
    )
    called_with = []
    manage_cartridge(cartridge, lambda mp: called_with.append(mp))
    assert called_with == [tmp_path]
