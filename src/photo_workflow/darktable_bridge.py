"""FR-1.8: Sync analyzed photos to Darktable via SQLite + XMP sidecars."""

from __future__ import annotations

import logging
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

XMP_TEMPLATE = """\
<?xpacket begin='\ufeff' id='W5M0MpCehiHzreSzNTczkc9d'?>
<x:xmpmeta xmlns:x='adobe:ns:meta/' x:xmptk='PHOTONForge'>
  <rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
    <rdf:Description rdf:about=''
      xmlns:xmp='http://ns.adobe.com/xap/1.0/'
      xmlns:dc='http://purl.org/dc/elements/1.1/'
      xmlns:photon='https://photonforge.local/xmp/1.0/'>
      <photon:SharpnessScore>{sharpness}</photon:SharpnessScore>
      <photon:CompositionScore>{composition}</photon:CompositionScore>
      <photon:ExposureScore>{exposure}</photon:ExposureScore>
      <photon:SemanticName>{semantic_name}</photon:SemanticName>
      <photon:SessionID>{session_id}</photon:SessionID>
      <photon:IsDuplicate>{is_duplicate}</photon:IsDuplicate>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end='w'?>
"""


def _write_xmp(record) -> None:
    xmp_path = record.path.with_suffix(".xmp")
    xmp_content = XMP_TEMPLATE.format(
        sharpness=record.sharpness_score,
        composition=record.composition_score,
        exposure=record.exposure_score,
        semantic_name=record.semantic_name,
        session_id=record.session_id,
        is_duplicate=str(record.is_duplicate).lower(),
    )
    xmp_path.write_text(xmp_content, encoding="utf-8")


def _upsert_to_darktable(conn: sqlite3.Connection, record) -> None:
    """Insert or update the image record in Darktable's images table."""
    conn.execute(
        """
        INSERT INTO images (filename, folder, flags)
        VALUES (?, ?, 0)
        ON CONFLICT(filename, folder) DO UPDATE SET flags = excluded.flags
        """,
        (record.path.name, str(record.path.parent)),
    )


def sync_to_darktable(records: list, db_path: Path) -> None:
    """
    Write XMP sidecars for all non-duplicate records and upsert into Darktable SQLite.
    """
    xmp_count = 0
    db_count = 0

    for record in records:
        if record.is_duplicate:
            continue
        try:
            _write_xmp(record)
            xmp_count += 1
        except Exception as e:
            logger.error("XMP write failed for %s: %s", record.path, e)

    if db_path.exists():
        try:
            with sqlite3.connect(db_path) as conn:
                for record in records:
                    if record.is_duplicate:
                        continue
                    try:
                        _upsert_to_darktable(conn, record)
                        db_count += 1
                    except Exception as e:
                        logger.error("DB upsert failed for %s: %s", record.path, e)
        except Exception as e:
            logger.error("Darktable DB connection failed: %s", e)
    else:
        logger.warning("Darktable library.db not found at %s — skipping DB sync", db_path)

    logger.info("Darktable sync: %d XMP written, %d DB rows upserted", xmp_count, db_count)
