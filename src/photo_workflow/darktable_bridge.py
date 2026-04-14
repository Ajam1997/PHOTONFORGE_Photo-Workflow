"""FR-1.8: Sync analyzed photos to Darktable via SQLite + XMP sidecars."""

from __future__ import annotations

import logging
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from .pipeline import PhotoRecord

logger = logging.getLogger(__name__)

_PHOTON_NS = "https://photonforge.local/xmp/1.0/"

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


def _write_xmp(record: "PhotoRecord") -> None:
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


def validate_xmp(xmp_path: Path) -> bool:
    """
    Parse an XMP sidecar and verify it contains required PHOTONForge fields.
    Returns True if valid, False otherwise.
    """
    try:
        tree = ET.parse(xmp_path)
        root = tree.getroot()
        # Root tag must be xmpmeta (any namespace prefix)
        if "xmpmeta" not in root.tag:
            logger.warning("XMP root is not xmpmeta in %s", xmp_path)
            return False

        xml_str = xmp_path.read_text(encoding="utf-8")
        # Check required fields are present in the raw text (namespace-agnostic)
        if f"{{{_PHOTON_NS}}}SharpnessScore" not in xml_str and "SharpnessScore" not in xml_str:
            logger.warning("XMP missing SharpnessScore in %s", xmp_path)
            return False
        if "SemanticName" not in xml_str:
            logger.warning("XMP missing SemanticName in %s", xmp_path)
            return False

        # Verify SharpnessScore is parseable as float
        ns = {"photon": _PHOTON_NS}
        score_el = root.find(".//{%s}SharpnessScore" % _PHOTON_NS)
        if score_el is not None and score_el.text is not None:
            float(score_el.text)  # raises ValueError if malformed

        return True

    except ET.ParseError as e:
        logger.warning("XMP parse error in %s: %s", xmp_path, e)
        return False
    except ValueError as e:
        logger.warning("XMP field value error in %s: %s", xmp_path, e)
        return False


def _upsert_to_darktable(conn: sqlite3.Connection, record: "PhotoRecord") -> None:
    """Insert or update the image record in Darktable's images table."""
    mean_score = (
        record.sharpness_score + record.composition_score + record.exposure_score
    ) / 3.0
    stars = round(mean_score * 5)
    flags = int(stars) & 0x07  # low 3 bits = star rating (0–5)

    conn.execute(
        """
        INSERT INTO images (filename, folder, flags, caption)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(filename, folder) DO UPDATE SET
            flags = excluded.flags,
            caption = excluded.caption
        """,
        (record.path.name, str(record.path.parent), flags, record.semantic_name),
    )


def _upsert_tags(conn: sqlite3.Connection, record: "PhotoRecord", img_id: int) -> None:
    """Create a session tag and link it to the image in tagged_images."""
    tag_name = f"session:{record.session_id}"
    conn.execute(
        "INSERT OR IGNORE INTO tags (name, synonyms, flags) VALUES (?, '', 0)",
        (tag_name,),
    )
    row = conn.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()
    if row is None:
        return
    tag_id: int = row[0]
    conn.execute(
        "INSERT OR IGNORE INTO tagged_images (imgid, tagid) VALUES (?, ?)",
        (img_id, tag_id),
    )


def sync_to_darktable(records: list["PhotoRecord"], db_path: Path) -> tuple[int, int]:
    """
    Write XMP sidecars for all non-duplicate records and upsert into Darktable SQLite.
    Ratings (star score) and session tags are written alongside each record.
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
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                for record in records:
                    if record.is_duplicate:
                        continue
                    try:
                        _upsert_to_darktable(conn, record)
                        row = conn.execute(
                            "SELECT id FROM images WHERE filename = ? AND folder = ?",
                            (record.path.name, str(record.path.parent)),
                        ).fetchone()
                        if row is not None:
                            _upsert_tags(conn, record, row[0])
                        db_count += 1
                    except Exception as e:
                        logger.error("DB upsert failed for %s: %s", record.path, e)
        except Exception as e:
            logger.error("Darktable DB connection failed: %s", e)
    else:
        logger.warning("Darktable library.db not found at %s — skipping DB sync", db_path)

    logger.info("Darktable sync: %d XMP written, %d DB rows upserted", xmp_count, db_count)
    return xmp_count, db_count


@click.command("darktable-sync")
@click.argument("db_path", type=click.Path(path_type=Path))
@click.option("--dry-run", is_flag=True, help="Validate XMP sidecars without writing to DB.")
def main(db_path: Path, dry_run: bool) -> None:
    """Validate XMP sidecars in the current directory and optionally sync to Darktable DB."""
    xmp_files = sorted(Path(".").glob("*.xmp"))
    click.echo(f"Found {len(xmp_files)} XMP sidecar(s)")
    for xmp in xmp_files:
        valid = validate_xmp(xmp)
        status = "OK" if valid else "INVALID"
        click.echo(f"  {xmp.name}: {status}")
    if not dry_run:
        click.echo(f"DB sync target: {db_path} (use sync_to_darktable() API for full sync)")
