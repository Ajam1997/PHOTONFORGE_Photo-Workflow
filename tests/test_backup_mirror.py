"""Tier-2 cartridge mirror: verified plain-tree copies to a second drive.

This is the tier migrate-fs consumes, so the tests pin the properties it
depends on: a browsable tree, a manifest that verifies, and a freshness
predicate that goes stale the moment the cartridge is written again.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from photo_workflow import backup


def _cartridge(tmp_path):
    root = tmp_path / "PHOTON-004"
    (root / "ICELAND").mkdir(parents=True)
    (root / "models").mkdir()
    (root / "dt-config").mkdir()
    conn = sqlite3.connect(root / "photonforge.db")
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()
    (root / "ICELAND" / "DSC0001.ARW").write_bytes(b"rawdata" * 1000)
    (root / "ICELAND" / "DSC0001.xmp").write_text("<x:xmpmeta/>")
    (root / "ICELAND" / "DSC0001__preview.jpg").write_bytes(b"litter")
    (root / "genre_labels.jsonl").write_text('{"a":1}\n')
    (root / "models" / "big.onnx").write_bytes(b"0" * 5000)
    return root


def test_mirror_copies_tree_and_writes_manifest(tmp_path):
    root = _cartridge(tmp_path)
    snap = backup.mirror_cartridge(root, tmp_path / "backups")
    assert (snap / "ICELAND" / "DSC0001.ARW").read_bytes() == b"rawdata" * 1000
    assert (snap / "models" / "big.onnx").exists()        # models INCLUDED by default
    assert not (snap / "ICELAND" / "DSC0001__preview.jpg").exists()   # litter excluded
    conn = sqlite3.connect(snap / "photonforge.db")       # DB via VACUUM INTO
    assert conn.execute("SELECT x FROM t").fetchone()[0] == 42
    conn.close()
    manifest = json.loads((snap / backup.MANIFEST_NAME).read_text())
    assert manifest["kind"] == "mirror"
    assert manifest["state_only"] is False
    assert manifest["totals"]["files"] > 0
    assert manifest["dbs"]["photonforge"]["sha256"]


def test_mirror_nests_under_the_cartridge_label(tmp_path):
    """Two cartridges backed up to one drive must not collide."""
    root = _cartridge(tmp_path)
    snap = backup.mirror_cartridge(root, tmp_path / "backups")
    assert snap.parent.parent == tmp_path / "backups"
    assert snap.parent.name  # a per-cartridge dir sits between dest and the snapshot


def test_mirror_preserves_the_darktable_catalog_path(tmp_path):
    """A mirror must restore onto a *working* cartridge.

    Tier 1 flattens DB names (a rescue copy you hand-inspect), but Tier 2 is
    what migrate-fs copies back after a reformat — flattening dt-config/library.db
    to the root would leave Darktable unable to find its catalog.
    """
    root = _cartridge(tmp_path)
    conn = sqlite3.connect(root / "dt-config" / "library.db")
    conn.execute("CREATE TABLE images (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    snap = backup.mirror_cartridge(root, tmp_path / "backups")
    assert (snap / "dt-config" / "library.db").exists()
    assert not (snap / "library.db").exists()
    assert backup.verify_snapshot(snap) == []

    target = tmp_path / "restored"
    backup.restore_snapshot(snap, target)
    assert (target / "dt-config" / "library.db").exists()
    assert (target / "photonforge.db").exists()      # root-level DBs stay at root


def test_state_only_mirror_also_preserves_catalog_path(tmp_path):
    root = _cartridge(tmp_path)
    conn = sqlite3.connect(root / "dt-config" / "library.db")
    conn.execute("CREATE TABLE images (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    snap = backup.mirror_cartridge(root, tmp_path / "backups", state_only=True)
    assert (snap / "dt-config" / "library.db").exists()


def test_tier1_snapshot_still_flattens(tmp_path):
    """The Tier-1 contract is unchanged: basenames, flat, easy to grab."""
    root = _cartridge(tmp_path)
    conn = sqlite3.connect(root / "dt-config" / "library.db")
    conn.execute("CREATE TABLE images (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    snap = backup.snapshot_databases(root, tmp_path / "t1")
    assert (snap / "library.db").exists()
    assert not (snap / "dt-config").exists()


def test_mirror_verifies_clean(tmp_path):
    snap = backup.mirror_cartridge(_cartridge(tmp_path), tmp_path / "backups")
    assert backup.verify_snapshot(snap) == []


def test_verify_detects_tampering(tmp_path):
    snap = backup.mirror_cartridge(_cartridge(tmp_path), tmp_path / "backups")
    (snap / "ICELAND" / "DSC0001.ARW").write_bytes(b"corrupted")
    problems = backup.verify_snapshot(snap)
    assert problems
    assert any("DSC0001.ARW" in p for p in problems)


def test_verify_detects_deletion(tmp_path):
    snap = backup.mirror_cartridge(_cartridge(tmp_path), tmp_path / "backups")
    (snap / "ICELAND" / "DSC0001.ARW").unlink()
    assert backup.verify_snapshot(snap)


def test_verify_detects_db_tampering(tmp_path):
    snap = backup.mirror_cartridge(_cartridge(tmp_path), tmp_path / "backups")
    (snap / "photonforge.db").write_bytes(b"not a database")
    assert any("photonforge.db" in p for p in backup.verify_snapshot(snap))


def test_state_only_skips_raws_but_keeps_state(tmp_path):
    root = _cartridge(tmp_path)
    snap = backup.mirror_cartridge(root, tmp_path / "backups", state_only=True)
    assert not (snap / "ICELAND" / "DSC0001.ARW").exists()
    assert not (snap / "models" / "big.onnx").exists()
    assert (snap / "ICELAND" / "DSC0001.xmp").exists()
    assert (snap / "genre_labels.jsonl").exists()
    assert (snap / "photonforge.db").exists()
    assert json.loads((snap / backup.MANIFEST_NAME).read_text())["state_only"] is True


def test_exclude_models_flag(tmp_path):
    snap = backup.mirror_cartridge(_cartridge(tmp_path), tmp_path / "backups",
                                   exclude_models=True)
    assert not (snap / "models" / "big.onnx").exists()
    assert (snap / "ICELAND" / "DSC0001.ARW").exists()


def test_nested_snapshot_dir_is_never_mirrored(tmp_path):
    """Tier-1 output lives on the cartridge; mirroring it would nest backups."""
    root = _cartridge(tmp_path)
    (root / backup.SNAPSHOT_DIRNAME / "2026-01-01T00-00-00").mkdir(parents=True)
    (root / backup.SNAPSHOT_DIRNAME / "2026-01-01T00-00-00" / "photonforge.db").write_bytes(b"x")
    snap = backup.mirror_cartridge(root, tmp_path / "backups")
    assert not (snap / backup.SNAPSHOT_DIRNAME).exists()


def test_incremental_links_unchanged_files_when_supported(tmp_path):
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    first = backup.mirror_cartridge(root, dest)
    if not backup.supports_hardlinks(dest):
        pytest.skip("destination filesystem has no hardlinks")
    second = backup.mirror_cartridge(root, dest, link_dest=first)
    raw1, raw2 = first / "ICELAND/DSC0001.ARW", second / "ICELAND/DSC0001.ARW"
    assert raw2.stat().st_ino == raw1.stat().st_ino          # linked, not re-copied
    manifest = json.loads((second / backup.MANIFEST_NAME).read_text())
    assert manifest["totals"]["linked"] > 0
    assert manifest["hardlinks"] is True
    # the DB is re-vacuumed every run, never linked
    assert (second / "photonforge.db").stat().st_ino != (first / "photonforge.db").stat().st_ino


def test_changed_file_is_recopied_not_linked(tmp_path):
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    first = backup.mirror_cartridge(root, dest)
    if not backup.supports_hardlinks(dest):
        pytest.skip("destination filesystem has no hardlinks")
    (root / "ICELAND" / "DSC0001.ARW").write_bytes(b"different content entirely")
    second = backup.mirror_cartridge(root, dest, link_dest=first)
    assert (second / "ICELAND/DSC0001.ARW").read_bytes() == b"different content entirely"
    assert (first / "ICELAND/DSC0001.ARW").read_bytes() == b"rawdata" * 1000   # untouched
    assert backup.verify_snapshot(second) == []


def test_no_hardlink_support_falls_back_to_copy(tmp_path, monkeypatch):
    """exFAT/FAT32 destinations: copy instead, and say so in the manifest."""
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    first = backup.mirror_cartridge(root, dest)
    monkeypatch.setattr(backup, "supports_hardlinks", lambda _dest: False)
    second = backup.mirror_cartridge(root, dest, link_dest=first)
    manifest = json.loads((second / backup.MANIFEST_NAME).read_text())
    assert manifest["hardlinks"] is False
    assert manifest["totals"]["linked"] == 0
    assert (second / "ICELAND/DSC0001.ARW").read_bytes() == b"rawdata" * 1000
    assert backup.verify_snapshot(second) == []


def test_retention_prunes_but_never_the_new_snapshot(tmp_path):
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    snaps = [backup.mirror_cartridge(root, dest, keep=2) for _ in range(4)]
    assert snaps[-1].exists()
    assert len(list(snaps[-1].parent.iterdir())) == 2


def test_mirror_refuses_when_busy(tmp_path):
    root = _cartridge(tmp_path)
    holder = sqlite3.connect(root / "photonforge.db")
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(backup.CartridgeBusy):
            backup.mirror_cartridge(root, tmp_path / "backups")
    finally:
        holder.rollback()
        holder.close()


def test_snapshot_is_fresh_predicate(tmp_path):
    """The gate migrate-fs uses: stale once the cartridge is written again."""
    root = _cartridge(tmp_path)
    snap = backup.mirror_cartridge(root, tmp_path / "backups")
    assert backup.snapshot_is_fresh(snap, root)
    (root / "ICELAND" / "DSC0002.ARW").write_bytes(b"new")
    assert not backup.snapshot_is_fresh(snap, root)


def test_latest_snapshot(tmp_path):
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    assert backup.latest_snapshot(dest) is None
    first = backup.mirror_cartridge(root, dest)
    assert backup.latest_snapshot(dest) == first
    second = backup.mirror_cartridge(root, dest)
    assert backup.latest_snapshot(dest) == second


def test_restore_backup_round_trips(tmp_path):
    root = _cartridge(tmp_path)
    snap = backup.mirror_cartridge(root, tmp_path / "backups")
    target = tmp_path / "restored"
    backup.restore_snapshot(snap, target)
    conn = sqlite3.connect(target / "photonforge.db")
    assert conn.execute("SELECT x FROM t").fetchone()[0] == 42
    conn.close()
    assert (target / "ICELAND" / "DSC0001.ARW").read_bytes() == b"rawdata" * 1000
    assert not list(target.rglob("*.db-wal"))
    assert not (target / backup.MANIFEST_NAME).exists()   # manifest is not payload


def test_restore_refuses_nonempty_target_without_force(tmp_path):
    root = _cartridge(tmp_path)
    snap = backup.mirror_cartridge(root, tmp_path / "backups")
    target = tmp_path / "restored"
    target.mkdir()
    (target / "existing.txt").write_text("do not clobber me")
    with pytest.raises(FileExistsError):
        backup.restore_snapshot(snap, target)
    backup.restore_snapshot(snap, target, force=True)
    assert (target / "photonforge.db").exists()
