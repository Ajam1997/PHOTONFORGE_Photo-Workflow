"""Shared pytest fixtures for photo-workflow tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image


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
