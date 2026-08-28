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

# Hierarchical tag prefixes — the cross-language protocol with the Lua plugin
# (lua/photonforge/tag_manager.lua keeps matching copies).
PHOTON_SUBJECT_PREFIX = "photon|subject|"
PHOTON_TYPE_PREFIX = "photon|type|"

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

def xmp_sidecar_path(photo_path: Path) -> Path:
    """Sidecar path in Darktable's convention: IMG_0001.ARW -> IMG_0001.ARW.xmp.

    Replacing the extension instead (IMG_0001.xmp) made RAW+JPEG pairs clobber
    each other's sidecar, and Darktable never associated the file anyway.
    """
    return photo_path.with_name(photo_path.name + ".xmp")


def _xml_escape(value: object) -> str:
    from xml.sax.saxutils import escape

    return escape(str(value), {'"': "&quot;"})


_RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_XPACKET_HEADER = "<?xpacket begin='﻿' id='W5M0MpCehiHzreSzNTczkc9d'?>"
_XPACKET_FOOTER = "<?xpacket end='w'?>"


def _photon_properties(record: "PhotoRecord") -> tuple[list[tuple[str, str]], list[str]]:
    """Photon property values in template order, plus the Genres bag entries.

    Single source for both write paths so the merged sidecar and the fresh
    template can never drift apart.
    """
    original_filename = record.metadata.get("original_filename", record.path.name)
    ss = record.sub_scores
    if getattr(record, "genres", None):
        genres = [str(g) for g, _ in record.genres]
    else:
        genres = [str(record.genre)]
    props = [
        ("SharpnessScore", str(record.sharpness_score)),
        ("CompositionScore", str(record.composition_score)),
        ("ExposureScore", str(record.exposure_score)),
        ("SemanticName", str(record.semantic_name)),
        ("OriginalFilename", str(original_filename)),
        ("SessionID", str(record.session_id)),
        ("IsDuplicate", str(record.is_duplicate).lower()),
        ("Genre", str(record.genre)),
        ("GenreConfidence", str(record.genre_confidence)),
        ("MasterScore", str(record.master_score)),
        ("NeedsReview", "true" if getattr(record, "needs_review", False) else "false"),
        ("EyeSharpness", str(ss.get("eye_sharpness", 0.0))),
        ("SubjectSharpness", str(ss.get("subject_sharpness", 0.0))),
        ("SubjectIsolation", str(ss.get("subject_isolation", 0.0))),
        ("BlurType", str(ss.get("blur_type", ""))),
        ("CompositionRoT", str(ss.get("composition_rot", 0.0))),
        ("Symmetry", str(ss.get("symmetry", 0.0))),
        ("LeadingLines", str(ss.get("leading_lines", 0.0))),
        ("NegativeSpace", str(ss.get("negative_space", 0.0))),
        ("ZoneEntropy", str(ss.get("zone_entropy", 0.0))),
        ("DynamicRange", str(ss.get("dynamic_range", 0.0))),
        ("ExposureStyle", str(ss.get("exposure_style", ""))),
        ("FaceExposure", str(ss.get("face_exposure", 0.0))),
        ("AestheticScore", str(ss.get("aesthetic_clip", 0.0))),
    ]
    return props, genres


def _atomic_write_text(path: Path, content: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _merge_photon_into_sidecar(
    xmp_path: Path, props: list[tuple[str, str]], genres: list[str]
) -> str | None:
    """Return the existing sidecar with only the photon:* block replaced.

    Everything outside the photon namespace — darktable:history_*, xmp:Rating,
    masks, unknown namespaces — is preserved. Returns None if the file cannot
    be parsed, so the caller can fall back safely.

    Serialization notes: ElementTree hoists all xmlns declarations onto the
    root element (semantically identical XML; exiv2/darktable parse it fine),
    and prefixes are kept by registering every declaration found in the file.
    """
    import re

    try:
        text = xmp_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for prefix, uri in re.findall(
        r'xmlns:([A-Za-z_][\w.-]*)\s*=\s*["\']([^"\']+)["\']', text
    ):
        if prefix != "xml":
            ET.register_namespace(prefix, uri)
    ET.register_namespace("photon", _PHOTON_NS)
    try:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
        root = ET.fromstring(text, parser=parser)
    except ET.ParseError:
        return None
    if "xmpmeta" not in root.tag:
        return None
    desc = root.find(f".//{{{_RDF_NS}}}Description")
    if desc is None:
        return None

    photon_clark = f"{{{_PHOTON_NS}}}"
    for child in list(desc):
        if isinstance(child.tag, str) and child.tag.startswith(photon_clark):
            desc.remove(child)
    for attr in [a for a in desc.attrib if a.startswith(photon_clark)]:
        del desc.attrib[attr]

    new_elems: list[ET.Element] = []
    for name, value in props:
        el = ET.Element(f"{photon_clark}{name}")
        el.text = value
        new_elems.append(el)
        if name == "MasterScore":
            genres_el = ET.Element(f"{photon_clark}Genres")
            bag = ET.SubElement(genres_el, f"{{{_RDF_NS}}}Bag")
            for genre in genres:
                li = ET.SubElement(bag, f"{{{_RDF_NS}}}li")
                li.text = genre
            new_elems.append(genres_el)

    indent, closing = "\n      ", "\n    "
    for el in new_elems:
        el.tail = indent
    new_elems[-1].tail = closing
    if len(desc):
        desc[-1].tail = indent
    else:
        desc.text = indent
    desc.extend(new_elems)

    body = ET.tostring(root, encoding="unicode")
    return f"{_XPACKET_HEADER}\n{body}\n{_XPACKET_FOOTER}\n"


def _write_xmp(record: "PhotoRecord") -> None:
    xmp_path = xmp_sidecar_path(record.path)
    props, genres = _photon_properties(record)

    if xmp_path.exists():
        merged = _merge_photon_into_sidecar(xmp_path, props, genres)
        if merged is not None:
            _atomic_write_text(xmp_path, merged)
            return
        # Unparseable sidecar: preserve it before writing fresh, never destroy.
        backup = xmp_path.with_name(xmp_path.name + ".bak")
        try:
            backup.write_bytes(xmp_path.read_bytes())
            logger.warning(
                "Sidecar %s is not parseable XML; preserved as %s and rewriting fresh",
                xmp_path,
                backup,
            )
        except OSError as exc:
            logger.error("Could not back up unparseable sidecar %s: %s; skipping", xmp_path, exc)
            return

    values = dict(props)
    genres_bag = "\n        ".join(f"<rdf:li>{_xml_escape(g)}</rdf:li>" for g in genres)
    xmp_content = XMP_TEMPLATE.format(
        sharpness=values["SharpnessScore"],
        composition=values["CompositionScore"],
        exposure=values["ExposureScore"],
        semantic_name=_xml_escape(values["SemanticName"]),
        original_filename=_xml_escape(values["OriginalFilename"]),
        session_id=_xml_escape(values["SessionID"]),
        is_duplicate=values["IsDuplicate"],
        genre=_xml_escape(values["Genre"]),
        genre_confidence=values["GenreConfidence"],
        master_score=values["MasterScore"],
        genres_bag=genres_bag,
        needs_review=values["NeedsReview"],
        eye_sharpness=values["EyeSharpness"],
        subject_sharpness=values["SubjectSharpness"],
        subject_isolation=values["SubjectIsolation"],
        blur_type=_xml_escape(values["BlurType"]),
        composition_rot=values["CompositionRoT"],
        symmetry=values["Symmetry"],
        leading_lines=values["LeadingLines"],
        negative_space=values["NegativeSpace"],
        zone_entropy=values["ZoneEntropy"],
        dynamic_range=values["DynamicRange"],
        exposure_style=_xml_escape(values["ExposureStyle"]),
        face_exposure=values["FaceExposure"],
        aesthetic_score=values["AestheticScore"],
    )
    _atomic_write_text(xmp_path, xmp_content)


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


def _open_dt(library_db_path: Path, check_lock: bool = True) -> sqlite3.Connection:
    """Open library.db with data.db attached and sane lock behavior.

    Writers must not race a running Darktable: its own lockfile is checked
    first, and busy_timeout makes residual lock contention wait instead of
    failing instantly (failures here were silently swallowed as lost tags).
    """
    if check_lock:
        lock = library_db_path.with_name(library_db_path.name + ".lock")
        if lock.exists():
            raise RuntimeError(
                f"Darktable appears to be running ({lock} exists); "
                "close it before syncing tags"
            )
    conn = sqlite3.connect(str(library_db_path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        "ATTACH DATABASE ? AS data", (str(_get_data_db_path(library_db_path)),)
    )
    return conn


def clear_photon_tags(library_db_path: Path, filename: str) -> None:
    """Remove all photon|* tagged_images entries for a given image.

    Called before writing new tags so re-scoring never accumulates stale
    photon|primary|* or photon|secondary|* entries on an image.
    """
    try:
        conn = _open_dt(library_db_path)
        try:
            image_row = conn.execute(
                "SELECT id FROM images WHERE filename=?", (filename,)
            ).fetchone()
            if image_row:
                conn.execute(
                    "DELETE FROM tagged_images WHERE imgid=? AND tagid IN "
                    "(SELECT id FROM data.tags WHERE name LIKE 'photon|%')",
                    (image_row[0],),
                )
                conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.error("Failed to clear photon tags for %s: %s", filename, e)


def purge_orphan_photon_tags(library_db_path: Path) -> int:
    """Delete *deprecated* photon|* tag definitions left empty by re-scores.

    clear_photon_tags removes image<->tag associations on re-score but leaves the
    tag definition in data.tags behind. Across taxonomy changes (renamed/removed
    genres) these accumulate as empty tags in Darktable's tag list. This deletes
    only photon|* tags whose name is NOT part of the *current* taxonomy AND that
    tag no image — so deprecated names (e.g. old subject 'glacier', old type
    'landscape') are removed, while valid-but-currently-unused tags (e.g.
    'photon|subject|building') are preserved. Returns the number purged.

    DT must be closed (direct SQLite write), same as the keyword writer.
    """
    from .genre_router import SUBJECTS, PHOTO_TYPES

    valid = {PHOTON_SUBJECT_PREFIX + s for s in SUBJECTS}
    valid |= {PHOTON_TYPE_PREFIX + t for t in PHOTO_TYPES}
    valid.add("photon|needs_review")

    try:
        conn = _open_dt(library_db_path)
        orphans = conn.execute(
            "SELECT id, name FROM data.tags WHERE name LIKE 'photon|%' "
            "AND id NOT IN (SELECT DISTINCT tagid FROM main.tagged_images)"
        ).fetchall()
        stale = [tid for tid, name in orphans if name not in valid]
        for tid in stale:
            conn.execute("DELETE FROM data.tags WHERE id=?", (tid,))
        conn.commit()
        conn.close()
        return len(stale)
    except Exception as e:
        logger.error("Failed to purge orphan photon tags: %s", e)
        return 0


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
    try:
        conn = _open_dt(library_db_path)
        try:
            image_row = conn.execute(
                "SELECT id FROM images WHERE filename=?",
                (filename,)
            ).fetchone()

            if not image_row:
                logger.warning("Image not found in Darktable library: %s", filename)
                return

            image_id = image_row["id"]

            # All keywords in one transaction (per-keyword commits meant a
            # kill mid-loop left the image partially tagged).
            for keyword in keywords:
                tag_row = conn.execute(
                    "SELECT id FROM data.tags WHERE name=?",
                    (keyword,)
                ).fetchone()
                if tag_row:
                    tag_id = tag_row["id"]
                else:
                    tag_id = conn.execute(
                        "INSERT INTO data.tags (name, synonyms, flags) VALUES (?, '', 0)",
                        (keyword,)
                    ).lastrowid

                conn.execute(
                    "INSERT OR IGNORE INTO tagged_images (imgid, tagid, position) "
                    "VALUES (?, ?, 0)",
                    (image_id, tag_id)
                )
            conn.commit()
        finally:
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
    keywords: list[str] = []
    try:
        # Reading concurrently with a running Darktable is safe; skip the
        # lockfile check writers use.
        conn = _open_dt(library_db_path, check_lock=False)

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


def read_darktable_color_label(
    library_db_path: Path,
    filename: str,
) -> int | None:
    """Read an image's Darktable color label (0-5, Darktable's own color-label
    ints — see score_fusion.stars_to_color_label for what PhotonForge writes
    into them) for a given file.

    Args:
        library_db_path: Path to Darktable's library.db
        filename: Image filename (basename only)

    Returns:
        The color label int if the image is found and has one, else None
        (image not found in the catalog, or found but has no color label —
        both are "nothing to show", not errors).
    """
    try:
        # Reading concurrently with a running Darktable is safe; skip the
        # lockfile check writers use.
        conn = _open_dt(library_db_path, check_lock=False)
        try:
            image_row = conn.execute(
                "SELECT id FROM images WHERE filename=?", (filename,)
            ).fetchone()
            if not image_row:
                logger.warning("Image not found in Darktable library: %s", filename)
                return None
            label_row = conn.execute(
                "SELECT color FROM color_labels WHERE imgid=?", (image_row["id"],)
            ).fetchone()
            return label_row["color"] if label_row else None
        finally:
            conn.close()
    except Exception as e:
        logger.error("Failed to read Darktable color label for %s: %s", filename, e)
        return None


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
