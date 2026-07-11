# Glossary — System Bible

<!-- AUTO:glossary -->
| Term | Definition | Aliases |
|---|---|---|
| ADR | Architecture Decision Record |  |
| dHash | Difference hash used for near-duplicate detection; FR-1.3 threshold is Hamming distance <= 2 |  |
| Florence-2 | Florence-2-base-ft INT8 ONNX model run via onnxruntime AVX2 for image captioning/naming (FR-1.7) |  |
| FR | Functional Requirement |  |
| HB-x | Harness behavior rule (e.g. HB-8: every agent comment ends with a Next action line) |  |
| House Style | This repo's documentation policy instance under dev-docs/house-style/ |  |
| ICD | Interface Control Document |  |
| IEA40K | Entropy threshold reference set used against the 11-zone luminance segmentation in FR-1.6 |  |
| IF | Interface Requirement (ICD-backed boundary) |  |
| KPM | Key Performance Measure — measured, rolled up parent-ward | budget |
| NFR | Non-Functional Requirement |  |
| PHOTON cartridge | External SSD cartridge holding library.db and user config for the photo-workflow pipeline (NFR-2.3); not host-resident |  |
| Profile A | Software-only tool-stack profile for this project; no EE/ME/firmware tooling |  |
| safe-eject | scripts/safe_eject.sh procedure for cleanly unmounting the PHOTON cartridge without SQLite corruption (KPM-1.4) |  |
| SOP-B | Resume mid-flight work procedure |  |
| stage gate | Milestone closure condition: all UNs in the stage verified |  |
| UN | User Need — top-level requirement, owns FR/NFR/IF/KPM children |  |
| V&V | Verification (per-commit, against requirements) and Validation (per-milestone, against user needs) |  |
| zenity | Linux dialog tool used to prompt the user (NFR-2.4: dialog when SD inserted without SSD connected) |  |
<!-- /AUTO:glossary -->
