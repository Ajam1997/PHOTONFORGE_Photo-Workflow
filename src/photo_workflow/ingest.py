"""FR-1.1: rsync-triggered volume ingestion."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".raw", ".cr2", ".cr3", ".nef", ".arw", ".dng"}


def ingest_volume(source_dir: Path, output_dir: Path, dry_run: bool = False) -> list[Path]:
    """
    Rsync photos from source_dir (SD/SSD mount) to output_dir.
    Returns list of destination paths for ingested files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "rsync",
        "--archive",
        "--checksum",
        "--include=*/",
    ]
    for ext in SUPPORTED_EXTENSIONS:
        cmd += [f"--include=*{ext}", f"--include=*{ext.upper()}"]
    cmd += ["--exclude=*", "--", str(source_dir) + "/", str(output_dir) + "/"]

    if dry_run:
        cmd.insert(1, "--dry-run")
        logger.info("Dry-run ingest: %s → %s", source_dir, output_dir)

    logger.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("rsync failed:\n%s", result.stderr)
        raise RuntimeError(f"rsync exited with code {result.returncode}")

    ingested = sorted(
        p for p in output_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    logger.info("Ingested %d files", len(ingested))
    return ingested
