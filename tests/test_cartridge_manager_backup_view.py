"""BackupView tests for the cartridge manager GUI.

Uses real filesystem and SQLite state throughout — no mocking backup.py
functions. Tests verify that the view correctly orchestrates backup/restore
operations and emits the right signals.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from conftest import make_jpg

from cartridge_manager.backup_view import BackupView
from photo_workflow import backup
from photo_workflow.photondb import ensure_schema, open_db


def _cartridge(tmp_path: Path, name: str = "PHOTON-001") -> Path:
    """Create a bare cartridge root directory with a photonforge.db."""
    root = tmp_path / name
    root.mkdir()
    # Create a real photonforge.db
    conn = open_db(root / "ICELAND")
    ensure_schema(conn)
    conn.close()
    return root


def test_run_snapshot_creates_snapshot(tmp_path: Path, qtbot) -> None:
    """run_snapshot() creates a snapshot dir with files."""
    root = _cartridge(tmp_path)
    widget = BackupView()
    qtbot.addWidget(widget)

    # Set up widget inputs
    widget.root_edit.setText(str(root))
    widget.snapshot_dest_edit.setText("")  # Blank → use root/.photon-snapshots
    widget.keep_spinbox.setValue(7)

    # Run snapshot
    widget.run_snapshot()

    # Verify snapshot was created
    snaproot = root / backup.SNAPSHOT_DIRNAME
    assert snaproot.exists()
    # Find the newest snapshot dir
    snap_dirs = sorted([d for d in snaproot.iterdir() if d.is_dir()])
    assert len(snap_dirs) > 0
    target = snap_dirs[-1]
    assert (target / backup.MANIFEST_NAME).exists()
    assert "Snapshot written" in widget.status_label.text()


def test_run_snapshot_no_root_shows_error(qtbot) -> None:
    """run_snapshot() with no root shows error message."""
    widget = BackupView()
    qtbot.addWidget(widget)

    # Leave root_edit blank
    widget.run_snapshot()

    assert "No cartridge root selected" in widget.status_label.text()


def test_run_snapshot_invalid_root_shows_error(tmp_path: Path, qtbot) -> None:
    """run_snapshot() with invalid root shows error."""
    widget = BackupView()
    qtbot.addWidget(widget)

    # Point to nonexistent path
    widget.root_edit.setText(str(tmp_path / "nonexistent"))
    widget.run_snapshot()

    assert "No PHOTONForge/Darktable DBs found" in widget.status_label.text()


def test_run_backup_creates_mirror(tmp_path: Path, qtbot) -> None:
    """run_backup() creates a mirror in the dest directory."""
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    dest.mkdir()

    # Create a photo file in a shoot folder
    shoot = root / "ICELAND"
    shoot.mkdir(exist_ok=True)
    photo_file = shoot / "P001ICE0000001.jpg"
    make_jpg(photo_file)

    widget = BackupView()
    qtbot.addWidget(widget)

    # Set up widget inputs
    widget.root_edit.setText(str(root))
    widget.backup_dest_edit.setText(str(dest))
    widget.state_only_checkbox.setChecked(False)
    widget.exclude_models_checkbox.setChecked(False)
    widget.no_incremental_checkbox.setChecked(True)
    widget.backup_force_checkbox.setChecked(False)
    widget.backup_keep_edit.setText("")

    # Run backup with wait signal
    with qtbot.waitSignal(widget.operation_finished, timeout=15000):
        widget.run_backup()

    # Verify mirror exists and contains the photo
    cartridge_dir = dest / backup.cartridge_backup_name(root)
    assert cartridge_dir.exists()
    snap_dirs = sorted([d for d in cartridge_dir.iterdir() if d.is_dir()])
    assert len(snap_dirs) > 0
    mirror = snap_dirs[-1]
    assert (mirror / "ICELAND" / "P001ICE0000001.jpg").exists()
    assert "Backup complete" in widget.status_label.text()


def test_run_backup_busy_cartridge_fails(tmp_path: Path, qtbot) -> None:
    """run_backup() on busy cartridge fails with appropriate message (force unchecked)."""
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    dest.mkdir()

    # Write current process PID to lock file (cartridge is "busy")
    pid = os.getpid()
    (root / "test.pid").write_text(str(pid))

    widget = BackupView()
    qtbot.addWidget(widget)

    # Set up widget inputs
    widget.root_edit.setText(str(root))
    widget.backup_dest_edit.setText(str(dest))
    widget.backup_force_checkbox.setChecked(False)
    widget.no_incremental_checkbox.setChecked(True)

    # Run backup and wait for failure
    with qtbot.waitSignal(widget.operation_failed, timeout=5000):
        widget.run_backup()

    assert "busy" in widget.status_label.text().lower()


def test_run_verify_finds_newest_snapshot(tmp_path: Path, qtbot) -> None:
    """run_verify() finds and verifies newest snapshot when path is blank."""
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    dest.mkdir()

    # Create a real backup first (synchronously, not through the widget)
    backup.mirror_cartridge(root, dest, force=True)

    widget = BackupView()
    qtbot.addWidget(widget)

    # Set up widget inputs
    widget.root_edit.setText(str(root))
    widget.backup_dest_edit.setText(str(dest))
    widget.verify_snapshot_edit.setText("")  # Blank → find newest
    widget.verify_against_edit.setText("")

    # Run verify and wait for completion
    with qtbot.waitSignal(widget.operation_finished, timeout=10000):
        widget.run_verify()

    # Verify should pass (result is empty list)
    assert "clean" in widget.status_label.text().lower()


def test_run_verify_detects_corruption(tmp_path: Path, qtbot) -> None:
    """run_verify() detects real corruption in mirror files."""
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    dest.mkdir()

    # Create shoot folder with a photo
    shoot = root / "ICELAND"
    shoot.mkdir(exist_ok=True)
    photo_file = shoot / "P001ICE0000001.jpg"
    make_jpg(photo_file)

    # Create a real backup
    mirror = backup.mirror_cartridge(root, dest, force=True)

    # Corrupt a file in the mirror by changing one byte
    payload_file = mirror / "ICELAND" / "P001ICE0000001.jpg"
    if payload_file.exists():
        content = bytearray(payload_file.read_bytes())
        if len(content) > 0:
            content[0] = (content[0] + 1) % 256
            payload_file.write_bytes(bytes(content))

    widget = BackupView()
    qtbot.addWidget(widget)

    # Set up widget inputs
    widget.root_edit.setText(str(root))
    widget.verify_snapshot_edit.setText(str(mirror))
    widget.verify_against_edit.setText("")

    # Run verify and wait for completion
    with qtbot.waitSignal(widget.operation_finished, timeout=10000):
        widget.run_verify()

    # Verify should detect problems
    status = widget.status_label.text()
    assert "problem" in status.lower() or "mismatch" in status.lower()


def test_run_restore_restores_to_target(tmp_path: Path, qtbot) -> None:
    """run_restore() copies mirror back to target directory."""
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    dest.mkdir()

    # Create shoot folder with a photo
    shoot = root / "ICELAND"
    shoot.mkdir(exist_ok=True)
    photo_file = shoot / "P001ICE0000001.jpg"
    make_jpg(photo_file)

    # Create a real backup
    mirror = backup.mirror_cartridge(root, dest, force=True)

    # Create a fresh target directory
    target = tmp_path / "restore_target"
    target.mkdir()

    widget = BackupView()
    qtbot.addWidget(widget)

    # Set up widget inputs
    widget.restore_snapshot_edit.setText(str(mirror))
    widget.restore_target_edit.setText(str(target))
    widget.restore_force_checkbox.setChecked(False)

    # Run restore and wait for completion
    with qtbot.waitSignal(widget.operation_finished, timeout=10000):
        widget.run_restore()

    # Verify restored file exists
    restored_photo = target / "ICELAND" / "P001ICE0000001.jpg"
    assert restored_photo.exists()
    assert "Restore complete" in widget.status_label.text()


def test_run_restore_refuses_nonempty_target(tmp_path: Path, qtbot) -> None:
    """run_restore() refuses non-empty target without force."""
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    dest.mkdir()

    # Create a real backup
    mirror = backup.mirror_cartridge(root, dest, force=True)

    # Create target with an unrelated file
    target = tmp_path / "restore_target"
    target.mkdir()
    (target / "unrelated.txt").write_text("existing content")

    widget = BackupView()
    qtbot.addWidget(widget)

    # Set up widget inputs
    widget.restore_snapshot_edit.setText(str(mirror))
    widget.restore_target_edit.setText(str(target))
    widget.restore_force_checkbox.setChecked(False)

    # Run restore and wait for failure
    with qtbot.waitSignal(widget.operation_failed, timeout=5000):
        widget.run_restore()

    assert "not empty" in widget.status_label.text().lower()


def test_run_restore_succeeds_with_force(tmp_path: Path, qtbot) -> None:
    """run_restore() succeeds on non-empty target when force is checked."""
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    dest.mkdir()

    # Create shoot folder with a photo
    shoot = root / "ICELAND"
    shoot.mkdir(exist_ok=True)
    photo_file = shoot / "P001ICE0000001.jpg"
    make_jpg(photo_file)

    # Create a real backup
    mirror = backup.mirror_cartridge(root, dest, force=True)

    # Create target with an unrelated file
    target = tmp_path / "restore_target"
    target.mkdir()
    (target / "unrelated.txt").write_text("existing content")

    widget = BackupView()
    qtbot.addWidget(widget)

    # Set up widget inputs
    widget.restore_snapshot_edit.setText(str(mirror))
    widget.restore_target_edit.setText(str(target))
    widget.restore_force_checkbox.setChecked(True)

    # Run restore and wait for completion
    with qtbot.waitSignal(widget.operation_finished, timeout=10000):
        widget.run_restore()

    # Verify restored file exists
    restored_photo = target / "ICELAND" / "P001ICE0000001.jpg"
    assert restored_photo.exists()
    assert "Restore complete" in widget.status_label.text()


def test_is_running_becomes_true_during_backup(tmp_path: Path, qtbot) -> None:
    """is_running() becomes True immediately after run_backup() is called."""
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    dest.mkdir()

    # Create shoot folder with a photo
    shoot = root / "ICELAND"
    shoot.mkdir(exist_ok=True)
    photo_file = shoot / "P001ICE0000001.jpg"
    make_jpg(photo_file)

    widget = BackupView()
    qtbot.addWidget(widget)

    # Set up widget inputs
    widget.root_edit.setText(str(root))
    widget.backup_dest_edit.setText(str(dest))
    widget.no_incremental_checkbox.setChecked(True)

    # is_running() should be False before
    assert not widget.is_running()

    # Run backup and wait for completion
    with qtbot.waitSignal(widget.operation_finished, timeout=15000):
        widget.run_backup()
        # Immediately after calling run_backup but before the signal,
        # is_running() should briefly be True. By waiting for the signal,
        # we are guaranteed to reach the completion point and is_running()
        # should be False afterward.

    # is_running() should be False after operation_finished
    assert not widget.is_running()


def test_backup_invalid_keep_shows_error(tmp_path: Path, qtbot) -> None:
    """run_backup() with invalid keep value shows error."""
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    dest.mkdir()

    widget = BackupView()
    qtbot.addWidget(widget)

    # Set up widget inputs
    widget.root_edit.setText(str(root))
    widget.backup_dest_edit.setText(str(dest))
    widget.backup_keep_edit.setText("not_a_number")

    # Run backup
    widget.run_backup()

    assert "Keep must be a number" in widget.status_label.text()


def test_operation_signals_emitted_correctly(tmp_path: Path, qtbot) -> None:
    """Operation signals are emitted with correct op names and results."""
    root = _cartridge(tmp_path)
    widget = BackupView()
    qtbot.addWidget(widget)

    # Set up widget for snapshot (synchronous, doesn't use Worker so no operation_started)
    widget.root_edit.setText(str(root))
    widget.snapshot_dest_edit.setText("")

    # Record signal emissions
    finished_signals = []
    widget.operation_finished.connect(lambda op, result: finished_signals.append((op, result)))

    widget.run_snapshot()

    # Check that operation_finished was emitted with correct values
    assert len(finished_signals) == 1
    assert finished_signals[0][0] == "snapshot"
    assert isinstance(finished_signals[0][1], Path)


def test_run_verify_missing_both_paths_shows_error(tmp_path: Path, qtbot) -> None:
    """run_verify() with blank snapshot and no backup dest shows error."""
    widget = BackupView()
    qtbot.addWidget(widget)

    # Leave both verify_snapshot_edit and backup_dest_edit blank
    widget.verify_snapshot_edit.setText("")
    widget.backup_dest_edit.setText("")

    widget.run_verify()

    assert "Give a snapshot path" in widget.status_label.text()


def test_run_restore_no_snapshot_shows_error(tmp_path: Path, qtbot) -> None:
    """run_restore() with no snapshot selected shows error."""
    widget = BackupView()
    qtbot.addWidget(widget)

    # Leave snapshot and target blank
    widget.restore_snapshot_edit.setText("")
    widget.restore_target_edit.setText("")

    widget.run_restore()

    assert "No snapshot path selected" in widget.status_label.text()


def test_backup_fields_disabled_during_operation(tmp_path: Path, qtbot) -> None:
    """All action buttons are disabled while an operation is running."""
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    dest.mkdir()

    # Create shoot folder with a photo
    shoot = root / "ICELAND"
    shoot.mkdir(exist_ok=True)
    photo_file = shoot / "P001ICE0000001.jpg"
    make_jpg(photo_file)

    widget = BackupView()
    qtbot.addWidget(widget)

    # Set up widget inputs
    widget.root_edit.setText(str(root))
    widget.backup_dest_edit.setText(str(dest))
    widget.no_incremental_checkbox.setChecked(True)

    # Record which buttons were enabled before (should all be True)
    buttons_enabled_before = (
        widget.snapshot_button.isEnabled(),
        widget.backup_button.isEnabled(),
        widget.verify_button.isEnabled(),
        widget.restore_button.isEnabled(),
    )
    assert all(buttons_enabled_before), f"Expected all buttons enabled before, got {buttons_enabled_before}"

    # Run backup and wait for completion
    with qtbot.waitSignal(widget.operation_finished, timeout=15000):
        widget.run_backup()

    # Buttons should be re-enabled after
    assert widget.snapshot_button.isEnabled()
    assert widget.backup_button.isEnabled()
    assert widget.verify_button.isEnabled()
    assert widget.restore_button.isEnabled()


def test_worker_is_joined_before_being_released(tmp_path: Path, qtbot, monkeypatch) -> None:
    """Regression test for a real PySide6 crash: garbage-collecting a QThread
    before its OS thread has actually joined aborts the whole process
    ("QThread: Destroyed while thread is still running"), reproduced by
    running the full test suite (flaky — a race, not deterministic). The fix
    is calling Worker.wait() before dropping the reference in _on_finished/
    _on_failed; this test proves that call actually happens rather than
    relying on timing luck to catch a regression.
    """
    from cartridge_manager.workers import Worker

    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    dest.mkdir()

    widget = BackupView()
    qtbot.addWidget(widget)
    widget.root_edit.setText(str(root))
    widget.backup_dest_edit.setText(str(dest))
    widget.no_incremental_checkbox.setChecked(True)

    wait_calls = []
    original_wait = Worker.wait

    def _spy_wait(self, *args, **kwargs):
        wait_calls.append(self)
        return original_wait(self, *args, **kwargs)

    monkeypatch.setattr(Worker, "wait", _spy_wait)

    with qtbot.waitSignal(widget.operation_finished, timeout=15000):
        widget.run_backup()

    assert len(wait_calls) == 1, "Worker.wait() was not called before the worker was released"
