"""FR-1.1: volume ingestion — copy photos from SD/SSD with cartridge-prefix renaming."""

from __future__ import annotations

import logging
import shutil
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
        raw = exif.get(0x9003) or exif.get(0x0132)
        if raw:
            return str(raw).replace(":", "-", 2)
        return None
    except Exception:
        return None


def get_volume_label(source_dir: Path) -> str:
    """Read the volume label of the drive containing source_dir."""
    from .volume import get_volume_label as _get_label

    return _get_label(source_dir)


def _get_already_ingested(output_dir: Path) -> set[str]:
    """Check photonforge.db for original names already ingested into this folder."""
    try:
        from .photondb import open_db, ensure_table, sanitize_table_name

        conn = open_db(output_dir)
        table = sanitize_table_name(output_dir.name)
        ensure_table(conn, table)
        rows = conn.execute(f"SELECT original_name FROM [{table}]").fetchall()
        conn.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


def _record_ingested(output_dir: Path, entries: list[tuple[str, str, str | None]]) -> None:
    """Write ingested file mappings to photonforge.db."""
    try:
        from .photondb import open_db, ensure_table, insert_photo

        conn = open_db(output_dir)
        table = output_dir.name
        ensure_table(conn, table)
        for new_name, original_name, ts in entries:
            insert_photo(conn, table, new_name, original_name, ts)
        conn.close()
    except Exception as e:
        logger.warning("Could not write to photonforge.db: %s", e)


def ingest_volume(source_dir: Path, output_dir: Path, dry_run: bool = False) -> list[Path]:
    """Copy photos from source_dir to output_dir with P{CCC}{TTT}{NNNNNNN} naming.

    Files are sorted by EXIF timestamp before sequence assignment.
    Skips files whose original name is already in photonforge.db.
    """
    from .volume import extract_cartridge_id, derive_trip_code, format_photo_name, get_next_sequence

    output_dir.mkdir(parents=True, exist_ok=True)

    label = get_volume_label(source_dir)
    cart_id = extract_cartridge_id(label)
    trip_code = derive_trip_code(output_dir.name)

    sources = sorted(
        p for p in source_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    already_ingested = _get_already_ingested(output_dir)

    timed: list[tuple[str, Path]] = []
    for src in sources:
        if src.name in already_ingested:
            logger.debug("Skipping (already ingested): %s", src.name)
            continue
        ts = _read_exif_timestamp(src) or "9999"
        timed.append((ts, src))
    timed.sort(key=lambda x: x[0])

    seq = get_next_sequence(output_dir, cart_id, trip_code)

    copied: list[Path] = []
    db_entries: list[tuple[str, str, str | None]] = []
    for ts, src in timed:
        new_name = format_photo_name(cart_id, trip_code, seq, src.suffix)
        dest = output_dir / new_name

        if dest.exists():
            seq += 1
            continue

        if dry_run:
            copied.append(dest)
            seq += 1
            continue

        shutil.copy2(src, dest)
        copied.append(dest)
        exif_ts = ts if ts != "9999" else None
        db_entries.append((new_name, src.name, exif_ts))
        seq += 1

    if db_entries and not dry_run:
        _record_ingested(output_dir, db_entries)

    logger.info("Ingested %d files%s", len(copied), " (dry run)" if dry_run else "")
    return copied
