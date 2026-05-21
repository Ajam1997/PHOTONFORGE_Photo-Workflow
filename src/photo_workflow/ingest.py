"""FR-1.1: volume ingestion — copy photos from SD/SSD with cartridge-prefix renaming."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

RAW_EXTENSIONS = {".arw", ".cr2", ".cr3", ".nef", ".dng", ".raw", ".orf", ".rw2"}
JPG_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif"}
SUPPORTED_EXTENSIONS = RAW_EXTENSIONS | JPG_EXTENSIONS


def _read_exif_timestamp(path: Path) -> str | None:
    """Read EXIF DateTimeOriginal via exifread. Returns sortable ISO string or None."""
    try:
        import exifread

        with open(path, "rb") as f:
            tags = exifread.process_file(f, stop_tag="EXIF DateTimeOriginal", details=False)
        raw = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
        if raw:
            return str(raw).replace(":", "-", 2)
        return None
    except Exception:
        return None


def get_volume_label(source_dir: Path) -> str:
    """Read the volume label of the drive containing source_dir."""
    from .volume import get_volume_label as _get_label

    return _get_label(source_dir)


def _get_already_ingested(output_dir: Path) -> set[tuple[str, str]]:
    """Check photonforge.db for (original_name, exif_timestamp) pairs already ingested."""
    try:
        from .photondb import open_db, ensure_table, sanitize_table_name

        conn = open_db(output_dir)
        table = sanitize_table_name(output_dir.name)
        ensure_table(conn, table)
        rows = conn.execute(f"SELECT original_name, exif_timestamp FROM [{table}]").fetchall()
        conn.close()
        return {(r[0], r[1] or "") for r in rows}
    except Exception:
        return set()


def ingest_volume(
    source_dir: Path,
    output_dir: Path,
    dry_run: bool = False,
    progress_fn: object = None,
    file_type: str = "both",
) -> list[Path]:
    """Copy photos from source_dir to output_dir with P{CCC}{TTT}{NNNNNNN} naming.

    Files are sorted by EXIF timestamp before sequence assignment.
    Skips files whose original name is already in photonforge.db.
    DB records are written per-file so interrupted ingests can resume.
    """
    from .photondb import open_db, ensure_table, insert_photo
    from .volume import extract_cartridge_id, derive_trip_code, format_photo_name, get_next_sequence

    if file_type == "raw":
        allowed = RAW_EXTENSIONS
    elif file_type == "jpg":
        allowed = JPG_EXTENSIONS
    else:
        allowed = SUPPORTED_EXTENSIONS

    output_dir.mkdir(parents=True, exist_ok=True)

    label = get_volume_label(output_dir)
    cart_id = extract_cartridge_id(label)
    trip_code = derive_trip_code(output_dir.name)

    conn = open_db(output_dir)
    table = output_dir.name
    ensure_table(conn, table)

    sources = sorted(
        p for p in source_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in allowed
    )

    already_ingested = _get_already_ingested(output_dir)

    timed: list[tuple[str, Path]] = []
    for src in sources:
        ts = _read_exif_timestamp(src)
        if (src.name, ts or "") in already_ingested:
            logger.debug("Skipping (already ingested): %s", src.name)
            continue
        timed.append((ts or "9999", src))
    timed.sort(key=lambda x: x[0])

    seq = get_next_sequence(output_dir, cart_id, trip_code)

    total = len(timed)
    copied: list[Path] = []
    for i, (ts, src) in enumerate(timed, 1):
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
        try:
            insert_photo(conn, table, new_name, src.name, exif_ts)
        except Exception as e:
            logger.warning("Could not write DB record for %s: %s", new_name, e)
        seq += 1

        if progress_fn is not None:
            progress_fn(new_name, src.name, i, total)

    conn.close()
    logger.info("Ingested %d files%s", len(copied), " (dry run)" if dry_run else "")
    return copied
