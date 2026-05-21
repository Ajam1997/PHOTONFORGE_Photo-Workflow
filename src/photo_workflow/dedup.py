"""FR-1.3: Perceptual deduplication using dHash."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DHASH_THRESHOLD = 2  # FR-1.3: Hamming distance <= 2 per spec


def _dhash(path: Path) -> int | None:
    try:
        import imagehash
        import numpy as np
        from .raw_loader import load_thumbnail
        img = load_thumbnail(path)
        h = imagehash.dhash(img)
        flat = h.hash.flatten().astype(np.uint8)
        result = 0
        for bit in flat:
            result = (result << 1) | int(bit)
        return result
    except Exception as e:
        logger.warning("dHash failed for %s: %s", path, e)
        return None


def deduplicate(records: list, progress_fn: object = None) -> list:
    """
    Mark duplicate PhotoRecords using dHash perceptual hashing.
    Within each session, the first occurrence is kept; duplicates are flagged.
    """
    seen: dict[str, dict[int, str]] = {}  # session_id → {hash: path}
    total = len(records)

    for i, rec in enumerate(records):
        if progress_fn and i % 50 == 0:
            progress_fn(i, total)
        h = _dhash(rec.path)
        if h is None:
            continue

        session_seen = seen.setdefault(rec.session_id, {})

        for existing_hash, existing_path in session_seen.items():
            if bin(h ^ existing_hash).count("1") <= DHASH_THRESHOLD:
                rec.is_duplicate = True
                logger.debug("Duplicate: %s ≈ %s", rec.path.name, existing_path)
                break
        else:
            session_seen[h] = str(rec.path)

    dupes = sum(1 for r in records if r.is_duplicate)
    logger.info("Deduplication: %d/%d marked as duplicates", dupes, len(records))
    return records
