"""Unit tests for soak_cycle._notify_physical and wait_for_replug_and_mount."""
import sys
from pathlib import Path
from unittest.mock import patch, call, MagicMock

import pytest

# soak_cycle.py lives in scripts/, not a package — import via sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import soak_cycle


# ---------------------------------------------------------------------------
# _notify_physical — blocking=True (zenity path)
# ---------------------------------------------------------------------------

def test_notify_physical_blocking_calls_zenity():
    """blocking=True must call zenity with DISPLAY=:0."""
    with patch("soak_cycle.subprocess.run") as mock_run:
        soak_cycle._notify_physical("Unplug the SSD now", blocking=True)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "zenity"
        assert "--info" in cmd
        assert any("PHOTONForge Soak Test" in arg for arg in cmd)
        env = mock_run.call_args[1]["env"]
        assert env["DISPLAY"] == ":0"


def test_notify_physical_blocking_does_not_call_wall_on_success():
    """If zenity succeeds, wall must NOT be called."""
    with patch("soak_cycle.subprocess.run") as mock_run:
        soak_cycle._notify_physical("msg", blocking=True)
        for c in mock_run.call_args_list:
            assert c[0][0][0] != "wall"


# ---------------------------------------------------------------------------
# _notify_physical — blocking=False (notify-send path)
# ---------------------------------------------------------------------------

def test_notify_physical_nonblocking_calls_notify_send():
    """blocking=False must call notify-send with DISPLAY=:0."""
    with patch("soak_cycle.subprocess.run") as mock_run:
        soak_cycle._notify_physical("Plug the SSD back in", blocking=False)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "notify-send"
        assert cmd[1] == "PHOTONForge"
        assert "Plug the SSD back in" in cmd
        env = mock_run.call_args[1]["env"]
        assert env["DISPLAY"] == ":0"


def test_notify_physical_nonblocking_does_not_call_wall_on_success():
    """If notify-send succeeds, wall must NOT be called."""
    with patch("soak_cycle.subprocess.run") as mock_run:
        soak_cycle._notify_physical("msg", blocking=False)
        for c in mock_run.call_args_list:
            assert c[0][0][0] != "wall"


# ---------------------------------------------------------------------------
# _notify_physical — wall fallback
# ---------------------------------------------------------------------------

def test_notify_physical_falls_back_to_wall_when_primary_missing():
    """FileNotFoundError on primary binary must trigger wall fallback."""
    def raise_fnf_for_primary(cmd, **kwargs):
        if cmd[0] in ("zenity", "notify-send"):
            raise FileNotFoundError(f"{cmd[0]} not found")

    with patch("soak_cycle.subprocess.run", side_effect=raise_fnf_for_primary) as mock_run:
        soak_cycle._notify_physical("test message", blocking=True)
        wall_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "wall"]
        assert len(wall_calls) == 1
        assert "test message" in wall_calls[0][0][0][1]


def test_notify_physical_silent_when_all_methods_fail():
    """If every subprocess call raises, _notify_physical must not propagate the exception."""
    with patch("soak_cycle.subprocess.run", side_effect=FileNotFoundError):
        soak_cycle._notify_physical("test", blocking=True)   # must not raise
        soak_cycle._notify_physical("test", blocking=False)  # must not raise
