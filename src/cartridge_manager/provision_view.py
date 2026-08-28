"""Provision view for assembling portable drives."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from photo_workflow import cartridge as cartridge_mod

from .workers import Worker


class ProvisionView(QWidget):
    """Assemble a self-contained portable drive onto an already-provisioned cartridge."""

    build_started = Signal()
    build_finished = Signal(object, bool)   # (PortableBuildResult, linux_via_wsl)
    build_failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._worker: Worker | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the UI: drive path, OS selection, config paths, build button."""
        layout = QVBoxLayout(self)

        # Drive selection
        drive_layout = QHBoxLayout()
        drive_layout.addWidget(QLabel("Drive Path:"))
        self.drive_edit = QLineEdit()
        self.drive_edit.setPlaceholderText("Already-provisioned PHOTON cartridge mount path")
        drive_layout.addWidget(self.drive_edit, 1)
        drive_browse = QPushButton("Browse…")
        drive_browse.clicked.connect(self._on_drive_browse)
        drive_layout.addWidget(drive_browse)
        layout.addLayout(drive_layout)

        # OS selection
        os_layout = QHBoxLayout()
        os_layout.addWidget(QLabel("Build for:"))
        self.win_checkbox = QCheckBox("Windows")
        self.win_checkbox.setChecked(True)
        os_layout.addWidget(self.win_checkbox)
        self.linux_checkbox = QCheckBox("Linux")
        self.linux_checkbox.setChecked(True)
        os_layout.addWidget(self.linux_checkbox)
        os_layout.addStretch()
        layout.addLayout(os_layout)

        # Manifest
        manifest_layout = QHBoxLayout()
        manifest_layout.addWidget(QLabel("Manifest (optional):"))
        self.manifest_edit = QLineEdit()
        self.manifest_edit.setPlaceholderText(
            "config/portable-manifest.yml (skip for no Darktable)"
        )
        manifest_layout.addWidget(self.manifest_edit, 1)
        manifest_browse = QPushButton("Browse…")
        manifest_browse.clicked.connect(self._on_manifest_browse)
        manifest_layout.addWidget(manifest_browse)
        layout.addLayout(manifest_layout)

        # Templates dir
        templates_layout = QHBoxLayout()
        templates_layout.addWidget(QLabel("Templates Dir:"))
        self.templates_dir_edit = QLineEdit()
        self.templates_dir_edit.setPlaceholderText("deploy/portable")
        templates_layout.addWidget(self.templates_dir_edit, 1)
        templates_browse = QPushButton("Browse…")
        templates_browse.clicked.connect(self._on_templates_dir_browse)
        templates_layout.addWidget(templates_browse)
        layout.addLayout(templates_layout)

        # Lua src
        lua_src_layout = QHBoxLayout()
        lua_src_layout.addWidget(QLabel("Lua Source Dir:"))
        self.lua_src_edit = QLineEdit()
        self.lua_src_edit.setPlaceholderText("lua/photonforge")
        lua_src_layout.addWidget(self.lua_src_edit, 1)
        lua_src_browse = QPushButton("Browse…")
        lua_src_browse.clicked.connect(self._on_lua_src_browse)
        lua_src_layout.addWidget(lua_src_browse)
        layout.addLayout(lua_src_layout)

        # Models src (optional)
        models_src_layout = QHBoxLayout()
        models_src_layout.addWidget(QLabel("Models Source (optional):"))
        self.models_src_edit = QLineEdit()
        self.models_src_edit.setPlaceholderText("models/")
        models_src_layout.addWidget(self.models_src_edit, 1)
        models_src_browse = QPushButton("Browse…")
        models_src_browse.clicked.connect(self._on_models_src_browse)
        models_src_layout.addWidget(models_src_browse)
        layout.addLayout(models_src_layout)

        # CLI src (optional)
        cli_src_layout = QHBoxLayout()
        cli_src_layout.addWidget(QLabel("CLI Source (optional):"))
        self.cli_src_edit = QLineEdit()
        self.cli_src_edit.setPlaceholderText("runtime/")
        cli_src_layout.addWidget(self.cli_src_edit, 1)
        cli_src_browse = QPushButton("Browse…")
        cli_src_browse.clicked.connect(self._on_cli_src_browse)
        cli_src_layout.addWidget(cli_src_browse)
        layout.addLayout(cli_src_layout)

        # Cache dir
        cache_dir_layout = QHBoxLayout()
        cache_dir_layout.addWidget(QLabel("Cache Dir (required if manifest given):"))
        self.cache_dir_edit = QLineEdit()
        self.cache_dir_edit.setPlaceholderText("Download cache for Darktable archives")
        cache_dir_layout.addWidget(self.cache_dir_edit, 1)
        cache_dir_browse = QPushButton("Browse…")
        cache_dir_browse.clicked.connect(self._on_cache_dir_browse)
        cache_dir_layout.addWidget(cache_dir_browse)
        layout.addLayout(cache_dir_layout)

        # Options
        options_layout = QHBoxLayout()
        self.offline_checkbox = QCheckBox("Offline (cache-only, error if not cached)")
        options_layout.addWidget(self.offline_checkbox)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        # Cart ID (optional override)
        cart_id_layout = QHBoxLayout()
        cart_id_layout.addWidget(QLabel("Cart ID (optional):"))
        self.cart_id_edit = QLineEdit()
        self.cart_id_edit.setPlaceholderText("auto-detect from volume label")
        self.cart_id_edit.setMaximumWidth(100)
        cart_id_layout.addWidget(self.cart_id_edit)
        cart_id_layout.addStretch()
        layout.addLayout(cart_id_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Build button
        button_layout = QHBoxLayout()
        self.build_button = QPushButton("Build")
        self.build_button.clicked.connect(self.run_build)
        button_layout.addWidget(self.build_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

    def _on_drive_browse(self) -> None:
        """Handle drive path browse button."""
        path = QFileDialog.getExistingDirectory(self, "Select cartridge drive")
        if path:
            self.drive_edit.setText(path)

    def _on_manifest_browse(self) -> None:
        """Handle manifest file browse button."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select portable manifest", "",
            "YAML files (*.yml *.yaml);;All files (*)"
        )
        if path:
            self.manifest_edit.setText(path)

    def _on_templates_dir_browse(self) -> None:
        """Handle templates directory browse button."""
        path = QFileDialog.getExistingDirectory(self, "Select templates directory")
        if path:
            self.templates_dir_edit.setText(path)

    def _on_lua_src_browse(self) -> None:
        """Handle Lua source directory browse button."""
        path = QFileDialog.getExistingDirectory(self, "Select Lua source directory")
        if path:
            self.lua_src_edit.setText(path)

    def _on_models_src_browse(self) -> None:
        """Handle models source directory browse button."""
        path = QFileDialog.getExistingDirectory(self, "Select models source directory")
        if path:
            self.models_src_edit.setText(path)

    def _on_cli_src_browse(self) -> None:
        """Handle CLI source directory browse button."""
        path = QFileDialog.getExistingDirectory(self, "Select CLI source directory")
        if path:
            self.cli_src_edit.setText(path)

    def _on_cache_dir_browse(self) -> None:
        """Handle cache directory browse button."""
        path = QFileDialog.getExistingDirectory(self, "Select cache directory")
        if path:
            self.cache_dir_edit.setText(path)

    def run_build(self) -> None:
        """Execute the portable drive build."""
        # Guard: no worker already running
        if self.is_running():
            return

        # Validate drive path
        drive_text = self.drive_edit.text()
        if not drive_text:
            self.status_label.setText("Drive path is required.")
            return
        drive = Path(drive_text)
        if not drive.is_dir():
            msg = f"Drive path does not exist or is not a directory: {drive_text}"
            self.status_label.setText(msg)
            return

        # Build OS list
        oses = []
        if self.win_checkbox.isChecked():
            oses.append("win")
        if self.linux_checkbox.isChecked():
            oses.append("linux")
        if not oses:
            self.status_label.setText("Select at least one OS to build.")
            return

        # Resolve optional paths
        manifest_text = self.manifest_edit.text()
        manifest = Path(manifest_text) if manifest_text else None

        templates_dir_text = self.templates_dir_edit.text()
        templates_dir = Path(templates_dir_text) if templates_dir_text else None
        if not templates_dir:
            self.status_label.setText("Templates dir is required.")
            return

        lua_src_text = self.lua_src_edit.text()
        lua_src = Path(lua_src_text) if lua_src_text else None
        if not lua_src:
            self.status_label.setText("Lua source dir is required.")
            return

        models_src_text = self.models_src_edit.text()
        models_src = Path(models_src_text) if models_src_text else None

        cli_src_text = self.cli_src_edit.text()
        cli_src = Path(cli_src_text) if cli_src_text else None

        cache_dir_text = self.cache_dir_edit.text()
        cache_dir = Path(cache_dir_text) if cache_dir_text else None

        cart_id_text = self.cart_id_edit.text()
        cart_id = cart_id_text if cart_id_text else None

        # Create worker
        self._worker = Worker(
            cartridge_mod.run_make_portable,
            drive,
            oses,
            manifest=manifest,
            templates_dir=templates_dir,
            lua_src=lua_src,
            models_src=models_src,
            cli_src=cli_src,
            cache_dir=cache_dir,
            offline=self.offline_checkbox.isChecked(),
            cart_id=cart_id,
        )

        # Connect signals
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.signals.failed.connect(self._on_failed)

        # Disable controls
        self.build_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()

        # Emit signal and start worker
        self.build_started.emit()
        self._worker.start()

    def _on_progress(self, index: int, total: int, label: str) -> None:
        """Handle progress signal from worker."""
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(index)
        self.status_label.setText(f"[{index}/{total}] {label}")

    def _on_finished(self, result: object) -> None:
        """Handle successful build completion."""
        # Unpack the tuple: (PortableBuildResult, linux_via_wsl)
        build_result, linux_via_wsl = result

        # Format completion message
        apps_summary = ", ".join(build_result.apps.keys()) if build_result.apps else "none"
        wsl_note = " (Linux via WSL)" if linux_via_wsl else ""
        msg = f"Build complete. Apps: {apps_summary}{wsl_note}. Plugin copied. "
        if build_result.models_copied:
            msg += "Models copied."
        msg += f" See {build_result.readme} for next steps."
        self.status_label.setText(msg)

        # Re-enable controls
        self.build_button.setEnabled(True)
        self.progress_bar.hide()

        # Teardown worker (exact sequence from move_view.py/_on_finished)
        self._worker.settle()
        # break the Worker <-> self reference cycle (signals hold the connected
        # bound slot, whose self is this view, which holds self._worker back) —
        # PySide6's QObject.disconnect() has no zero-arg "disconnect everything"
        # form (that's PyQt-only), so disconnect each bound signal individually.
        self._worker.signals.progress.disconnect()
        self._worker.signals.finished.disconnect()
        self._worker.signals.failed.disconnect()
        self._worker = None

        # Emit signal
        self.build_finished.emit(build_result, linux_via_wsl)

    def _on_failed(self, message: str) -> None:
        """Handle build failure."""
        self.status_label.setText(f"Build failed: {message}")

        # Re-enable controls
        self.build_button.setEnabled(True)
        self.progress_bar.hide()

        # Teardown worker (exact sequence from move_view.py/_on_failed)
        self._worker.settle()
        # break the Worker <-> self reference cycle (signals hold the connected
        # bound slot, whose self is this view, which holds self._worker back) —
        # PySide6's QObject.disconnect() has no zero-arg "disconnect everything"
        # form (that's PyQt-only), so disconnect each bound signal individually.
        self._worker.signals.progress.disconnect()
        self._worker.signals.finished.disconnect()
        self._worker.signals.failed.disconnect()
        self._worker = None

        # Emit signal
        self.build_failed.emit(message)

    def is_running(self) -> bool:
        """Return whether a worker is currently active."""
        return self._worker is not None and self._worker.isRunning()
