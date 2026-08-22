"""GUI cartridge list + detail panel."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import cartridges


class CartridgeListWidget(QWidget):
    """Cartridge list + detail panel: add/remove/refresh cartridge roots."""

    COLUMNS: ClassVar[list[str]] = [
        "Label",
        "ID",
        "Root",
        "Free / Total",
        "Status",
        "Photonforge DB",
        "Darktable",
    ]

    def __init__(self, settings: QSettings | None = None, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings or QSettings("PhotonForge", "CartridgeManager")
        self._setup_ui()
        self.refresh()

    def _setup_ui(self) -> None:
        """Build the UI: table, detail panel, and buttons."""
        layout = QVBoxLayout(self)

        # Table widget
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        # Detail panel (multi-line label)
        detail_layout = QHBoxLayout()
        detail_layout.addWidget(QLabel("Details:"))
        self._detail_label = QLabel()
        self._detail_label.setWordWrap(True)
        detail_layout.addWidget(self._detail_label)
        layout.addLayout(detail_layout)

        # Buttons
        button_layout = QHBoxLayout()
        self._add_button = QPushButton("Add Cartridge…")
        self._add_button.clicked.connect(self._on_add_clicked)
        button_layout.addWidget(self._add_button)

        self._remove_button = QPushButton("Remove Selected")
        self._remove_button.clicked.connect(self.remove_selected)
        button_layout.addWidget(self._remove_button)

        self._refresh_button = QPushButton("Refresh")
        self._refresh_button.clicked.connect(self.refresh)
        button_layout.addWidget(self._refresh_button)

        button_layout.addStretch()
        layout.addLayout(button_layout)

    def _on_add_clicked(self) -> None:
        """Handle 'Add Cartridge…' button: open file dialog."""
        path = QFileDialog.getExistingDirectory(self, "Select cartridge root")
        if path:
            self.add_cartridge(Path(path))

    def _on_selection_changed(self) -> None:
        """Update detail panel when selection changes."""
        current_row = self.table.currentRow()
        if current_row < 0:
            self._detail_label.setText("")
            return

        roots = self.roots()
        if current_row >= len(roots):
            self._detail_label.setText("")
            return

        info = cartridges.describe(roots[current_row])
        detail_text = self._format_detail(info)
        self._detail_label.setText(detail_text)

    @staticmethod
    def _format_detail(info: cartridges.CartridgeInfo) -> str:
        """Format a CartridgeInfo for display in the detail panel."""
        lines = [
            f"Root: {info.root}",
            f"Label: {info.label}",
            f"ID: {info.cart_id}",
            f"Free / Total: {info.free_bytes / 1e9:.1f} / {info.total_bytes / 1e9:.1f} GB",
            f"Status: {'busy' if info.busy_reason else 'idle'}",
        ]
        if info.busy_reason:
            lines.append(f"  Reason: {info.busy_reason}")
        lines.append(f"Photonforge DB: {'yes' if info.has_photonforge_db else 'no'}")
        lines.append(f"Darktable: {'yes' if info.has_darktable else 'no'}")
        return "\n".join(lines)

    def add_cartridge(self, root: Path) -> None:
        """Add a cartridge root; skip if already present."""
        root = Path(root)
        current_roots = self.roots()

        # Skip if already present
        if root in current_roots:
            return

        # Add to list and persist
        current_roots.append(root)
        self._settings.setValue("cartridge_roots", [str(p) for p in current_roots])

        # Refresh the table
        self.refresh()

    def remove_selected(self) -> None:
        """Remove the currently-selected row's cartridge."""
        current_row = self.table.currentRow()
        if current_row < 0:
            return

        current_roots = self.roots()
        if current_row >= len(current_roots):
            return

        # Remove and persist
        del current_roots[current_row]
        self._settings.setValue("cartridge_roots", [str(p) for p in current_roots])

        # Refresh
        self.refresh()

    def refresh(self) -> None:
        """Re-read stored roots and repopulate the table."""
        roots = self.roots()

        # Clear the table
        self.table.setRowCount(0)

        # Repopulate
        for i, root in enumerate(roots):
            info = cartridges.describe(root)
            self.table.insertRow(i)

            # Format free/total space as decimal GB
            space_str = f"{info.free_bytes / 1e9:.1f} / {info.total_bytes / 1e9:.1f} GB"

            # Status: "idle" or the busy reason
            status_str = info.busy_reason if info.busy_reason else "idle"

            # Database flags: "yes" or "no"
            photonforge_str = "yes" if info.has_photonforge_db else "no"
            darktable_str = "yes" if info.has_darktable else "no"

            # Build row items
            items = [
                info.label,
                info.cart_id,
                str(info.root),
                space_str,
                status_str,
                photonforge_str,
                darktable_str,
            ]

            for col, text in enumerate(items):
                self.table.setItem(i, col, QTableWidgetItem(text))

    def roots(self) -> list[Path]:
        """Return the currently-stored cartridge roots."""
        roots_list = self._settings.value("cartridge_roots", [], type=list)
        return [Path(p) for p in roots_list]
