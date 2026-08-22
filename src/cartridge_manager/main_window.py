"""Main window for the Cartridge Manager app."""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow

from .cartridge_list_widget import CartridgeListWidget


class MainWindow(QMainWindow):
    """Top-level window hosting the cartridge list widget."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PhotonForge Cartridge Manager")
        self.cartridge_list = CartridgeListWidget(parent=self)
        self.setCentralWidget(self.cartridge_list)
