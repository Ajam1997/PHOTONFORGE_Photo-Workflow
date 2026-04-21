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
