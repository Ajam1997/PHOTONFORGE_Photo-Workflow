"""GUI tests for the Provision view (make-portable assembly)."""

from __future__ import annotations

from pathlib import Path

import pytest

# Skip this entire module if PySide6 is not installed
pytest.importorskip("PySide6")

from cartridge_manager.provision_view import ProvisionView
from photo_workflow import volume

# Paths to real repo directories
REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "deploy" / "portable"
LUA_DIR = REPO_ROOT / "lua" / "photonforge"


def _mount_photon_cartridge(tmp_path: Path, monkeypatch, label: str = "PHOTON-001") -> Path:
    """Create a mock PHOTON-labeled cartridge directory."""
    drive = tmp_path / "drive"
    drive.mkdir()
    monkeypatch.setattr(volume, "get_volume_label", lambda _p: label)
    return drive


def test_provision_view_initial_state(qtbot) -> None:
    """ProvisionView initializes with expected UI state."""
    widget = ProvisionView()
    qtbot.addWidget(widget)

    # Checkboxes should be checked by default
    assert widget.win_checkbox.isChecked()
    assert widget.linux_checkbox.isChecked()
    # Offline should be unchecked by default
    assert not widget.offline_checkbox.isChecked()
    # Build button should be enabled
    assert widget.build_button.isEnabled()
    # Progress bar should be hidden
    assert not widget.progress_bar.isVisible()
    # Status label should be empty or default
    assert isinstance(widget.status_label.text(), str)


def test_validation_empty_drive_field(qtbot) -> None:
    """run_build() with empty drive field shows error."""
    widget = ProvisionView()
    qtbot.addWidget(widget)

    # Leave drive blank
    widget.run_build()

    assert "Drive path is required" in widget.status_label.text()
    # Should not start a worker
    assert not widget.is_running()


def test_validation_nonexistent_drive_path(tmp_path: Path, qtbot) -> None:
    """run_build() with nonexistent drive path shows error."""
    widget = ProvisionView()
    qtbot.addWidget(widget)

    widget.drive_edit.setText(str(tmp_path / "nonexistent"))
    widget.run_build()

    assert "does not exist" in widget.status_label.text()
    assert not widget.is_running()


def test_validation_no_os_selected(tmp_path: Path, qtbot) -> None:
    """run_build() with both OS checkboxes unchecked shows error."""
    widget = ProvisionView()
    qtbot.addWidget(widget)

    drive = tmp_path / "drive"
    drive.mkdir()
    widget.drive_edit.setText(str(drive))
    widget.win_checkbox.setChecked(False)
    widget.linux_checkbox.setChecked(False)

    widget.run_build()

    assert "Select at least one OS" in widget.status_label.text()
    assert not widget.is_running()


def test_validation_missing_templates_dir(tmp_path: Path, qtbot) -> None:
    """run_build() with empty templates dir shows error."""
    widget = ProvisionView()
    qtbot.addWidget(widget)

    drive = tmp_path / "drive"
    drive.mkdir()
    widget.drive_edit.setText(str(drive))
    # Leave templates_dir_edit blank
    widget.lua_src_edit.setText(str(tmp_path / "lua"))

    widget.run_build()

    assert "Templates dir is required" in widget.status_label.text()
    assert not widget.is_running()


def test_validation_missing_lua_src(tmp_path: Path, qtbot) -> None:
    """run_build() with empty lua_src shows error."""
    widget = ProvisionView()
    qtbot.addWidget(widget)

    drive = tmp_path / "drive"
    drive.mkdir()
    widget.drive_edit.setText(str(drive))
    widget.templates_dir_edit.setText(str(tmp_path / "templates"))
    # Leave lua_src_edit blank

    widget.run_build()

    assert "Lua source dir is required" in widget.status_label.text()
    assert not widget.is_running()


def test_build_real_manifest_less_drive(tmp_path: Path, monkeypatch, qtbot) -> None:
    """Full build test: assemble drive without manifest (no Darktable download)."""
    drive = _mount_photon_cartridge(tmp_path, monkeypatch)

    widget = ProvisionView()
    qtbot.addWidget(widget)

    # Set all required fields
    widget.drive_edit.setText(str(drive))
    widget.templates_dir_edit.setText(str(TEMPLATES_DIR))
    widget.lua_src_edit.setText(str(LUA_DIR))
    # Leave manifest blank (no Darktable download)
    widget.win_checkbox.setChecked(True)
    widget.linux_checkbox.setChecked(False)  # Don't build Linux to avoid WSL dispatch

    # Track finished signal
    finished_signals = []
    widget.build_finished.connect(
        lambda result, linux_via_wsl: finished_signals.append((result, linux_via_wsl))
    )

    # Run build and wait for completion
    with qtbot.waitSignal(widget.build_finished, timeout=15000):
        widget.run_build()

    # Verify completion
    assert len(finished_signals) == 1
    result, linux_via_wsl = finished_signals[0]
    assert result is not None
    assert not linux_via_wsl
    # Real files should be on drive
    assert (drive / "dt-config" / "lua" / "photonforge" / "main.lua").exists()
    assert (drive / "!START_PHOTONForge.sh").exists()
    assert (drive / "!README.txt").exists()
    assert (drive / "autorun.inf").exists()
    # Check status message
    assert "Build complete" in widget.status_label.text()
    # Build button should be re-enabled
    assert widget.build_button.isEnabled()


def test_build_refuses_non_photon_drive(tmp_path: Path, monkeypatch, qtbot) -> None:
    """build fails if drive volume label doesn't start with PHOTON."""
    # Create a drive with non-PHOTON label
    drive = tmp_path / "drive"
    drive.mkdir()
    monkeypatch.setattr(volume, "get_volume_label", lambda _p: "OTHERLABEL")

    widget = ProvisionView()
    qtbot.addWidget(widget)

    widget.drive_edit.setText(str(drive))
    widget.templates_dir_edit.setText(str(TEMPLATES_DIR))
    widget.lua_src_edit.setText(str(LUA_DIR))

    # Track failed signal
    failed_signals = []
    widget.build_failed.connect(lambda msg: failed_signals.append(msg))

    # Run build and wait for failure
    with qtbot.waitSignal(widget.build_failed, timeout=5000):
        widget.run_build()

    assert len(failed_signals) == 1
    assert "does not look like a PHOTON cartridge" in failed_signals[0]
    assert "Build failed" in widget.status_label.text()


def test_build_checks_cart_id_if_provided(tmp_path: Path, monkeypatch, qtbot) -> None:
    """build fails if explicit cart_id doesn't match volume label."""
    drive = _mount_photon_cartridge(tmp_path, monkeypatch, label="PHOTON-002")

    widget = ProvisionView()
    qtbot.addWidget(widget)

    widget.drive_edit.setText(str(drive))
    widget.templates_dir_edit.setText(str(TEMPLATES_DIR))
    widget.lua_src_edit.setText(str(LUA_DIR))
    widget.cart_id_edit.setText("001")  # Wrong ID

    # Track failed signal
    failed_signals = []
    widget.build_failed.connect(lambda msg: failed_signals.append(msg))

    # Run build and wait for failure
    with qtbot.waitSignal(widget.build_failed, timeout=5000):
        widget.run_build()

    assert len(failed_signals) == 1
    assert "does not match" in failed_signals[0]


def test_build_accepts_matching_cart_id(tmp_path: Path, monkeypatch, qtbot) -> None:
    """build succeeds when explicit cart_id matches volume label."""
    drive = _mount_photon_cartridge(tmp_path, monkeypatch, label="PHOTON-003")

    widget = ProvisionView()
    qtbot.addWidget(widget)

    widget.drive_edit.setText(str(drive))
    widget.templates_dir_edit.setText(str(TEMPLATES_DIR))
    widget.lua_src_edit.setText(str(LUA_DIR))
    widget.cart_id_edit.setText("003")  # Correct ID
    widget.win_checkbox.setChecked(True)
    widget.linux_checkbox.setChecked(False)

    # Track finished signal
    finished_signals = []
    widget.build_finished.connect(
        lambda result, linux_via_wsl: finished_signals.append((result, linux_via_wsl))
    )

    # Run build and wait for completion
    with qtbot.waitSignal(widget.build_finished, timeout=15000):
        widget.run_build()

    assert len(finished_signals) == 1
    assert "Build complete" in widget.status_label.text()


def test_build_progress_updates_status_label(tmp_path: Path, monkeypatch, qtbot) -> None:
    """Progress signals update the status label."""
    drive = _mount_photon_cartridge(tmp_path, monkeypatch)

    widget = ProvisionView()
    qtbot.addWidget(widget)

    widget.drive_edit.setText(str(drive))
    widget.templates_dir_edit.setText(str(TEMPLATES_DIR))
    widget.lua_src_edit.setText(str(LUA_DIR))
    widget.win_checkbox.setChecked(True)
    widget.linux_checkbox.setChecked(False)

    # Run build
    with qtbot.waitSignal(widget.build_finished, timeout=15000):
        widget.run_build()

    # Status label should have been updated with progress or final message
    # (the exact content depends on what run_make_portable reports)
    status = widget.status_label.text()
    assert status  # Should not be empty
    assert "Build complete" in status or "[" in status


def test_build_button_disabled_during_build(tmp_path: Path, monkeypatch, qtbot) -> None:
    """Build button is disabled while build is running."""
    drive = _mount_photon_cartridge(tmp_path, monkeypatch)

    widget = ProvisionView()
    qtbot.addWidget(widget)

    widget.drive_edit.setText(str(drive))
    widget.templates_dir_edit.setText(str(TEMPLATES_DIR))
    widget.lua_src_edit.setText(str(LUA_DIR))
    widget.win_checkbox.setChecked(True)
    widget.linux_checkbox.setChecked(False)

    # Start build (don't wait for completion yet)
    widget.run_build()

    # Button should be disabled while running
    assert not widget.build_button.isEnabled()
    assert widget.is_running()

    # Wait for completion
    with qtbot.waitSignal(widget.build_finished, timeout=15000):
        pass

    # Button should be re-enabled after completion
    assert widget.build_button.isEnabled()
    assert not widget.is_running()


def test_build_progress_bar_shown_during_build(tmp_path: Path, monkeypatch, qtbot) -> None:
    """Progress bar is hidden after build completes."""
    drive = _mount_photon_cartridge(tmp_path, monkeypatch)

    widget = ProvisionView()
    qtbot.addWidget(widget)

    assert not widget.progress_bar.isVisible()

    widget.drive_edit.setText(str(drive))
    widget.templates_dir_edit.setText(str(TEMPLATES_DIR))
    widget.lua_src_edit.setText(str(LUA_DIR))
    widget.win_checkbox.setChecked(True)
    widget.linux_checkbox.setChecked(False)

    widget.run_build()

    # Wait for completion
    with qtbot.waitSignal(widget.build_finished, timeout=15000):
        pass

    # Progress bar should be hidden after completion
    assert not widget.progress_bar.isVisible()


def test_build_signals_emitted_correctly(tmp_path: Path, monkeypatch, qtbot) -> None:
    """build_started and build_finished signals are emitted in order."""
    drive = _mount_photon_cartridge(tmp_path, monkeypatch)

    widget = ProvisionView()
    qtbot.addWidget(widget)

    signal_order = []
    widget.build_started.connect(lambda: signal_order.append("started"))
    widget.build_finished.connect(lambda *args: signal_order.append("finished"))

    widget.drive_edit.setText(str(drive))
    widget.templates_dir_edit.setText(str(TEMPLATES_DIR))
    widget.lua_src_edit.setText(str(LUA_DIR))
    widget.win_checkbox.setChecked(True)
    widget.linux_checkbox.setChecked(False)

    with qtbot.waitSignal(widget.build_finished, timeout=15000):
        widget.run_build()

    assert signal_order == ["started", "finished"]


def test_build_failed_signal_emitted_on_error(tmp_path: Path, monkeypatch, qtbot) -> None:
    """build_failed signal is emitted when build fails."""
    drive = _mount_photon_cartridge(tmp_path, monkeypatch)

    widget = ProvisionView()
    qtbot.addWidget(widget)

    signal_order = []
    widget.build_started.connect(lambda: signal_order.append("started"))
    widget.build_failed.connect(lambda msg: signal_order.append("failed"))

    widget.drive_edit.setText(str(drive))
    widget.templates_dir_edit.setText(str(TEMPLATES_DIR))
    widget.lua_src_edit.setText(str(LUA_DIR / "nonexistent"))  # Invalid Lua dir
    widget.win_checkbox.setChecked(True)
    widget.linux_checkbox.setChecked(False)

    with qtbot.waitSignal(widget.build_failed, timeout=5000):
        widget.run_build()

    assert signal_order == ["started", "failed"]


def test_is_running_returns_false_when_idle(qtbot) -> None:
    """is_running() returns False when no build is active."""
    widget = ProvisionView()
    qtbot.addWidget(widget)

    assert not widget.is_running()


def test_guard_prevents_concurrent_builds(tmp_path: Path, monkeypatch, qtbot) -> None:
    """Calling run_build() while one is running is a no-op (guard returns early)."""
    drive = _mount_photon_cartridge(tmp_path, monkeypatch)

    widget = ProvisionView()
    qtbot.addWidget(widget)

    widget.drive_edit.setText(str(drive))
    widget.templates_dir_edit.setText(str(TEMPLATES_DIR))
    widget.lua_src_edit.setText(str(LUA_DIR))
    widget.win_checkbox.setChecked(True)
    widget.linux_checkbox.setChecked(False)

    # Start a build
    widget.run_build()
    assert widget.is_running()

    # Try to start another build while the first is running
    initial_worker = widget._worker
    widget.run_build()

    # Worker should still be the same (no new build started)
    assert widget._worker is initial_worker

    # Wait for completion
    with qtbot.waitSignal(widget.build_finished, timeout=15000):
        pass


def test_optional_fields_can_be_blank(tmp_path: Path, monkeypatch, qtbot) -> None:
    """Optional fields (manifest, models_src, cli_src) can be left blank."""
    drive = _mount_photon_cartridge(tmp_path, monkeypatch)

    widget = ProvisionView()
    qtbot.addWidget(widget)

    widget.drive_edit.setText(str(drive))
    widget.templates_dir_edit.setText(str(TEMPLATES_DIR))
    widget.lua_src_edit.setText(str(LUA_DIR))
    # Leave manifest_edit, models_src_edit, cli_src_edit blank
    widget.win_checkbox.setChecked(True)
    widget.linux_checkbox.setChecked(False)

    finished_signals = []
    widget.build_finished.connect(
        lambda result, linux_via_wsl: finished_signals.append((result, linux_via_wsl))
    )

    with qtbot.waitSignal(widget.build_finished, timeout=15000):
        widget.run_build()

    assert len(finished_signals) == 1
    assert "Build complete" in widget.status_label.text()
