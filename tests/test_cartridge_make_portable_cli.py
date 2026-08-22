"""click surface for `photo-cartridge make-portable` and the `init` deprecation notice."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from photo_workflow import cartridge, volume

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "deploy" / "portable"
LUA_DIR = Path(__file__).resolve().parent.parent / "lua" / "photonforge"


def _mount_photon_cartridge(tmp_path, monkeypatch, label="PHOTON-001"):
    drive = tmp_path / "drive"
    drive.mkdir()
    monkeypatch.setattr(volume, "get_volume_label", lambda _p: label)
    return drive


def test_make_portable_refuses_a_non_photon_drive(tmp_path, monkeypatch):
    drive = tmp_path / "drive"
    drive.mkdir()
    monkeypatch.setattr(volume, "get_volume_label", lambda _p: "OTHERDRIVE")
    result = CliRunner().invoke(cartridge.main, ["make-portable", str(drive), "--cache", str(tmp_path / "cache")])
    assert result.exit_code != 0
    assert "does not look like a PHOTON cartridge" in result.output


def test_make_portable_checks_the_requested_id(tmp_path, monkeypatch):
    drive = _mount_photon_cartridge(tmp_path, monkeypatch, label="PHOTON-002")
    result = CliRunner().invoke(
        cartridge.main,
        ["make-portable", str(drive), "--id", "001", "--cache", str(tmp_path / "cache")],
    )
    assert result.exit_code != 0
    assert "does not match --id 001" in result.output


def test_make_portable_assembles_without_a_manifest(tmp_path, monkeypatch):
    drive = _mount_photon_cartridge(tmp_path, monkeypatch)
    result = CliRunner().invoke(
        cartridge.main,
        [
            "make-portable", str(drive),
            "--templates-dir", str(TEMPLATES_DIR),
            "--lua-src", str(LUA_DIR),
            "--cache", str(tmp_path / "cache"),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["apps"] == {}
    assert (drive / "dt-config" / "lua" / "photonforge" / "main.lua").exists()
    assert (drive / "!START_PHOTONForge.sh").exists()
    assert (drive / "!README.txt").exists()
    assert (drive / "autorun.inf").exists()
    assert "PHOTON-001" in (drive / "autorun.inf").read_text(encoding="utf-8")
    assert Path(payload["manifest_lock"]).exists()
    assert Path(payload["readme"]).exists()
    assert Path(payload["autorun_inf"]).exists()


def test_make_portable_human_output_lists_plugin_and_launchers(tmp_path, monkeypatch):
    drive = _mount_photon_cartridge(tmp_path, monkeypatch)
    result = CliRunner().invoke(
        cartridge.main,
        [
            "make-portable", str(drive),
            "--templates-dir", str(TEMPLATES_DIR),
            "--lua-src", str(LUA_DIR),
            "--cache", str(tmp_path / "cache"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Portable drive assembled" in result.output
    assert "manifest lock" in result.output


def test_make_portable_wraps_a_build_error_as_a_clean_click_exception(tmp_path, monkeypatch):
    drive = _mount_photon_cartridge(tmp_path, monkeypatch)
    empty_lua_dir = tmp_path / "not-lua"
    empty_lua_dir.mkdir()
    result = CliRunner().invoke(
        cartridge.main,
        [
            "make-portable", str(drive),
            "--templates-dir", str(TEMPLATES_DIR),
            "--lua-src", str(empty_lua_dir),
            "--cache", str(tmp_path / "cache"),
        ],
    )
    assert result.exit_code != 0
    assert "Missing plugin file" in result.output
    assert "Traceback" not in result.output


def test_init_command_still_works_but_prints_a_deprecation_notice(tmp_path):
    mount = tmp_path / "cart"
    mount.mkdir()
    result = CliRunner().invoke(cartridge.main, ["init", str(mount)])
    assert result.exit_code == 0, result.output
    assert "deprecated" in result.output.lower() or "warning" in result.output.lower()
    assert (mount / "darktable" / "library.db").exists()


# ============================================================================
# WSL bridge integration tests
# ============================================================================


def test_make_portable_on_linux_does_not_invoke_wsl(tmp_path, monkeypatch):
    """On Linux (sys.platform != 'win32'), WSL bridge is never invoked."""
    import sys

    drive = _mount_photon_cartridge(tmp_path, monkeypatch)

    # Mock wsl_bridge.run_make_portable_linux to track if it's called
    stub_calls = []

    def stub_wsl(*args, **kwargs):
        stub_calls.append(True)

    from photo_workflow import wsl_bridge

    monkeypatch.setattr(wsl_bridge, "run_make_portable_linux", stub_wsl)

    # Mock sys.platform to return 'linux' (or whatever it is)
    original_platform = sys.platform
    try:
        # Only run this test on non-Windows
        if original_platform != "win32":
            result = CliRunner().invoke(
                cartridge.main,
                [
                    "make-portable", str(drive),
                    "--os", "win", "--os", "linux",
                    "--templates-dir", str(TEMPLATES_DIR),
                    "--lua-src", str(LUA_DIR),
                    "--cache", str(tmp_path / "cache"),
                ],
            )
            assert result.exit_code == 0, result.output
            # On non-Windows, stub should never be called
            assert len(stub_calls) == 0
    finally:
        pass


def test_make_portable_with_wsl_split_on_windows_simulation(tmp_path, monkeypatch):
    """Simulates Windows --os win --os linux split: in-process builds win, WSL stub called for linux."""
    drive = _mount_photon_cartridge(tmp_path, monkeypatch)

    # Track WSL invocations
    wsl_calls = []

    def stub_wsl(drive_arg, **kwargs):
        wsl_calls.append({"drive": drive_arg, "kwargs": kwargs})

    from photo_workflow import wsl_bridge

    monkeypatch.setattr(wsl_bridge, "run_make_portable_linux", stub_wsl)

    # Simulate Windows by monkeypatching sys.platform
    monkeypatch.setattr("sys.platform", "win32")

    result = CliRunner().invoke(
        cartridge.main,
        [
            "make-portable", str(drive),
            "--os", "win", "--os", "linux",
            "--templates-dir", str(TEMPLATES_DIR),
            "--lua-src", str(LUA_DIR),
            "--cache", str(tmp_path / "cache"),
        ],
    )

    # The command should succeed
    assert result.exit_code == 0, result.output

    # WSL stub should have been called exactly once for linux half
    assert len(wsl_calls) == 1
    assert wsl_calls[0]["drive"] == drive

    # Output should mention the WSL build
    assert "via WSL" in result.output or "Linux" in result.output


def test_make_portable_wsl_error_surfaces_as_click_exception(tmp_path, monkeypatch):
    """If wsl_bridge.run_make_portable_linux raises WslError, it becomes a ClickException."""
    from photo_workflow import wsl_bridge

    drive = _mount_photon_cartridge(tmp_path, monkeypatch)

    def stub_wsl_error(*args, **kwargs):
        raise wsl_bridge.WslError("Test WSL error: WSL is not installed")

    monkeypatch.setattr(wsl_bridge, "run_make_portable_linux", stub_wsl_error)
    monkeypatch.setattr("sys.platform", "win32")

    result = CliRunner().invoke(
        cartridge.main,
        [
            "make-portable", str(drive),
            "--os", "linux",
            "--templates-dir", str(TEMPLATES_DIR),
            "--lua-src", str(LUA_DIR),
            "--cache", str(tmp_path / "cache"),
        ],
    )

    # Should fail with a clean error message
    assert result.exit_code != 0
    assert "Test WSL error" in result.output
    # Should not have a Python traceback
    assert "Traceback" not in result.output


def test_make_portable_with_windows_os_only_does_not_invoke_wsl(tmp_path, monkeypatch):
    """On Windows with only --os win, WSL is not needed."""
    from photo_workflow import wsl_bridge

    drive = _mount_photon_cartridge(tmp_path, monkeypatch)

    wsl_calls = []

    def stub_wsl(*args, **kwargs):
        wsl_calls.append(True)

    monkeypatch.setattr(wsl_bridge, "run_make_portable_linux", stub_wsl)
    monkeypatch.setattr("sys.platform", "win32")

    result = CliRunner().invoke(
        cartridge.main,
        [
            "make-portable", str(drive),
            "--os", "win",
            "--templates-dir", str(TEMPLATES_DIR),
            "--lua-src", str(LUA_DIR),
            "--cache", str(tmp_path / "cache"),
        ],
    )

    assert result.exit_code == 0, result.output
    # WSL should not be invoked for win-only builds
    assert len(wsl_calls) == 0


def test_make_portable_json_includes_linux_via_wsl_marker(tmp_path, monkeypatch):
    """JSON output includes linux_via_wsl=true when Linux built via WSL."""
    import json as _json

    from photo_workflow import wsl_bridge

    drive = _mount_photon_cartridge(tmp_path, monkeypatch)

    def stub_wsl(*args, **kwargs):
        # Pretend we built linux; create a dummy manifest lock so re-read works
        dot_dir = drive / ".photonforge"
        dot_dir.mkdir(parents=True, exist_ok=True)
        lock_path = dot_dir / "manifest.lock.json"
        lock_data = {
            "schema": 1,
            "tool_version": "test",
            "created_at": "2026-01-01T00:00:00Z",
            "git_sha": None,
            "oses": ["linux"],
            "darktable": {},
        }
        lock_path.write_text(_json.dumps(lock_data), encoding="utf-8")

    monkeypatch.setattr(wsl_bridge, "run_make_portable_linux", stub_wsl)
    monkeypatch.setattr("sys.platform", "win32")

    result = CliRunner().invoke(
        cartridge.main,
        [
            "make-portable", str(drive),
            "--os", "linux",
            "--templates-dir", str(TEMPLATES_DIR),
            "--lua-src", str(LUA_DIR),
            "--cache", str(tmp_path / "cache"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _json.loads(result.output)
    assert payload.get("linux_via_wsl") is True
