"""Tests for darktable_bridge: XMP writing and color label computation."""

from __future__ import annotations

import inspect
from pathlib import Path


from photo_workflow.darktable_bridge import (
    xmp_sidecar_path,
    sync_to_darktable,
    validate_xmp,
    _write_xmp,
    write_darktable_keywords,
    purge_orphan_photon_tags,
    read_darktable_keywords,
)
from photo_workflow.pipeline import PhotoRecord
import sqlite3


_SAMPLE_SUB_SCORES = {
    "eye_sharpness": 0.85,
    "subject_sharpness": 0.78,
    "subject_isolation": 0.64,
    "blur_type": "bokeh",
    "composition_rot": 0.71,
    "symmetry": 0.32,
    "leading_lines": 0.45,
    "negative_space": 0.68,
    "zone_entropy": 0.82,
    "dynamic_range": 0.91,
    "exposure_style": "normal",
    "face_exposure": 0.88,
    "aesthetic_clip": 0.65,
}


def _make_record(tmp_path: Path, name: str = "test", duplicate: bool = False) -> PhotoRecord:
    img_path = tmp_path / f"{name}.jpg"
    img_path.touch()
    rec = PhotoRecord(path=img_path)
    rec.session_id = "session_0001"
    rec.is_duplicate = duplicate
    rec.sharpness_score = 0.85
    rec.composition_score = 0.72
    rec.exposure_score = 0.91
    rec.semantic_name = "golden_hour_landscape"
    rec.genre = "wildlife"
    rec.genre_confidence = 0.87
    rec.master_score = 0.72
    rec.sub_scores = dict(_SAMPLE_SUB_SCORES)
    return rec


# ---------------------------------------------------------------------------
# XMP tests
# ---------------------------------------------------------------------------

def test_xmp_written_for_non_duplicate(tmp_path: Path) -> None:
    rec = _make_record(tmp_path)
    _write_xmp(rec)
    xmp_path = xmp_sidecar_path(rec.path)
    assert xmp_path.exists()
    content = xmp_path.read_text()
    assert "0.85" in content
    assert "golden_hour_landscape" in content


def test_xmp_contains_genre_fields(tmp_path: Path) -> None:
    rec = _make_record(tmp_path)
    _write_xmp(rec)
    content = xmp_sidecar_path(rec.path).read_text()
    assert "<photon:Genre>wildlife</photon:Genre>" in content
    assert "<photon:GenreConfidence>0.87</photon:GenreConfidence>" in content
    assert "<photon:MasterScore>0.72</photon:MasterScore>" in content


def test_xmp_contains_all_sub_scores(tmp_path: Path) -> None:
    rec = _make_record(tmp_path)
    _write_xmp(rec)
    content = xmp_sidecar_path(rec.path).read_text()
    assert "<photon:EyeSharpness>0.85</photon:EyeSharpness>" in content
    assert "<photon:SubjectSharpness>0.78</photon:SubjectSharpness>" in content
    assert "<photon:SubjectIsolation>0.64</photon:SubjectIsolation>" in content
    assert "<photon:BlurType>bokeh</photon:BlurType>" in content
    assert "<photon:CompositionRoT>0.71</photon:CompositionRoT>" in content
    assert "<photon:Symmetry>0.32</photon:Symmetry>" in content
    assert "<photon:LeadingLines>0.45</photon:LeadingLines>" in content
    assert "<photon:NegativeSpace>0.68</photon:NegativeSpace>" in content
    assert "<photon:ZoneEntropy>0.82</photon:ZoneEntropy>" in content
    assert "<photon:DynamicRange>0.91</photon:DynamicRange>" in content
    assert "<photon:ExposureStyle>normal</photon:ExposureStyle>" in content
    assert "<photon:FaceExposure>0.88</photon:FaceExposure>" in content
    assert "<photon:AestheticScore>0.65</photon:AestheticScore>" in content


def test_xmp_defaults_when_no_sub_scores(tmp_path: Path) -> None:
    img = tmp_path / "bare.jpg"
    img.touch()
    rec = PhotoRecord(path=img, semantic_name="test")
    _write_xmp(rec)
    content = xmp_sidecar_path(img).read_text()
    assert "<photon:Genre></photon:Genre>" in content
    assert "<photon:MasterScore>0.0</photon:MasterScore>" in content
    assert "<photon:EyeSharpness>0.0</photon:EyeSharpness>" in content
    assert "<photon:BlurType></photon:BlurType>" in content
    assert "<photon:ExposureStyle></photon:ExposureStyle>" in content


def test_xmp_not_written_for_duplicate(tmp_path: Path) -> None:
    rec = _make_record(tmp_path, duplicate=True)
    count = sync_to_darktable([rec])
    xmp_path = xmp_sidecar_path(rec.path)
    assert not xmp_path.exists()
    assert count == 0


def test_validate_xmp_passes_for_valid_sidecar(tmp_path: Path) -> None:
    rec = _make_record(tmp_path)
    _write_xmp(rec)
    assert validate_xmp(xmp_sidecar_path(rec.path)) is True


def test_validate_xmp_fails_for_malformed(tmp_path: Path) -> None:
    bad_xmp = tmp_path / "bad.xmp"
    bad_xmp.write_text("<not-valid-xmp>garbage</not-valid-xmp>", encoding="utf-8")
    assert validate_xmp(bad_xmp) is False


# ---------------------------------------------------------------------------
# sync_to_darktable tests
# ---------------------------------------------------------------------------

def test_sync_to_darktable_xmp_only(tmp_path: Path) -> None:
    img = tmp_path / "00001.ARW"
    img.write_bytes(b"fake")
    record = PhotoRecord(
        path=img, session_id="s1",
        sharpness_score=0.7, composition_score=0.6, exposure_score=0.7,
        semantic_name="a-blue-waterfall",
        metadata={"original_filename": "DSC001.ARW"},
    )
    count = sync_to_darktable([record])
    assert (tmp_path / "00001.ARW.xmp").exists()
    assert count == 1


def test_sync_to_darktable_no_db_param() -> None:
    sig = inspect.signature(sync_to_darktable)
    assert "db_path" not in sig.parameters


def test_xmp_contains_multi_genre_bag(tmp_path: Path) -> None:
    """XMP should contain multi-genre rdf:Bag with entries for each genre."""
    rec = _make_record(tmp_path)
    rec.genres = [("wildlife", 0.87), ("landscape", 0.05)]
    rec.needs_review = False
    _write_xmp(rec)
    content = xmp_sidecar_path(rec.path).read_text()
    assert "<rdf:Bag>" in content
    assert "<rdf:li>wildlife</rdf:li>" in content
    assert "<rdf:li>landscape</rdf:li>" in content
    assert "<photon:NeedsReview>false</photon:NeedsReview>" in content


def test_xmp_contains_needs_review_flag(tmp_path: Path) -> None:
    """XMP should contain needs_review flag."""
    rec = _make_record(tmp_path)
    rec.genres = [("general", 1.0)]
    rec.needs_review = True
    _write_xmp(rec)
    content = xmp_sidecar_path(rec.path).read_text()
    assert "<photon:NeedsReview>true</photon:NeedsReview>" in content


# ---------------------------------------------------------------------------
# Darktable keyword tests  (Darktable 5.x split-DB schema)
# ---------------------------------------------------------------------------
# DT5 stores tag names in data.db and tag links in library.db.
# Helpers below create both files so tests match production behaviour.

def _make_dt5_dbs(tmp_path: Path) -> tuple[Path, Path]:
    """Create minimal Darktable 5.x library.db + data.db in tmp_path."""
    lib = tmp_path / "library.db"
    data = tmp_path / "data.db"

    conn = sqlite3.connect(str(lib))
    conn.execute("CREATE TABLE images (id INTEGER PRIMARY KEY, filename TEXT)")
    conn.execute(
        "CREATE TABLE tagged_images (imgid INTEGER, tagid INTEGER, position INTEGER)"
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(str(data))
    conn.execute(
        "CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT UNIQUE, "
        "synonyms TEXT, flags INTEGER)"
    )
    conn.commit()
    conn.close()

    return lib, data


def test_purge_orphan_photon_tags(tmp_path: Path) -> None:
    """Orphaned photon|* tag definitions are purged; used + non-photon tags kept."""
    lib, data = _make_dt5_dbs(tmp_path)

    conn = sqlite3.connect(str(lib))
    conn.execute("INSERT INTO images (id, filename) VALUES (1, 'a.jpg')")
    conn.commit()
    conn.close()

    conn = sqlite3.connect(str(data))
    # 1 = used photon tag; 2/3 = orphaned + deprecated (not in taxonomy);
    # 4 = orphaned non-photon; 5 = orphaned but valid current taxonomy
    conn.executescript(
        "INSERT INTO tags (id, name, synonyms, flags) VALUES "
        "(1,'photon|subject|vehicle','',0),"
        "(2,'photon|type|landscape','',0),"
        "(3,'photon|subject|glacier','',0),"
        "(4,'vacation','',0),"
        "(5,'photon|subject|building','',0);"
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(str(lib))
    conn.execute("INSERT INTO tagged_images (imgid, tagid, position) VALUES (1, 1, 0)")
    conn.commit()
    conn.close()

    purged = purge_orphan_photon_tags(lib)
    assert purged == 2  # only the deprecated orphans

    conn = sqlite3.connect(str(data))
    names = {r[0] for r in conn.execute("SELECT name FROM tags").fetchall()}
    conn.close()
    assert "photon|subject|vehicle" in names    # used -> kept
    assert "vacation" in names                  # non-photon orphan -> kept
    assert "photon|subject|building" in names   # valid current taxonomy -> kept
    assert "photon|type|landscape" not in names   # deprecated orphan -> purged
    assert "photon|subject|glacier" not in names


def test_write_darktable_keywords_creates_tags(tmp_path: Path) -> None:
    """write_darktable_keywords should create tags in data.db and links in library.db."""
    lib, data = _make_dt5_dbs(tmp_path)

    conn = sqlite3.connect(str(lib))
    conn.execute("INSERT INTO images (filename) VALUES ('test.jpg')")
    conn.commit()
    conn.close()

    write_darktable_keywords(lib, "test.jpg", ["wildlife", "portrait"])

    # Tags written to data.db
    conn = sqlite3.connect(str(data))
    tag_names = {r[0] for r in conn.execute("SELECT name FROM tags").fetchall()}
    conn.close()
    assert "wildlife" in tag_names
    assert "portrait" in tag_names

    # Links written to library.db
    conn = sqlite3.connect(str(lib))
    links = conn.execute("SELECT COUNT(*) FROM tagged_images").fetchone()[0]
    conn.close()
    assert links == 2


def test_read_darktable_keywords_retrieves_tags(tmp_path: Path) -> None:
    """read_darktable_keywords should retrieve tags across the split databases."""
    lib, data = _make_dt5_dbs(tmp_path)

    conn = sqlite3.connect(str(lib))
    conn.execute("INSERT INTO images (filename) VALUES ('test.jpg')")
    conn.execute("INSERT INTO tagged_images (imgid, tagid, position) VALUES (1, 1, 0)")
    conn.execute("INSERT INTO tagged_images (imgid, tagid, position) VALUES (1, 2, 0)")
    conn.commit()
    conn.close()

    conn = sqlite3.connect(str(data))
    conn.execute("INSERT INTO tags (name, synonyms, flags) VALUES ('wildlife', '', 0)")
    conn.execute("INSERT INTO tags (name, synonyms, flags) VALUES ('landscape', '', 0)")
    conn.commit()
    conn.close()

    keywords = read_darktable_keywords(lib, "test.jpg")
    assert set(keywords) == {"wildlife", "landscape"}


def test_read_darktable_keywords_nonexistent_image(tmp_path: Path) -> None:
    """read_darktable_keywords should return empty list for missing image."""
    lib, _ = _make_dt5_dbs(tmp_path)
    keywords = read_darktable_keywords(lib, "nonexistent.jpg")
    assert keywords == []


def test_keywords_round_trip(tmp_path: Path) -> None:
    """Writing then reading keywords should preserve the list."""
    lib, _ = _make_dt5_dbs(tmp_path)

    conn = sqlite3.connect(str(lib))
    conn.execute("INSERT INTO images (filename) VALUES ('photo.jpg')")
    conn.commit()
    conn.close()

    original = ["macro", "nature", "insect"]
    write_darktable_keywords(lib, "photo.jpg", original)
    retrieved = read_darktable_keywords(lib, "photo.jpg")
    assert set(retrieved) == set(original)


def test_xmp_escapes_xml_special_chars(tmp_path: Path) -> None:
    """Regression: captions with &/</> produced malformed XMP."""
    img = tmp_path / "00002.ARW"
    img.write_bytes(b"fake")
    record = PhotoRecord(
        path=img, session_id="s1",
        sharpness_score=0.7, composition_score=0.6, exposure_score=0.7,
        semantic_name="fish & chips <on> a \"plate\"",
        metadata={"original_filename": "DSC002.ARW"},
    )
    _write_xmp(record)
    xmp = xmp_sidecar_path(img)
    assert xmp.name == "00002.ARW.xmp"  # darktable convention, no RAW+JPEG collision
    assert validate_xmp(xmp) is True
    assert "fish &amp; chips" in xmp.read_text()


def test_write_keywords_refuses_when_darktable_lockfile_present(tmp_path: Path) -> None:
    """Regression: direct library.db writes raced a running Darktable."""
    lib, data = _make_dt5_dbs(tmp_path)
    conn = sqlite3.connect(str(lib))
    conn.execute("INSERT INTO images (filename) VALUES ('IMG_0001.ARW')")
    conn.commit()
    conn.close()

    lock = lib.with_name(lib.name + ".lock")
    lock.write_text("12345")
    write_darktable_keywords(lib, "IMG_0001.ARW", ["photon|subject|people"])

    # Nothing written while Darktable holds its lock
    assert read_darktable_keywords(lib, "IMG_0001.ARW") == []
    lock.unlink()
    write_darktable_keywords(lib, "IMG_0001.ARW", ["photon|subject|people"])
    assert read_darktable_keywords(lib, "IMG_0001.ARW") == ["photon|subject|people"]


# ---------------------------------------------------------------------------
# XMP parse-modify-write (darktable edit-history preservation)
# ---------------------------------------------------------------------------

_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_XMP = "http://ns.adobe.com/xap/1.0/"
_DT = "http://darktable.sf.net/"

_DT_SIDECAR = """<?xpacket begin='﻿' id='W5M0MpCehiHzreSzNTczkc9d'?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="XMP Core 4.4.0-Exiv2">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:darktable="http://darktable.sf.net/"
    xmp:Rating="2"
    darktable:xmp_version="5"
    darktable:history_end="1">
   <darktable:history>
    <rdf:Seq>
     <rdf:li darktable:operation="exposure" darktable:params="abc123"/>
    </rdf:Seq>
   </darktable:history>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end='w'?>
"""


def test_xmp_merge_preserves_darktable_history(tmp_path: Path) -> None:
    """Regression: _write_xmp used to overwrite the whole sidecar, destroying
    darktable's edit stack, rating, and any non-photon metadata."""
    import xml.etree.ElementTree as ET

    rec = _make_record(tmp_path)
    xmp_path = xmp_sidecar_path(rec.path)
    xmp_path.write_text(_DT_SIDECAR, encoding="utf-8")

    _write_xmp(rec)

    content = xmp_path.read_text()
    assert "<photon:Genre>wildlife</photon:Genre>" in content
    assert "golden_hour_landscape" in content
    assert validate_xmp(xmp_path) is True

    root = ET.fromstring(content)
    desc = root.find(f".//{{{_RDF}}}Description")
    assert desc is not None
    assert desc.attrib.get(f"{{{_XMP}}}Rating") == "2"
    assert desc.attrib.get(f"{{{_DT}}}history_end") == "1"
    hist = desc.find(f"{{{_DT}}}history")
    assert hist is not None
    li = hist.find(f".//{{{_RDF}}}li")
    assert li is not None
    assert li.attrib.get(f"{{{_DT}}}operation") == "exposure"
    assert li.attrib.get(f"{{{_DT}}}params") == "abc123"


def test_xmp_merge_is_idempotent(tmp_path: Path) -> None:
    rec = _make_record(tmp_path)
    _write_xmp(rec)
    rec.sharpness_score = 0.5
    _write_xmp(rec)
    _write_xmp(rec)

    content = xmp_sidecar_path(rec.path).read_text()
    # exactly one element: one open + one close tag
    assert content.count("SharpnessScore") == 2
    assert "<photon:SharpnessScore>0.5</photon:SharpnessScore>" in content
    assert content.count("<photon:Genres>") == 1
    assert validate_xmp(xmp_sidecar_path(rec.path)) is True


def test_xmp_merge_updates_values_in_existing_dt_sidecar(tmp_path: Path) -> None:
    rec = _make_record(tmp_path)
    xmp_path = xmp_sidecar_path(rec.path)
    xmp_path.write_text(_DT_SIDECAR, encoding="utf-8")
    _write_xmp(rec)

    rec.sharpness_score = 0.11
    rec.genre = "landscape"
    _write_xmp(rec)

    content = xmp_path.read_text()
    assert "<photon:SharpnessScore>0.11</photon:SharpnessScore>" in content
    assert "<photon:Genre>landscape</photon:Genre>" in content
    assert content.count("SharpnessScore") == 2
    # darktable state still intact after two merge passes
    assert 'darktable:operation="exposure"' in content or "exposure" in content


def test_xmp_unparseable_sidecar_backed_up_not_destroyed(tmp_path: Path) -> None:
    rec = _make_record(tmp_path)
    xmp_path = xmp_sidecar_path(rec.path)
    xmp_path.write_text("<not-xml", encoding="utf-8")

    _write_xmp(rec)

    assert validate_xmp(xmp_path) is True
    backup = xmp_path.with_name(xmp_path.name + ".bak")
    assert backup.exists()
    assert backup.read_text() == "<not-xml"
