"""FR-1.2: Spatio-temporal clustering of photos into sessions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

SESSION_GAP_MINUTES = 30  # New session if gap between shots exceeds this


def _read_exif_datetime(path: Path) -> datetime | None:
    try:
        import exifread
        with open(path, "rb") as f:
            tags = exifread.process_file(f, stop_tag="EXIF DateTimeOriginal", details=False)
        raw = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
        if raw:
            return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


def cluster_sessions(records: list) -> list:
    """
    Assign session_id to each PhotoRecord based on temporal proximity.
    Records without EXIF timestamps are assigned to a fallback session.
    """
    timed: list[tuple[datetime, object]] = []
    untimed: list[object] = []

    for rec in records:
        dt = _read_exif_datetime(rec.path)
        if dt:
            timed.append((dt, rec))
        else:
            untimed.append(rec)

    timed.sort(key=lambda x: x[0])

    session_idx = 0
    prev_time: datetime | None = None

    for dt, rec in timed:
        if prev_time is None or (dt - prev_time) > timedelta(minutes=SESSION_GAP_MINUTES):
            session_idx += 1
        rec.session_id = f"session_{session_idx:04d}"
        prev_time = dt

    for rec in untimed:
        rec.session_id = "session_0000"

    logger.info("Clustered %d records into %d sessions", len(records), session_idx)
    return records
