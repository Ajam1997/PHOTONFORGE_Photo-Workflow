# IF-3.2 — Scoring + Naming → Darktable Bridge

**Side A:** Scoring System + Semantic Naming (via State DB)
**Side B:** Darktable Bridge (`darktable_bridge.py`, `sidecar_cli.py`)
**Status:** living
**Owner:** @software_lead

## What crosses

Per-photo results — `FusionResult` flat fields + `GenreResult` tags +
the semantic filename — flow into XMP sidecars and the Darktable
SQLite `library.db`.

## Contract

### Flat score fields (from `FusionResult.as_flat_dict()`)

The bridge consumes the flat dict, not the typed dataclass:

```
sharpness, composition, exposure, master   # 0.0–1.0 floats
```

These map to XMP `photon:*` numeric fields and Darktable star ratings.

### Hierarchical tags (from `GenreResult`)

Written as Darktable hierarchical tags and XMP sequences:

```
photon|subject|<label>      e.g. photon|subject|person
photon|type|<label>         e.g. photon|type|portrait
```

Multi-label (FR-1.7.2) emits `photon:Subjects` / `photon:PhotoTypes`
`rdf:Seq` blocks with per-label confidence. The argmax scalar fields
(`photon:Subject`, `photon:PhotoType`) are preserved.

### Semantic filename

The descriptive filename string from Naming (FR-1.7) becomes the file
rename target + an XMP title field.

## Verified By (Side A)

- pytest: tests/test_score_fusion.py

## Verified By (Side B)

- pytest: tests/test_darktable.py
- pytest: tests/test_sidecar_cli.py

## Validated By

- (none yet) — e2e: Stage 3 milestone — scores + tags visible in Darktable after sync-tags

## Notes

`FusionResult.as_flat_dict()` is the stability boundary: the scoring
subsystem can be re-architected (Stage 6) without touching the bridge,
as long as the flat keys are preserved. The Lua `applicator.lua` reads
the same XMP/tag namespace (see IF-1.1 §4).
