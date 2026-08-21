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
