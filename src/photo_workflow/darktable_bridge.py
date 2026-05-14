"""FR-1.8: XMP sidecar writer for Darktable integration."""

from __future__ import annotations

import logging
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


def compute_color_label(sharpness: float, composition: float, exposure: float) -> int:
    """Return the Darktable color label int for a set of scores.

    Priority: yellow > blue > purple > green > none. Returns -1 if no label applies.
    """
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
    xmp_content = XMP_TEMPLATE.format(
        sharpness=record.sharpness_score,
        composition=record.composition_score,
        exposure=record.exposure_score,
        semantic_name=record.semantic_name,
        original_filename=original_filename,
        session_id=record.session_id,
        is_duplicate=str(record.is_duplicate).lower(),
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
