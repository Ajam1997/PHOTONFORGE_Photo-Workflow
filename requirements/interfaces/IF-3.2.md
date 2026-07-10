# IF-3.2 — Scoring + Naming → Darktable Bridge

**Side A:** Scoring System + Semantic Naming (via State DB)
**Side B:** Darktable Bridge (`darktable_bridge.py`)
**Status:** living
**Owner:** @software_lead

## What crosses

Per-photo results — `FusionResult` flat fields + `GenreResult` tags +
the semantic name — flow into XMP sidecars and the Darktable
SQLite `library.db`.

## Contract

### Flat score fields (from `FusionResult`)

The bridge consumes the flat score fields, not the typed dataclass:

```
sharpness, composition, exposure, master   # 0.0–1.0 floats
```

These map to XMP `photon:*` numeric fields and Darktable star ratings
(stars come from the per-shoot percentile rating, IF-2.1).

### XMP sidecar convention

- Sidecar path follows the Darktable convention: **append `.xmp` to
  the full filename** — `IMG_0001.ARW` → `IMG_0001.ARW.xmp`
  (`darktable_bridge.xmp_sidecar_path()`).
- All field values are **XML-escaped** before writing
  (`_xml_escape`, including `"` → `&quot;`).
- Namespace: `photon:*` fields (scores, semantic name, session id,
  genre, blur/exposure style, …).

### Hierarchical tags (from `GenreResult`)

Written as Darktable hierarchical tags and XMP sequences, using the
prefixes exported by the bridge (`PHOTON_SUBJECT_PREFIX`,
`PHOTON_TYPE_PREFIX`):

```
photon|subject|<label>      e.g. photon|subject|people
photon|type|<label>         e.g. photon|type|portrait
```

Valid labels are exactly `genre_router.SUBJECTS` (15) ×
`genre_router.PHOTO_TYPES` (11).

### Semantic name

The descriptive name from Naming (FR-1.7) is written to the
**Darktable description field** (and the XMP `photon:` semantic-name
field). Files are **not renamed** on disk.

## Verified By (Side A)

- pytest: tests/test_score_fusion.py

## Verified By (Side B)

- pytest: tests/test_darktable.py

## Validated By

- (none yet) — e2e: Stage 3 milestone — scores + tags visible in Darktable after sync-tags

## Notes

The flat score fields + the `photon:*` / `photon|subject|*` /
`photon|type|*` namespace are the stability boundary: scoring
internals can change without touching the bridge as long as these are
preserved. The Lua `applicator.lua` + `tag_manager.lua` read the same
XMP/tag namespace (see IF-1.1 §4).
