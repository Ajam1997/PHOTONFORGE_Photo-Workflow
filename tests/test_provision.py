# tests/test_provision.py
import json
import subprocess
from unittest.mock import Mock, patch

from photo_workflow.provision import analyze_device, DeviceAnalysis


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
