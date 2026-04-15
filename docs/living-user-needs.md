# Living User Need Document -- PHOTONForge

## Format
UN-[ID]: [User need in plain language]
Acceptance: [Observable, measurable output]
KPM: [KPM ID or NONE]
Stage: [Roadmap stage number]
Status: [DEFINED | VERIFIED | VALIDATED]

## Requirements

UN-001: The system installs without errors on the target machine.
Acceptance: pip install -e . exits 0. pytest --collect-only finds all test files.
KPM: NONE
Stage: 1
Status: DEFINED

UN-002: All five primary agents are discoverable by Claude Code.
Acceptance: claude agents lists @architect, @engineer, @devops, @verification, @validation.
KPM: NONE
Stage: 1
Status: DEFINED

UN-010: Photos are automatically grouped into shooting sessions.
Acceptance: cluster_sessions() correctly groups fixture images by time and location.
KPM: NONE
Stage: 2
Status: DEFINED

UN-011: Near-duplicate photos are archived.
Acceptance: deduplicate() archives images with dHash Hamming <= 2. No false positives.
KPM: NONE
Stage: 2
Status: DEFINED

UN-012: Each photo receives a sharpness score.
Acceptance: score_sharpness() returns float in [0.0, 1.0] for all fixture images.
KPM: NONE
Stage: 2
Status: DEFINED

UN-013: Each photo receives a composition score.
Acceptance: score_composition() returns float in [0.0, 1.0].
KPM: NONE
Stage: 2
Status: DEFINED

UN-014: Each photo receives an exposure score.
Acceptance: score_exposure() returns float in [0.0, 1.0]. 11-zone entropy applied.
KPM: NONE
Stage: 2
Status: DEFINED

UN-020: Each photo receives a descriptive semantic filename.
Acceptance: generate_name() returns a non-empty string. No raw DSC names in output.
KPM: KPM-1.2
Stage: 3
Status: DEFINED

UN-021: Processed photos are synced to Darktable with scores and metadata.
Acceptance: library.db contains a record per image. XMP sidecar written per image.
KPM: NONE
Stage: 3
Status: DEFINED

UN-030: Photos ingest automatically from SD card on insertion.
Acceptance: SD insertion triggers rsync to SSD within 10 seconds.
KPM: KPM-1.1
Stage: 4
Status: DEFINED

UN-031: SSD cartridges function as portable photo libraries.
Acceptance: SSD mounts at /mnt/photon_ssd/001. library.db resides on cartridge.
KPM: NONE
Stage: 4
Status: DEFINED

UN-032: SSD cartridges eject safely without data loss.
Acceptance: safe_eject.sh flushes SQLite WAL. Zero corruption over 50 eject cycles.
KPM: KPM-1.4
Stage: 4
Status: DEFINED
