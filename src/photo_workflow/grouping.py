"""FR-1.2: Spatio-temporal clustering of photos into sessions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

SESSION_GAP_MINUTES = 30  # New session if gap between shots exceeds this


from .raw_loader import read_exif_datetime  # noqa: F401  (re-exported: public API)


def cluster_sessions(
    records: list,
    timestamps: dict[str, datetime] | None = None,
) -> list:
    """
    Assign session_id to each PhotoRecord based on temporal proximity.
    Records without EXIF timestamps are assigned to a fallback session.

    If *timestamps* is provided (filename → datetime), uses those instead
    of re-reading EXIF from disk — much faster when timestamps are already
    in the DB from the scan step.
    """
    timed: list[tuple[datetime, object]] = []
    untimed: list[object] = []

    for rec in records:
        if timestamps is not None:
            dt = timestamps.get(rec.path.name)
        else:
            dt = read_exif_datetime(rec.path)
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
