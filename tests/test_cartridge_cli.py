"""click surface for photo-cartridge backup subcommands."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from click.testing import CliRunner

from photo_workflow.cartridge import main


def _cartridge(tmp_path):
    root = tmp_path / "cart"
    root.mkdir()
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


def test_snapshot_reports_failure_on_a_cartridge_with_no_dbs(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = CliRunner().invoke(main, ["snapshot", str(empty)])
    assert result.exit_code != 0
    # a clean click error, not a leaked traceback
    assert "no photonforge/darktable dbs found" in result.output.lower()
