# PHOTONForge — Photo-Workflow

An **offline, autonomous photography pipeline** for a single hobbyist
on a Lenovo Yoga 910 (i7-7500U, 8 GB RAM). It ingests RAW/JPEG from an
SD card, stages to an external SSD cartridge, groups shooting sessions,
removes near-duplicates, scores each photo (sharpness / composition /
exposure), classifies subject + photo-type, generates a descriptive
semantic filename via local Florence-2 INT8 ONNX, and syncs scores +
tags into Darktable — all with **zero network access at runtime**.

A Darktable Lua plugin drives the whole run from inside the editor.

## Status

Built and largely functional (Stages 1–6 complete; the Stage-6 scoring
system shipped as-built inside `score_fusion.py` — two-axis 15×11
subject/type weighting, hard-reject gates, percentile star rating).
Migrated to the
[systems-first-template](https://github.com/Ajam1997/systems-first-template)
structure on 2026-05-29 — see `dev-docs/migration-plan.md`.

## How it works

```
SD card → [ingest] → SSD staging → [scan/group] → [dedup] → [score] → [name] → [sync-tags] → Darktable
```

Run a stage:

```bash
photo-workflow ingest    --source /media/sd --dest /mnt/ssd/inbox
photo-workflow scan      --source /mnt/ssd/inbox --db library.db
photo-workflow dedup     --db library.db --folder shoot --source-dir /mnt/ssd/inbox
photo-workflow score     --db library.db --folder shoot --source-dir /mnt/ssd/inbox
photo-workflow name      --db library.db --folder shoot --source-dir /mnt/ssd/inbox
photo-workflow sync-tags --photon-db library.db --folder shoot --dt-library ~/.config/darktable/library.db  # doc-ref: ignore
```

…or drive it all from the Darktable Lua plugin panel.

## Project structure

| Path | What |
|---|---|
| `src/photo_workflow/` | The pipeline — one module per stage + the `pipeline.py` CLI orchestrator |
| `lua/photonforge/` | Darktable Lua plugin (operator UI; drives the CLI over subprocess — IF-1.1) |
| `models/` | Vendored INT8 ONNX models (MobileCLIP, YOLO, Florence-2-base-ft) — not downloaded at runtime |
| `requirements/` | Requirement decomposition tree (`requirement-map.yml`) + interface ICDs (`interfaces/IF-*.md`) |
| `config/` | Discipline / stage / evidence-kind config (Profile A — software) |
| `dev-docs/` | Developer docs (rendered to the GitHub Wiki). Architecture, contracts, system reviews. |
| `scripts/` | Pipeline support + the systems-first-template automation (generate_docs, kpm_rollup, export_sysml, …) |
| `tests/` | pytest suite (one `test_*.py` per module) + `fixtures/` |
| `deploy/` | Dockerfile + docker-compose for the Yoga 910 (SD/SSD hotplug via udisks2 polling + polkit) |

## Where to start

- **Agents / contributors:** `dev-docs/start-work-checklist.md` (~60 s), then `CLAUDE.md`
- **Architecture:** `dev-docs/architecture/system-architecture-contracts.md` (the 10-module map)
- **Requirements:** `requirements/requirement-map.yml` (UN → FR/NFR/IF/KPM tree)

## Constraints (NFRs)

- **NFR-2.1** 100% offline at runtime (provisioning may use the internet)
- **NFR-2.2** Resource budget: RSS ≤ 1.5 GB, CPU ≤ 80% of cores during scoring
- **NFR-2.3** `library.db` + config live on the external SSD, not the host
- **NFR-2.4 / 2.5** zenity prompts: SD-without-SSD dialog; safe-to-remove notification

## License

To be decided.
