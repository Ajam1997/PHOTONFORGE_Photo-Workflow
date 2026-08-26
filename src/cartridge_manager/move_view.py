"""Move view for relocating photos between cartridge folders."""

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
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from photo_workflow import relocate, volume
from photo_workflow.raw_loader import IMAGE_EXTENSIONS

from .workers import Worker


class MoveView(QWidget):
    """Move/relocate photos from one cartridge folder to another."""

    move_started = Signal()
    move_finished = Signal(object)   # the RelocateResult
    move_failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mode = "photos"
        self._source_photos: list[Path] = []
        self._source_folder: Path | None = None
        self._destination: Path | None = None
        self._worker: Worker | None = None
        self._preview_ready = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the UI: mode selection, source/dest, options, preview, move."""
        layout = QVBoxLayout(self)

        # Mode selection
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Mode:"))
        self._photos_radio = QRadioButton("Individual Photos")
        self._photos_radio.setChecked(True)
        self._photos_radio.toggled.connect(self._on_mode_changed)
        mode_layout.addWidget(self._photos_radio)
        self._folder_radio = QRadioButton("Whole Shoot Folder")
        self._folder_radio.toggled.connect(self._on_mode_changed)
        mode_layout.addWidget(self._folder_radio)
        mode_layout.addStretch()
        layout.addLayout(mode_layout)

        # Source selection
        source_layout = QHBoxLayout()
        source_layout.addWidget(QLabel("Source:"))
        self._source_label = QLabel("(none)")
        source_layout.addWidget(self._source_label, 1)
        self._source_button = QPushButton("Choose Source…")
        self._source_button.clicked.connect(self._on_source_clicked)
        source_layout.addWidget(self._source_button)
        layout.addLayout(source_layout)

        # Destination selection
        dest_layout = QHBoxLayout()
        dest_layout.addWidget(QLabel("Destination:"))
        self._dest_label = QLabel("(none)")
        dest_layout.addWidget(self._dest_label, 1)
        self._dest_button = QPushButton("Choose Destination…")
        self._dest_button.clicked.connect(self._on_dest_clicked)
        dest_layout.addWidget(self._dest_button)
        layout.addLayout(dest_layout)

        # Cart ID and Trip Code
        params_layout = QHBoxLayout()
        params_layout.addWidget(QLabel("Cart ID:"))
        self.cart_id_edit = QLineEdit()
        self.cart_id_edit.setPlaceholderText("auto-detect from volume")
        self.cart_id_edit.setMaximumWidth(100)
        params_layout.addWidget(self.cart_id_edit)
        params_layout.addWidget(QLabel("Trip Code:"))
        self.trip_code_edit = QLineEdit()
        self.trip_code_edit.setPlaceholderText("auto-derive from folder name")
        self.trip_code_edit.setMaximumWidth(100)
        params_layout.addWidget(self.trip_code_edit)
        params_layout.addStretch()
        layout.addLayout(params_layout)

        # Options
        options_layout = QHBoxLayout()
        self.ungroup_checkbox = QCheckBox("Ungroup RAW+JPEG")
        options_layout.addWidget(self.ungroup_checkbox)
        self.force_checkbox = QCheckBox("Force (if busy)")
        options_layout.addWidget(self.force_checkbox)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        # Preview table
        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(2)
        self.preview_table.setHorizontalHeaderLabels(["From", "To"])
        layout.addWidget(self.preview_table)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Buttons
        button_layout = QHBoxLayout()
        self._preview_button = QPushButton("Preview (Dry Run)")
        self._preview_button.clicked.connect(self.run_preview)
        button_layout.addWidget(self._preview_button)
        self.move_button = QPushButton("Move")
        self.move_button.setEnabled(False)
        self.move_button.clicked.connect(self.run_move)
        button_layout.addWidget(self.move_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

    def _on_mode_changed(self) -> None:
        """Update internal mode when radio button changes."""
        if self._photos_radio.isChecked():
            self._mode = "photos"
        else:
            self._mode = "folder"
        self._reset_preview()

    def _reset_preview(self) -> None:
        """Clear preview state when source/dest changes."""
        self._preview_ready = False
        self.move_button.setEnabled(False)
        self.preview_table.setRowCount(0)

    def _on_source_clicked(self) -> None:
        """Handle 'Choose Source…' button."""
        if self._mode == "photos":
            extensions = " ".join(f"*{ext}" for ext in sorted(IMAGE_EXTENSIONS))
            file_filter = f"Images ({extensions})"
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Select photos", "", file_filter
            )
            if paths:
                self.set_source_photos([Path(p) for p in paths])
        else:
            path = QFileDialog.getExistingDirectory(self, "Select shoot folder")
            if path:
                self.set_source_folder(Path(path))

    def _on_dest_clicked(self) -> None:
        """Handle 'Choose Destination…' button."""
        path = QFileDialog.getExistingDirectory(self, "Select destination folder")
        if path:
            self.set_destination(Path(path))

    def set_source_photos(self, paths: list[Path]) -> None:
        """Set photos-mode source; switches mode to photos."""
        self._mode = "photos"
        self._photos_radio.setChecked(True)
        self._source_photos = [Path(p) for p in paths]
        self._source_folder = None
        if paths:
            self._source_label.setText(f"{len(paths)} photo(s)")
        else:
            self._source_label.setText("(none)")
        self._reset_preview()

    def set_source_folder(self, path: Path) -> None:
        """Set folder-mode source; switches mode to folder."""
        self._mode = "folder"
        self._folder_radio.setChecked(True)
        self._source_folder = Path(path)
        self._source_photos = []
        self._source_label.setText(str(path.name))
        self._reset_preview()

    def set_destination(self, path: Path) -> None:
        """Set the destination folder."""
        self._destination = Path(path)
        self._dest_label.setText(str(path))
        self._reset_preview()

    def run_preview(self) -> None:
        """Dry-run the move to preview it."""
        # Guard: no worker already running
        if self.is_running():
            return

        # Resolve destination
        if self._destination is None:
            self.status_label.setText("No destination selected.")
            return

        # Resolve cart_id
        cart_id_text = self.cart_id_edit.text()
        try:
            cart_id = volume.resolve_cart_id(
                self._destination,
                cart_id_text if cart_id_text else None
            )
        except ValueError as e:
            self.status_label.setText(f"Cart ID error: {e}")
            return

        # Resolve trip_code
        trip_code_text = self.trip_code_edit.text()
        if not trip_code_text:
            trip_code = volume.derive_trip_code(self._destination.name)
        else:
            trip_code = trip_code_text

        # Resolve source
        if self._mode == "photos":
            if not self._source_photos:
                self.status_label.setText("No photos selected.")
                return
            photo_paths = self._source_photos
        else:  # folder mode
            if self._source_folder is None:
                self.status_label.setText("No source folder selected.")
                return
            photo_paths = None
            source_dir = self._source_folder

        # Run the dry-run move
        try:
            if self._mode == "photos":
                result = relocate.move_photos(
                    photo_paths,
                    self._destination,
                    cart_id,
                    trip_code,
                    ungroup=self.ungroup_checkbox.isChecked(),
                    dry_run=True,
                )
            else:
                result = relocate.move_shoot_folder(
                    source_dir,
                    self._destination.parent,
                    cart_id,
                    dest_folder_name=self._destination.name,
                    ungroup=self.ungroup_checkbox.isChecked(),
                    dry_run=True,
                )

            # Populate preview table
            self.preview_table.setRowCount(0)
            for src, dest in result.moved:
                row = self.preview_table.rowCount()
                self.preview_table.insertRow(row)
                self.preview_table.setItem(row, 0, QTableWidgetItem(str(src)))
                self.preview_table.setItem(row, 1, QTableWidgetItem(str(dest)))

            # Update state
            self._preview_ready = True
            self.move_button.setEnabled(True)
            self.status_label.setText(f"Preview: {len(result.moved)} photo(s) ready to move.")

        except relocate.RelocateError as e:
            # Clear preview on error
            self.preview_table.setRowCount(0)
            self._preview_ready = False
            self.move_button.setEnabled(False)
            self.status_label.setText(str(e))

    def run_move(self) -> None:
        """Execute the actual move (after preview)."""
        # Guard: preview was not run recently
        if not self._preview_ready or self.is_running():
            return

        # Re-resolve the same parameters as in run_preview
        if self._destination is None:
            self.status_label.setText("No destination selected.")
            return

        cart_id_text = self.cart_id_edit.text()
        try:
            cart_id = volume.resolve_cart_id(
                self._destination,
                cart_id_text if cart_id_text else None
            )
        except ValueError as e:
            self.status_label.setText(f"Cart ID error: {e}")
            return

        trip_code_text = self.trip_code_edit.text()
        if not trip_code_text:
            trip_code = volume.derive_trip_code(self._destination.name)
        else:
            trip_code = trip_code_text

        # Determine which function and args to use
        if self._mode == "photos":
            if not self._source_photos:
                return
            fn = relocate.move_photos
            args = (self._source_photos, self._destination, cart_id, trip_code)
        else:
            if self._source_folder is None:
                return
            fn = relocate.move_shoot_folder
            args = (
                self._source_folder,
                self._destination.parent,
                cart_id,
            )

        # Build the worker
        kwargs = {
            "ungroup": self.ungroup_checkbox.isChecked(),
            "force": self.force_checkbox.isChecked(),
        }
        if self._mode == "photos":
            # move_photos doesn't take dest_folder_name
            pass
        else:
            # move_shoot_folder does
            kwargs["dest_folder_name"] = self._destination.name

        self._worker = Worker(fn, *args, **kwargs)

        # Connect signals
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.signals.failed.connect(self._on_failed)

        # Disable controls and show progress
        self._preview_ready = False
        self.move_button.setEnabled(False)
        self._preview_button.setEnabled(False)
        self._source_button.setEnabled(False)
        self._dest_button.setEnabled(False)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.show()

        # Emit signal and start worker
        self.move_started.emit()
        self._worker.start()

    def _on_progress(self, index: int, total: int, label: str) -> None:
        """Handle progress signal from worker."""
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(index)
        self.status_label.setText(f"[{index}/{total}] {label}")

    def _on_finished(self, result: object) -> None:
        """Handle successful move completion."""
        self._preview_ready = False
        self.preview_table.setRowCount(0)

        # Format completion message
        if hasattr(result, "snapshot") and result.snapshot:
            msg = f"Move complete. Snapshot: {result.snapshot}"
        else:
            msg = "Move complete."
        self.status_label.setText(msg)

        # Re-enable controls
        self._preview_button.setEnabled(True)
        self._source_button.setEnabled(True)
        self._dest_button.setEnabled(True)
        self.progress_bar.hide()
        self._worker.wait()  # ensure the OS thread has actually joined before releasing it
        self._worker = None

        # Emit signal
        self.move_finished.emit(result)

    def _on_failed(self, message: str) -> None:
        """Handle move failure."""
        self.status_label.setText(f"Move failed: {message}")

        # Re-enable controls
        self._preview_button.setEnabled(True)
        self._source_button.setEnabled(True)
        self._dest_button.setEnabled(True)
        self.progress_bar.hide()
        self._worker.wait()  # ensure the OS thread has actually joined before releasing it
        self._worker = None

        # Emit signal
        self.move_failed.emit(message)

    def is_running(self) -> bool:
        """Return whether a worker is currently active."""
        return self._worker is not None and self._worker.isRunning()
