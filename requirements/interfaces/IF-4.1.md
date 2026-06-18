# IF-4.1 — Ingest & Cartridge → Analysis Pipeline

**Side A:** Ingest & Cartridge (`ingest.py`, `manifest.py`, `cartridge.py`)
**Side B:** Analysis Pipeline (Grouping / Dedup / Scoring stages)
**Status:** living
**Owner:** @software_lead

> The hand-off from host-integration code (historically @devops) to the
> analysis pipeline (historically @engineer). The staged file set + its
> manifest is the contract.

## What crosses

Staged media files on the SSD cartridge + an ingest manifest
describing them, so downstream stages can process without re-reading
the SD card (which may already be ejected — UN-040).

## Contract

### Staged layout

Ingest copies SD media into a staging path on the SSD cartridge. The
SD card may be safely removed (UN-041) once the manifest is written —
all downstream stages read only from the SSD.

### Ingest manifest

`manifest.py` records, per ingested file:
- original SD path + new staged path
- file type (raw / jpg)
- EXIF capture timestamp + GPS (consumed by Grouping IF for clustering)
- copy integrity marker (supports KPM-1.4 zero-corruption)

Downstream stages (`scan`/`dedup`/`score`) take `--source-dir`
pointing at the staged location + `--db` for the PHOTON state DB. The
manifest schema + staged-path convention is the contract.

## Verified By (Side A)

- pytest: tests/test_ingest.py
- pytest: tests/test_manifest.py
- pytest: tests/test_cartridge.py

## Verified By (Side B)

- pytest: tests/test_grouping.py

## Validated By

- (none yet) — e2e: Stage 3 milestone — full card ingests to SSD, SD removed, pipeline completes from staged files

## Notes

This interface is what makes UN-040 (move to SSD before processing)
and UN-041 (auto-eject + notify) safe: once the manifest is durable on
the SSD, the SD card is no longer on the critical path.
