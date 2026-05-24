# Living User Need Document -- PHOTONForge

> **Source of truth:** [GitHub Projects — Requirements Board](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/projects).
> This file is auto-generated from GitHub Issues — do not edit the section below manually.

## Format
UN-[ID]: [User need in plain language]
Acceptance: [Observable, measurable output]
KPM: [KPM ID or NONE]
Stage: [Roadmap stage number]
Status: [DEFINED | VERIFIED | VALIDATED]

## Requirements

<!-- AUTO:user_needs -->
[UN-001](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/30): The system installs without errors on the target machine.
Acceptance: pip install -e . exits 0. pytest --collect-only finds all test files.
KPM: NONE
Stage: 1
Status: DEFINED

[UN-002](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/31): All five primary agents are discoverable by Claude Code.
Acceptance: claude agents lists @architect, @engineer, @devops, @verification, @validation.
KPM: NONE
Stage: 1
Status: DEFINED

[UN-010](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/32): Photos are automatically grouped into shooting sessions.
Acceptance: cluster_sessions() correctly groups fixture images by time and location.
KPM: NONE
Stage: 2
Status: DEFINED

[UN-011](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/33): Near-duplicate photos are archived.
Acceptance: deduplicate() archives images with dHash Hamming <= 2. No false positives.
KPM: NONE
Stage: 2
Status: DEFINED

[UN-012](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/34): Each photo receives a sharpness score.
Acceptance: score_sharpness() returns float in [0.0, 1.0] for all fixture images.
KPM: NONE
Stage: 2
Status: DEFINED

[UN-013](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/35): Each photo receives a composition score.
Acceptance: score_composition() returns float in [0.0, 1.0].
KPM: NONE
Stage: 2
Status: DEFINED

[UN-014](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/36): Each photo receives an exposure score.
Acceptance: score_exposure() returns float in [0.0, 1.0]. 11-zone entropy applied.
KPM: NONE
Stage: 2
Status: DEFINED

[UN-020](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/37): Each photo receives a descriptive semantic filename.
Acceptance: generate_name() returns a non-empty string. No raw DSC names in output.
KPM: KPM-1.2
Stage: 3
Status: DEFINED

[UN-021](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/38): Processed photos are synced to Darktable with scores and metadata.
Acceptance: library.db contains a record per image. XMP sidecar written per image.
KPM: NONE
Stage: 3
Status: DEFINED

[UN-030](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/39): Photos ingest automatically from SD card on insertion.
Acceptance: SD insertion triggers rsync to SSD within 10 seconds.
KPM: KPM-1.1
Stage: 4
Status: DEFINED

[UN-031](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/40): SSD cartridges function as portable photo libraries.
Acceptance: SSD mounts at /mnt/photon_ssd/001. library.db resides at /mnt/photon_ssd/001/darktable/library.db on cartridge.
KPM: NONE
Stage: 4
Status: DEFINED

[UN-032](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/41): SSD cartridges eject safely without data loss.
Acceptance: safe_eject.sh flushes SQLite WAL. Zero corruption over 50 eject cycles.
KPM: KPM-1.4
Stage: 4
Status: DEFINED

[UN-040](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/42): Workflow should move photos from SD card to temporary storage on SSD to allow for safe removal of SD card before processing.
Acceptance: rsync 1000 images to SSD per 120 seconds.
KPM: KPM-1.1
Stage: 6
Status: DEFINED

[UN-041](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/43): The system should automaticaly eject and notify the SD card after transfering photos to the SSD.
Acceptance: SD card is ejected and the user is notified that the photos have been transfered to the SSD.
KPM: KPM-1.4/KPM-1.1
Stage: 7
Status: DEFINED

[UN-051](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/45): The pipeline tracks per-photo processing state across stages via a DB File.
Acceptance: ingest creates a SQLite DB file. Each subsequent stage reads and updates it. DB records per-photo stages_completed, scores, semantic_name, and errors.
KPM: NONE
Stage: 5
Status: DEFINED

[UN-052](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/46): Long-running pipeline stages are resumable after interruption.
Acceptance: score and name stages with --resume skip photos already completed. Checkpoint flush every 50 photos via atomic file replace. On crash, at most 50 photos of progress lost.
KPM: NONE
Stage: 5
Status: DEFINED

[UN-053](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/47): The pipeline displays real-time progress with throughput and ETA during batch processing.
Acceptance: score and name stages print in-place progress line showing count/total, percentage, images/sec, ETA, and RSS. --verbose and --quiet flags control detail level.
KPM: NONE
Stage: 5
Status: DEFINED

[UN-054](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/48): The pipeline gracefully handles per-photo errors without aborting the batch.
Acceptance: Corrupt files or inference failures log a warning, record error in manifest, and continue. Failed photos are retried on --resume. Final summary reports error count.
KPM: NONE
Stage: 5
Status: DEFINED

<!-- /AUTO:user_needs -->
