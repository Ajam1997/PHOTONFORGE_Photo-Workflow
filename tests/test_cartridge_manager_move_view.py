"""GUI tests for the Move view."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

# Skip this entire module if PySide6 is not installed
pytest.importorskip("PySide6")

from conftest import make_real_darktable_db

from cartridge_manager.move_view import MoveView


def _cartridge(tmp_path: Path, name: str = "PHOTON-001") -> Path:
    """Create a bare cartridge root directory."""
    root = tmp_path / name
    root.mkdir()
    return root


def _shoot_folder(cartridge_root: Path, folder_name: str, filenames: list[str]) -> Path:
    """Create a shoot folder with fake photo files."""
    d = cartridge_root / folder_name
    d.mkdir()
    for fn in filenames:
        (d / fn).write_bytes(f"fake photo bytes for {fn}".encode())
    return d


def _darktable(cartridge_root: Path) -> tuple[Path, Path]:
    """Create a real Darktable library.db + data.db pair."""
    dt_config = cartridge_root / "dt-config"
    dt_config.mkdir()
    library_db = dt_config / "library.db"
    data_db = dt_config / "data.db"
    make_real_darktable_db(library_db, data_db)
    return library_db, data_db


def _insert_image(
    conn: sqlite3.Connection, film_id: int, filename: str, group_id: int | None = None
) -> int:
    """Insert an image row into Darktable."""
    cur = conn.execute("INSERT INTO images (film_id, filename) VALUES (?, ?)", (film_id, filename))
    image_id = cur.lastrowid
    conn.execute("UPDATE images SET group_id=? WHERE id=?", (group_id or image_id, image_id))
    return image_id


def _ensure_film_roll(conn: sqlite3.Connection, folder: str) -> int:
    """Ensure a film_roll exists for the given folder."""
    row = conn.execute("SELECT id FROM film_rolls WHERE folder=?", (folder,)).fetchone()
    if row:
        return row[0]
    return conn.execute(
        "INSERT INTO film_rolls (folder, access_timestamp) VALUES (?, 0)", (folder,)
    ).lastrowid


# ---------------------------------------------------------------------------
# Basic preview and move
# ---------------------------------------------------------------------------


def test_photos_mode_preview_populates_table(tmp_path: Path, qtbot) -> None:
    """Photos mode: set source, set destination, preview shows rows."""
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg", "P001ICE0000002.jpg"])
    dest = root / "ICELAND2"

    widget = MoveView()
    qtbot.addWidget(widget)

    widget.set_source_photos([src / "P001ICE0000001.jpg", src / "P001ICE0000002.jpg"])
    widget.set_destination(dest)
    widget.cart_id_edit.setText("001")  # Explicit cart ID
    widget.run_preview()

    assert widget.preview_table.rowCount() == 2
    assert widget.move_button.isEnabled() is True
    assert "2 photo(s) ready" in widget.status_label.text()


def test_folder_mode_preview_populates_table(tmp_path: Path, qtbot) -> None:
    """Folder mode: set source folder, set destination, preview shows rows."""
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg", "P001ICE0000002.jpg"])
    dest = root / "ICELAND2"

    widget = MoveView()
    qtbot.addWidget(widget)

    widget.set_source_folder(src)
    widget.set_destination(dest)
    widget.cart_id_edit.setText("001")  # Explicit cart ID
    widget.run_preview()

    assert widget.preview_table.rowCount() == 2
    assert widget.move_button.isEnabled() is True
    assert "2 photo(s) ready" in widget.status_label.text()


def test_preview_error_clears_table_and_disables_move(tmp_path: Path, qtbot) -> None:
    """Preview error (cross-cartridge) shows error and keeps Move disabled."""
    root1 = _cartridge(tmp_path, "PHOTON-001")
    root2 = _cartridge(tmp_path, "PHOTON-002")
    src = _shoot_folder(root1, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root2 / "ICELAND"

    widget = MoveView()
    qtbot.addWidget(widget)

    widget.set_source_photos([src / "P001ICE0000001.jpg"])
    widget.set_destination(dest)
    widget.cart_id_edit.setText("001")  # Explicit cart ID
    widget.run_preview()

    assert widget.preview_table.rowCount() == 0
    assert widget.move_button.isEnabled() is False
    assert "different cartridges" in widget.status_label.text()


def test_move_real_files_and_clears_preview(tmp_path: Path, qtbot) -> None:
    """End-to-end move: source file moves to destination, preview clears."""
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root / "ICELAND2"

    widget = MoveView()
    qtbot.addWidget(widget)

    src_file = src / "P001ICE0000001.jpg"
    widget.set_source_photos([src_file])
    widget.set_destination(dest)
    widget.cart_id_edit.setText("001")  # Explicit cart ID
    widget.run_preview()

    assert src_file.exists()
    assert widget.move_button.isEnabled() is True

    # Run the move
    with qtbot.waitSignal(widget.move_finished, timeout=5000):
        widget.run_move()

    # Verify file moved
    assert not src_file.exists()
    # Trip code from "ICELAND2" is "ICE" (first 3 letters after removing non-alpha)
    assert (dest / "P001ICE0000001.jpg").exists()
    assert widget.preview_table.rowCount() == 0
    assert widget.move_button.isEnabled() is False


def test_preview_required_before_move(tmp_path: Path, qtbot) -> None:
    """Move button is disabled until preview succeeds."""
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root / "ICELAND2"

    widget = MoveView()
    qtbot.addWidget(widget)

    widget.set_source_photos([src / "P001ICE0000001.jpg"])
    widget.set_destination(dest)
    widget.cart_id_edit.setText("001")  # Explicit cart ID

    # Before preview: Move button disabled
    assert widget.move_button.isEnabled() is False

    # After preview: Move button enabled
    widget.run_preview()
    assert widget.move_button.isEnabled() is True

    # After changing source: Move button disabled again
    widget.set_source_photos([src / "P001ICE0000001.jpg"])
    assert widget.move_button.isEnabled() is False


def test_grouped_photo_without_ungroup_fails_preview(tmp_path: Path, qtbot) -> None:
    """Grouped photo without ungroup flag raises GroupConflictError in preview."""
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg", "P001ICE0000001.ARW"])
    library_db, _ = _darktable(root)

    # Set up Darktable group
    conn = sqlite3.connect(library_db)
    film_id = _ensure_film_roll(conn, str(src))
    image_id1 = _insert_image(conn, film_id, "P001ICE0000001.jpg")
    _insert_image(conn, film_id, "P001ICE0000001.ARW", group_id=image_id1)
    conn.commit()
    conn.close()

    dest = root / "ICELAND2"

    widget = MoveView()
    qtbot.addWidget(widget)

    # Only select the JPEG, not the RAW
    widget.set_source_photos([src / "P001ICE0000001.jpg"])
    widget.set_destination(dest)
    widget.cart_id_edit.setText("001")  # Explicit cart ID
    widget.ungroup_checkbox.setChecked(False)
    widget.run_preview()

    # Preview should fail with GroupConflictError
    assert widget.preview_table.rowCount() == 0
    assert widget.move_button.isEnabled() is False
    assert "Grouped photos" in widget.status_label.text()


def test_grouped_photo_with_ungroup_succeeds(tmp_path: Path, qtbot) -> None:
    """Grouped photo with ungroup flag allows preview to succeed."""
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg", "P001ICE0000001.ARW"])
    library_db, _ = _darktable(root)

    # Set up Darktable group
    conn = sqlite3.connect(library_db)
    film_id = _ensure_film_roll(conn, str(src))
    image_id1 = _insert_image(conn, film_id, "P001ICE0000001.jpg")
    _insert_image(conn, film_id, "P001ICE0000001.ARW", group_id=image_id1)
    conn.commit()
    conn.close()

    dest = root / "ICELAND2"

    widget = MoveView()
    qtbot.addWidget(widget)

    # Only select the JPEG, but use ungroup
    widget.set_source_photos([src / "P001ICE0000001.jpg"])
    widget.set_destination(dest)
    widget.cart_id_edit.setText("001")  # Explicit cart ID
    widget.ungroup_checkbox.setChecked(True)
    widget.run_preview()

    # Preview should succeed
    assert widget.preview_table.rowCount() == 1
    assert widget.move_button.isEnabled() is True
    assert "1 photo(s) ready" in widget.status_label.text()


def test_progress_bar_updates_during_move(tmp_path: Path, qtbot) -> None:
    """Progress bar actually reflects progress signals during the move, not just at the end."""
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg", "P001ICE0000002.jpg"])
    dest = root / "ICELAND2"

    widget = MoveView()
    qtbot.addWidget(widget)

    widget.set_source_photos([src / "P001ICE0000001.jpg", src / "P001ICE0000002.jpg"])
    widget.set_destination(dest)
    widget.cart_id_edit.setText("001")  # Explicit cart ID
    widget.run_preview()

    # Initially hidden
    assert widget.progress_bar.isHidden() is True

    # Record every value the progress bar actually takes on, so we can prove
    # real progress flowed through the worker's signal — not just that the
    # move finished and the bar was reset afterward.
    seen_values: list[int] = []
    widget.progress_bar.valueChanged.connect(seen_values.append)

    # Start move
    with qtbot.waitSignal(widget.move_finished, timeout=5000):
        widget.run_move()

    assert not src.exists() or len(list(src.iterdir())) == 0
    assert seen_values, "progress_bar.valueChanged never fired — progress signal did not reach the UI"
    assert max(seen_values) == 2, f"expected progress to reach 2 (both photos), got {seen_values}"


def test_missing_source_shows_error_in_preview(tmp_path: Path, qtbot) -> None:
    """Missing source shows error in status label."""
    root = _cartridge(tmp_path)
    dest = root / "ICELAND2"

    widget = MoveView()
    qtbot.addWidget(widget)

    # Set destination but no source
    widget.set_destination(dest)
    widget.cart_id_edit.setText("001")  # Explicit cart ID
    widget.run_preview()

    assert "No photos selected" in widget.status_label.text()
    assert widget.move_button.isEnabled() is False


def test_missing_destination_shows_error_in_preview(tmp_path: Path, qtbot) -> None:
    """Missing destination shows error in status label."""
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])

    widget = MoveView()
    qtbot.addWidget(widget)

    # Set source but no destination
    widget.set_source_photos([src / "P001ICE0000001.jpg"])
    widget.run_preview()

    assert "No destination selected" in widget.status_label.text()
    assert widget.move_button.isEnabled() is False


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
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root / "ICELAND2"

    widget = MoveView()
    qtbot.addWidget(widget)
    widget.set_source_photos([src / "P001ICE0000001.jpg"])
    widget.set_destination(dest)
    widget.cart_id_edit.setText("001")
    widget.run_preview()

    wait_calls = []
    original_wait = Worker.wait

    def _spy_wait(self, *args, **kwargs):
        wait_calls.append(self)
        return original_wait(self, *args, **kwargs)

    monkeypatch.setattr(Worker, "wait", _spy_wait)

    with qtbot.waitSignal(widget.move_finished, timeout=5000):
        widget.run_move()

    assert len(wait_calls) == 1, "Worker.wait() was not called before the worker was released"
