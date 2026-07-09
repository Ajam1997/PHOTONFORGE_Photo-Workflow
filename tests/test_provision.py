# tests/test_provision.py
import json
import subprocess
from unittest.mock import Mock, patch

import pytest

from photo_workflow.provision import (
    analyze_device,
    DeviceAnalysis,
    next_available_cartridge_id,
    ProvisionResult,
    provision_cartridge,
)


def test_analyze_device_returns_correct_structure():
    """Test that analyze_device returns a DeviceAnalysis dataclass."""
    mock_lsblk = json.dumps({
        "blockdevices": [{
            "name": "sdb",
            "size": 500107862016,
            "children": []
        }]
    })
    with patch('subprocess.run') as mock_run:
        mock_run.return_value = Mock(stdout=mock_lsblk, returncode=0)
        result = analyze_device("/dev/sdb")
        assert isinstance(result, DeviceAnalysis)
        assert result.device == "/dev/sdb"


def test_next_available_cartridge_id_returns_001_when_no_cartridges_exist():
    """Test that next_available_cartridge_id returns '001' when no cartridges exist."""
    with patch('pathlib.Path.exists') as mock_exists, \
         patch('pathlib.Path.iterdir') as mock_iterdir:
        mock_exists.return_value = False
        mock_iterdir.return_value = []
        result = next_available_cartridge_id()
        assert result == "001"


def test_provision_cartridge_raises_on_nonexistent_device():
    """Test that provision_cartridge raises ValueError for non-existent device."""
    with pytest.raises(ValueError, match="does not exist"):
        provision_cartridge("/dev/nonexistent", "PHOTON-001")


def test_partition_node_suffixes():
    from photo_workflow.provision import _partition_node

    assert _partition_node("/dev/sdb") == "/dev/sdb1"
    assert _partition_node("/dev/nvme0n1") == "/dev/nvme0n1p1"
    assert _partition_node("/dev/mmcblk0") == "/dev/mmcblk0p1"


def _lsblk_json(name: str, children: list) -> str:
    return json.dumps({
        "blockdevices": [
            {"name": name, "size": 1000, "label": None, "type": "disk", "children": children}
        ]
    })


def test_analyze_device_uses_kernel_partition_name():
    from photo_workflow.provision import analyze_device

    mock_out = _lsblk_json(
        "nvme0n1", [{"name": "nvme0n1p1", "size": 1000, "label": "PHOTON-001", "type": "part"}]
    )
    with patch("photo_workflow.provision.subprocess.run") as mock_run:
        mock_run.return_value = Mock(stdout=mock_out, returncode=0)
        analysis = analyze_device("/dev/nvme0n1")
    assert analysis.partition_device == "/dev/nvme0n1p1"


def _run_provision(lsblk_out: str, **kwargs):
    from photo_workflow.provision import provision_cartridge

    def side_effect(cmd, **_):
        if cmd[0] == "lsblk":
            return Mock(stdout=lsblk_out, returncode=0)
        return Mock(returncode=0)

    with patch("photo_workflow.provision.subprocess.run", side_effect=side_effect) as mock_run, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value=""):
        result = provision_cartridge("/dev/sdb", "PHOTON-002", **kwargs)
    return result, [list(c.args[0]) for c in mock_run.call_args_list]


def test_provision_existing_partition_preserves_partition_table():
    """Regression: wipefs -a on the whole device erased the GPT even when the
    existing partition was being reused, bricking the cartridge on replug."""
    lsblk_out = _lsblk_json(
        "sdb", [{"name": "sdb1", "size": 1000, "label": "PHOTON-001", "type": "part"}]
    )
    result, cmds = _run_provision(lsblk_out, force_repartition=False)

    assert ["sudo", "-n", "wipefs", "-a", "/dev/sdb"] not in cmds
    assert ["sudo", "-n", "wipefs", "-a", "/dev/sdb1"] in cmds
    assert not any("parted" in c for c in cmds)
    assert any("mkfs.ext4" in c and "/dev/sdb1" in c for c in cmds)
    assert result.device == "/dev/sdb1"
    assert result.created_partition is False


def test_provision_repartition_wipes_device_and_settles_udev():
    lsblk_out = _lsblk_json("sdb", [])
    result, cmds = _run_provision(lsblk_out, force_repartition=True)

    assert ["sudo", "-n", "wipefs", "-a", "/dev/sdb"] in cmds
    assert any("parted" in c for c in cmds)
    assert ["sudo", "-n", "udevadm", "settle"] in cmds
    parted_idx = next(i for i, c in enumerate(cmds) if "parted" in c)
    mkfs_idx = next(i for i, c in enumerate(cmds) if "mkfs.ext4" in c)
    settle_idx = next(i for i, c in enumerate(cmds) if "settle" in c)
    assert parted_idx < settle_idx < mkfs_idx
    assert result.created_partition is True
    assert result.device == "/dev/sdb1"
