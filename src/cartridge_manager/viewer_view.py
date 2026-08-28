"""Photo viewer widget — read-only, lightweight gallery browser."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import photo_state
from .workers import Worker


class ViewerView(QWidget):
    """Read-only photo gallery viewer for a shoot folder or cartridge.

    Displays a thumbnail grid with metadata (score, genre, stages, tags, color label).
    No editing, no culling controls — pure read-only browsing of photonforge.db +
    Darktable state.
    """

    gallery_loaded = Signal(list)     # list[PhotoInfo]
    gallery_load_failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._photos: list[photo_state.PhotoInfo] = []
        self._worker: Worker | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the UI: folder selection, thumbnail grid, detail panel, buttons."""
        layout = QVBoxLayout(self)

        # Folder selection
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("Folder:"))
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Shoot folder or cartridge root")
        folder_layout.addWidget(self.folder_edit, 1)
        self._browse_button = QPushButton("Browse…")
        self._browse_button.clicked.connect(self._on_browse_clicked)
        folder_layout.addWidget(self._browse_button)
        layout.addLayout(folder_layout)

        # Load button
        button_layout = QHBoxLayout()
        self.load_button = QPushButton("Load")
        self.load_button.clicked.connect(self.run_load)
        button_layout.addWidget(self.load_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        # Progress bar (hidden until load starts)
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        # Main content: thumbnail grid + detail panel side by side
        content_layout = QHBoxLayout()

        # Thumbnail grid
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QSize(160, 160))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setWrapping(True)
        self.grid.itemSelectionChanged.connect(self._on_selection_changed)
        content_layout.addWidget(self.grid, 1)

        # Detail panel (word-wrapped label)
        self.detail_label = QLabel()
        self.detail_label.setWordWrap(True)
        self.detail_label.setMinimumWidth(200)
        self.detail_label.setMaximumWidth(300)
        content_layout.addWidget(self.detail_label)

        layout.addLayout(content_layout, 1)

        # Status label (errors, completion messages)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def _on_browse_clicked(self) -> None:
        """Handle 'Browse…' button click."""
        path = QFileDialog.getExistingDirectory(
            self, "Select shoot folder or cartridge root"
        )
        if path:
            self.folder_edit.setText(path)

    def run_load(self) -> None:
        """Execute the gallery load operation in a worker thread."""
        # Guard: no worker already running
        if self.is_running():
            return

        # Validate folder input
        folder_text = self.folder_edit.text().strip()
        if not folder_text:
            self.status_label.setText("Please enter or browse to a folder.")
            return

        folder = Path(folder_text)
        if not folder.is_dir():
            self.status_label.setText(f"Not a directory: {folder_text}")
            return

        # Set up cache directory
        cache_dir = folder / ".photonforge" / "thumb-cache"

        # Build the worker
        self._worker = Worker(photo_state.build_gallery, folder, cache_dir)

        # Connect signals
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.signals.failed.connect(self._on_failed)

        # Disable controls and show progress
        self.load_button.setEnabled(False)
        self._browse_button.setEnabled(False)
        self.folder_edit.setReadOnly(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.progress_bar.show()

        # Start worker
        self._worker.start()

    def _on_progress(self, index: int, total: int, label: str) -> None:
        """Handle progress signal from worker."""
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(index)
        self.status_label.setText(f"[{index}/{total}] Loading {label}…")

    def _on_finished(self, result: object) -> None:
        """Handle successful gallery load completion."""
        result_list = result if isinstance(result, list) else []
        self._photos = result_list

        # Populate grid: clear and add items
        self.grid.clear()
        for info in self._photos:
            item = QListWidgetItem()
            item.setText(info.path.name)

            # Try to set thumbnail icon
            if info.thumbnail_path is not None:
                pixmap = QPixmap(str(info.thumbnail_path))
                if not pixmap.isNull():
                    item.setIcon(QIcon(pixmap))
                else:
                    # Pixmap failed to load; use blank icon
                    item.setIcon(QIcon())
            else:
                # No thumbnail; use blank icon
                item.setIcon(QIcon())

            self.grid.addItem(item)

        # Update status
        self.status_label.setText(f"Loaded {len(result_list)} photo(s).")

        # Re-enable controls
        self.load_button.setEnabled(True)
        self._browse_button.setEnabled(True)
        self.folder_edit.setReadOnly(False)
        self.progress_bar.hide()

        # Exact teardown sequence from move_view.py (critical for thread safety)
        self._worker.settle()
        self._worker.signals.progress.disconnect()
        self._worker.signals.finished.disconnect()
        self._worker.signals.failed.disconnect()
        self._worker = None

        # Emit signal
        self.gallery_loaded.emit(result_list)

    def _on_failed(self, message: str) -> None:
        """Handle gallery load failure."""
        self.status_label.setText(f"Load failed: {message}")

        # Clear grid on error
        self.grid.clear()
        self._photos = []

        # Re-enable controls
        self.load_button.setEnabled(True)
        self._browse_button.setEnabled(True)
        self.folder_edit.setReadOnly(False)
        self.progress_bar.hide()

        # Exact teardown sequence from move_view.py (critical for thread safety)
        self._worker.settle()
        self._worker.signals.progress.disconnect()
        self._worker.signals.finished.disconnect()
        self._worker.signals.failed.disconnect()
        self._worker = None

        # Emit signal
        self.gallery_load_failed.emit(message)

    def _on_selection_changed(self) -> None:
        """Update detail panel when a grid item is selected."""
        current_row = self.grid.currentRow()

        # Guard: no selection or out-of-range
        if current_row < 0 or current_row >= len(self._photos):
            self.detail_label.setText("")
            return

        info = self._photos[current_row]

        # Format detail text
        parts = [
            f"File: {info.path.name}",
            f"Score: {info.master_score if info.master_score is not None else '(not scored)'}",
            f"Genre: {info.primary_genre or '(none)'}",
            f"Stages: {', '.join(info.stages) if info.stages else '(none)'}",
            f"Needs Review: {'Yes' if info.needs_review else 'No'}",
            f"Darktable Tags: {', '.join(info.darktable_tags) if info.darktable_tags else '(none)'}",
            f"Color Label: {info.darktable_color_label if info.darktable_color_label is not None else '(none)'}",
        ]

        self.detail_label.setText("\n".join(parts))

    def is_running(self) -> bool:
        """Return whether a worker is currently active."""
        return self._worker is not None and self._worker.isRunning()
