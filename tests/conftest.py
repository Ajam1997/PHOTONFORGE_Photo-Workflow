"""Shared pytest fixtures for photo-workflow tests."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

# Add project root to sys.path so tests can import from scripts/
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def sharp_image(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """256×256 checkerboard PNG — high Laplacian variance (sharp)."""
    p = tmp_path_factory.mktemp("fixtures") / "sharp.png"
    # np.indices returns (2, H, W); summing axis=0 gives a checkerboard of 0/1
    arr = np.indices((256, 256)).sum(axis=0) % 2
    Image.fromarray((arr * 255).astype(np.uint8), mode="L").save(p)
    return p


@pytest.fixture(scope="session")
def blurry_image(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """256×256 solid gray PNG — near-zero Laplacian variance (blurry)."""
    p = tmp_path_factory.mktemp("fixtures") / "blurry.png"
    arr = np.full((256, 256), 128, dtype=np.uint8)
    Image.fromarray(arr, mode="L").save(p)
    return p


def make_darktable_db(path: Path) -> None:
    """Create a minimal Darktable-compatible SQLite DB at path."""
    import sqlite3
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS images (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                folder   TEXT NOT NULL DEFAULT '',
                flags    INTEGER DEFAULT 0,
                caption  TEXT DEFAULT '',
                UNIQUE(filename, folder)
            );
            CREATE TABLE IF NOT EXISTS tags (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT UNIQUE,
                synonyms TEXT DEFAULT '',
                flags    INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS tagged_images (
                imgid  INTEGER,
                tagid  INTEGER,
                UNIQUE(imgid, tagid)
            );
        """)


def make_real_darktable_db(library_path: Path, data_path: Path) -> None:
    """A real-schema Darktable library.db + data.db pair, for relocate.py tests.

    `make_darktable_db` above is NOT this: it's a simplified, non-standard
    schema (images.folder, images.caption — columns real Darktable does not
    have) left over from the deleted Layout-A prototype. It is fine for the
    tag read/write tests that use it, since darktable_bridge.py's queries
    never touch a folder or path column. relocate.py's UPDATE-in-place move
    logic touches images.film_id and film_rolls, which that fixture cannot
    represent at all.

    This fixture's tables were verified against a *real* Darktable 5.6.0
    (the same build the portable-drive plan's Task 7 downloaded and hashed)
    by importing real files under xvfb-run and dumping sqlite_master — not
    hand-guessed. It carries only the columns relocate.py and
    darktable_bridge.py actually touch, not the full ~40-column images
    table (iso/aperture/exposure/... are irrelevant to a move and add
    nothing to test fidelity) — but every column and foreign key it does
    carry (film_rolls.folder, images.film_id/group_id, and the imgid-keyed
    side tables) matches the real names, types, and relationships. If a
    real Darktable becomes available again, regenerate by re-running the
    same xvfb-run import and diffing `sqlite_master.sql`.
    """
    import sqlite3

    with sqlite3.connect(library_path) as conn:
        conn.executescript("""
            CREATE TABLE film_rolls (
                id               INTEGER PRIMARY KEY,
                access_timestamp INTEGER,
                folder           VARCHAR(1024) NOT NULL
            );
            CREATE TABLE images (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                film_id  INTEGER,
                filename VARCHAR,
                write_timestamp INTEGER,
                FOREIGN KEY(film_id) REFERENCES film_rolls(id) ON DELETE CASCADE ON UPDATE CASCADE,
                FOREIGN KEY(group_id) REFERENCES images(id) ON DELETE RESTRICT ON UPDATE CASCADE
            );
            -- Real Darktable columns are (imgid, key, value) for history steps;
            -- kept minimal here (one opaque payload column) since relocate.py
            -- never parses history content, only proves it survives untouched
            -- by imgid across a move.
            CREATE TABLE history (
                imgid   INTEGER,
                num     INTEGER,
                payload TEXT,
                FOREIGN KEY(imgid) REFERENCES images(id) ON DELETE CASCADE
            );
            CREATE TABLE history_hash (
                imgid       INTEGER PRIMARY KEY,
                basic_hash  BLOB,
                auto_hash   BLOB,
                current_hash BLOB,
                FOREIGN KEY(imgid) REFERENCES images(id) ON DELETE CASCADE
            );
            CREATE TABLE masks_history (
                imgid   INTEGER,
                num     INTEGER,
                payload TEXT,
                FOREIGN KEY(imgid) REFERENCES images(id) ON DELETE CASCADE
            );
            CREATE TABLE color_labels (
                imgid INTEGER,
                color INTEGER,
                UNIQUE(imgid, color)
            );
            CREATE TABLE tagged_images (
                imgid    INTEGER,
                tagid    INTEGER,
                position INTEGER,
                UNIQUE(imgid, tagid)
            );
            CREATE TABLE selected_images (
                imgid INTEGER PRIMARY KEY
            );
        """)
    with sqlite3.connect(data_path) as conn:
        conn.executescript("""
            CREATE TABLE tags (
                id       INTEGER PRIMARY KEY,
                name     VARCHAR,
                synonyms VARCHAR,
                flags    INTEGER
            );
        """)


def make_jpg(
    path,
    dt_str: str = "2026:05:10 14:32:01",
    *,
    size: int = 8,
    quality: int = 75,
) -> None:
    """Create a tiny JPEG with EXIF DateTimeOriginal (shared test helper)."""
    import numpy as np
    from PIL import Image

    arr = np.full((size, size, 3), 128, dtype=np.uint8)
    img = Image.fromarray(arr)
    exif = img.getexif()
    exif[0x9003] = dt_str  # DateTimeOriginal
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=quality, exif=exif.tobytes())
