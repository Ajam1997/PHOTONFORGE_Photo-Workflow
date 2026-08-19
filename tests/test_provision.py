# tests/test_provision.py
import json
from unittest.mock import Mock, patch

import pytest

from photo_workflow.provision import (
    analyze_device,
    DeviceAnalysis,
    next_available_cartridge_id,
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


def _is_mkfs(cmd):
    """True for any mkfs.* invocation, whatever filesystem is in play."""
    return any(isinstance(part, str) and part.startswith("mkfs.") for part in cmd)


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
    assert any(_is_mkfs(c) and "/dev/sdb1" in c for c in cmds)
    assert result.device == "/dev/sdb1"
    assert result.created_partition is False


def test_provision_repartition_wipes_device_and_settles_udev():
    lsblk_out = _lsblk_json("sdb", [])
    result, cmds = _run_provision(lsblk_out, force_repartition=True)

    assert ["sudo", "-n", "wipefs", "-a", "/dev/sdb"] in cmds
    assert any("parted" in c for c in cmds)
    assert ["sudo", "-n", "udevadm", "settle"] in cmds
    parted_idx = next(i for i, c in enumerate(cmds) if "parted" in c)
    mkfs_idx = next(i for i, c in enumerate(cmds) if _is_mkfs(c))
    settle_idx = next(i for i, c in enumerate(cmds) if "settle" in c)
    assert parted_idx < settle_idx < mkfs_idx
    assert result.created_partition is True
    assert result.device == "/dev/sdb1"


# --- Filesystem selection (portable-drive plan, Task 4) ---------------------
# A cartridge must be readable on Windows/macOS/Android as well as Linux, so
# exFAT is the default; ext4 stays available for a Linux-only drive.


def test_default_filesystem_is_exfat():
    lsblk_out = _lsblk_json("sdb", [])
    result, cmds = _run_provision(lsblk_out, force_repartition=True)

    mkfs = next(c for c in cmds if _is_mkfs(c))
    assert mkfs == ["sudo", "-n", "mkfs.exfat", "-L", "PHOTON-002", "/dev/sdb1"]
    assert result.filesystem == "exfat"


def test_exfat_partition_gets_the_microsoft_basic_data_type():
    """parted's fs-type only sets the partition GUID, and Windows will not
    assign a drive letter to a partition typed as Linux filesystem data."""
    lsblk_out = _lsblk_json("sdb", [])
    _, cmds = _run_provision(lsblk_out, force_repartition=True)

    parted = next(c for c in cmds if "parted" in c)
    assert "ntfs" in parted, parted
    assert "ext4" not in parted


def test_ext4_is_still_available_for_a_linux_only_drive():
    lsblk_out = _lsblk_json("sdb", [])
    result, cmds = _run_provision(lsblk_out, force_repartition=True, fs="ext4")

    mkfs = next(c for c in cmds if _is_mkfs(c))
    assert mkfs == ["sudo", "-n", "mkfs.ext4", "-L", "PHOTON-002", "-F", "/dev/sdb1"]
    parted = next(c for c in cmds if "parted" in c)
    assert "ext4" in parted
    assert result.filesystem == "ext4"


def test_unsupported_filesystem_is_refused():
    with pytest.raises(ValueError, match="Unsupported filesystem"):
        provision_cartridge("/dev/sdb", "PHOTON-002", fs="btrfs")


def test_label_too_long_for_exfat_is_refused_before_touching_the_device():
    """exFAT caps volume labels at 11 characters; failing at mkfs would be
    after the partition table has already been rewritten."""
    with pytest.raises(ValueError, match="at most 11"):
        provision_cartridge("/dev/sdb", "PHOTON-001-EXTRA-LONG", fs="exfat")


def test_mount_point_comes_from_the_kernel_not_a_hardcoded_path():
    """udisks2 mounts under /media/$USER/<LABEL>; the old hardcoded
    /mnt/photon_ssd/<id> pointed at a directory with nothing on it."""
    lsblk_out = _lsblk_json("sdb", [])
    mounted = json.dumps({"blockdevices": [
        {"name": "sdb1", "mountpoint": "/media/alex/PHOTON-002"}
    ]})

    calls = {"n": 0}

    def side_effect(cmd, **_):
        if cmd[0] == "lsblk":
            calls["n"] += 1
            # first call is analyze_device, later ones resolve the mount point
            return Mock(stdout=lsblk_out if calls["n"] == 1 else mounted, returncode=0)
        return Mock(returncode=0)

    with patch("photo_workflow.provision.subprocess.run", side_effect=side_effect), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value=""):
        result = provision_cartridge("/dev/sdb", "PHOTON-002", force_repartition=True)

    assert result.mount_point == "/media/alex/PHOTON-002"


def test_mount_point_falls_back_when_the_kernel_has_no_answer_yet():
    lsblk_out = _lsblk_json("sdb", [])
    result, _ = _run_provision(lsblk_out, force_repartition=True)
    assert result.mount_point.endswith("/PHOTON-002")
    assert not result.mount_point.startswith("/mnt/photon_ssd")
