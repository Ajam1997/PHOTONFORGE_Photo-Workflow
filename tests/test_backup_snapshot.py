"""Tier-1 catalog snapshots: cartridge layout discovery and VACUUM INTO copies."""

from __future__ import annotations

import json
import sqlite3

import pytest

from photo_workflow.backup import (
    MANIFEST_NAME,
    cartridge_layout,
    rotate_snapshots,
    sha256_file,
    snapshot_databases,
    snapshot_timestamp,
)


def _db(path, value=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (?)", (value,))
    conn.commit()
    conn.close()


def _cartridge_layout_a(root):
    """Legacy layout: Darktable catalog under darktable/."""
    for rel in ("photonforge.db", "training_weights.db",
                "darktable/library.db", "darktable/data.db"):
        _db(root / rel)
    return root


def test_layout_finds_present_dbs(tmp_path):
    layout = cartridge_layout(_cartridge_layout_a(tmp_path / "cart"))
    assert set(layout.dbs) == {"photonforge", "training_weights", "dt_library", "dt_data"}


def test_layout_finds_portable_dt_config(tmp_path):
    """Layout B (portable drive) puts the DT catalog under dt-config/."""
    root = tmp_path / "cart"
    _db(root / "photonforge.db")
    _db(root / "dt-config/library.db")
    layout = cartridge_layout(root)
    assert set(layout.dbs) == {"photonforge", "dt_library"}
    assert layout.dbs["dt_library"].parent.name == "dt-config"


def test_layout_prefers_portable_over_legacy(tmp_path):
    """A migrated cartridge may carry both; dt-config/ is canonical."""
    root = tmp_path / "cart"
    _db(root / "dt-config/library.db")
    _db(root / "darktable/library.db")
    assert cartridge_layout(root).dbs["dt_library"].parent.name == "dt-config"


def test_layout_omits_absent_dbs(tmp_path):
    root = tmp_path / "cart"
    _db(root / "photonforge.db")
    assert set(cartridge_layout(root).dbs) == {"photonforge"}


def test_snapshot_copies_and_manifests(tmp_path):
    root = _cartridge_layout_a(tmp_path / "cart")
    dest = tmp_path / "snap"
    assert snapshot_databases(root, dest) == dest
    assert (dest / "photonforge.db").exists()
    assert (dest / "library.db").exists()          # basename, not the darktable/ path
    # VACUUM INTO produces a clean, queryable copy
    conn = sqlite3.connect(dest / "photonforge.db")
    assert conn.execute("SELECT x FROM t").fetchone()[0] == 1
    conn.close()
    manifest = json.loads((dest / MANIFEST_NAME).read_text())
    assert manifest["kind"] == "catalog"
    assert manifest["schema"] == 1
    entry = manifest["dbs"]["photonforge"]
    assert entry["bytes"] > 0
    assert entry["sha256"] == sha256_file(dest / "photonforge.db")
    assert manifest["started_at"] and manifest["finished_at"]


def test_snapshot_raises_when_no_dbs(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        snapshot_databases(empty, tmp_path / "snap")


def test_snapshot_survives_a_path_with_a_quote(tmp_path):
    """VACUUM INTO takes no bind parameters, so the path is quoted by hand."""
    root = tmp_path / "cart"
    _db(root / "photonforge.db")
    dest = tmp_path / "it's a snapshot"
    snapshot_databases(root, dest)
    conn = sqlite3.connect(dest / "photonforge.db")
    assert conn.execute("SELECT x FROM t").fetchone()[0] == 1
    conn.close()


def test_timestamp_is_filename_safe_and_sortable():
    ts = snapshot_timestamp()
    assert ":" not in ts
    assert len(ts) == 19


def test_rotate_keeps_newest_n(tmp_path):
    snaproot = tmp_path / ".photon-snapshots"
    snaproot.mkdir()
    for name in ["2026-07-01T00-00-00", "2026-07-02T00-00-00",
                 "2026-07-03T00-00-00", "2026-07-04T00-00-00"]:
        (snaproot / name).mkdir()
    deleted = rotate_snapshots(snaproot, keep=2)
    assert sorted(p.name for p in snaproot.iterdir()) == [
        "2026-07-03T00-00-00", "2026-07-04T00-00-00"]
    assert len(deleted) == 2


def test_rotate_keep_zero_is_a_noop(tmp_path):
    snaproot = tmp_path / "s"
    (snaproot / "2026-07-01T00-00-00").mkdir(parents=True)
    assert rotate_snapshots(snaproot, keep=0) == []
    assert len(list(snaproot.iterdir())) == 1


def test_rotate_missing_root_is_a_noop(tmp_path):
    assert rotate_snapshots(tmp_path / "nope", keep=3) == []


def test_rotate_never_deletes_the_protected_snapshot(tmp_path):
    """The snapshot just written survives even if it sorts oldest."""
    snaproot = tmp_path / "s"
    snaproot.mkdir()
    for name in ("2026-07-01T00-00-00", "2026-07-02T00-00-00", "2026-07-03T00-00-00"):
        (snaproot / name).mkdir()
    oldest = snaproot / "2026-07-01T00-00-00"
    deleted = rotate_snapshots(snaproot, keep=1, protect=oldest)
    assert oldest.exists()
    assert oldest not in deleted


def test_rotate_ignores_loose_files(tmp_path):
    snaproot = tmp_path / "s"
    snaproot.mkdir()
    (snaproot / "2026-07-01T00-00-00").mkdir()
    (snaproot / "README.txt").write_text("not a snapshot")
    assert rotate_snapshots(snaproot, keep=1) == []
    assert (snaproot / "README.txt").exists()
