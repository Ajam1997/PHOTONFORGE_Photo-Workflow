"""Tests for photo_state backend (no PySide6 import).

Uses real filesystem and SQLite state throughout — no mocking. Tests verify that
photo discovery, metadata gathering, thumbnail caching, and gallery building all
work correctly with degraded-graceful error handling.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from conftest import make_jpg, make_real_darktable_db

from cartridge_manager import photo_state
from photo_workflow.photondb import ensure_schema, insert_photo, open_db


def _cartridge(tmp_path: Path, name: str = "PHOTON-001") -> Path:
    """Create a bare cartridge root directory with a photonforge.db."""
    root = tmp_path / name
    root.mkdir()
    # Create a real photonforge.db at the cartridge root
    conn = open_db(root / "ICELAND")
    ensure_schema(conn)
    conn.close()
    return root


def test_list_photos_in_shoot_folder(tmp_path: Path) -> None:
    """list_photos finds .jpg/.jpeg/.png and RAW files directly in a shoot folder."""
    shoot_folder = tmp_path / "ICELAND"
    shoot_folder.mkdir()

    # Create a few fixture photos
    photo1 = shoot_folder / "P001ICE.jpg"
    photo2 = shoot_folder / "P002ICE.cr2"
    photo3 = shoot_folder / "P003ICE.arw"

    make_jpg(photo1)
    make_jpg(photo2)
    make_jpg(photo3)

    # Also add a non-image file (should be skipped)
    (shoot_folder / "notes.txt").write_text("not a photo")

    photos = photo_state.list_photos(shoot_folder)

    assert len(photos) == 3
    assert photo1 in photos
    assert photo2 in photos
    assert photo3 in photos
    # Verify sorted order
    assert photos == sorted(photos, key=lambda p: p.name)


def test_list_photos_excludes_xmp_sidecars(tmp_path: Path) -> None:
    """list_photos excludes .xmp sidecar files."""
    shoot_folder = tmp_path / "ICELAND"
    shoot_folder.mkdir()

    photo = shoot_folder / "P001ICE.jpg"
    sidecar = shoot_folder / "P001ICE.xmp"

    make_jpg(photo)
    sidecar.write_text("<x:xmpmeta/>")

    photos = photo_state.list_photos(shoot_folder)

    assert len(photos) == 1
    assert photos[0] == photo


def test_list_photos_recursive_in_cartridge(tmp_path: Path) -> None:
    """list_photos recursively finds photos one level down (cartridge with shoot subfolders)."""
    cartridge = tmp_path / "PHOTON-001"
    cartridge.mkdir()

    shoot1 = cartridge / "ICELAND"
    shoot2 = cartridge / "BAJA"
    shoot1.mkdir()
    shoot2.mkdir()

    photo1 = shoot1 / "P001ICE.jpg"
    photo2 = shoot2 / "P001BAJ.jpg"

    make_jpg(photo1)
    make_jpg(photo2)

    photos = photo_state.list_photos(cartridge)

    assert len(photos) == 2
    assert photo1 in photos
    assert photo2 in photos


def test_describe_photo_with_photonforge_row(tmp_path: Path) -> None:
    """describe_photo reads scores and metadata from photonforge.db."""
    cartridge = _cartridge(tmp_path)
    shoot_folder = cartridge / "ICELAND"
    shoot_folder.mkdir()

    photo_file = shoot_folder / "P001ICE.jpg"
    make_jpg(photo_file)

    # Insert a photo row with metadata
    conn = open_db(shoot_folder)
    try:
        ensure_schema(conn)
        insert_photo(conn, "ICELAND", "P001ICE.jpg", "P001ICE.jpg", "2026:05:10 14:32:01")
        conn.execute(
            "UPDATE photos SET master_score=?, primary_genre=?, stages=?, needs_review=? "
            "WHERE folder=? AND filename=?",
            (8.5, "landscape", "ingested,scored,named", 1, "ICELAND", "P001ICE.jpg")
        )
        conn.commit()
    finally:
        conn.close()

    info = photo_state.describe_photo(photo_file)

    assert info.path == photo_file
    assert info.master_score == 8.5
    assert info.primary_genre == "landscape"
    assert info.stages == ["ingested", "scored", "named"]
    assert info.needs_review is True
    assert info.darktable_tags == []  # No Darktable state
    assert info.darktable_color_label is None


def test_describe_photo_no_photonforge_row(tmp_path: Path) -> None:
    """describe_photo degrades gracefully when no photonforge.db row exists."""
    cartridge = _cartridge(tmp_path)
    shoot_folder = cartridge / "ICELAND"
    shoot_folder.mkdir()

    photo_file = shoot_folder / "P001ICE.jpg"
    make_jpg(photo_file)

    # Don't insert a row — just call describe_photo
    info = photo_state.describe_photo(photo_file)

    assert info.path == photo_file
    assert info.master_score is None
    assert info.primary_genre == ""
    assert info.stages == []
    assert info.needs_review is False
    assert info.thumbnail_path is None  # Caller fills this in


def test_describe_photo_with_darktable_tags(tmp_path: Path) -> None:
    """describe_photo reads Darktable tags when library.db exists."""
    cartridge = _cartridge(tmp_path)
    shoot_folder = cartridge / "ICELAND"
    shoot_folder.mkdir()

    photo_file = shoot_folder / "P001ICE.jpg"
    make_jpg(photo_file)

    # Create a real Darktable DB pair
    dt_config = cartridge / "dt-config"
    dt_config.mkdir()
    lib_path = dt_config / "library.db"
    data_path = dt_config / "data.db"

    make_real_darktable_db(lib_path, data_path)

    # Insert the photo into Darktable and tag it
    with sqlite3.connect(lib_path) as conn:
        conn.row_factory = sqlite3.Row
        # Insert a film roll at the shoot folder
        cursor = conn.execute(
            "INSERT INTO film_rolls (folder, access_timestamp) VALUES (?, ?)",
            (str(shoot_folder), 0)
        )
        film_id = cursor.lastrowid

        # Insert the image
        cursor = conn.execute(
            "INSERT INTO images (film_id, filename, write_timestamp) VALUES (?, ?, ?)",
            (film_id, photo_file.name, 0)
        )
        image_id = cursor.lastrowid

        # Tag it in data.db
        with sqlite3.connect(data_path) as data_conn:
            data_conn.row_factory = sqlite3.Row
            cursor = data_conn.execute(
                "INSERT INTO tags (name, synonyms, flags) VALUES (?, ?, ?)",
                ("landscape", "", 0)
            )
            tag_id = cursor.lastrowid
            data_conn.commit()

        # Link tag to image in library.db
        conn.execute(
            "INSERT INTO tagged_images (imgid, tagid, position) VALUES (?, ?, ?)",
            (image_id, tag_id, 0)
        )
        conn.commit()

    # Now describe the photo
    info = photo_state.describe_photo(photo_file)

    assert info.darktable_tags == ["landscape"]


def test_describe_photo_with_darktable_color_label(tmp_path: Path) -> None:
    """describe_photo reads Darktable color label when set."""
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

    # Insert photo and set color label
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

        # Set color label
        conn.execute(
            "INSERT INTO color_labels (imgid, color) VALUES (?, ?)",
            (image_id, 3)
        )
        conn.commit()

    info = photo_state.describe_photo(photo_file)

    assert info.darktable_color_label == 3


def test_describe_photo_no_darktable_db(tmp_path: Path) -> None:
    """describe_photo degrades gracefully when no Darktable DB exists."""
    cartridge = _cartridge(tmp_path)
    shoot_folder = cartridge / "ICELAND"
    shoot_folder.mkdir()

    photo_file = shoot_folder / "P001ICE.jpg"
    make_jpg(photo_file)

    # No Darktable DB — just call describe_photo
    info = photo_state.describe_photo(photo_file)

    assert info.darktable_tags == []
    assert info.darktable_color_label is None


def test_get_cached_thumbnail_generates_on_miss(tmp_path: Path) -> None:
    """get_cached_thumbnail generates a JPEG thumbnail and caches it."""
    photo_file = tmp_path / "photo.jpg"
    make_jpg(photo_file)
    cache_dir = tmp_path / "cache"

    result = photo_state.get_cached_thumbnail(photo_file, cache_dir)

    assert result is not None
    assert result.exists()
    assert result.suffix == ".jpg"
    # Verify it's a valid image
    from PIL import Image
    img = Image.open(result)
    assert img.size[0] <= 256 and img.size[1] <= 256


def test_get_cached_thumbnail_cache_hit_no_regenerate(tmp_path: Path) -> None:
    """get_cached_thumbnail returns cached file on second call without regenerating."""
    photo_file = tmp_path / "photo.jpg"
    make_jpg(photo_file)
    cache_dir = tmp_path / "cache"

    # First call: generate
    result1 = photo_state.get_cached_thumbnail(photo_file, cache_dir)

    # Patch load_thumbnail to ensure it's not called on cache hit
    with patch("cartridge_manager.photo_state.load_thumbnail") as mock_load:
        # Second call: should be from cache
        result2 = photo_state.get_cached_thumbnail(photo_file, cache_dir)

    assert result1 == result2
    # load_thumbnail should not have been called (it's mocked and unused)
    assert not mock_load.called


def test_get_cached_thumbnail_invalidates_on_mtime_change(tmp_path: Path) -> None:
    """get_cached_thumbnail regenerates when source file's mtime changes."""
    photo_file = tmp_path / "photo.jpg"
    make_jpg(photo_file)
    cache_dir = tmp_path / "cache"

    # First cache
    result1 = photo_state.get_cached_thumbnail(photo_file, cache_dir)

    # Modify the source file (touch with a future mtime)
    import os

    current_mtime = photo_file.stat().st_mtime
    future_mtime = current_mtime + 10000  # 10k seconds in the future
    os.utime(photo_file, (future_mtime, future_mtime))

    # Second cache should be different (different mtime in filename)
    result2 = photo_state.get_cached_thumbnail(photo_file, cache_dir)

    assert result1 != result2
    assert result1.exists()  # Old cache still there
    assert result2.exists()  # New cache created


def test_get_cached_thumbnail_corrupt_file_returns_none(tmp_path: Path) -> None:
    """get_cached_thumbnail returns None for corrupt/unreadable files."""
    photo_file = tmp_path / "corrupt.jpg"
    photo_file.write_bytes(b"not a valid image")
    cache_dir = tmp_path / "cache"

    result = photo_state.get_cached_thumbnail(photo_file, cache_dir)

    assert result is None


def test_build_gallery_end_to_end(tmp_path: Path) -> None:
    """build_gallery loads and processes a small folder end-to-end."""
    cartridge = _cartridge(tmp_path)
    shoot_folder = cartridge / "ICELAND"
    shoot_folder.mkdir()

    # Create a few test photos
    photos_to_make = [
        shoot_folder / "P001ICE.jpg",
        shoot_folder / "P002ICE.jpg",
        shoot_folder / "P003ICE.jpg",
    ]

    for p in photos_to_make:
        make_jpg(p)

    cache_dir = tmp_path / "cache"

    # Track progress calls
    progress_calls = []
    def track_progress(index: int, total: int, name: str) -> None:
        progress_calls.append((index, total, name))

    gallery = photo_state.build_gallery(shoot_folder, cache_dir, progress=track_progress)

    assert len(gallery) == 3
    # All should have thumbnail_path set (not None)
    for info in gallery:
        assert info.thumbnail_path is not None
        assert info.thumbnail_path.exists()

    # Verify progress was called correctly (1-based index)
    assert len(progress_calls) == 3
    assert progress_calls[0][0] == 1 and progress_calls[0][1] == 3
    assert progress_calls[1][0] == 2 and progress_calls[1][1] == 3
    assert progress_calls[2][0] == 3 and progress_calls[2][1] == 3


def test_build_gallery_empty_folder(tmp_path: Path) -> None:
    """build_gallery handles an empty folder gracefully."""
    empty_folder = tmp_path / "empty"
    empty_folder.mkdir()
    cache_dir = tmp_path / "cache"

    gallery = photo_state.build_gallery(empty_folder, cache_dir)

    assert gallery == []


def test_build_gallery_ignores_corrupt_thumbnails(tmp_path: Path) -> None:
    """build_gallery completes even if one photo's thumbnail fails to generate."""
    shoot_folder = tmp_path / "ICELAND"
    shoot_folder.mkdir()

    # One good photo
    good_photo = shoot_folder / "P001ICE.jpg"
    make_jpg(good_photo)

    # One corrupt photo
    corrupt_photo = shoot_folder / "P002ICE.jpg"
    corrupt_photo.write_bytes(b"not a valid image")

    cache_dir = tmp_path / "cache"

    gallery = photo_state.build_gallery(shoot_folder, cache_dir)

    # Both should be in the gallery
    assert len(gallery) == 2
    # Good photo has thumbnail
    good_info = next(info for info in gallery if info.path == good_photo)
    assert good_info.thumbnail_path is not None
    # Corrupt photo has no thumbnail
    corrupt_info = next(info for info in gallery if info.path == corrupt_photo)
    assert corrupt_info.thumbnail_path is None
