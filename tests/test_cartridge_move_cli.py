"""click surface for `photo-cartridge move-photos` / `move-shoot` / `resume-move`."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from click.testing import CliRunner
from conftest import make_real_darktable_db

from photo_workflow import volume
from photo_workflow.cartridge import main
from photo_workflow.photondb import ensure_schema, insert_photo, open_db


def _cartridge(tmp_path: Path, name: str = "PHOTON-001") -> Path:
    root = tmp_path / name
    root.mkdir()
    return root


def _shoot_folder(cartridge_root: Path, folder_name: str, filenames: list[str]) -> Path:
    d = cartridge_root / folder_name
    d.mkdir()
    for fn in filenames:
        (d / fn).write_bytes(f"fake bytes for {fn}".encode())
    return d


def _darktable(cartridge_root: Path) -> tuple[Path, Path]:
    dt_config = cartridge_root / "dt-config"
    dt_config.mkdir()
    library_db = dt_config / "library.db"
    data_db = dt_config / "data.db"
    make_real_darktable_db(library_db, data_db)
    return library_db, data_db


def _insert_image(
    conn: sqlite3.Connection, film_id: int, filename: str, group_id: int | None = None
) -> int:
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


def test_move_photos_with_explicit_cart_id(tmp_path):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root / "ICELAND2"

    result = CliRunner().invoke(
        main,
        [
            "move-photos", str(src / "P001ICE0000001.jpg"),
            "--dest", str(dest), "--cart-id", "001", "--trip-code", "IC2",
        ],
    )
    assert result.exit_code == 0, result.output
    assert not (src / "P001ICE0000001.jpg").exists()
    assert (dest / "P001IC20000001.jpg").exists()


def test_move_photos_auto_detects_cart_id_from_volume_label(tmp_path, monkeypatch):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root / "ICELAND2"
    monkeypatch.setattr(volume, "get_volume_label", lambda _p: "PHOTON-007")

    result = CliRunner().invoke(
        main,
        ["move-photos", str(src / "P001ICE0000001.jpg"), "--dest", str(dest)],
    )
    assert result.exit_code == 0, result.output
    assert (dest / "P007ICE0000001.jpg").exists()


def test_move_photos_json_output(tmp_path):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root / "ICELAND2"
    # A photonforge.db must already exist for the pre-move snapshot to have
    # anything to snapshot — a bare cartridge with no scoring done yet
    # legitimately skips it (see relocate.move_photos's FileNotFoundError
    # handling), so an empty fixture would make `snapshot` correctly None.
    conn = open_db(src)
    ensure_schema(conn)
    insert_photo(conn, "ICELAND", "P001ICE0000001.jpg", "DSC_0001.ARW", "2026:01:01 12:00:00")
    conn.commit()
    conn.close()

    result = CliRunner().invoke(
        main,
        [
            "move-photos", str(src / "P001ICE0000001.jpg"),
            "--dest", str(dest), "--cart-id", "001", "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["step"] == "move-photos"
    assert len(payload["moved"]) == 1
    assert payload["dry_run"] is False
    assert payload["snapshot"] is not None


def test_move_photos_dry_run_touches_nothing(tmp_path):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root / "ICELAND2"

    result = CliRunner().invoke(
        main,
        [
            "move-photos", str(src / "P001ICE0000001.jpg"),
            "--dest", str(dest), "--cart-id", "001", "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert (src / "P001ICE0000001.jpg").exists()
    assert not dest.exists()


def test_move_photos_requires_cart_id_when_no_volume_label(tmp_path, monkeypatch):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root / "ICELAND2"
    monkeypatch.setattr(volume, "get_volume_label", lambda _p: "")

    result = CliRunner().invoke(
        main, ["move-photos", str(src / "P001ICE0000001.jpg"), "--dest", str(dest)],
    )
    assert result.exit_code != 0
    assert "--cart-id" in result.output
    assert "Traceback" not in result.output


def test_move_photos_group_conflict_is_a_clean_error(tmp_path):
    """RelocateError surfaces as a ClickException, not a leaked traceback."""
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
    result = CliRunner().invoke(
        main,
        [
            "move-photos", str(src / "P001ICE0000001.jpg"),
            "--dest", str(dest), "--cart-id", "001",
        ],
    )
    assert result.exit_code != 0
    assert "grouped" in result.output.lower()
    assert "Traceback" not in result.output
    # nothing touched
    assert (src / "P001ICE0000001.arw").exists()
    assert (src / "P001ICE0000001.jpg").exists()


def test_move_photos_cross_cartridge_is_a_clean_error(tmp_path):
    root_a = _cartridge(tmp_path, "PHOTON-001")
    root_b = _cartridge(tmp_path, "PHOTON-002")
    src = _shoot_folder(root_a, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root_b / "ICELAND"

    result = CliRunner().invoke(
        main,
        [
            "move-photos", str(src / "P001ICE0000001.jpg"),
            "--dest", str(dest), "--cart-id", "002",
        ],
    )
    assert result.exit_code != 0
    assert "cartridge" in result.output.lower()
    assert "Traceback" not in result.output


def test_move_shoot_moves_every_photo(tmp_path):
    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg", "P001ICE0000002.jpg"])

    result = CliRunner().invoke(
        main,
        ["move-shoot", str(src), str(root), "--dest-folder-name", "ICELAND2", "--cart-id", "001"],
    )
    assert result.exit_code == 0, result.output
    assert len(list((root / "ICELAND2").iterdir())) == 2


def test_resume_move_completes_an_interrupted_move(tmp_path, monkeypatch):
    from photo_workflow import relocate

    root = _cartridge(tmp_path)
    src = _shoot_folder(root, "ICELAND", ["P001ICE0000001.jpg"])
    dest = root / "ICELAND2"

    def _boom(*a, **k):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(relocate, "_update_photondb", _boom)
    crashed = CliRunner().invoke(
        main,
        [
            "move-photos", str(src / "P001ICE0000001.jpg"),
            "--dest", str(dest), "--cart-id", "001", "--trip-code", "IC2",
        ],
    )
    assert crashed.exit_code != 0
    monkeypatch.undo()

    intent_log = root / ".photonforge" / relocate.INTENT_LOG_NAME
    assert intent_log.exists()

    result = CliRunner().invoke(main, ["resume-move", str(intent_log)])
    assert result.exit_code == 0, result.output
    assert not (src / "P001ICE0000001.jpg").exists()
    assert (dest / "P001IC20000001.jpg").exists()
    assert not intent_log.exists()
