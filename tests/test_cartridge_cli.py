"""click surface for photo-cartridge backup subcommands."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from click.testing import CliRunner

from photo_workflow.cartridge import main


def _cartridge(tmp_path, name="cart"):
    root = tmp_path / name
    root.mkdir(parents=True)
    conn = sqlite3.connect(root / "photonforge.db")
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()
    return root


def test_snapshot_command_creates_timestamped_dir(tmp_path):
    root = _cartridge(tmp_path)
    result = CliRunner().invoke(main, ["snapshot", str(root), "--keep", "3"])
    assert result.exit_code == 0, result.output
    snaps = list((root / ".photon-snapshots").iterdir())
    assert len(snaps) == 1
    assert (snaps[0] / "photonforge.db").exists()
    assert (snaps[0] / "snapshot-manifest.json").exists()


def test_snapshot_json_output_is_machine_readable(tmp_path):
    root = _cartridge(tmp_path)
    result = CliRunner().invoke(main, ["snapshot", str(root), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["step"] == "snapshot"
    assert payload["pruned"] == 0
    assert Path(payload["path"]).exists()


def test_snapshot_honours_custom_dest(tmp_path):
    root = _cartridge(tmp_path)
    dest = tmp_path / "elsewhere"
    result = CliRunner().invoke(main, ["snapshot", str(root), "--dest", str(dest)])
    assert result.exit_code == 0, result.output
    assert not (root / ".photon-snapshots").exists()
    assert len(list(dest.iterdir())) == 1


def test_snapshot_rotates_across_runs(tmp_path):
    root = _cartridge(tmp_path)
    dest = tmp_path / "snaps"
    runner = CliRunner()
    # distinct timestamps: seed the dir with older-looking snapshots
    for name in ("2026-01-01T00-00-00", "2026-01-02T00-00-00"):
        (dest / name).mkdir(parents=True)
    result = runner.invoke(main, ["snapshot", str(root), "--dest", str(dest), "--keep", "2"])
    assert result.exit_code == 0, result.output
    remaining = sorted(p.name for p in dest.iterdir())
    assert len(remaining) == 2
    assert "2026-01-01T00-00-00" not in remaining      # oldest pruned
    assert "2026-01-02T00-00-00" in remaining


def _full_cartridge(tmp_path, name="cart"):
    root = _cartridge(tmp_path, name)
    (root / "ICELAND").mkdir()
    (root / "ICELAND" / "DSC0001.ARW").write_bytes(b"raw" * 100)
    return root


def test_backup_command_writes_a_verified_mirror(tmp_path):
    root = _full_cartridge(tmp_path)
    dest = tmp_path / "backups"
    result = CliRunner().invoke(main, ["backup", str(root), "--dest", str(dest), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    snap = Path(payload["path"])
    assert (snap / "ICELAND" / "DSC0001.ARW").exists()
    assert payload["files"] >= 1


def test_verify_backup_passes_then_fails_on_tampering(tmp_path):
    root = _full_cartridge(tmp_path)
    dest = tmp_path / "backups"
    runner = CliRunner()
    created = runner.invoke(main, ["backup", str(root), "--dest", str(dest), "--json"])
    snap = json.loads(created.output)["path"]

    ok = runner.invoke(main, ["verify-backup", snap])
    assert ok.exit_code == 0, ok.output

    (Path(snap) / "ICELAND" / "DSC0001.ARW").write_bytes(b"tampered")
    bad = runner.invoke(main, ["verify-backup", snap])
    assert bad.exit_code != 0
    assert "DSC0001.ARW" in bad.output


def test_verify_backup_resolves_latest_from_dest(tmp_path):
    """The panel has no snapshot picker, so --dest means 'verify the newest'."""
    root = _full_cartridge(tmp_path)
    dest = tmp_path / "backups"
    runner = CliRunner()
    runner.invoke(main, ["backup", str(root), "--dest", str(dest), "--json"])
    second = json.loads(
        runner.invoke(main, ["backup", str(root), "--dest", str(dest), "--json"]).output
    )["path"]

    result = runner.invoke(main, ["verify-backup", "--dest", str(dest), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["path"] == second          # newest, not the first
    assert payload["problems"] == []


def test_verify_backup_scopes_latest_to_the_named_cartridge(tmp_path):
    root_a = _full_cartridge(tmp_path, "PHOTON-001")
    root_b = _full_cartridge(tmp_path, "PHOTON-002")
    dest = tmp_path / "backups"
    runner = CliRunner()
    runner.invoke(main, ["backup", str(root_a), "--dest", str(dest), "--json"])
    b_snap = json.loads(
        runner.invoke(main, ["backup", str(root_b), "--dest", str(dest), "--json"]).output
    )["path"]
    result = runner.invoke(
        main, ["verify-backup", "--dest", str(dest), "--root", str(root_a), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["path"] != b_snap


def test_verify_backup_needs_a_snapshot_or_a_dest(tmp_path):
    result = CliRunner().invoke(main, ["verify-backup"])
    assert result.exit_code != 0
    assert "--dest" in result.output


def test_verify_backup_reports_an_empty_dest(tmp_path):
    empty = tmp_path / "nothing"
    empty.mkdir()
    result = CliRunner().invoke(main, ["verify-backup", "--dest", str(empty)])
    assert result.exit_code != 0
    assert "no snapshot" in result.output.lower()


def test_restore_backup_command(tmp_path):
    root = _full_cartridge(tmp_path)
    dest = tmp_path / "backups"
    runner = CliRunner()
    created = runner.invoke(main, ["backup", str(root), "--dest", str(dest), "--json"])
    snap = json.loads(created.output)["path"]

    target = tmp_path / "restored"
    result = runner.invoke(main, ["restore-backup", snap, "--to", str(target)])
    assert result.exit_code == 0, result.output
    assert (target / "photonforge.db").exists()
    assert (target / "ICELAND" / "DSC0001.ARW").exists()


def test_backup_refuses_busy_cartridge_with_a_clean_error(tmp_path):
    root = _full_cartridge(tmp_path)
    holder = sqlite3.connect(root / "photonforge.db")
    holder.execute("BEGIN IMMEDIATE")
    try:
        result = CliRunner().invoke(
            main, ["backup", str(root), "--dest", str(tmp_path / "b")])
        assert result.exit_code != 0
        assert "busy" in result.output.lower()
    finally:
        holder.rollback()
        holder.close()


def test_snapshot_reports_failure_on_a_cartridge_with_no_dbs(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = CliRunner().invoke(main, ["snapshot", str(empty)])
    assert result.exit_code != 0
    # a clean click error, not a leaked traceback
    assert "no photonforge/darktable dbs found" in result.output.lower()
