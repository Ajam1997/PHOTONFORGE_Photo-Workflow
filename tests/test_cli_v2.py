"""Integration tests for v2 CLI commands using photondb."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from photo_workflow.pipeline import cli


from conftest import make_jpg


def _make_jpg(path: Path, dt_str: str = "2026:05:10 14:32:01") -> None:
    make_jpg(path, dt_str, size=64, quality=95)


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
    rows = conn.execute("SELECT * FROM photos WHERE folder='ICELAND'").fetchall()
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
    rows = conn.execute("SELECT * FROM photos WHERE folder='ICELAND' AND is_duplicate=1").fetchall()
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
    rows = conn.execute("SELECT sharpness FROM photos WHERE folder='ICELAND' AND is_duplicate=0").fetchall()
    assert all(r["sharpness"] is not None for r in rows)
    conn.close()


def test_status_reports(photo_dir: Path, db_path: Path):
    runner = CliRunner()
    runner.invoke(cli, ["scan", "--source", str(photo_dir), "--db", str(db_path)])
    result = runner.invoke(cli, ["status", "--db", str(db_path), "--folder", "ICELAND"])
    assert result.exit_code == 0
    assert "Total photos:" in result.output


def test_score_passes_faces_into_fusion(photo_dir: Path, db_path: Path, monkeypatch):
    """Regression: fuse_scores must receive faces/image_gray from the context —
    omitting them silently disabled the eyes-closed gate and face weights."""
    import photo_workflow.score_fusion as sf

    calls: list[dict] = []
    real_fuse = sf.fuse_scores

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return real_fuse(*args, **kwargs)

    monkeypatch.setattr(sf, "fuse_scores", spy)

    runner = CliRunner()
    runner.invoke(cli, ["scan", "--source", str(photo_dir), "--db", str(db_path)])
    result = runner.invoke(cli, [
        "score", "--db", str(db_path), "--folder", "ICELAND",
        "--source-dir", str(photo_dir),
    ])
    assert result.exit_code == 0, result.output
    assert calls, "genre-aware fusion was never reached"
    for kw in calls:
        assert "faces" in kw, "faces not passed to fuse_scores"
        assert kw.get("image_gray") is not None, "image_gray not passed to fuse_scores"


def test_score_skip_genre_preserves_genres(photo_dir: Path, db_path: Path):
    """Regression: --skip-genre crashed on sqlite3.Row.get() and silently fell
    back to legacy scoring, which never updates the master score."""
    import json as _json

    runner = CliRunner()
    runner.invoke(cli, ["scan", "--source", str(photo_dir), "--db", str(db_path)])
    r1 = runner.invoke(cli, [
        "score", "--db", str(db_path), "--folder", "ICELAND",
        "--source-dir", str(photo_dir),
    ])
    assert r1.exit_code == 0, r1.output

    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE photos SET primary_genre='wildlife', "
        "genres='{\"subject\": \"wildlife\", \"photo_type\": \"scenic\"}', "
        "master_score=-1.0 WHERE folder='ICELAND'"
    )
    conn.commit()
    conn.close()

    r2 = runner.invoke(cli, [
        "score", "--db", str(db_path), "--folder", "ICELAND",
        "--source-dir", str(photo_dir), "--force", "--skip-genre",
    ])
    assert r2.exit_code == 0, r2.output

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM photos WHERE folder='ICELAND' AND is_duplicate=0"
    ).fetchall()
    conn.close()
    assert rows
    for r in rows:
        # Legacy fallback never touches master_score; the sentinel surviving
        # means the genre-aware path crashed.
        assert r["master_score"] != -1.0, "skip-genre fell back to legacy scoring"
        assert _json.loads(r["genres"])["subject"] == "wildlife"
