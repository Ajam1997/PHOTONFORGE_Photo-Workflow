"""GUI tests for the cartridge list widget."""

from __future__ import annotations

from pathlib import Path

import pytest

# Skip this entire module if PySide6 is not installed
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings

from cartridge_manager.cartridge_list_widget import CartridgeListWidget
from photo_workflow.photondb import ensure_schema, open_db


def _cartridge(tmp_path: Path, name: str = "PHOTON-001") -> Path:
    """Create a bare cartridge root directory."""
    root = tmp_path / name
    root.mkdir()
    return root


def test_add_cartridge_populates_table(tmp_path: Path, qtbot) -> None:
    """Adding two cartridges creates rows in the right order."""
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    widget = CartridgeListWidget(settings=settings)
    qtbot.addWidget(widget)

    cart1 = _cartridge(tmp_path, "PHOTON-001")
    cart2 = _cartridge(tmp_path, "PHOTON-002")

    widget.add_cartridge(cart1)
    widget.add_cartridge(cart2)

    assert widget.table.rowCount() == 2
    assert widget.roots() == [cart1, cart2]


def test_no_duplicate_rows_on_double_add(tmp_path: Path, qtbot) -> None:
    """Adding the same root twice does not create a duplicate row."""
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    widget = CartridgeListWidget(settings=settings)
    qtbot.addWidget(widget)

    cart = _cartridge(tmp_path, "PHOTON-001")

    widget.add_cartridge(cart)
    widget.add_cartridge(cart)

    assert widget.table.rowCount() == 1
    assert widget.roots() == [cart]


def test_remove_selected_removes_row(tmp_path: Path, qtbot) -> None:
    """Selecting and removing a row deletes exactly that cartridge."""
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    widget = CartridgeListWidget(settings=settings)
    qtbot.addWidget(widget)

    cart1 = _cartridge(tmp_path, "PHOTON-001")
    cart2 = _cartridge(tmp_path, "PHOTON-002")

    widget.add_cartridge(cart1)
    widget.add_cartridge(cart2)
    assert widget.table.rowCount() == 2

    # Select the first row and remove it
    widget.table.selectRow(0)
    widget.remove_selected()

    assert widget.table.rowCount() == 1
    assert widget.roots() == [cart2]


def test_refresh_picks_up_database_changes(tmp_path: Path, qtbot) -> None:
    """Refresh re-queries database presence from disk."""
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    widget = CartridgeListWidget(settings=settings)
    qtbot.addWidget(widget)

    cart = _cartridge(tmp_path, "PHOTON-001")
    widget.add_cartridge(cart)

    # Initial refresh: no DBs
    assert widget.table.item(0, 5).text() == "no"  # Photonforge DB column

    # Create a photonforge.db
    # open_db expects a folder path and creates the DB at parent / "photonforge.db"
    conn = open_db(cart / "ICELAND")
    ensure_schema(conn)
    conn.close()

    # Refresh should pick it up
    widget.refresh()

    assert widget.table.item(0, 5).text() == "yes"


def test_selection_updates_detail_panel(tmp_path: Path, qtbot) -> None:
    """Selecting a row updates the detail panel."""
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    widget = CartridgeListWidget(settings=settings)
    qtbot.addWidget(widget)

    cart = _cartridge(tmp_path, "PHOTON-001")
    widget.add_cartridge(cart)

    # Select the row
    widget.table.selectRow(0)

    detail_text = widget._detail_label.text()

    # Should contain root path
    assert str(cart) in detail_text
    assert "idle" in detail_text


def test_persistence_with_presaved_settings(tmp_path: Path, qtbot) -> None:
    """A CartridgeListWidget loaded with pre-saved roots shows them immediately."""
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)

    cart1 = _cartridge(tmp_path, "PHOTON-001")
    cart2 = _cartridge(tmp_path, "PHOTON-002")

    # Pre-populate settings before creating the widget
    settings.setValue("cartridge_roots", [str(cart1), str(cart2)])

    # Now create widget and it should load the roots
    widget = CartridgeListWidget(settings=settings)
    qtbot.addWidget(widget)

    assert widget.table.rowCount() == 2
    assert widget.roots() == [cart1, cart2]
