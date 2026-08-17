"""Busy-guard: refuse to back up (or migrate) a cartridge that is mid-pipeline.

Shared with the portable-drive plan's migrate-fs, which must not reformat a
drive that something is still writing to.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from photo_workflow.backup import CartridgeBusy, assert_cartridge_idle, cartridge_busy_reason


def _cart(tmp_path):
    root = tmp_path / "cart"
    root.mkdir()
    conn = sqlite3.connect(root / "photonforge.db")
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()
    return root


def test_idle_cartridge_passes(tmp_path):
    root = _cart(tmp_path)
    assert cartridge_busy_reason(root) is None
    assert_cartridge_idle(root)          # must not raise


def test_live_pid_file_blocks(tmp_path):
    root = _cart(tmp_path)
    (root / ".photonforge.pid").write_text(str(os.getpid()))
    reason = cartridge_busy_reason(root)
    assert reason is not None
    assert "pid" in reason.lower()
    with pytest.raises(CartridgeBusy):
        assert_cartridge_idle(root)


def test_stale_pid_file_does_not_block(tmp_path):
    """A crashed run leaves a pid file behind; it must not strand the user."""
    root = _cart(tmp_path)
    (root / ".photonforge.pid").write_text("999999")     # not a live PID
    assert cartridge_busy_reason(root) is None


def test_unparseable_pid_file_does_not_block(tmp_path):
    root = _cart(tmp_path)
    (root / ".photonforge.pid").write_text("not-a-pid")
    assert cartridge_busy_reason(root) is None


def test_write_locked_db_blocks(tmp_path):
    root = _cart(tmp_path)
    holder = sqlite3.connect(root / "photonforge.db")
    holder.execute("BEGIN IMMEDIATE")
    try:
        reason = cartridge_busy_reason(root)
        assert reason is not None
        assert "photonforge.db" in reason
        with pytest.raises(CartridgeBusy):
            assert_cartridge_idle(root)
        assert_cartridge_idle(root, force=True)          # --force overrides
    finally:
        holder.rollback()
        holder.close()


def test_guard_on_cartridge_with_no_dbs_is_idle(tmp_path):
    """Nothing to lock is not the same as busy."""
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cartridge_busy_reason(empty) is None
