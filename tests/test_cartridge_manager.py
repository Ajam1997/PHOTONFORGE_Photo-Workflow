"""Tests for the cartridge manager tool modules."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("tkinter", reason="cartridge_manager is a Tk app; skip on headless builds")

from tools.cartridge_manager import db_ops, file_ops, sampler, training_io
from tools.cartridge_manager.labeler import LabelStore


# ── Fixtures ─────────────────────────────────────────────


@pytest.fixture
def cartridge(tmp_path: Path) -> Path:
    """Create a minimal cartridge structure with photonforge.db."""
    root = tmp_path / "PHOTON001"
    root.mkdir()
    (root / "darktable").mkdir()
    (root / "photos").mkdir()

    # Init darktable library.db
    dt_conn = sqlite3.connect(str(root / "darktable" / "library.db"))
    dt_conn.executescript("""
        CREATE TABLE images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            folder TEXT NOT NULL DEFAULT '',
            flags INTEGER DEFAULT 0,
            caption TEXT DEFAULT '',
            UNIQUE(filename, folder)
        );
        CREATE TABLE tagged_images (imgid INTEGER, tagid INTEGER, UNIQUE(imgid, tagid));
    """)
    dt_conn.close()

    # Init data.db for darktable 5.x compat
    data_conn = sqlite3.connect(str(root / "darktable" / "data.db"))
    data_conn.execute(
        "CREATE TABLE tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, synonyms TEXT DEFAULT '', flags INTEGER DEFAULT 0)"
    )
    data_conn.close()

    return root


@pytest.fixture
def photon_conn(cartridge: Path) -> sqlite3.Connection:
    conn = db_ops.open_photondb(cartridge)
    yield conn
    conn.close()


def _make_photo(directory: Path, filename: str) -> Path:
    """Create a dummy photo file + XMP sidecar."""
    photo = directory / filename
    photo.write_bytes(b"\x00" * 100)
    xmp = photo.with_suffix(".xmp")
    xmp.write_text("<xmp>test</xmp>", encoding="utf-8")
    return photo


def _seed_table(conn: sqlite3.Connection, table: str, photos: list[dict]) -> None:
    """Insert photo rows into a table."""
    db_ops.create_table(conn, table)
    for p in photos:
        conn.execute(
            f"INSERT INTO [{db_ops.sanitize_table_name(table)}] "
            f"(filename, original_name, genre, master_score, stages, is_duplicate) "
            f"VALUES (?, ?, ?, ?, ?, ?)",
            (
                p["filename"],
                p.get("original_name", p["filename"]),
                p.get("genre", ""),
                p.get("master_score", 0.0),
                p.get("stages", ""),
                p.get("is_duplicate", 0),
            ),
        )
    conn.commit()


# ── db_ops tests ─────────────────────────────────────────


class TestDbOps:
    def test_sanitize_table_name(self):
        assert db_ops.sanitize_table_name("ICELAND") == "ICELAND"
        assert db_ops.sanitize_table_name("my-trip") == "my_trip"
        assert db_ops.sanitize_table_name("") == "default"
        assert db_ops.sanitize_table_name("trip 2024!") == "trip_2024_"

    def test_create_and_list_tables(self, photon_conn):
        db_ops.create_table(photon_conn, "ICELAND")
        db_ops.create_table(photon_conn, "SAFARI")
        tables = db_ops.list_tables(photon_conn)
        assert "ICELAND" in tables
        assert "SAFARI" in tables

    def test_get_table_info(self, photon_conn):
        _seed_table(
            photon_conn,
            "TRIP",
            [
                {"filename": "P001TRP0000001.ARW", "stages": "scan,score,name"},
                {"filename": "P001TRP0000002.ARW", "stages": "scan,score"},
                {"filename": "P001TRP0000003.ARW", "stages": "scan"},
            ],
        )
        info = db_ops.get_table_info(photon_conn, "TRIP")
        assert info.photo_count == 3
        assert info.has_scored == 2
        assert info.has_named == 1

    def test_move_row(self, photon_conn):
        _seed_table(photon_conn, "SRC", [{"filename": "P001SRC0000001.ARW"}])
        db_ops.create_table(photon_conn, "DST")

        db_ops.move_row(photon_conn, "SRC", "DST", "P001SRC0000001.ARW")

        assert db_ops.get_row(photon_conn, "SRC", "P001SRC0000001.ARW") is None
        assert db_ops.get_row(photon_conn, "DST", "P001SRC0000001.ARW") is not None

    def test_move_row_not_found(self, photon_conn):
        _seed_table(photon_conn, "SRC", [])
        db_ops.create_table(photon_conn, "DST")

        with pytest.raises(ValueError, match="not found"):
            db_ops.move_row(photon_conn, "SRC", "DST", "nonexistent.ARW")

    def test_copy_row(self, photon_conn):
        _seed_table(
            photon_conn,
            "SRC",
            [{"filename": "P001SRC0000001.ARW", "master_score": 0.85}],
        )
        db_ops.create_table(photon_conn, "DST")

        db_ops.copy_row(photon_conn, "SRC", "DST", "P001SRC0000001.ARW")

        src_row = db_ops.get_row(photon_conn, "SRC", "P001SRC0000001.ARW")
        dst_row = db_ops.get_row(photon_conn, "DST", "P001SRC0000001.ARW")
        assert src_row is not None
        assert dst_row is not None
        assert dst_row["master_score"] == 0.85

    def test_delete_table(self, photon_conn):
        db_ops.create_table(photon_conn, "TEMP")
        assert "TEMP" in db_ops.list_tables(photon_conn)
        db_ops.delete_table(photon_conn, "TEMP")
        assert "TEMP" not in db_ops.list_tables(photon_conn)

    def test_darktable_folder_update(self, cartridge):
        dt_conn = db_ops.open_darktable_db(cartridge)
        dt_conn.execute(
            "INSERT INTO images (filename, folder) VALUES (?, ?)",
            ("P001ICE0000001.ARW", "ICELAND"),
        )
        dt_conn.commit()

        db_ops.update_darktable_folder(dt_conn, "P001ICE0000001.ARW", "ARCHIVE")
        row = dt_conn.execute(
            "SELECT folder FROM images WHERE filename=?", ("P001ICE0000001.ARW",)
        ).fetchone()
        assert row["folder"] == "ARCHIVE"
        dt_conn.close()


# ── file_ops tests ───────────────────────────────────────


class TestFileOps:
    def test_move_photo_with_sidecar(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()

        _make_photo(src, "P001ICE0000001.ARW")

        moved = file_ops.move_photo(src, dst, "P001ICE0000001.ARW")

        assert len(moved) == 2
        assert (dst / "P001ICE0000001.ARW").exists()
        assert (dst / "P001ICE0000001.xmp").exists()
        assert not (src / "P001ICE0000001.ARW").exists()
        assert not (src / "P001ICE0000001.xmp").exists()

    def test_move_photo_with_darktable_sidecar(self, tmp_path):
        """Darktable creates .ARW.xmp sidecars (appended, not replaced)."""
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()

        photo = src / "P001ICE0000001.ARW"
        photo.write_bytes(b"\x00" * 100)
        # Darktable-style appended sidecar
        dt_xmp = src / "P001ICE0000001.ARW.xmp"
        dt_xmp.write_text("<xmp>darktable</xmp>", encoding="utf-8")

        moved = file_ops.move_photo(src, dst, "P001ICE0000001.ARW")

        assert len(moved) == 2
        assert (dst / "P001ICE0000001.ARW").exists()
        assert (dst / "P001ICE0000001.ARW.xmp").exists()
        assert not (src / "P001ICE0000001.ARW").exists()
        assert not (src / "P001ICE0000001.ARW.xmp").exists()

    def test_move_photo_with_both_sidecar_styles(self, tmp_path):
        """Both PHOTONForge (.xmp) and Darktable (.ARW.xmp) sidecars move."""
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()

        photo = src / "P001ICE0000001.ARW"
        photo.write_bytes(b"\x00" * 100)
        (src / "P001ICE0000001.xmp").write_text("<xmp>photon</xmp>", encoding="utf-8")
        (src / "P001ICE0000001.ARW.xmp").write_text("<xmp>dt</xmp>", encoding="utf-8")

        moved = file_ops.move_photo(src, dst, "P001ICE0000001.ARW")

        assert len(moved) == 3
        assert (dst / "P001ICE0000001.ARW").exists()
        assert (dst / "P001ICE0000001.xmp").exists()
        assert (dst / "P001ICE0000001.ARW.xmp").exists()

    def test_copy_photo_with_sidecar(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()

        _make_photo(src, "P001ICE0000001.ARW")

        copied = file_ops.copy_photo(src, dst, "P001ICE0000001.ARW")

        assert len(copied) == 2
        assert (dst / "P001ICE0000001.ARW").exists()
        assert (src / "P001ICE0000001.ARW").exists()

    def test_move_not_found(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()

        with pytest.raises(FileNotFoundError):
            file_ops.move_photo(src, dst, "nonexistent.ARW")

    def test_move_already_exists(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        dst.mkdir()

        _make_photo(src, "P001ICE0000001.ARW")
        (dst / "P001ICE0000001.ARW").write_bytes(b"existing")

        with pytest.raises(FileExistsError):
            file_ops.move_photo(src, dst, "P001ICE0000001.ARW")

    def test_journal_records_operations(self, tmp_path):
        src = tmp_path / "src"
        dst = tmp_path / "dst"
        src.mkdir()
        _make_photo(src, "test.ARW")

        journal = file_ops.OperationJournal(path=tmp_path / "journal.json")
        file_ops.move_photo(src, dst, "test.ARW", journal=journal)

        assert len(journal.entries) == 2  # .ARW + .xmp
        assert all(e.completed for e in journal.entries)

    def test_journal_load_and_pending(self, tmp_path):
        journal_path = tmp_path / "journal.json"
        journal = file_ops.OperationJournal(path=journal_path)
        entry = journal.add("move", tmp_path / "a.ARW", tmp_path / "b.ARW")
        assert len(journal.pending()) == 1

        loaded = file_ops.OperationJournal.load(journal_path)
        assert len(loaded.pending()) == 1

    def test_list_photos(self, tmp_path):
        _make_photo(tmp_path, "photo1.ARW")
        _make_photo(tmp_path, "photo2.jpg")
        (tmp_path / "readme.txt").write_text("not a photo")

        photos = file_ops.list_photos(tmp_path)
        assert "photo1.ARW" in photos
        assert "photo2.jpg" in photos
        assert "readme.txt" not in photos
        assert "photo1.xmp" not in photos

    def test_create_directory(self, tmp_path):
        new_dir = file_ops.create_directory(tmp_path, "NEW_TRIP")
        assert new_dir.is_dir()
        assert new_dir.name == "NEW_TRIP"


# ── scan & rename tests ─────────────────────────────────


class TestScanAndRename:
    def test_derive_trip_code(self):
        assert file_ops.derive_trip_code("ICELAND") == "ICE"
        assert file_ops.derive_trip_code("My Trip") == "MYT"
        assert file_ops.derive_trip_code("AB") == "ABX"
        assert file_ops.derive_trip_code("a") == "AXX"

    def test_extract_cartridge_id(self):
        assert file_ops.extract_cartridge_id("PHOTONFORGE-003") == "003"
        assert file_ops.extract_cartridge_id("PHOTON-42") == "042"
        assert file_ops.extract_cartridge_id("NOLABEL") == "000"

    def test_format_photo_name(self):
        assert file_ops.format_photo_name("003", "ICE", 1, ".ARW") == "P003ICE0000001.ARW"
        assert file_ops.format_photo_name("001", "TRP", 999, ".jpg") == "P001TRP0000999.jpg"

    def test_scan_and_rename_basic(self, tmp_path):
        folder = tmp_path / "ICELAND"
        folder.mkdir()

        (folder / "IMG_0001.ARW").write_bytes(b"\x00" * 100)
        (folder / "IMG_0002.ARW").write_bytes(b"\x00" * 100)
        (folder / "IMG_0003.jpg").write_bytes(b"\xff\xd8" + b"\x00" * 98)

        result = file_ops.scan_and_rename(
            folder, tmp_path, cart_id="001", trip_code="ICE",
        )

        assert result.renamed == 3
        assert result.already_named == 0
        assert len(result.renames) == 3
        assert (folder / "P001ICE0000001.ARW").exists()
        assert (folder / "P001ICE0000002.ARW").exists()
        assert (folder / "P001ICE0000003.jpg").exists()
        assert not (folder / "IMG_0001.ARW").exists()

    def test_scan_and_rename_skips_already_named(self, tmp_path):
        folder = tmp_path / "TRIP"
        folder.mkdir()

        (folder / "P001TRP0000001.ARW").write_bytes(b"\x00" * 100)
        (folder / "IMG_0099.ARW").write_bytes(b"\x00" * 100)

        result = file_ops.scan_and_rename(
            folder, tmp_path, cart_id="001", trip_code="TRP",
        )

        assert result.already_named == 1
        assert result.renamed == 1
        # Should continue sequence after existing P001TRP0000001
        assert (folder / "P001TRP0000002.ARW").exists()

    def test_scan_and_rename_renames_wrong_trip_code(self, tmp_path):
        """Files with a PHOTONForge name but wrong trip code get re-named."""
        folder = tmp_path / "1TEST"
        folder.mkdir()

        # These have ICE trip code but are in the 1TEST folder (should be TES)
        (folder / "P001ICE0004507.ARW").write_bytes(b"\x00" * 100)
        (folder / "P001ICE0004013.ARW").write_bytes(b"\x00" * 100)

        result = file_ops.scan_and_rename(
            folder, tmp_path, cart_id="001", trip_code="TES",
        )

        assert result.already_named == 0
        assert result.renamed == 2
        assert (folder / "P001TES0000001.ARW").exists()
        assert (folder / "P001TES0000002.ARW").exists()
        assert not (folder / "P001ICE0004507.ARW").exists()

    def test_scan_and_rename_dry_run(self, tmp_path):
        folder = tmp_path / "TEST"
        folder.mkdir()

        (folder / "IMG_0001.ARW").write_bytes(b"\x00" * 100)

        result = file_ops.scan_and_rename(
            folder, tmp_path, cart_id="001", trip_code="TST", dry_run=True,
        )

        assert result.renamed == 1
        assert len(result.renames) == 1
        # File should NOT be renamed
        assert (folder / "IMG_0001.ARW").exists()
        assert not (folder / "P001TST0000001.ARW").exists()

    def test_scan_and_rename_with_sidecars(self, tmp_path):
        folder = tmp_path / "SAFARI"
        folder.mkdir()

        (folder / "DSC_0001.ARW").write_bytes(b"\x00" * 100)
        (folder / "DSC_0001.xmp").write_text("<xmp>photon</xmp>")
        (folder / "DSC_0001.ARW.xmp").write_text("<xmp>dt</xmp>")

        result = file_ops.scan_and_rename(
            folder, tmp_path, cart_id="002", trip_code="SAF",
        )

        assert result.renamed == 1
        assert (folder / "P002SAF0000001.ARW").exists()
        assert (folder / "P002SAF0000001.xmp").exists()
        assert (folder / "P002SAF0000001.ARW.xmp").exists()
        assert not (folder / "DSC_0001.ARW").exists()
        assert not (folder / "DSC_0001.xmp").exists()
        assert not (folder / "DSC_0001.ARW.xmp").exists()

    def test_scan_and_rename_derives_trip_code_from_dir(self, tmp_path):
        folder = tmp_path / "WILDLIFE_TRIP"
        folder.mkdir()

        (folder / "photo.ARW").write_bytes(b"\x00" * 100)

        result = file_ops.scan_and_rename(
            folder, tmp_path, cart_id="005",
        )

        assert result.renamed == 1
        old, new = result.renames[0]
        assert new.startswith("P005WIL")

    def test_scan_and_rename_empty_dir(self, tmp_path):
        folder = tmp_path / "EMPTY"
        folder.mkdir()

        result = file_ops.scan_and_rename(
            folder, tmp_path, cart_id="001", trip_code="EMP",
        )

        assert result.total_found == 0
        assert result.renamed == 0


# ── sampler tests ────────────────────────────────────────


class TestSampler:
    def _seed_photos(self, conn, table, n, genres=None):
        photos = []
        for i in range(n):
            genre = genres[i % len(genres)] if genres else "wildlife"
            photos.append({
                "filename": f"P001TST{i:07d}.ARW",
                "genre": genre,
                "master_score": i / n,
                "stages": "scan,score",
            })
        _seed_table(conn, table, photos)

    def test_random_sample(self, photon_conn):
        self._seed_photos(photon_conn, "SRC", 50)
        result = sampler.random_sample(photon_conn, "SRC", 10, seed=42)
        assert len(result) == 10

    def test_random_sample_with_seed_reproducibility(self, photon_conn):
        self._seed_photos(photon_conn, "SRC", 50)
        r1 = [r["filename"] for r in sampler.random_sample(photon_conn, "SRC", 10, seed=99)]
        r2 = [r["filename"] for r in sampler.random_sample(photon_conn, "SRC", 10, seed=99)]
        assert r1 == r2

    def test_random_sample_n_exceeds_total(self, photon_conn):
        self._seed_photos(photon_conn, "SRC", 5)
        result = sampler.random_sample(photon_conn, "SRC", 100, seed=1)
        assert len(result) == 5

    def test_stratified_sample(self, photon_conn):
        self._seed_photos(
            photon_conn, "SRC", 60,
            genres=["wildlife", "wildlife", "landscape", "portrait"],
        )
        result = sampler.stratified_sample(photon_conn, "SRC", 20, by="genre", seed=42)
        genres = [r["genre"] for r in result]
        assert "wildlife" in genres
        assert "landscape" in genres

    def test_top_bottom_sample(self, photon_conn):
        self._seed_photos(photon_conn, "SRC", 100)
        result = sampler.top_bottom_sample(photon_conn, "SRC", 10, by="master_score")
        scores = [r["master_score"] for r in result]
        assert min(scores) < 0.1
        assert max(scores) > 0.9

    def test_generate_test_dataset(self, photon_conn, cartridge):
        src_dir = cartridge / "SRC"
        src_dir.mkdir()
        photos = []
        for i in range(20):
            fn = f"P001TST{i:07d}.ARW"
            _make_photo(src_dir, fn)
            photos.append({"filename": fn, "master_score": i / 20})
        _seed_table(photon_conn, "SRC", photos)

        manifest = sampler.generate_test_dataset(
            conn=photon_conn,
            src_table="SRC",
            src_dir=src_dir,
            cartridge_root=cartridge,
            n=5,
            strategy="random",
            seed=42,
        )

        assert manifest.n_sampled == 5
        assert manifest.strategy == "random"
        assert manifest.seed == 42

        dataset_dir = cartridge / f"_testset_{manifest.timestamp}"
        assert dataset_dir.is_dir()
        assert (dataset_dir / "manifest.json").exists()

        manifest_data = json.loads((dataset_dir / "manifest.json").read_text())
        assert len(manifest_data["filenames"]) == 5


# ── training_io tests ───────────────────────────────────


def _make_training_db(path: Path, n_corrections: int = 5, genres: list[str] | None = None) -> None:
    """Create a training weights DB with test data."""
    import numpy as np

    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE genre_prototypes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version INTEGER NOT NULL,
            genre TEXT NOT NULL,
            prototype BLOB NOT NULL,
            n_corrections INTEGER DEFAULT 0,
            alpha REAL DEFAULT 1.0,
            created_at TEXT DEFAULT (datetime('now')),
            is_active INTEGER DEFAULT 1,
            UNIQUE(version, genre)
        );
        CREATE TABLE genre_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_path TEXT NOT NULL,
            clip_embedding BLOB NOT NULL,
            aux_features BLOB,
            original_genres TEXT NOT NULL,
            corrected_genres TEXT NOT NULL,
            correction_source TEXT DEFAULT 'darktable',
            corrected_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE genre_adapter (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version INTEGER NOT NULL,
            model_onnx BLOB NOT NULL,
            n_training_samples INTEGER,
            f1_score REAL,
            created_at TEXT DEFAULT (datetime('now')),
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE custom_genres (
            name TEXT PRIMARY KEY,
            first_seen_at TEXT DEFAULT (datetime('now')),
            n_examples INTEGER DEFAULT 0,
            promoted INTEGER DEFAULT 0
        );
    """)

    genres = genres or ["wildlife", "landscape", "portrait"]
    for i, g in enumerate(genres):
        proto = np.random.RandomState(i).randn(512).astype(np.float32)
        conn.execute(
            "INSERT INTO genre_prototypes (version, genre, prototype, n_corrections, alpha) VALUES (?, ?, ?, ?, ?)",
            (1, g, proto.tobytes(), 0, 1.0),
        )

    for i in range(n_corrections):
        emb = np.random.RandomState(100 + i).randn(512).astype(np.float32)
        conn.execute(
            "INSERT INTO genre_corrections (image_path, clip_embedding, original_genres, corrected_genres) "
            "VALUES (?, ?, ?, ?)",
            (f"photo_{i}.ARW", emb.tobytes(), '{"subject": "wildlife"}', '{"subject": "landscape"}'),
        )

    conn.execute("INSERT INTO custom_genres (name, n_examples) VALUES ('astrophoto', 3)")
    conn.commit()
    conn.close()


class TestTrainingIO:
    def test_get_local_stats(self, tmp_path):
        db = tmp_path / "training_weights.db"
        _make_training_db(db)
        stats = training_io.get_local_stats(db)
        assert stats.n_active_prototypes == 3
        assert stats.n_corrections == 5
        assert "astrophoto" in stats.custom_genre_names

    def test_get_local_stats_missing_db(self, tmp_path):
        stats = training_io.get_local_stats(tmp_path / "nonexistent.db")
        assert stats.n_corrections == 0

    def test_export_full_bundle(self, tmp_path):
        db = tmp_path / "training_weights.db"
        _make_training_db(db)

        out = tmp_path / "export.photon-training"
        result = training_io.export_training_bundle(db, out, source_cartridge="PHOTON-001")

        assert result.exists()
        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
            assert "training_weights.db" in names
            assert "manifest.json" in names
            assert "checksums.sha256" in names

            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["source_cartridge"] == "PHOTON-001"
            assert manifest["n_corrections"] == 5

    def test_export_corrections_only(self, tmp_path):
        db = tmp_path / "training_weights.db"
        _make_training_db(db)

        out = tmp_path / "corrections.photon-training"
        result = training_io.export_corrections_only(db, out)

        assert result.exists()
        with zipfile.ZipFile(result) as zf:
            manifest = json.loads(zf.read("manifest.json"))
            assert manifest["type"] == "corrections_only"

            with zf.open("training_weights.db") as f:
                lite_db = tmp_path / "lite_check.db"
                lite_db.write_bytes(f.read())
            conn = sqlite3.connect(str(lite_db))
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            assert "genre_corrections" in tables
            assert "custom_genres" in tables
            assert "genre_prototypes" not in tables
            conn.close()

    def test_preview_import(self, tmp_path):
        local_db = tmp_path / "local.db"
        _make_training_db(local_db, n_corrections=3, genres=["wildlife", "landscape"])

        bundle_db = tmp_path / "bundle_src.db"
        _make_training_db(bundle_db, n_corrections=5, genres=["wildlife", "portrait", "macro"])

        bundle_path = tmp_path / "bundle.photon-training"
        training_io.export_training_bundle(bundle_db, bundle_path)

        preview = training_io.preview_import(bundle_path, local_db)
        assert preview.new_corrections > 0
        assert preview.conflicting_prototypes > 0  # "wildlife" in both
        assert "macro" in preview.new_custom_genres or preview.new_custom_genres == []

    def test_import_replace(self, tmp_path):
        local_db = tmp_path / "local.db"
        _make_training_db(local_db, n_corrections=2)

        bundle_db = tmp_path / "bundle_src.db"
        _make_training_db(bundle_db, n_corrections=10)

        bundle_path = tmp_path / "bundle.photon-training"
        training_io.export_training_bundle(bundle_db, bundle_path)

        stats = training_io.import_training_bundle(bundle_path, local_db, strategy="replace")
        assert stats.n_corrections == 10

    def test_import_merge_corrections(self, tmp_path):
        local_db = tmp_path / "local.db"
        _make_training_db(local_db, n_corrections=3)

        bundle_db = tmp_path / "bundle_src.db"
        _make_training_db(bundle_db, n_corrections=5)

        bundle_path = tmp_path / "bundle.photon-training"
        training_io.export_training_bundle(bundle_db, bundle_path)

        stats = training_io.import_training_bundle(
            bundle_path, local_db, strategy="merge_corrections"
        )
        # Should have local 3 + new ones from bundle (some overlap on image_path)
        assert stats.n_corrections >= 5

    def test_import_merge_all(self, tmp_path):
        local_db = tmp_path / "local.db"
        _make_training_db(local_db, n_corrections=2, genres=["wildlife"])

        bundle_db_path = tmp_path / "bundle_src.db"
        _make_training_db(bundle_db_path, n_corrections=4, genres=["wildlife", "macro"])
        # Bump bundle prototypes to v2
        conn = sqlite3.connect(str(bundle_db_path))
        conn.execute("UPDATE genre_prototypes SET version=2")
        conn.commit()
        conn.close()

        bundle_path = tmp_path / "bundle.photon-training"
        training_io.export_training_bundle(bundle_db_path, bundle_path)

        stats = training_io.import_training_bundle(bundle_path, local_db, strategy="merge_all")
        assert stats.n_corrections >= 4
        assert stats.max_version == 2

    def test_analyze_corpus_basic(self, tmp_path):
        corpus = tmp_path / "labels.jsonl"
        corpus.write_text(
            "\n".join([
                json.dumps({"filename": "a.ARW", "subject": "wildlife", "photo_type": "macro", "source_folder": "TRIP1", "needs_review": False, "labeled_at": "2026-01-01T00:00:00+00:00", "labeler": "alice"}),
                json.dumps({"filename": "b.ARW", "subject": "wildlife", "photo_type": "landscape", "source_folder": "TRIP1", "needs_review": False, "labeled_at": "2026-01-02T00:00:00+00:00", "labeler": "alice"}),
                json.dumps({"filename": "c.ARW", "subject": "people", "photo_type": "portrait", "source_folder": "TRIP2", "needs_review": True, "labeled_at": "2026-01-03T00:00:00+00:00", "labeler": "bob"}),
                json.dumps({"filename": "d.ARW", "subject": "", "photo_type": "", "source_folder": "TRIP2", "needs_review": False, "labeled_at": "2026-01-03T00:00:00+00:00", "labeler": "bob"}),
            ]) + "\n",
            encoding="utf-8",
        )

        stats = training_io.analyze_corpus(corpus)

        assert stats.unique_filenames == 4
        assert stats.subject_counts["wildlife"] == 2
        assert stats.subject_counts["people"] == 1
        assert stats.type_counts["macro"] == 1
        assert stats.type_counts["landscape"] == 1
        assert stats.type_counts["portrait"] == 1
        assert stats.labeler_counts["alice"] == 2
        assert stats.labeler_counts["bob"] == 2
        assert stats.source_folder_counts["TRIP1"] == 2
        assert stats.needs_review_count == 1
        assert stats.unlabeled_count == 1
        assert stats.date_range[0].startswith("2026-01-01")
        assert stats.date_range[1].startswith("2026-01-03")

    def test_analyze_corpus_last_write_wins(self, tmp_path):
        corpus = tmp_path / "labels.jsonl"
        corpus.write_text(
            "\n".join([
                json.dumps({"filename": "a.ARW", "subject": "wildlife", "photo_type": "general", "source_folder": "T", "needs_review": False, "labeled_at": "2026-01-01T00:00:00+00:00", "labeler": "alice"}),
                json.dumps({"filename": "a.ARW", "subject": "people", "photo_type": "portrait", "source_folder": "T", "needs_review": False, "labeled_at": "2026-01-02T00:00:00+00:00", "labeler": "bob"}),
            ]) + "\n",
            encoding="utf-8",
        )

        stats = training_io.analyze_corpus(corpus)

        assert stats.unique_filenames == 1
        assert stats.subject_counts == {"people": 1}
        assert "wildlife" not in stats.subject_counts

    def test_format_corpus_report(self, tmp_path):
        corpus = tmp_path / "labels.jsonl"
        corpus.write_text(
            json.dumps({"filename": "a.ARW", "subject": "wildlife", "photo_type": "macro", "source_folder": "TRIP", "needs_review": False, "labeled_at": "2026-01-01T00:00:00+00:00", "labeler": "alice"}) + "\n",
            encoding="utf-8",
        )

        stats = training_io.analyze_corpus(corpus)
        report = training_io.format_corpus_report(stats)

        assert "CORPUS SUMMARY" in report
        assert "wildlife" in report
        assert "macro" in report
        assert "alice" in report
        assert "TRIP" in report

    def test_export_clean_corpus(self, tmp_path):
        source = tmp_path / "raw.jsonl"
        out = tmp_path / "clean.jsonl"

        source.write_text(
            "\n".join([
                json.dumps({"filename": "a.ARW", "subject": "wildlife", "photo_type": "macro", "source_folder": "T", "needs_review": False, "labeled_at": "2026-01-01", "labeler": "x"}),
                # Duplicate — last-write-wins
                json.dumps({"filename": "a.ARW", "subject": "people", "photo_type": "portrait", "source_folder": "T", "needs_review": False, "labeled_at": "2026-01-02", "labeler": "x"}),
                # Labeled photo
                json.dumps({"filename": "b.ARW", "subject": "cat", "photo_type": "general", "source_folder": "T", "needs_review": False, "labeled_at": "2026-01-02", "labeler": "x"}),
                # Empty / skipped — should be dropped
                json.dumps({"filename": "c.ARW", "subject": "", "photo_type": "", "source_folder": "T", "needs_review": False, "labeled_at": "2026-01-02", "labeler": "x"}),
            ]) + "\n",
            encoding="utf-8",
        )

        result = training_io.export_clean_corpus(source, out)

        assert result.input_records == 4
        assert result.dropped_dupes == 1  # a.ARW overridden
        assert result.dropped_empty == 1  # c.ARW empty subject
        assert result.output_records == 2  # a.ARW (people) + b.ARW

        lines = [l for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2
        recs = [json.loads(l) for l in lines]
        subjects = {r["filename"]: r["subject"] for r in recs}
        assert subjects["a.ARW"] == "people"  # last-write-wins
        assert subjects["b.ARW"] == "cat"

    def test_export_clean_corpus_keeps_review_by_default(self, tmp_path):
        source = tmp_path / "raw.jsonl"
        out = tmp_path / "clean.jsonl"

        source.write_text(
            json.dumps({"filename": "a.ARW", "subject": "wildlife", "photo_type": "macro", "source_folder": "T", "needs_review": True, "labeled_at": "2026-01-01", "labeler": "x"}) + "\n",
            encoding="utf-8",
        )

        result = training_io.export_clean_corpus(source, out, drop_needs_review=False)
        assert result.output_records == 1

        result2 = training_io.export_clean_corpus(source, out, drop_needs_review=True)
        assert result2.output_records == 0

    def test_merge_corpora_basic(self, tmp_path):
        base = tmp_path / "base.jsonl"
        new = tmp_path / "new.jsonl"
        out = tmp_path / "merged.jsonl"

        base.write_text(
            json.dumps({"filename": "a.ARW", "subject": "wildlife", "photo_type": "landscape", "source_folder": "T", "needs_review": False, "labeled_at": "2026-01-01", "labeler": "alice"}) + "\n"
            + json.dumps({"filename": "b.ARW", "subject": "people", "photo_type": "portrait", "source_folder": "T", "needs_review": False, "labeled_at": "2026-01-01", "labeler": "alice"}) + "\n",
            encoding="utf-8",
        )
        new.write_text(
            json.dumps({"filename": "c.ARW", "subject": "cat", "photo_type": "macro", "source_folder": "T", "needs_review": False, "labeled_at": "2026-01-02", "labeler": "bob"}) + "\n",
            encoding="utf-8",
        )

        result = training_io.merge_corpora(base, new, out)

        assert result.base_count == 2
        assert result.new_count == 1
        assert result.added == 1
        assert result.updated == 0
        assert result.merged_count == 3

        lines = [l for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 3

    def test_merge_corpora_last_write_wins(self, tmp_path):
        base = tmp_path / "base.jsonl"
        new = tmp_path / "new.jsonl"
        out = tmp_path / "merged.jsonl"

        base.write_text(
            json.dumps({"filename": "photo1.ARW", "subject": "wildlife", "photo_type": "landscape", "source_folder": "T", "needs_review": False, "labeled_at": "2026-01-01", "labeler": "alice"}) + "\n",
            encoding="utf-8",
        )
        new.write_text(
            json.dumps({"filename": "photo1.ARW", "subject": "people", "photo_type": "portrait", "source_folder": "T", "needs_review": False, "labeled_at": "2026-01-02", "labeler": "bob"}) + "\n",
            encoding="utf-8",
        )

        result = training_io.merge_corpora(base, new, out)

        assert result.updated == 1
        assert result.added == 0
        assert result.merged_count == 1

        rec = json.loads(out.read_text(encoding="utf-8").strip())
        assert rec["subject"] == "people"
        assert rec["labeler"] == "bob"

    def test_merge_corpora_in_place(self, tmp_path):
        base = tmp_path / "corpus.jsonl"
        new = tmp_path / "new.jsonl"

        base.write_text(
            json.dumps({"filename": "a.ARW", "subject": "wildlife", "photo_type": "general", "source_folder": "T", "needs_review": False, "labeled_at": "2026-01-01", "labeler": "x"}) + "\n",
            encoding="utf-8",
        )
        new.write_text(
            json.dumps({"filename": "b.ARW", "subject": "cat", "photo_type": "macro", "source_folder": "T", "needs_review": False, "labeled_at": "2026-01-02", "labeler": "y"}) + "\n",
            encoding="utf-8",
        )

        result = training_io.merge_corpora(base, new)

        assert result.merged_count == 2
        lines = [l for l in base.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2

    def test_checksum_validation(self, tmp_path):
        db = tmp_path / "training_weights.db"
        _make_training_db(db)

        bundle_path = tmp_path / "bundle.photon-training"
        training_io.export_training_bundle(db, bundle_path)

        # Corrupt the bundle
        corrupted = tmp_path / "corrupted.photon-training"
        with zipfile.ZipFile(bundle_path, "r") as zin:
            with zipfile.ZipFile(corrupted, "w") as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == "training_weights.db":
                        data = b"corrupted data"
                    zout.writestr(item, data)

        with pytest.raises(ValueError, match="checksum"):
            training_io.preview_import(corrupted, db)


# ── labeler tests ────────────────────────────────────────


class TestLabelStore:
    def test_commit_and_read(self, tmp_path):
        corpus = tmp_path / "labels.jsonl"
        store = LabelStore(corpus, labeler="test_user")

        store.commit("photo1.ARW", "wildlife", "macro", "TRIP", False)

        assert store.is_labelled("photo1.ARW")
        assert not store.is_labelled("photo2.ARW")

        label = store.current_label("photo1.ARW")
        assert label["subject"] == "wildlife"
        assert label["photo_type"] == "macro"
        assert label["source_folder"] == "TRIP"
        assert label["labeler"] == "test_user"
        assert not label["needs_review"]

    def test_persistence_across_instances(self, tmp_path):
        corpus = tmp_path / "labels.jsonl"

        store1 = LabelStore(corpus, labeler="alice")
        store1.commit("photo1.ARW", "people", "portrait", "TRIP", False)
        store1.commit("photo2.ARW", "cat", "general", "TRIP", False)

        store2 = LabelStore(corpus, labeler="bob")
        assert store2.is_labelled("photo1.ARW")
        assert store2.is_labelled("photo2.ARW")
        assert not store2.is_labelled("photo3.ARW")

    def test_rewind(self, tmp_path):
        corpus = tmp_path / "labels.jsonl"
        store = LabelStore(corpus, labeler="test")

        store.commit("photo1.ARW", "wildlife", "landscape", "TRIP", False)
        store.commit("photo2.ARW", "people", "street", "TRIP", False)

        assert store.is_labelled("photo2.ARW")
        store.rewind("photo2.ARW")
        assert not store.is_labelled("photo2.ARW")
        assert store.is_labelled("photo1.ARW")

        # Verify JSONL file only has photo1
        lines = [
            l for l in corpus.read_text(encoding="utf-8").splitlines() if l.strip()
        ]
        assert len(lines) == 1
        assert json.loads(lines[0])["filename"] == "photo1.ARW"

    def test_needs_review(self, tmp_path):
        corpus = tmp_path / "labels.jsonl"
        store = LabelStore(corpus, labeler="test")
        store.commit("photo1.ARW", "wildlife", "", "TRIP", True)

        label = store.current_label("photo1.ARW")
        assert label["needs_review"] is True

    def test_custom_genre_history(self, tmp_path):
        corpus = tmp_path / "labels.jsonl"
        store = LabelStore(corpus, labeler="test")

        store.record_custom("astrophoto")
        store.record_custom("birding")
        store.record_custom("astrophoto")

        history = store.custom_history()
        assert history[0] == "astrophoto"
        assert history[1] == "birding"
        assert len(history) == 2

    def test_empty_label_still_recorded_if_committed(self, tmp_path):
        """An explicit commit with empty fields is stored (e.g. review marker)."""
        corpus = tmp_path / "labels.jsonl"
        store = LabelStore(corpus, labeler="test")
        store.commit("photo1.ARW", "", "", "TRIP", False)

        assert store.is_labelled("photo1.ARW")
        label = store.current_label("photo1.ARW")
        assert label["subject"] == ""
        assert label["photo_type"] == ""

    def test_corpus_format_compatible_with_label_corpus_script(self, tmp_path):
        """Verify output matches the JSONL format used by scripts/label_corpus.py."""
        corpus = tmp_path / "labels.jsonl"
        store = LabelStore(corpus, labeler="alice")
        store.commit("P001ICE0000001.ARW", "wildlife", "macro", "ICELAND", False)

        line = corpus.read_text(encoding="utf-8").strip()
        rec = json.loads(line)

        assert "filename" in rec
        assert "subject" in rec
        assert "photo_type" in rec
        assert "source_folder" in rec
        assert "labeled_at" in rec
        assert "labeler" in rec
        assert rec["filename"] == "P001ICE0000001.ARW"
        assert rec["subject"] == "wildlife"
        assert rec["photo_type"] == "macro"

    def test_relabel_overwrites_via_last_write_wins(self, tmp_path):
        corpus = tmp_path / "labels.jsonl"
        store = LabelStore(corpus, labeler="test")

        store.commit("photo1.ARW", "wildlife", "landscape", "TRIP", False)
        store.commit("photo1.ARW", "people", "portrait", "TRIP", False)

        label = store.current_label("photo1.ARW")
        assert label["subject"] == "people"
        assert label["photo_type"] == "portrait"

        lines = [
            l for l in corpus.read_text(encoding="utf-8").splitlines() if l.strip()
        ]
        assert len(lines) == 2
