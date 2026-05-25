"""FR-1.8: XMP sidecar writer for Darktable integration."""

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
<?xpacket begin='﻿' id='W5M0MpCehiHzreSzNTczkc9d'?>
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
      <photon:OriginalFilename>{original_filename}</photon:OriginalFilename>
      <photon:SessionID>{session_id}</photon:SessionID>
      <photon:IsDuplicate>{is_duplicate}</photon:IsDuplicate>
      <photon:Genre>{genre}</photon:Genre>
      <photon:GenreConfidence>{genre_confidence}</photon:GenreConfidence>
      <photon:MasterScore>{master_score}</photon:MasterScore>
      <photon:Genres>
        <rdf:Bag>{genres_bag}</rdf:Bag>
      </photon:Genres>
      <photon:NeedsReview>{needs_review}</photon:NeedsReview>
      <photon:EyeSharpness>{eye_sharpness}</photon:EyeSharpness>
      <photon:SubjectSharpness>{subject_sharpness}</photon:SubjectSharpness>
      <photon:SubjectIsolation>{subject_isolation}</photon:SubjectIsolation>
      <photon:BlurType>{blur_type}</photon:BlurType>
      <photon:CompositionRoT>{composition_rot}</photon:CompositionRoT>
      <photon:Symmetry>{symmetry}</photon:Symmetry>
      <photon:LeadingLines>{leading_lines}</photon:LeadingLines>
      <photon:NegativeSpace>{negative_space}</photon:NegativeSpace>
      <photon:ZoneEntropy>{zone_entropy}</photon:ZoneEntropy>
      <photon:DynamicRange>{dynamic_range}</photon:DynamicRange>
      <photon:ExposureStyle>{exposure_style}</photon:ExposureStyle>
      <photon:FaceExposure>{face_exposure}</photon:FaceExposure>
      <photon:AestheticScore>{aesthetic_score}</photon:AestheticScore>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end='w'?>
"""

# Darktable color label integers: 0=red, 1=yellow, 2=green, 3=blue, 4=purple, -1=none
_DT_YELLOW = 1
_DT_GREEN  = 2
_DT_BLUE   = 3
_DT_PURPLE = 4
_DT_NONE   = -1

_THRESH_SHARPNESS   = 0.3
_THRESH_EXPOSURE    = 0.5
_THRESH_COMPOSITION = 0.2
_THRESH_GREEN_MEAN  = 0.5


def compute_color_label(
    sharpness: float,
    composition: float | None = None,
    exposure: float | None = None,
    master_score: float | None = None,
    hard_reject: bool = False,
) -> int:
    """Return the Darktable color label int for a set of scores.

    Supports both legacy 3-score mode and new master_score mode.

    Priority (legacy): yellow > blue > purple > green > none. Returns -1 if no label applies.
    Priority (new): hard_reject -> none, master_score -> colors by threshold.
    """
    if master_score is not None:
        if hard_reject:
            return _DT_NONE
        if master_score < 0.3:
            return _DT_YELLOW
        if master_score < 0.5:
            return _DT_NONE
        if master_score < 0.75:
            return _DT_GREEN
        return _DT_BLUE

    if composition is None or exposure is None:
        if sharpness < 0.3:
            return _DT_YELLOW
        if sharpness < 0.5:
            return _DT_NONE
        if sharpness < 0.75:
            return _DT_GREEN
        return _DT_BLUE

    if sharpness < _THRESH_SHARPNESS:
        return _DT_YELLOW
    if exposure < _THRESH_EXPOSURE:
        return _DT_BLUE
    if composition < _THRESH_COMPOSITION:
        return _DT_PURPLE
    mean = (sharpness + composition + exposure) / 3.0
    if mean >= _THRESH_GREEN_MEAN:
        return _DT_GREEN
    return _DT_NONE


def _write_xmp(record: "PhotoRecord") -> None:
    xmp_path = record.path.with_suffix(".xmp")
    original_filename = record.metadata.get("original_filename", record.path.name)
    ss = record.sub_scores

    # Build genres rdf:Bag (multi-genre entries)
    genres_bag = ""
    if hasattr(record, "genres") and record.genres:
        genres_bag = "\n        ".join(
            f'<rdf:li>{g}</rdf:li>' for g, _ in record.genres
        )
    else:
        # Fallback to primary genre
        genres_bag = f'<rdf:li>{record.genre}</rdf:li>'

    needs_review = "true" if getattr(record, "needs_review", False) else "false"

    xmp_content = XMP_TEMPLATE.format(
        sharpness=record.sharpness_score,
        composition=record.composition_score,
        exposure=record.exposure_score,
        semantic_name=record.semantic_name,
        original_filename=original_filename,
        session_id=record.session_id,
        is_duplicate=str(record.is_duplicate).lower(),
        genre=record.genre,
        genre_confidence=record.genre_confidence,
        master_score=record.master_score,
        genres_bag=genres_bag,
        needs_review=needs_review,
        eye_sharpness=ss.get("eye_sharpness", 0.0),
        subject_sharpness=ss.get("subject_sharpness", 0.0),
        subject_isolation=ss.get("subject_isolation", 0.0),
        blur_type=ss.get("blur_type", ""),
        composition_rot=ss.get("composition_rot", 0.0),
        symmetry=ss.get("symmetry", 0.0),
        leading_lines=ss.get("leading_lines", 0.0),
        negative_space=ss.get("negative_space", 0.0),
        zone_entropy=ss.get("zone_entropy", 0.0),
        dynamic_range=ss.get("dynamic_range", 0.0),
        exposure_style=ss.get("exposure_style", ""),
        face_exposure=ss.get("face_exposure", 0.0),
        aesthetic_score=ss.get("aesthetic_clip", 0.0),
    )
    xmp_path.write_text(xmp_content, encoding="utf-8")


def validate_xmp(xmp_path: Path) -> bool:
    """Parse an XMP sidecar and verify it contains required PHOTONForge fields."""
    try:
        tree = ET.parse(xmp_path)
        root = tree.getroot()
        if "xmpmeta" not in root.tag:
            logger.warning("XMP root is not xmpmeta in %s", xmp_path)
            return False
        xml_str = xmp_path.read_text(encoding="utf-8")
        if f"{{{_PHOTON_NS}}}SharpnessScore" not in xml_str and "SharpnessScore" not in xml_str:
            logger.warning("XMP missing SharpnessScore in %s", xmp_path)
            return False
        if "SemanticName" not in xml_str:
            logger.warning("XMP missing SemanticName in %s", xmp_path)
            return False
        score_el = root.find(".//{%s}SharpnessScore" % _PHOTON_NS)
        if score_el is not None and score_el.text is not None:
            float(score_el.text)
        return True
    except ET.ParseError as e:
        logger.warning("XMP parse error in %s: %s", xmp_path, e)
        return False
    except ValueError as e:
        logger.warning("XMP field value error in %s: %s", xmp_path, e)
        return False


def _get_data_db_path(library_db_path: Path) -> Path:
    """Return the path to Darktable's data.db (same directory as library.db).

    Darktable 5.x splits tag storage across two databases:
      library.db  — images, tagged_images (imgid, tagid, position)
      data.db     — tags (id, name, synonyms, flags)
    """
    return library_db_path.parent / "data.db"


def write_darktable_keywords(
    library_db_path: Path,
    filename: str,
    keywords: list[str],
) -> None:
    """Write flat keyword entries to Darktable's databases for a given file.

    Compatible with Darktable 5.x which splits tag storage:
      tags            → data.db   (id, name, synonyms, flags)
      tagged_images   → library.db (imgid, tagid, position)
      images          → library.db

    Uses SQLite ATTACH so both files are accessed in a single connection,
    keeping the writes atomic.

    Args:
        library_db_path: Path to Darktable's library.db
        filename: Image filename (basename only, not full path)
        keywords: List of keyword strings to apply (e.g., ["wildlife", "portrait"])
    """
    data_db_path = _get_data_db_path(library_db_path)
    try:
        conn = sqlite3.connect(str(library_db_path))
        conn.row_factory = sqlite3.Row

        # Attach data.db so we can read/write tags in the same connection
        conn.execute("ATTACH DATABASE ? AS data", (str(data_db_path),))

        # Find the image
        image_row = conn.execute(
            "SELECT id FROM images WHERE filename=?",
            (filename,)
        ).fetchone()

        if not image_row:
            logger.warning("Image not found in Darktable library: %s", filename)
            conn.close()
            return

        image_id = image_row["id"]

        for keyword in keywords:
            # Get or create tag in data.db
            tag_row = conn.execute(
                "SELECT id FROM data.tags WHERE name=?",
                (keyword,)
            ).fetchone()

            if tag_row:
                tag_id = tag_row["id"]
            else:
                conn.execute(
                    "INSERT INTO data.tags (name, synonyms, flags) VALUES (?, '', 0)",
                    (keyword,)
                )
                conn.commit()
                tag_id = conn.execute(
                    "SELECT id FROM data.tags WHERE name=?",
                    (keyword,)
                ).fetchone()["id"]

            # Check if already tagged
            existing = conn.execute(
                "SELECT imgid FROM tagged_images WHERE imgid=? AND tagid=?",
                (image_id, tag_id)
            ).fetchone()

            if not existing:
                conn.execute(
                    "INSERT INTO tagged_images (imgid, tagid, position) VALUES (?, ?, 0)",
                    (image_id, tag_id)
                )
                conn.commit()

        conn.close()
    except Exception as e:
        logger.error("Failed to write Darktable keywords for %s: %s", filename, e)


def read_darktable_keywords(
    library_db_path: Path,
    filename: str,
) -> list[str]:
    """Read flat keyword entries from Darktable's databases for a given file.

    Compatible with Darktable 5.x (tags in data.db, tagged_images in library.db).

    Args:
        library_db_path: Path to Darktable's library.db
        filename: Image filename (basename only)

    Returns:
        List of keyword strings currently tagged on the image.
    """
    data_db_path = _get_data_db_path(library_db_path)
    keywords: list[str] = []
    try:
        conn = sqlite3.connect(str(library_db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("ATTACH DATABASE ? AS data", (str(data_db_path),))

        image_row = conn.execute(
            "SELECT id FROM images WHERE filename=?",
            (filename,)
        ).fetchone()

        if not image_row:
            logger.warning("Image not found in Darktable library: %s", filename)
            conn.close()
            return keywords

        image_id = image_row["id"]

        tag_rows = conn.execute(
            "SELECT data.tags.name FROM data.tags "
            "INNER JOIN tagged_images ON tagged_images.tagid = data.tags.id "
            "WHERE tagged_images.imgid=?",
            (image_id,)
        ).fetchall()

        keywords = [row["name"] for row in tag_rows]
        conn.close()
    except Exception as e:
        logger.error("Failed to read Darktable keywords for %s: %s", filename, e)

    return keywords


def sync_to_darktable(records: list["PhotoRecord"], verbose: bool = False) -> int:
    """Write XMP sidecars for all non-duplicate records. Returns count written."""
    xmp_count = 0
    dup_count = sum(1 for r in records if r.is_duplicate)
    if dup_count > 0:
        logger.info("Skipping %d duplicates for XMP write", dup_count)

    for record in records:
        if record.is_duplicate:
            continue
        try:
            _write_xmp(record)
            xmp_count += 1
            if verbose:
                click.echo(f"  XMP {record.path.name} -> {record.semantic_name}")
        except Exception as e:
            logger.error("XMP write failed for %s: %s", record.path, e)
    logger.info("XMP written: %d", xmp_count)
    return xmp_count


@click.command("darktable-sync")
@click.argument("xmp_dir", type=click.Path(path_type=Path))
@click.option("--dry-run", is_flag=True, help="Validate XMP sidecars without writing.")
def main(xmp_dir: Path, dry_run: bool) -> None:
    """Validate XMP sidecars in XMP_DIR."""
    xmp_files = sorted(xmp_dir.glob("*.xmp"))
    click.echo(f"Found {len(xmp_files)} XMP sidecar(s)")
    for xmp in xmp_files:
        valid = validate_xmp(xmp)
        click.echo(f"  {xmp.name}: {'OK' if valid else 'INVALID'}")
