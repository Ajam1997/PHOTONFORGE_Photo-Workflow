"""Integration tests for Stage 6: full pipeline end-to-end."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from photo_workflow.darktable_bridge import validate_xmp
from photo_workflow.pipeline import AnalysisPipeline, PipelineConfig, PipelineSummary
from tests.conftest import make_darktable_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def integration_sd_images(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create 6 synthetic JPEG images on a simulated SD card directory."""
    sd = tmp_path_factory.mktemp("sd_card")

    def save_jpg(arr: np.ndarray, name: str, dt_str: str) -> None:
        p = sd / name
        img = Image.fromarray(arr.astype(np.uint8))
        exif = img.getexif()
        exif[0x0132] = dt_str  # Image DateTime tag (IFD0 tag 0x0132)
        img.save(p, "JPEG", quality=95, exif=exif.tobytes())

    checker = (np.indices((256, 256)).sum(axis=0) % 2 * 255).astype(np.uint8)
    checker_rgb = np.stack([checker, checker, checker], axis=2)
    save_jpg(checker_rgb, "IMG_0001.jpg", "2026:04:01 10:00:00")

    # IMG_0002: byte-identical copy — dHash distance 0
    shutil.copy2(sd / "IMG_0001.jpg", sd / "IMG_0002.jpg")

    gray = np.full((256, 256, 3), 128, dtype=np.uint8)
    save_jpg(gray, "IMG_0003.jpg", "2026:04:01 10:00:10")

    row = np.linspace(0, 255, 256).astype(np.uint8)
    gradient_rgb = np.stack([np.tile(row, (256, 1))] * 3, axis=2)
    save_jpg(gradient_rgb, "IMG_0004.jpg", "2026:04:01 10:00:15")

    # IMG_0005: byte-identical copy of IMG_0001 — dHash distance 0
    shutil.copy2(sd / "IMG_0001.jpg", sd / "IMG_0005.jpg")

    rng = np.random.default_rng(42)
    noise = rng.integers(0, 256, (256, 256, 3), dtype=np.uint8)
    save_jpg(noise, "IMG_0006.jpg", "2026:04:01 14:00:00")

    return sd


def _mock_ingest(source_dir: Path, output_dir: Path, dry_run: bool = False) -> list[Path]:
    """Substitute for rsync: copies JPEGs from source to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for src in sorted(source_dir.glob("*.jpg")):
        dst = output_dir / src.name
        shutil.copy2(src, dst)
        paths.append(dst)
    return paths


def _run_pipeline(
    integration_sd_images: Path,
    tmp_path: Path,
    dry_run: bool = False,
) -> tuple[list, PipelineSummary, Path, Path]:
    """Helper: set up staging dir + DB, run the pipeline, return (records, summary, staging_dir, db_path)."""
    staging_dir = tmp_path / "ssd" / "001" / "staging"
    db_path = tmp_path / "ssd" / "001" / "library.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    make_darktable_db(db_path)

    config = PipelineConfig(
        source_dir=integration_sd_images,
        output_dir=staging_dir,
        darktable_db=db_path,
        model_dir=Path("models"),
        dry_run=dry_run,
    )
    with patch("photo_workflow.ingest.ingest_volume", side_effect=_mock_ingest):
        pipeline = AnalysisPipeline(config)
        records, summary = pipeline.run()

    return records, summary, staging_dir, db_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_integration_record_count(integration_sd_images: Path, tmp_path: Path) -> None:
    """Pipeline processes all 6 fixture images and returns a PipelineSummary."""
    records, summary, _, _ = _run_pipeline(integration_sd_images, tmp_path)
    assert len(records) == 6
    assert summary.total == 6
    assert isinstance(summary.elapsed_seconds, float)
    assert summary.elapsed_seconds >= 0.0


@pytest.mark.integration
def test_integration_duplicate_detection(integration_sd_images: Path, tmp_path: Path) -> None:
    """IMG_0002 and IMG_0005 (both byte-identical copies of IMG_0001) are flagged as duplicates."""
    records, summary, _, _ = _run_pipeline(integration_sd_images, tmp_path)
    by_name = {r.path.name: r for r in records}

    assert by_name["IMG_0002.jpg"].is_duplicate is True
    assert by_name["IMG_0005.jpg"].is_duplicate is True
    assert by_name["IMG_0001.jpg"].is_duplicate is False
    assert by_name["IMG_0003.jpg"].is_duplicate is False
    assert by_name["IMG_0004.jpg"].is_duplicate is False
    assert by_name["IMG_0006.jpg"].is_duplicate is False
    assert summary.duplicates_skipped == 2


@pytest.mark.integration
def test_integration_session_grouping(integration_sd_images: Path, tmp_path: Path) -> None:
    """Images within 30 min share a session; IMG_0006 (4h later) gets its own."""
    records, _, _, _ = _run_pipeline(integration_sd_images, tmp_path)
    by_name = {r.path.name: r for r in records}

    session_a = by_name["IMG_0001.jpg"].session_id
    for name in ("IMG_0001.jpg", "IMG_0002.jpg", "IMG_0003.jpg", "IMG_0004.jpg", "IMG_0005.jpg"):
        assert by_name[name].session_id == session_a, f"{name} should share session with IMG_0001"

    assert by_name["IMG_0006.jpg"].session_id != session_a


@pytest.mark.integration
def test_integration_sharpness_scores(integration_sd_images: Path, tmp_path: Path) -> None:
    """Checkerboard is sharp; solid gray is blurry; duplicates score 0.0 (skipped)."""
    records, _, _, _ = _run_pipeline(integration_sd_images, tmp_path)
    by_name = {r.path.name: r for r in records}

    assert by_name["IMG_0001.jpg"].sharpness_score > 0.5
    assert by_name["IMG_0003.jpg"].sharpness_score < 0.05
    assert by_name["IMG_0002.jpg"].sharpness_score == 0.0
    assert by_name["IMG_0005.jpg"].sharpness_score == 0.0


@pytest.mark.integration
def test_integration_exposure_scores(integration_sd_images: Path, tmp_path: Path) -> None:
    """Gradient (full tonal range) scores higher than solid gray (single zone)."""
    records, _, _, _ = _run_pipeline(integration_sd_images, tmp_path)
    by_name = {r.path.name: r for r in records}

    assert by_name["IMG_0004.jpg"].exposure_score > by_name["IMG_0003.jpg"].exposure_score
    assert by_name["IMG_0003.jpg"].exposure_score < 0.3
    for rec in records:
        assert 0.0 <= rec.exposure_score <= 1.0


@pytest.mark.integration
def test_integration_naming_fallback(integration_sd_images: Path, tmp_path: Path) -> None:
    """Without Florence-2 weights, semantic_name falls back to the file stem."""
    records, _, _, _ = _run_pipeline(integration_sd_images, tmp_path)
    non_dupes = [r for r in records if not r.is_duplicate]
    for rec in non_dupes:
        assert rec.semantic_name == rec.path.stem


@pytest.mark.integration
def test_integration_xmp_sidecars(integration_sd_images: Path, tmp_path: Path) -> None:
    """XMP sidecars are written for non-duplicates and validate correctly."""
    records, summary, _, _ = _run_pipeline(integration_sd_images, tmp_path)
    non_dupes = [r for r in records if not r.is_duplicate]
    dupes = [r for r in records if r.is_duplicate]

    assert summary.xmp_written == len(non_dupes)
    for rec in non_dupes:
        xmp = rec.path.with_suffix(".xmp")
        assert xmp.exists(), f"XMP missing for {rec.path.name}"
        assert validate_xmp(xmp) is True

    for rec in dupes:
        assert not rec.path.with_suffix(".xmp").exists()


@pytest.mark.integration
def test_integration_darktable_db(integration_sd_images: Path, tmp_path: Path) -> None:
    """DB contains 4 rows (non-dupes), with ratings, captions, and session tags."""
    records, summary, _, db_path = _run_pipeline(integration_sd_images, tmp_path)
    non_dupes = [r for r in records if not r.is_duplicate]

    assert summary.db_upserted == len(non_dupes)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT filename, flags, caption FROM images").fetchall()
        tags = conn.execute("SELECT name FROM tags").fetchall()
        tag_links = conn.execute("SELECT COUNT(*) FROM tagged_images").fetchone()[0]

    assert len(rows) == len(non_dupes)
    for _, flags, caption in rows:
        assert 0 <= flags <= 7
        assert caption != ""

    tag_names = {t[0] for t in tags}
    assert any(t.startswith("session:") for t in tag_names)
    assert tag_links == len(non_dupes)


@pytest.mark.integration
def test_integration_idempotent_rerun(integration_sd_images: Path, tmp_path: Path) -> None:
    """Running the pipeline twice upserts cleanly — no duplicate DB rows."""
    records, _, _, db_path = _run_pipeline(integration_sd_images, tmp_path)
    non_dupes = [r for r in records if not r.is_duplicate]

    # Reuse same DB + staging dir, re-run
    staging_dir = tmp_path / "ssd" / "001" / "staging"
    config = PipelineConfig(
        source_dir=integration_sd_images,
        output_dir=staging_dir,
        darktable_db=db_path,
        model_dir=Path("models"),
    )
    with patch("photo_workflow.ingest.ingest_volume", side_effect=_mock_ingest):
        _, _ = AnalysisPipeline(config).run()

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
        tag_count = conn.execute("SELECT COUNT(*) FROM tagged_images").fetchone()[0]

    assert count == len(non_dupes)
    assert tag_count == len(non_dupes)


@pytest.mark.integration
def test_integration_dry_run(integration_sd_images: Path, tmp_path: Path) -> None:
    """Dry-run scores records but writes no XMP files and leaves the DB empty."""
    records, summary, staging_dir, db_path = _run_pipeline(
        integration_sd_images, tmp_path, dry_run=True
    )

    assert isinstance(records, list)
    assert summary.xmp_written == 0
    assert summary.db_upserted == 0

    # No XMP files
    assert list(staging_dir.rglob("*.xmp")) == []

    # DB untouched
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM images").fetchone()[0] == 0
