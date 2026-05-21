"""Integration tests for v2 CLI commands using photondb."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

from photo_workflow.pipeline import cli


def _make_jpg(path: Path, dt_str: str = "2026:05:10 14:32:01") -> None:
    arr = np.full((64, 64, 3), 128, dtype=np.uint8)
    img = Image.fromarray(arr)
    exif = img.getexif()
    exif[0x9003] = dt_str
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=95, exif=exif.tobytes())


@pytest.fixture()
def photo_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ICELAND"
    d.mkdir()
    _make_jpg(d / "P003ICE0000001.jpg", "2026:04:01 10:00:00")
    _make_jpg(d / "P003ICE0000002.jpg", "2026:04:01 10:05:00")
    _make_jpg(d / "P003ICE0000003.jpg", "2026:04:01 14:00:00")
    return d


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "photonforge.db"


def test_scan_creates_db_entries(photo_dir: Path, db_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, [
        "scan", "--source", str(photo_dir), "--db", str(db_path),
    ])
    assert result.exit_code == 0, result.output

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM ICELAND").fetchall()
    assert len(rows) == 3
    assert all("scan" in r["stages"] for r in rows)
    conn.close()


def test_dedup_flags_duplicates(photo_dir: Path, db_path: Path):
    import shutil
    shutil.copy2(photo_dir / "P003ICE0000001.jpg", photo_dir / "P003ICE0000004.jpg")

    runner = CliRunner()
    runner.invoke(cli, ["scan", "--source", str(photo_dir), "--db", str(db_path)])
    result = runner.invoke(cli, [
        "dedup", "--db", str(db_path), "--folder", "ICELAND",
        "--source-dir", str(photo_dir),
    ])
    assert result.exit_code == 0, result.output

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM ICELAND WHERE is_duplicate=1").fetchall()
    assert len(rows) >= 1
    conn.close()


def test_score_writes_scores(photo_dir: Path, db_path: Path):
    runner = CliRunner()
    runner.invoke(cli, ["scan", "--source", str(photo_dir), "--db", str(db_path)])
    runner.invoke(cli, ["dedup", "--db", str(db_path), "--folder", "ICELAND",
                        "--source-dir", str(photo_dir)])
    result = runner.invoke(cli, [
        "score", "--db", str(db_path), "--folder", "ICELAND",
        "--source-dir", str(photo_dir),
    ])
    assert result.exit_code == 0, result.output

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT sharpness FROM ICELAND WHERE is_duplicate=0").fetchall()
    assert all(r["sharpness"] is not None for r in rows)
    conn.close()


def test_status_reports(photo_dir: Path, db_path: Path):
    runner = CliRunner()
    runner.invoke(cli, ["scan", "--source", str(photo_dir), "--db", str(db_path)])
    result = runner.invoke(cli, ["status", "--db", str(db_path), "--folder", "ICELAND"])
    assert result.exit_code == 0
    assert "Total photos:" in result.output
