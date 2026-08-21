"""src/photo_workflow/relocate.py — Cartridge Manager plan Task 1.

Real SQLite throughout, against the schema verified by importing real files
into real Darktable (see conftest.make_real_darktable_db) — no mocking the
DB layer. The whole point of this module is that these tables must actually
agree with each other after an operation, which a mock can't prove.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from conftest import make_real_darktable_db

from photo_workflow import relocate
from photo_workflow.photondb import ensure_schema, insert_photo, open_db


def _cartridge(tmp_path: Path, name: str = "PHOTON-001") -> Path:
    root = tmp_path / name
    root.mkdir()
    return root


def _shoot_folder(cartridge_root: Path, folder_name: str, filenames: list[str]) -> Path:
    d = cartridge_root / folder_name
    d.mkdir()
    for fn in filenames:
        (d / fn).write_bytes(f"fake photo bytes for {fn}".encode())
    return d


def _darktable(cartridge_root: Path) -> tuple[Path, Path]:
    dt_config = cartridge_root / "dt-config"
    dt_config.mkdir()
    library_db = dt_config / "library.db"
    data_db = dt_config / "data.db"
    make_real_darktable_db(library_db, data_db)
    return library_db, data_db


def _insert_image(conn: sqlite3.Connection, film_id: int, filename: str,
                  group_id: int | None = None) -> int:
    cur = conn.execute("INSERT INTO images (film_id, filename) VALUES (?, ?)", (film_id, filename))
    image_id = cur.lastrowid
    conn.execute("UPDATE images SET group_id=? WHERE id=?", (group_id or image_id, image_id))
    return image_id


def _ensure_film_roll(conn: sqlite3.Connection, folder: str) -> int:
    row = conn.execute("SELECT id FROM film_rolls WHERE folder=?", (folder,)).fetchone()
    if row:
        return row[0]
    return conn.execute(
        "INSERT INTO film_rolls (folder, access_timestamp) VALUES (?, 0)", (folder,)
    ).lastrowid


def _photonforge_row(cartridge_root: Path, folder: str, filename: str) -> sqlite3.Row | None:
    conn = open_db(cartridge_root / folder)
    ensure_schema(conn)
    row = conn.execute(
        "SELECT * FROM photos WHERE folder=? AND filename=?", (folder, filename)
    ).fetchone()
    conn.close()
    return row


# ---------------------------------------------------------------------------
# Basic single-photo move
# ---------------------------------------------------------------------------


def test_move_single_photo_renames_and_relocates(tmp_path):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root / "ICELAND2"

    result = relocate.move_photos(
        [src / "P001ICE0000001.jpg"], dest, "001", "IC2",
    )

    assert len(result.moved) == 1
    old_path, new_path = result.moved[0]
    assert not old_path.exists()
    assert new_path.exists()
    assert new_path.name == "P001IC20000001.jpg"
    assert new_path.read_bytes() == b"fake photo bytes for P001ICE0000001.jpg"


def test_move_migrates_photonforge_row(tmp_path):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    conn = open_db(src)
    ensure_schema(conn)
    insert_photo(conn, "ICELAND", "P001ICE0000001.jpg", "DSC_0001.ARW", "2026:01:01 12:00:00")
    conn.execute(
        "UPDATE photos SET sharpness=0.9, master_score=4.2 WHERE folder='ICELAND' AND filename='P001ICE0000001.jpg'"
    )
    conn.commit()
    conn.close()

    dest = root / "ICELAND2"
    relocate.move_photos([src / "P001ICE0000001.jpg"], dest, "001", "IC2")

    old_row = _photonforge_row(root, "ICELAND", "P001ICE0000001.jpg")
    assert old_row is None
    new_row = _photonforge_row(root, "ICELAND2", "P001IC20000001.jpg")
    assert new_row is not None
    assert new_row["sharpness"] == 0.9
    assert new_row["master_score"] == 4.2
    assert new_row["original_name"] == "DSC_0001.ARW"


def test_move_without_a_photondb_row_is_not_an_error(tmp_path):
    """A photo that was never scored (no photonforge.db row) is legal to move."""
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root / "ICELAND2"
    result = relocate.move_photos([src / "P001ICE0000001.jpg"], dest, "001", "IC2")
    assert len(result.moved) == 1


# ---------------------------------------------------------------------------
# Darktable row migration, film_roll creation
# ---------------------------------------------------------------------------


def test_move_updates_darktable_row_in_place_new_film_roll(tmp_path):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    library_db, _ = _darktable(root)

    conn = sqlite3.connect(library_db)
    film_id = _ensure_film_roll(conn, str(src))
    image_id = _insert_image(conn, film_id, "P001ICE0000001.jpg")
    conn.commit()
    conn.close()

    dest = root / "ICELAND2"
    relocate.move_photos([src / "P001ICE0000001.jpg"], dest, "001", "IC2")

    conn = sqlite3.connect(library_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
    assert row["filename"] == "P001IC20000001.jpg"
    new_film = conn.execute("SELECT folder FROM film_rolls WHERE id=?", (row["film_id"],)).fetchone()
    assert new_film["folder"] == str(dest.resolve())
    conn.close()


def test_history_tags_and_color_labels_survive_byte_identical(tmp_path):
    """The core safety claim: UPDATE-in-place never orphans anything keyed by imgid."""
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    library_db, data_db = _darktable(root)

    conn = sqlite3.connect(library_db)
    film_id = _ensure_film_roll(conn, str(src))
    image_id = _insert_image(conn, film_id, "P001ICE0000001.jpg")
    conn.execute("INSERT INTO history (imgid, num, payload) VALUES (?, 0, 'exposure=1.2')", (image_id,))
    conn.execute(
        "INSERT INTO history_hash (imgid, basic_hash, auto_hash, current_hash) VALUES (?, ?, ?, ?)",
        (image_id, b"a", b"b", b"c"),
    )
    conn.execute("INSERT INTO color_labels (imgid, color) VALUES (?, 1)", (image_id,))
    conn.commit()
    conn.close()

    data_conn = sqlite3.connect(data_db)
    tag_id = data_conn.execute(
        "INSERT INTO tags (name, synonyms, flags) VALUES ('photon|subject|forest', '', 0)"
    ).lastrowid
    data_conn.commit()
    data_conn.close()
    conn = sqlite3.connect(library_db)
    conn.execute("INSERT INTO tagged_images (imgid, tagid, position) VALUES (?, ?, 0)", (image_id, tag_id))
    conn.commit()
    conn.close()

    dest = root / "ICELAND2"
    relocate.move_photos([src / "P001ICE0000001.jpg"], dest, "001", "IC2")

    conn = sqlite3.connect(library_db)
    conn.row_factory = sqlite3.Row

    # The claim is that THIS SPECIFIC ROW never got deleted+reinserted — so
    # first prove the photo's current id, found independently by looking it
    # up at its new location, is still the exact same id. A delete+reinsert
    # would silently orphan the rows below (still readable by the *old* id,
    # since nothing enforces the FK in this fixture) without this check.
    current = conn.execute(
        "SELECT images.id FROM images JOIN film_rolls ON images.film_id = film_rolls.id "
        "WHERE film_rolls.folder=? AND images.filename=?",
        (str(dest.resolve()), "P001IC20000001.jpg"),
    ).fetchone()
    assert current is not None
    assert current["id"] == image_id, "moved photo got a new imgid — was deleted and reinserted"

    history = conn.execute("SELECT * FROM history WHERE imgid=?", (image_id,)).fetchone()
    assert history["payload"] == "exposure=1.2"
    hh = conn.execute("SELECT * FROM history_hash WHERE imgid=?", (image_id,)).fetchone()
    assert hh["basic_hash"] == b"a"
    color = conn.execute("SELECT * FROM color_labels WHERE imgid=?", (image_id,)).fetchone()
    assert color["color"] == 1
    tagged = conn.execute("SELECT tagid FROM tagged_images WHERE imgid=?", (image_id,)).fetchone()
    assert tagged["tagid"] == tag_id
    conn.close()


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def test_group_moves_together_when_both_requested(tmp_path):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.arw", "P001ICE0000001.jpg"])
    library_db, _ = _darktable(root)

    conn = sqlite3.connect(library_db)
    film_id = _ensure_film_roll(conn, str(src))
    raw_id = _insert_image(conn, film_id, "P001ICE0000001.arw")
    _insert_image(conn, film_id, "P001ICE0000001.jpg", group_id=raw_id)
    conn.commit()
    conn.close()

    dest = root / "ICELAND2"
    result = relocate.move_photos(
        [src / "P001ICE0000001.arw", src / "P001ICE0000001.jpg"], dest, "001", "IC2",
    )
    assert len(result.moved) == 2
    assert not (src / "P001ICE0000001.arw").exists()
    assert not (src / "P001ICE0000001.jpg").exists()


def test_group_conflict_without_ungroup_raises(tmp_path):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.arw", "P001ICE0000001.jpg"])
    library_db, _ = _darktable(root)

    conn = sqlite3.connect(library_db)
    film_id = _ensure_film_roll(conn, str(src))
    raw_id = _insert_image(conn, film_id, "P001ICE0000001.arw")
    _insert_image(conn, film_id, "P001ICE0000001.jpg", group_id=raw_id)
    conn.commit()
    conn.close()

    dest = root / "ICELAND2"
    with pytest.raises(relocate.GroupConflictError, match="P001ICE0000001.jpg"):
        relocate.move_photos([src / "P001ICE0000001.arw"], dest, "001", "IC2")
    # nothing touched
    assert (src / "P001ICE0000001.arw").exists()
    assert (src / "P001ICE0000001.jpg").exists()


def test_ungroup_splits_the_group_and_moves_only_the_requested_photo(tmp_path):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.arw", "P001ICE0000001.jpg"])
    library_db, _ = _darktable(root)

    conn = sqlite3.connect(library_db)
    film_id = _ensure_film_roll(conn, str(src))
    raw_id = _insert_image(conn, film_id, "P001ICE0000001.arw")
    jpg_id = _insert_image(conn, film_id, "P001ICE0000001.jpg", group_id=raw_id)
    conn.commit()
    conn.close()

    dest = root / "ICELAND2"
    relocate.move_photos(
        [src / "P001ICE0000001.arw"], dest, "001", "IC2", ungroup=True,
    )
    assert not (src / "P001ICE0000001.arw").exists()
    assert (src / "P001ICE0000001.jpg").exists()  # sibling stays behind

    conn = sqlite3.connect(library_db)
    conn.row_factory = sqlite3.Row
    raw_row = conn.execute("SELECT * FROM images WHERE id=?", (raw_id,)).fetchone()
    jpg_row = conn.execute("SELECT * FROM images WHERE id=?", (jpg_id,)).fetchone()
    assert raw_row["group_id"] == raw_id  # split out, its own leader now
    assert jpg_row["group_id"] == jpg_id  # repointed to a valid remaining leader
    conn.close()


# ---------------------------------------------------------------------------
# Refusals — must not touch anything
# ---------------------------------------------------------------------------


def test_destination_collision_refuses_cleanly(tmp_path, monkeypatch):
    """get_next_sequence already avoids collisions in the normal case (it scans
    dest_dir first) — force one anyway to prove the defensive check actually
    fires rather than being dead code."""
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    dest = _shoot_folder(root, "ICELAND2", ["P001IC20000001.jpg"])

    monkeypatch.setattr(relocate, "get_next_sequence", lambda *a, **k: 1)
    with pytest.raises(relocate.RelocateError, match="collision"):
        relocate.move_photos([src / "P001ICE0000001.jpg"], dest, "001", "IC2")
    assert (src / "P001ICE0000001.jpg").exists()


def test_busy_cartridge_refuses(tmp_path):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    conn = open_db(src)
    ensure_schema(conn)
    insert_photo(conn, "ICELAND", "P001ICE0000001.jpg", "DSC_0001.ARW", None)
    holder = sqlite3.connect(root / "photonforge.db")
    holder.execute("BEGIN IMMEDIATE")
    try:
        dest = root / "ICELAND2"
        with pytest.raises(relocate.RelocateError):
            relocate.move_photos([src / "P001ICE0000001.jpg"], dest, "001", "IC2")
    finally:
        holder.rollback()
        holder.close()
        conn.close()
    assert (src / "P001ICE0000001.jpg").exists()


def test_insufficient_disk_space_refuses_before_any_copy(tmp_path, monkeypatch):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root / "ICELAND2"

    class _FakeUsage:
        free = 1  # bytes — smaller than any real file

    monkeypatch.setattr(relocate.shutil, "disk_usage", lambda _p: _FakeUsage())
    with pytest.raises(relocate.RelocateError, match="[Nn]ot enough"):
        relocate.move_photos([src / "P001ICE0000001.jpg"], dest, "001", "IC2")
    assert (src / "P001ICE0000001.jpg").exists()
    assert not dest.exists()


def test_cross_cartridge_move_is_not_supported(tmp_path):
    root_a = _cartridge(tmp_path, "PHOTON-001")
    root_b = _cartridge(tmp_path, "PHOTON-002")
    src = _shoot_folder(root_a, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root_b / "ICELAND"

    with pytest.raises(relocate.CrossCartridgeNotSupportedError):
        relocate.move_photos([src / "P001ICE0000001.jpg"], dest, "002", "ICE")
    assert (src / "P001ICE0000001.jpg").exists()


# ---------------------------------------------------------------------------
# dry-run, snapshot
# ---------------------------------------------------------------------------


def test_dry_run_touches_nothing(tmp_path):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root / "ICELAND2"

    result = relocate.move_photos(
        [src / "P001ICE0000001.jpg"], dest, "001", "IC2", dry_run=True,
    )
    assert result.dry_run is True
    assert len(result.moved) == 1
    assert (src / "P001ICE0000001.jpg").exists()
    assert not dest.exists()
    assert not (root / ".photonforge" / relocate.INTENT_LOG_NAME).exists()
    assert not (root / relocate.SNAPSHOT_DIRNAME).exists()


def test_move_takes_a_restorable_snapshot_first(tmp_path):
    from photo_workflow.backup import verify_snapshot

    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    conn = open_db(src)
    ensure_schema(conn)
    insert_photo(conn, "ICELAND", "P001ICE0000001.jpg", "DSC_0001.ARW", None)
    conn.close()

    dest = root / "ICELAND2"
    result = relocate.move_photos([src / "P001ICE0000001.jpg"], dest, "001", "IC2")
    assert result.snapshot is not None
    assert result.snapshot.exists()
    assert verify_snapshot(result.snapshot) == []


# ---------------------------------------------------------------------------
# Crash + resume
# ---------------------------------------------------------------------------


def test_resume_after_crash_between_copy_and_db_update(tmp_path, monkeypatch):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    conn = open_db(src)
    ensure_schema(conn)
    insert_photo(conn, "ICELAND", "P001ICE0000001.jpg", "DSC_0001.ARW", None)
    conn.close()
    dest = root / "ICELAND2"

    def _boom(*a, **k):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(relocate, "_update_photondb", _boom)
    with pytest.raises(RuntimeError, match="simulated crash"):
        relocate.move_photos([src / "P001ICE0000001.jpg"], dest, "001", "IC2")

    # source untouched (copy succeeded, but nothing destructive happened yet)
    assert (src / "P001ICE0000001.jpg").exists()
    assert (dest / "P001IC20000001.jpg").exists()
    intent_log = root / ".photonforge" / relocate.INTENT_LOG_NAME
    assert intent_log.exists()
    state = json.loads(intent_log.read_text())
    assert state["targets"][0]["state"] == "verified"

    monkeypatch.undo()  # restore the real _update_photondb
    result = relocate.resume_move(intent_log)
    assert len(result.moved) == 1
    assert not (src / "P001ICE0000001.jpg").exists()
    assert (dest / "P001IC20000001.jpg").exists()
    assert not intent_log.exists()
    row = _photonforge_row(root, "ICELAND2", "P001IC20000001.jpg")
    assert row is not None


def test_resume_with_nothing_in_progress_is_a_clean_noop(tmp_path):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root / "ICELAND2"
    relocate.move_photos([src / "P001ICE0000001.jpg"], dest, "001", "IC2")

    # a second move attempt while nothing is in-progress must succeed normally
    src2 = _shoot_folder(root, "ICELAND3", ["P001ICE0000002.jpg"])
    result = relocate.move_photos([src2 / "P001ICE0000002.jpg"], dest, "001", "IC2")
    assert len(result.moved) == 1


def test_move_in_progress_refuses_a_second_concurrent_move(tmp_path, monkeypatch):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root / "ICELAND2"

    def _boom(*a, **k):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(relocate, "_update_photondb", _boom)
    with pytest.raises(RuntimeError):
        relocate.move_photos([src / "P001ICE0000001.jpg"], dest, "001", "IC2")
    monkeypatch.undo()

    src2 = _shoot_folder(root, "ICELAND3", ["P001ICE0000002.jpg"])
    with pytest.raises(relocate.MoveInProgressError):
        relocate.move_photos([src2 / "P001ICE0000002.jpg"], dest, "001", "IC2")


# ---------------------------------------------------------------------------
# move_shoot_folder
# ---------------------------------------------------------------------------


def test_move_shoot_folder_moves_every_photo(tmp_path):
    root = _cartridge(tmp_path)
    src = _shoot_folder(
        root, "ICELAND", ["P001ICE0000001.jpg", "P001ICE0000002.jpg", "notes.txt"]
    )
    dest_root = root

    result = relocate.move_shoot_folder(src, dest_root, "001", dest_folder_name="ICELAND2")
    assert len(result.moved) == 2  # notes.txt is not a photo, left alone
    assert (src / "notes.txt").exists()
    assert sorted(p.name for p in (root / "ICELAND2").iterdir()) == [
        "P001ICE0000001.jpg", "P001ICE0000002.jpg",
    ]
