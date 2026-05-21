"""FR-1.1: volume ingestion — copy photos from SD/SSD with cartridge-prefix renaming."""

from __future__ import annotations

import hashlib
import logging
import shutil
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    ".arw", ".cr2", ".cr3", ".nef", ".dng", ".raw", ".orf", ".rw2",
    ".jpg", ".jpeg", ".png", ".tiff", ".tif",
}


def _read_exif_timestamp(path: Path) -> str | None:
    """Read EXIF DateTimeOriginal. Returns sortable string or None."""
    try:
        from PIL import Image

        img = Image.open(path)
        exif = img.getexif()
        raw = exif.get(0x9003) or exif.get(0x0132)  # DateTimeOriginal or DateTime
        if raw:
            return str(raw).replace(":", "-", 2)
        return None
    except Exception:
        return None


def _sha256_file(path: Path) -> str:
    """Compute SHA256 hash of file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_volume_label(source_dir: Path) -> str:
    """Read the volume label of the drive containing source_dir."""
    from .volume import get_volume_label as _get_label

    return _get_label(source_dir)


def ingest_volume(source_dir: Path, output_dir: Path, dry_run: bool = False) -> list[Path]:
    """Copy photos from source_dir to output_dir with P{CCC}{TTT}{NNNNNNN} naming.

    Files are sorted by EXIF timestamp before sequence assignment.
    Tracks ingested files in photonforge.db to avoid re-copying.
    """
    from .volume import derive_trip_code, extract_cartridge_id, format_photo_name, get_next_sequence

    output_dir.mkdir(parents=True, exist_ok=True)

    label = get_volume_label(source_dir)
    cart_id = extract_cartridge_id(label)
    trip_code = derive_trip_code(output_dir.name)

    sources = sorted(
        p for p in source_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    # Initialize database for tracking ingested file hashes (only if not dry_run)
    db_path = output_dir / "photonforge.db"
    conn: sqlite3.Connection | None = None
    ingested_hashes: set[str] = set()

    if not dry_run:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ingested (
                file_hash TEXT PRIMARY KEY,
                dest_name TEXT NOT NULL
            )
        """)
        conn.commit()

        # Build set of already-ingested file hashes
        cursor.execute("SELECT file_hash FROM ingested")
        ingested_hashes = {row[0] for row in cursor.fetchall()}

    # Sort by EXIF timestamp for consistent sequence assignment
    timed: list[tuple[str, Path]] = []
    for src in sources:
        ts = _read_exif_timestamp(src) or "9999"
        timed.append((ts, src))
    timed.sort(key=lambda x: x[0])

    seq = get_next_sequence(output_dir, cart_id, trip_code)

    copied: list[Path] = []
    for _, src in timed:
        file_hash = _sha256_file(src)

        # Skip if already ingested
        if file_hash in ingested_hashes:
            logger.debug("Skipping (already ingested): %s", src.name)
            continue

        new_name = format_photo_name(cart_id, trip_code, seq, src.suffix)
        dest = output_dir / new_name

        if dry_run:
            copied.append(dest)
            seq += 1
            continue

        shutil.copy2(src, dest)
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO ingested (file_hash, dest_name) VALUES (?, ?)",
                (file_hash, new_name),
            )
            conn.commit()
        copied.append(dest)
        seq += 1
        logger.debug("Copied: %s -> %s", src.name, new_name)

    if conn is not None:
        conn.close()
    logger.info("Ingested %d files%s", len(copied), " (dry run)" if dry_run else "")
    return copied
