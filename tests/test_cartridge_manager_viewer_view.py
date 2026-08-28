"""Tests for ViewerView GUI widget.

Uses real filesystem and Qt event loop throughout. Tests verify that the view
correctly orchestrates gallery loading, selection, and detail display.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from conftest import make_jpg, make_real_darktable_db

from cartridge_manager.viewer_view import ViewerView
from photo_workflow.photondb import ensure_schema, insert_photo, open_db


def _cartridge(tmp_path: Path, name: str = "PHOTON-001") -> Path:
    """Create a bare cartridge root directory with a photonforge.db."""
    root = tmp_path / name
    root.mkdir()
    conn = open_db(root / "ICELAND")
    ensure_schema(conn)
    conn.close()
    return root


def test_validation_empty_folder_field(qtbot) -> None:
    """run_load() with empty folder field shows error, no worker started."""
    view = ViewerView()
    qtbot.addWidget(view)

    view.folder_edit.setText("")
    view.run_load()

    assert "Please enter" in view.status_label.text()
    assert not view.is_running()


def test_validation_nonexistent_folder(tmp_path: Path, qtbot) -> None:
    """run_load() with nonexistent path shows error."""
    view = ViewerView()
    qtbot.addWidget(view)

    view.folder_edit.setText(str(tmp_path / "nonexistent"))
    view.run_load()

    assert "Not a directory" in view.status_label.text()
    assert not view.is_running()


def test_load_real_folder_end_to_end(tmp_path: Path, qtbot) -> None:
    """run_load() on a real folder completes and populates grid."""
    cartridge = _cartridge(tmp_path)
    shoot_folder = cartridge / "ICELAND"
    shoot_folder.mkdir()

    # Create a few test photos
    photos_to_make = [
        shoot_folder / "P001ICE.jpg",
        shoot_folder / "P002ICE.jpg",
    ]
    for p in photos_to_make:
        make_jpg(p)

    view = ViewerView()
    qtbot.addWidget(view)

    view.folder_edit.setText(str(shoot_folder))

    # Wait for gallery_loaded signal
    with qtbot.waitSignal(view.gallery_loaded, timeout=15000):
        view.run_load()

    # Verify grid was populated
    assert view.grid.count() == 2
    assert "Loaded 2 photo(s)" in view.status_label.text()


def test_load_button_disabled_while_running(tmp_path: Path, qtbot) -> None:
    """load_button is disabled while is_running()."""
    cartridge = _cartridge(tmp_path)
    shoot_folder = cartridge / "ICELAND"
    shoot_folder.mkdir()

    # Create a photo
    make_jpg(shoot_folder / "P001ICE.jpg")

    view = ViewerView()
    qtbot.addWidget(view)

    view.folder_edit.setText(str(shoot_folder))

    # Start load
    view.run_load()
    assert not view.load_button.isEnabled()

    # Wait for completion
    with qtbot.waitSignal(view.gallery_loaded, timeout=15000):
        pass

    # Re-enabled after completion
    assert view.load_button.isEnabled()


def test_browse_button_reenabled_after_successful_load(tmp_path: Path, qtbot) -> None:
    """Regression test: _on_finished must re-enable the browse button too, not
    just the load button — a real bug found in review (the success path had
    setEnabled(False) where the failure path correctly had setEnabled(True),
    leaving Browse permanently disabled after the very first successful load).
    """
    cartridge = _cartridge(tmp_path)
    shoot_folder = cartridge / "ICELAND"
    shoot_folder.mkdir()
    make_jpg(shoot_folder / "P001ICE.jpg")

    view = ViewerView()
    qtbot.addWidget(view)

    view.folder_edit.setText(str(shoot_folder))
    assert view._browse_button.isEnabled()

    with qtbot.waitSignal(view.gallery_loaded, timeout=15000):
        view.run_load()

    assert view._browse_button.isEnabled(), "Browse button was left disabled after a successful load"


def test_selection_updates_detail_label(tmp_path: Path, qtbot) -> None:
    """Selecting a grid item updates detail_label with photo metadata."""
    cartridge = _cartridge(tmp_path)
    shoot_folder = cartridge / "ICELAND"
    shoot_folder.mkdir()

    photo_file = shoot_folder / "P001ICE.jpg"
    make_jpg(photo_file)

    # Insert metadata into photonforge.db
    conn = open_db(shoot_folder)
    try:
        ensure_schema(conn)
        insert_photo(conn, "ICELAND", "P001ICE.jpg", "P001ICE.jpg", "2026:05:10 14:32:01")
        conn.execute(
            "UPDATE photos SET master_score=?, primary_genre=?, stages=?, needs_review=? "
            "WHERE folder=? AND filename=?",
            (7.5, "portrait", "ingested,scored", 0, "ICELAND", "P001ICE.jpg")
        )
        conn.commit()
    finally:
        conn.close()

    view = ViewerView()
    qtbot.addWidget(view)

    view.folder_edit.setText(str(shoot_folder))

    with qtbot.waitSignal(view.gallery_loaded, timeout=15000):
        view.run_load()

    # Select the first item
    view.grid.setCurrentRow(0)

    # Verify detail label contains the photo's metadata
    detail_text = view.detail_label.text()
    assert "P001ICE.jpg" in detail_text
    assert "7.5" in detail_text
    assert "portrait" in detail_text


def test_no_selection_clears_detail_label(tmp_path: Path, qtbot) -> None:
    """Clearing selection sets detail_label to empty."""
    cartridge = _cartridge(tmp_path)
    shoot_folder = cartridge / "ICELAND"
    shoot_folder.mkdir()

    make_jpg(shoot_folder / "P001ICE.jpg")

    view = ViewerView()
    qtbot.addWidget(view)

    view.folder_edit.setText(str(shoot_folder))

    with qtbot.waitSignal(view.gallery_loaded, timeout=15000):
        view.run_load()

    # Select an item
    view.grid.setCurrentRow(0)
    assert view.detail_label.text() != ""

    # Clear selection by setting row to -1
    view.grid.setCurrentRow(-1)
    assert view.detail_label.text() == ""


def test_load_empty_folder(tmp_path: Path, qtbot) -> None:
    """run_load() on a folder with zero photos completes cleanly."""
    empty_folder = tmp_path / "empty"
    empty_folder.mkdir()

    view = ViewerView()
    qtbot.addWidget(view)

    view.folder_edit.setText(str(empty_folder))

    with qtbot.waitSignal(view.gallery_loaded, timeout=15000):
        view.run_load()

    assert view.grid.count() == 0
    assert "Loaded 0 photo(s)" in view.status_label.text()


def test_browse_button_opens_dialog_and_sets_folder(tmp_path: Path, qtbot, monkeypatch) -> None:
    """'Browse…' button opens folder dialog and sets folder_edit."""
    shoot_folder = tmp_path / "ICELAND"
    shoot_folder.mkdir()

    view = ViewerView()
    qtbot.addWidget(view)

    # Mock QFileDialog.getExistingDirectory to return our shoot_folder
    def mock_dialog(parent, title):
        return str(shoot_folder)

    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", mock_dialog)

    # Click browse button
    view._browse_button.click()

    # folder_edit should be set
    assert view.folder_edit.text() == str(shoot_folder)


def test_gallery_loaded_signal_emitted(tmp_path: Path, qtbot) -> None:
    """gallery_loaded signal is emitted with the PhotoInfo list."""
    cartridge = _cartridge(tmp_path)
    shoot_folder = cartridge / "ICELAND"
    shoot_folder.mkdir()

    make_jpg(shoot_folder / "P001ICE.jpg")
    make_jpg(shoot_folder / "P002ICE.jpg")

    view = ViewerView()
    qtbot.addWidget(view)

    view.folder_edit.setText(str(shoot_folder))

    gallery_result = None

    def capture_result(result):
        nonlocal gallery_result
        gallery_result = result

    view.gallery_loaded.connect(capture_result)

    with qtbot.waitSignal(view.gallery_loaded, timeout=15000):
        view.run_load()

    assert gallery_result is not None
    assert len(gallery_result) == 2


def test_gallery_load_failed_signal_on_error(tmp_path: Path, qtbot, monkeypatch) -> None:
    """gallery_load_failed signal is emitted when build_gallery raises."""
    cartridge = _cartridge(tmp_path)
    shoot_folder = cartridge / "ICELAND"
    shoot_folder.mkdir()

    make_jpg(shoot_folder / "P001ICE.jpg")

    view = ViewerView()
    qtbot.addWidget(view)

    view.folder_edit.setText(str(shoot_folder))

    # Patch build_gallery to raise
    def mock_build_gallery(folder, cache_dir, progress=None):
        raise RuntimeError("Simulated error")

    from cartridge_manager import photo_state
    monkeypatch.setattr(photo_state, "build_gallery", mock_build_gallery)

    error_result = None

    def capture_error(msg):
        nonlocal error_result
        error_result = msg

    view.gallery_load_failed.connect(capture_error)

    with qtbot.waitSignal(view.gallery_load_failed, timeout=15000):
        view.run_load()

    assert error_result is not None
    assert "Simulated error" in error_result
    assert "Load failed" in view.status_label.text()


def test_detail_label_shows_unscored_photo(tmp_path: Path, qtbot) -> None:
    """detail_label shows '(not scored)' for photos with no master_score."""
    cartridge = _cartridge(tmp_path)
    shoot_folder = cartridge / "ICELAND"
    shoot_folder.mkdir()

    photo_file = shoot_folder / "P001ICE.jpg"
    make_jpg(photo_file)

    # Insert row but leave master_score as NULL (set it to NULL explicitly)
    conn = open_db(shoot_folder)
    try:
        ensure_schema(conn)
        insert_photo(conn, "ICELAND", "P001ICE.jpg", "P001ICE.jpg", "2026:05:10 14:32:01")
        conn.execute(
            "UPDATE photos SET master_score=NULL WHERE folder=? AND filename=?",
            ("ICELAND", "P001ICE.jpg")
        )
        conn.commit()
    finally:
        conn.close()

    view = ViewerView()
    qtbot.addWidget(view)

    view.folder_edit.setText(str(shoot_folder))

    with qtbot.waitSignal(view.gallery_loaded, timeout=15000):
        view.run_load()

    view.grid.setCurrentRow(0)

    assert "(not scored)" in view.detail_label.text()


def test_detail_label_shows_darktable_tags(tmp_path: Path, qtbot) -> None:
    """detail_label shows Darktable tags when set."""
    cartridge = _cartridge(tmp_path)
    shoot_folder = cartridge / "ICELAND"
    shoot_folder.mkdir()

    photo_file = shoot_folder / "P001ICE.jpg"
    make_jpg(photo_file)

    # Create Darktable DB pair
    dt_config = cartridge / "dt-config"
    dt_config.mkdir()
    lib_path = dt_config / "library.db"
    data_path = dt_config / "data.db"

    make_real_darktable_db(lib_path, data_path)

    # Insert photo and tag it
    with sqlite3.connect(lib_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "INSERT INTO film_rolls (folder, access_timestamp) VALUES (?, ?)",
            (str(shoot_folder), 0)
        )
        film_id = cursor.lastrowid

        cursor = conn.execute(
            "INSERT INTO images (film_id, filename, write_timestamp) VALUES (?, ?, ?)",
            (film_id, photo_file.name, 0)
        )
        image_id = cursor.lastrowid

        with sqlite3.connect(data_path) as data_conn:
            data_conn.row_factory = sqlite3.Row
            cursor = data_conn.execute(
                "INSERT INTO tags (name, synonyms, flags) VALUES (?, ?, ?)",
                ("wildlife", "", 0)
            )
            tag_id = cursor.lastrowid
            data_conn.commit()

        conn.execute(
            "INSERT INTO tagged_images (imgid, tagid, position) VALUES (?, ?, ?)",
            (image_id, tag_id, 0)
        )
        conn.commit()

    view = ViewerView()
    qtbot.addWidget(view)

    view.folder_edit.setText(str(shoot_folder))

    with qtbot.waitSignal(view.gallery_loaded, timeout=15000):
        view.run_load()

    view.grid.setCurrentRow(0)

    assert "wildlife" in view.detail_label.text()


def test_progress_bar_shown_during_load(tmp_path: Path, qtbot) -> None:
    """progress_bar is shown and hidden at the right times."""
    cartridge = _cartridge(tmp_path)
    shoot_folder = cartridge / "ICELAND"
    shoot_folder.mkdir()

    make_jpg(shoot_folder / "P001ICE.jpg")

    view = ViewerView()
    qtbot.addWidget(view)

    # Initially hidden
    assert view.progress_bar.isHidden()

    view.folder_edit.setText(str(shoot_folder))
    view.run_load()

    # Should be visible while loading
    assert not view.progress_bar.isHidden()

    with qtbot.waitSignal(view.gallery_loaded, timeout=15000):
        pass

    # Should be hidden after completion
    assert view.progress_bar.isHidden()


def test_folder_edit_readonly_while_loading(tmp_path: Path, qtbot) -> None:
    """folder_edit becomes read-only while loading."""
    cartridge = _cartridge(tmp_path)
    shoot_folder = cartridge / "ICELAND"
    shoot_folder.mkdir()

    make_jpg(shoot_folder / "P001ICE.jpg")

    view = ViewerView()
    qtbot.addWidget(view)

    # Initially editable
    assert not view.folder_edit.isReadOnly()

    view.folder_edit.setText(str(shoot_folder))
    view.run_load()

    # Should be read-only while loading
    assert view.folder_edit.isReadOnly()

    with qtbot.waitSignal(view.gallery_loaded, timeout=15000):
        pass

    # Should be editable again after completion
    assert not view.folder_edit.isReadOnly()
