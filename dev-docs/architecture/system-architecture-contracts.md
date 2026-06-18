# Photo-Workflow — System Architecture Contracts

**Owner:** @systems_lead
**Status:** living
**Last updated:** 2026-05-29
**Companion ICDs:** see `requirements/interfaces/IF-*.md` (filed in Phase 6)
**Format spec:** [architecture-contracts-format.md](architecture-contracts-format.md)

## System overview

An offline photography pipeline for a single hobbyist on a Lenovo
Yoga 910 (i7-7500U, 8 GB RAM). It ingests RAW/JPEG from an SD card,
stages them to an external SSD cartridge, groups them into shooting
sessions, removes near-duplicates, scores each photo (sharpness /
composition / exposure), classifies subject + photo-type, generates a
descriptive semantic filename via local Florence-2 INT8 ONNX, and
syncs scores + tags into Darktable. A Darktable Lua plugin drives the
whole run from inside the photo editor. Top-level success criterion:
a full SD card processes end-to-end, unattended, with zero network
access at runtime and the results visible as Darktable tags.

> **Single-discipline note.** This is a Profile A (software) project —
> every module below is owned by **@software_lead** (historical
> sub-area in parens for provenance: the old @engineer vs @devops
> split). The Owner column is therefore uniform; the real per-module
> differentiation lives in the *Performance envelope* (which KPM/NFR
> each module is on the hook for) and in the cross-module interface
> seed list.

## Module table

| Module | Responsibilities | Inputs | Outputs | Owner | Performance envelope |
|---|---|---|---|---|---|
| **CLI Orchestrator** (`pipeline.py`) | The `photo-workflow` click CLI + `AnalysisPipeline`. Sequences the stages (ingest → scan → dedup → score → name → sync-tags), owns `PhotoRecord` / `PipelineSummary`, emits JSON progress, manages the PID sentinel for stop/resume. | Stage commands + flags (CLI); progress requests from the Lua plugin (`IF-1.1`) | Per-stage invocations; JSON progress stream + sentinel (`IF-1.1`); `PipelineSummary` telemetry | software (engineer) | UN-050, UN-052, UN-053, UN-054; KPM-1.5 end-to-end throughput |
| **Ingest & Cartridge** (`ingest.py`, `volume.py`, `cartridge.py`, `manifest.py`, `provision.py`) | SD→SSD staging copy, cartridge identity + provisioning, volume mounting, safe ejection, ingest manifest. | SD card media; cartridge volume (`IF-4.1`) | Staged files on SSD + ingest manifest (`IF-4.2`); eject + notify events | software (devops) | FR-1.1, FR-1.9, FR-1.10; UN-030/031/032/040/041; KPM-1.1 ingest latency, KPM-1.4 data integrity; NFR-2.3 storage portability, NFR-2.4/2.5 prompts |
| **Grouping** (`grouping.py`) | Spatio-temporal session clustering (`cluster_sessions()`): temporal delta + dHash proximity. | Staged image set + EXIF (`IF-4.2`) | Session IDs per photo → state DB | software (engineer) | FR-1.2, UN-010; KPM-1.10 session-grouping precision |
| **Dedup** (`dedup.py`) | Perceptual near-duplicate detection (dHash Hamming ≤ 2); archives duplicates. | Grouped image set | Duplicate flags → state DB | software (engineer) | FR-1.3, UN-011; KPM-1.6 dedup false-positive rate |
| **Scoring System** (`score_fusion.py`, `scoring_types.py`, `sharpness.py`, `composition.py`, `exposure.py`; Stage-6 modular: `region_router` → `sub_scores/*` → `technical_gate` + `aesthetic_weighter` → `fusion`) | Per-photo technical + aesthetic scoring. Subject routes regions; Photo-Type weights aesthetics; master = `min(technical, aesthetic)`. | Image + `GenreResult` (Subject/Type) (`IF-3.1`); per-Type weights from SQLite | `FusionResult` (sharpness, composition, exposure, master) → state DB (`IF-3.2`) | software (engineer) | FR-1.4/1.5/1.6, UN-012/013/014; KPM-1.8 determinism; NFR-2.2 (KPM-1.3 RSS, KPM-1.9 CPU) |
| **Genre / Subject Classifier** (`genre_router.py`, `genre_trainer.py`, `subject_context.py`, `training_weights_db.py`) | Two-axis taxonomy (16 Subjects × 12 Photo Types) via MobileCLIP prototypes + EXIF priors; per-axis back-training from user corrections. | Image + EXIF; user corrections (`IF-1.1` via Darktable tags) | `GenreResult` (subject, photo_type, distributions) (`IF-3.1`); updated prototype DB | software (engineer) | FR-1.7.1 calibration, FR-1.7.2 multi-genre; UN-020/022 |
| **Semantic Naming** (`naming.py`, `raw_loader.py`) | Florence-2-base-ft INT8 ONNX captioning → descriptive filename; RAW decode for inference. | Image + Subject/Type priors (`IF-3.1`) | Semantic filename string → state DB (`IF-3.2`) | software (engineer) | FR-1.7, UN-020; KPM-1.2 inference speed (≤2.5 s/img), KPM-1.7 naming validity; NFR-2.1 offline |
| **Darktable Bridge** (`darktable_bridge.py`, `sidecar_cli.py`) | Writes scores + Subject/Type tags to XMP sidecars and the Darktable SQLite library; the sync-tags stage. | `FusionResult` + `GenreResult` + filename from state DB (`IF-3.2`) | XMP sidecars + Darktable `library.db` rows (`IF-1.1` result store) | software (engineer) | FR-1.8, UN-021; NFR-2.3 DB portability |
| **State & Progress DB** (`photondb.py`, `progress.py`) | Per-photo processing state across stages (PHOTON SQLite); resume bookkeeping; throughput/ETA progress. | Stage results from every module | Persisted per-photo state; progress/ETA stream | software (engineer) | UN-051 state DB, UN-052 resume, UN-053 progress |
| **Darktable Lua Plugin** (`lua/photonforge/*`) | Operator-facing UI inside Darktable: panel, run/stop controls, genre-correction buttons, tag applicator, reads result store. | Operator clicks; result store (XMP + `library.db`) | `photo-workflow` subprocess invocations + stop via PID sentinel (`IF-1.1`); Darktable tags applied | software (lua) | NFR-2.4 interactive prompts; surfaces all UN outputs to the user |

## Cross-cutting concerns

### Offline at runtime (NFR-2.1)
No module may make a network call during a pipeline run. All models
(MobileCLIP, YOLO, Florence-2 INT8) are vendored under `models/` and
loaded from disk. Provisioning (`provision.py`) is the *only* code
permitted internet access, and only during initial machine setup —
never during `ingest`/`scan`/`dedup`/`score`/`name`/`sync-tags`.

### Resource budget (NFR-2.2)
The score stage is the binding constraint: CLIP + YOLO + Florence-2
INT8 are all resident simultaneously. Budget is **RSS ≤ 1.5 GB**
(KPM-1.3) and **CPU ≤ 80% of logical cores** (KPM-1.9) on the
i7-7500U, leaving headroom for the Darktable UI running alongside.
This spans the Scoring System + Genre Classifier + Semantic Naming
modules, which is why it's a cross-cutting NFR rather than owned by
one module.

### Storage portability (NFR-2.3)
The Darktable `library.db` and user config live on the external SSD
cartridge, not the host filesystem — the cartridge IS the portable
library. The Ingest & Cartridge and Darktable Bridge modules both
honor this; the host machine stays stateless.

### Interactive prompts (NFR-2.4 / NFR-2.5)
zenity dialogs surface two operator-facing conditions: SD inserted
without an SSD connected (NFR-2.4, on UN-030), and "safe to remove"
notification after transfer (NFR-2.5, on UN-041). Raised by the
Ingest & Cartridge module and the Lua plugin.

## Cross-module interface seed list (Phase 6 ICDs)

All boundaries are internal to the software discipline, but several
carry a real contract worth an ICD. Phase 6 files each as an
`IF-X.Y` Issue + `requirements/interfaces/IF-X.Y.md`.

| IF | From → To | What crosses | Why it needs an ICD |
|---|---|---|---|
| **IF-1.1** | Lua Plugin ↔ CLI Orchestrator | `photo-workflow <stage> --json-progress` subprocess; JSON progress schema (stdout); PID sentinel file; XMP + `library.db` result store | **The one genuinely cross-language boundary** (Lua ↔ Python over subprocess IPC). Command names, progress JSON schema, sentinel format, and the result-store schema are all contracts the two sides must agree on. Highest-value ICD. |
| **IF-3.1** | Genre Classifier → Scoring + Naming | `GenreResult` (subject, photo_type, per-axis distributions + confidence) | Subject drives region routing; Photo-Type drives aesthetic weighting. Multi-label (FR-1.7.2) changes the contract shape. Partly specified in `scoring-module-contracts.md`. |
| **IF-3.2** | Scoring + Naming → Darktable Bridge | `FusionResult` flat fields + `GenreResult` tags + semantic filename | The XMP/SQLite write contract. `FusionResult.as_flat_dict()` + `SubScoreBundle.as_flat_dict()` preserve backward compatibility — that's the contract. |
| **IF-2.x** | region_router → sub_scores → gate/weighter → fusion | `RegionSpec`, `SubScoreBundle`, `TechnicalResult`, `AestheticResult`, `FusionResult` | The Stage-6 scoring-subsystem internal contracts. **Already fully specified** in `scoring-module-contracts.md` — Phase 6 lifts that content into formal IF docs. |
| **IF-4.x** | Ingest → Grouping / pipeline | staged file set + ingest manifest + EXIF | The hand-off from host-integration (devops) code to the analysis pipeline (engineer) code. The manifest schema is the contract. |

## Open Questions if Frozen Mid-Authoring

- **Module granularity for scoring.** The Scoring System row collapses
  the legacy `score_fusion.py` and the Stage-6 five-module pipeline
  into one module. Once Stage 6 lands, should `region_router` /
  `aesthetic_weighter` become first-class modules in this table, or
  stay an internal decomposition documented only in
  `scoring-module-contracts.md`? Decide at Stage 6 close-out.
- **State DB vs Darktable DB.** The PHOTON state DB (`photondb.py`) and
  the Darktable `library.db` are two separate SQLite stores. Is the
  boundary between them worth its own IF, or is it adequately covered
  by IF-3.2? Revisit in Phase 6.
- **Genre as a module vs a scoring input.** The Genre Classifier is
  listed as its own module because it has independent back-training
  (FR-1.7.1) and its own model + DB. But it's only ever consumed by
  Scoring + Naming. Keep separate (current) or fold into Scoring?
  Separate is correct while back-training is an independent concern.

---

## See also

- [architecture-contracts-format.md](architecture-contracts-format.md) — the spec this doc follows
- [scoring-module-contracts.md](scoring-module-contracts.md) — the Stage-6 scoring-subsystem internal contracts (IF-2.x source)
- [system-state-machine.md](system-state-machine.md) — pipeline stage state machine
- [pipeline-activity.md](pipeline-activity.md) — stage activity flow
- `requirements/requirement-map.yml` — the UN/FR/NFR/KPM decomposition these modules satisfy
