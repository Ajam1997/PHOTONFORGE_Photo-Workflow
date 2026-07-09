"""FR-1.1: volume ingestion — copy photos from SD/SSD with cartridge-prefix renaming."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from .raw_loader import IMAGE_EXTENSIONS as SUPPORTED_EXTENSIONS
from .raw_loader import JPG_EXTENSIONS, RAW_EXTENSIONS

logger = logging.getLogger(__name__)


def _read_exif_timestamp(path: Path) -> str | None:
    """EXIF DateTimeOriginal as a sortable string, via the shared reader."""
    from .raw_loader import read_exif_datetime

    dt = read_exif_datetime(path)
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


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
        rows = conn.execute(
            "SELECT original_name, exif_timestamp FROM photos WHERE folder=?", (table,)
        ).fetchall()
        conn.close()
        return {(r[0], r[1] or "") for r in rows}
    except Exception:
        return set()


def ingest_volume(
    source_dir: Path,
    output_dir: Path,
    dry_run: bool = False,
    progress_fn: object = None,
    scan_progress_fn: object = None,
    file_type: str = "both",
) -> list[Path]:
    """Copy photos from source_dir to output_dir with P{CCC}{TTT}{NNNNNNN} naming.

    Files are sorted by EXIF timestamp before sequence assignment.
    Skips files whose original name is already in photonforge.db.
    DB records are written per-file so interrupted ingests can resume.

    *scan_progress_fn(done, total)* is called during the EXIF reading
    phase so callers can show progress before copies begin.
    """
    from .photondb import open_db, ensure_table, insert_photo, update_stages
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
    scan_total = len(sources)
    for scan_i, src in enumerate(sources, 1):
        ts = _read_exif_timestamp(src)
        if scan_progress_fn is not None:
            scan_progress_fn(scan_i, scan_total)
        if (src.name, ts or "") in already_ingested:
            logger.debug("Skipping (already ingested): %s", src.name)
            continue
        timed.append((ts or "9999", src))
    timed.sort(key=lambda x: x[0])

    # Clean up interrupted copies from previous runs
    for tmp in output_dir.glob("*.tmp"):
        try:
            tmp.unlink()
        except OSError:
            pass

    seq = get_next_sequence(output_dir, cart_id, trip_code)

    total = len(timed)
    copied: list[Path] = []
    for i, (ts, src) in enumerate(timed, 1):
        # Find a free destination name, retrying THIS source with the next
        # sequence on collision (a collision must never skip the photo).
        while True:
            new_name = format_photo_name(cart_id, trip_code, seq, src.suffix)
            dest = output_dir / new_name
            if not dest.exists():
                break
            seq += 1

        if dry_run:
            copied.append(dest)
            seq += 1
            continue

        # Copy first, record second: a crash between the two re-ingests the
        # file on the next run (harmless duplicate) instead of the DB claiming
        # a photo that was never copied (permanent loss once the SD is wiped).
        temp = dest.with_suffix(dest.suffix + ".tmp")
        shutil.copy2(src, temp)
        with open(temp, "rb+") as f:
            os.fsync(f.fileno())
        temp.rename(dest)
        copied.append(dest)

        exif_ts = ts if ts != "9999" else None
        try:
            insert_photo(conn, table, new_name, src.name, exif_ts)
            update_stages(conn, table, new_name, "scan")
        except Exception as e:
            logger.error(
                "%s copied but DB record failed (%s); it will be re-ingested "
                "under a new name on the next run",
                new_name,
                e,
            )
        seq += 1

        if progress_fn is not None:
            progress_fn(new_name, src.name, i, total)

    conn.close()
    logger.info("Ingested %d files%s", len(copied), " (dry run)" if dry_run else "")
    return copied
