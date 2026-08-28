"""Main window for the Cartridge Manager app."""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QTabWidget

from .backup_view import BackupView
from .cartridge_list_widget import CartridgeListWidget
from .move_view import MoveView
from .provision_view import ProvisionView
from .viewer_view import ViewerView


class MainWindow(QMainWindow):
    """Top-level window hosting cartridge management and move views."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PhotonForge Cartridge Manager")

        # Create tab widget
        tabs = QTabWidget()

        # Cartridges tab
        self.cartridge_list = CartridgeListWidget(parent=self)
        tabs.addTab(self.cartridge_list, "Cartridges")

        # Move tab
        self.move_view = MoveView(parent=self)
        tabs.addTab(self.move_view, "Move")

        # Backup tab
        self.backup_view = BackupView(parent=self)
        tabs.addTab(self.backup_view, "Backup")

        # Make Portable tab
        self.provision_view = ProvisionView(parent=self)
        tabs.addTab(self.provision_view, "Make Portable")

        # Viewer tab
        self.viewer_view = ViewerView(parent=self)
        tabs.addTab(self.viewer_view, "Viewer")

        self.setCentralWidget(tabs)
