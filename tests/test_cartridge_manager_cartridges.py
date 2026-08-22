"""Backend cartridge introspection tests — no GUI dependency."""

from __future__ import annotations

import os
from pathlib import Path

from conftest import make_real_darktable_db

from cartridge_manager import cartridges
from photo_workflow.photondb import ensure_schema, open_db


def _cartridge(tmp_path: Path, name: str = "PHOTON-001") -> Path:
    """Create a bare cartridge root directory."""
    root = tmp_path / name
    root.mkdir()
    return root


def test_describe_bare_cartridge(tmp_path: Path) -> None:
    """A bare cartridge root (no DBs) has proper defaults."""
    root = _cartridge(tmp_path)

    info = cartridges.describe(root)

    assert info.root == root
    assert info.label == ""
    assert info.cart_id == ""
    assert info.busy_reason is None
    assert info.has_photonforge_db is False
    assert info.has_darktable is False
    assert info.free_bytes > 0
    assert info.total_bytes > 0


def test_describe_with_photonforge_db(tmp_path: Path) -> None:
    """Describe recognizes a real photonforge.db."""
    root = _cartridge(tmp_path)

    # Create a real photonforge.db
    # open_db expects a folder path and creates the DB at parent / "photonforge.db"
    conn = open_db(root / "ICELAND")
    ensure_schema(conn)
    conn.close()

    info = cartridges.describe(root)

    assert info.has_photonforge_db is True
    assert info.has_darktable is False


def test_describe_with_darktable_db(tmp_path: Path) -> None:
    """Describe recognizes a real Darktable dt-config layout."""
    root = _cartridge(tmp_path)

    # Create real Darktable databases
    dt_config = root / "dt-config"
    dt_config.mkdir()
    make_real_darktable_db(dt_config / "library.db", dt_config / "data.db")

    info = cartridges.describe(root)

    assert info.has_darktable is True
    assert info.has_photonforge_db is False


def test_describe_detects_busy(tmp_path: Path) -> None:
    """Describe detects a busy cartridge via a live PID lock file."""
    root = _cartridge(tmp_path)

    # Write the current test process's PID to a lock file
    pid = os.getpid()
    (root / "test.pid").write_text(str(pid))

    info = cartridges.describe(root)

    # Should detect the lock file and report busy
    assert info.busy_reason is not None
    assert "test.pid" in info.busy_reason
    assert str(pid) in info.busy_reason


def test_describe_nonexistent_path() -> None:
    """Describe a path that doesn't exist: gracefully degrade."""
    nonexistent = Path("/does/not/exist/PHOTON-999")

    info = cartridges.describe(nonexistent)

    # Should not raise; free/total default to 0
    assert info.root == nonexistent
    assert info.label == ""
    assert info.cart_id == ""
    assert info.free_bytes == 0
    assert info.total_bytes == 0
    assert info.busy_reason is None
    assert info.has_photonforge_db is False
    assert info.has_darktable is False
