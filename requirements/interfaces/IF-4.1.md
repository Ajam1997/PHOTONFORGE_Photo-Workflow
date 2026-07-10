# IF-4.1 — Ingest & Cartridge → Analysis Pipeline

**Side A:** Ingest & Cartridge (`ingest.py`, `cartridge.py`)
**Side B:** Analysis Pipeline (Grouping / Dedup / Scoring stages)
**Status:** living
**Owner:** @software_lead

> The hand-off from host-integration code to the analysis pipeline.
> The staged file set + its per-photo rows in the PHOTON state DB
> (`photondb.py`) is the contract.

## What crosses

Staged media files on the SSD cartridge + per-photo state rows in the
PHOTON SQLite DB, so downstream stages can process without re-reading
the SD card (which may already be ejected — UN-040).

## Contract

### Staged layout

Ingest copies SD media into a staging path on the SSD cartridge
(copy-then-record, with collision retry). The SD card may be safely
removed (UN-041) once the copies are recorded in the state DB — all
downstream stages read only from the SSD.

### State DB rows (`photondb.py`)

The `photos` table records, per staged file:
- folder + filename (the staged location)
- EXIF capture timestamp (consumed by Grouping for clustering)
- a `stages` column tracking which stages have completed
  (`scan`/`dedup`/`score`/`name`), appended via `update_stages()`
- **Resume** = `photondb.get_pending()` returning the rows missing a
  given stage; a crashed or stopped run picks up where it left off.

Downstream stages (`scan`/`dedup`/`score`) take `--source-dir`
pointing at the staged location + `--db` for the PHOTON state DB. The
`photos` schema + staged-path convention is the contract.

## Verified By (Side A)

- pytest: tests/test_ingest.py
- pytest: tests/test_ingest_v2.py
- pytest: tests/test_photondb.py
- pytest: tests/test_cartridge.py

## Verified By (Side B)

- pytest: tests/test_grouping.py

## Validated By

- (none yet) — e2e: Stage 3 milestone — full card ingests to SSD, SD removed, pipeline completes from staged files

## Notes

This interface is what makes UN-040 (move to SSD before processing)
and UN-041 (auto-eject + notify) safe: once the staged copies are
durable in the state DB on the SSD, the SD card is no longer on the
critical path.
