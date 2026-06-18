# Phase 4 — Issue Body Conversion Review

67 existing Issues + 1 NEW (NFR-2.2). Diff `issue-bodies-new/` vs `issue-bodies-original/`.

See PHASE-4-APPLY-PLAN.md for the GitHub mutation list.

| # | Class | ReqID | Title | Changes |
|---|---|---|---|---|
| 9 | out-of-tree |  | Lua plugin: Stop button delayed during scan st | add: Type |
| 10 | out-of-tree |  | Scan step does not support resume — restarts f | add: Type |
| 11 | out-of-tree |  | Ingest step is slow — per-file commits, no par | add: Type |
| 12 | out-of-tree |  | Improve Darktable plugin logging, progress ind | add: Type |
| 13 | out-of-tree |  | Dedup step is slow — redundant EXIF reads, no  | add: Type |
| 14 | UN | UN-003 | [UN-003] Users can install and configure the s | add: Validated By |
| 15 | out-of-tree |  | Write genre/category from scoring step to Dark | add: Type |
| 16 | UN | UN-022 | [UN-022] Semantic filenames incorporate genre  | add: Validated By |
| 17 | out-of-tree |  | Experimental: creative titling and edit preset | add: Type |
| 18 | out-of-tree |  | Repo cleanup: migrate docs to GitHub, link roa | add: Type |
| 19 | out-of-tree |  | Windows: Stop button silently fails if PID fil | add: Type |
| 20 | out-of-tree |  | Scan step emits no progress — progress bar sta | add: Type |
| 21 | out-of-tree |  | Stale sentinel file causes 5-minute hang after | add: Type |
| 30 | UN | UN-001 | [UN-001] The system installs without errors on | add: Validated By |
| 31 | UN | UN-002 | [UN-002] All five primary agents are discovera | add: Validated By |
| 32 | UN | UN-010 | [UN-010] Photos are automatically grouped into | add: Validated By; KPM wired |
| 33 | UN | UN-011 | [UN-011] Near-duplicate photos are archived. | add: Validated By; KPM wired |
| 34 | UN | UN-012 | [UN-012] Each photo receives a sharpness score | KPM wired |
| 35 | UN | UN-013 | [UN-013] Each photo receives a composition sco | add: Validated By; KPM wired |
| 36 | UN | UN-014 | [UN-014] Each photo receives an exposure score | add: Validated By; KPM wired |
| 37 | UN | UN-020 | [UN-020] Each photo receives a descriptive sem | add: Validated By |
| 38 | UN | UN-021 | [UN-021] Processed photos are synced to Darkta | add: Validated By |
| 39 | UN | UN-030 | [UN-030] Photos ingest automatically from SD c | add: Validated By |
| 40 | UN | UN-031 | [UN-031] SSD cartridges function as portable p | add: Validated By |
| 41 | UN | UN-032 | [UN-032] SSD cartridges eject safely without d | add: Validated By |
| 42 | UN | UN-040 | [UN-040] Workflow should move photos from SD c | add: Validated By |
| 43 | UN | UN-041 | [UN-041] The system should automaticaly eject  | add: Validated By |
| 44 | UN | UN-050 | [UN-050] The pipeline CLI supports staged exec | add: Validated By |
| 45 | UN | UN-051 | [UN-051] The pipeline tracks per-photo process | add: Validated By |
| 46 | UN | UN-052 | [UN-052] Long-running pipeline stages are resu | add: Validated By |
| 47 | UN | UN-053 | [UN-053] The pipeline displays real-time progr | add: Validated By |
| 48 | UN | UN-054 | [UN-054] The pipeline gracefully handles per-p | add: Validated By |
| 49 | FR | FR-1.2 | [FR-1.2] Spatio-Temporal Grouping | add: Verified By,Validated By |
| 50 | FR | FR-1.3 | [FR-1.3] Perceptual Deduplication | add: Verified By,Validated By |
| 51 | FR | FR-1.4 | [FR-1.4] Sharpness Scoring | no change |
| 52 | FR | FR-1.5 | [FR-1.5] Compositional Evaluation | add: Verified By,Validated By |
| 53 | FR | FR-1.6 | [FR-1.6] Exposure Assessment | add: Verified By,Validated By |
| 54 | FR | FR-1.7 | [FR-1.7] Local Semantic Naming | add: Verified By,Validated By |
| 55 | FR | FR-1.8 | [FR-1.8] Darktable Integration | add: Verified By,Validated By |
| 56 | FR | FR-1.1 | [FR-1.1] Automated Media Ingest | add: Verified By,Validated By |
| 57 | FR | FR-1.9 | [FR-1.9] Library Cartridge Management | add: Verified By,Validated By |
| 58 | FR | FR-1.10 | [FR-1.10] Safe Ejection | add: Verified By,Validated By |
| 59 | NFR | NFR-2.1 | [NFR-2.1] Internet Independence | add: Linked Budget,Verified By,Validated By |
| 60 | NFR | NFR-2.4 | [NFR-2.4] Interactive UI Prompts | add: Linked Budget,Verified By,Validated By |
| 61 | NFR | NFR-2.3 | [NFR-2.3] Database Portability | add: Linked Budget,Verified By,Validated By |
| 62 | NFR | NFR-2.5 | [NFR-2.4] Interactive UI Prompts | **RENUMBER NFR-2.4→NFR-2.5 + respec**; add: Linked Budget,Verified By,Validated By |
| 63 | KPM | KPM-1.2 | [KPM-1.2] Inference Speed | add: KPM Status,Measurement Method,Linked Requirements; Status→KPM Status |
| 64 | KPM | KPM-1.1 | [KPM-1.1] Ingest Latency | add: KPM Status,Measurement Method,Linked Requirements; Status→KPM Status |
| 65 | KPM | KPM-1.4 | [KPM-1.4] Data Integrity | add: KPM Status,Measurement Method,Linked Requirements; Status→KPM Status |
| 66 | FR | FR-1.7.1 | [FR-1.7.1] Genre Detection Calibration and Bac | add: Verified By,Validated By; path-fix |
| 67 | FR | FR-1.7.2 | [FR-1.7.2] Multi-Genre Tagging Support | add: Verified By,Validated By; path-fix |
| 68 | KPM | KPM-1.3 | [KPM-1.3] Analyzer Peak RSS | add: KPM Status,Measurement Method,Linked Requirements; Status→KPM Status; Notes→Method |
| 69 | KPM | KPM-1.5 | [KPM-1.5] End-to-End Pipeline Throughput | add: KPM Status,Measurement Method,Linked Requirements; Status→KPM Status; Notes→Method |
| 70 | KPM | KPM-1.6 | [KPM-1.6] Dedup False-Positive Rate | add: KPM Status,Measurement Method,Linked Requirements; Status→KPM Status; Notes→Method |
| 71 | KPM | KPM-1.7 | [KPM-1.7] Naming Output Validity Rate | add: KPM Status,Measurement Method,Linked Requirements; Status→KPM Status; Notes→Method |
| 72 | KPM | KPM-1.8 | [KPM-1.8] Scoring Determinism | add: KPM Status,Measurement Method,Linked Requirements; Status→KPM Status; Notes→Method |
| 73 | KPM | KPM-1.9 | [KPM-1.9] CPU Cap Compliance | add: KPM Status,Measurement Method,Linked Requirements; Status→KPM Status; Notes→Method |
| 74 | KPM | KPM-1.10 | [KPM-1.10] Session Grouping Precision | add: KPM Status,Measurement Method,Linked Requirements; Status→KPM Status; Notes→Method |
| 75 | out-of-tree |  | [Fixture Corpus] Labeled reference image set f | **RECLASSIFY type:fr→verification fixture**; add: Type,Used by,Location |
| 76 | out-of-tree |  | [Enhancement] Lua plugin: genre correction & c | add: Type |
| 77 | out-of-tree |  | [Enhancement] Per-genre score breakdown alongs | add: Type |
| 78 | out-of-tree |  | [Enhancement] Custom tag management UI for Dar | add: Type |
| 80 | out-of-tree |  | Florence-2 grounded captioning: feed Subject/T | add: Type; path-fix |
| 82 | out-of-tree |  | Stage 6: Define fusion error-path semantics | add: Type; path-fix |
| 83 | out-of-tree |  | Stage 6: Add DepthModel Protocol stub to contr | add: Type; path-fix |
| 84 | out-of-tree |  | Stage 6: Specify first-run bootstrap path for  | add: Type; path-fix |
| 85 | out-of-tree |  | Research spike: per-Type weight priors for 5 m | add: Type; path-fix |
| NEW | NFR | NFR-2.2 | Resource Budget | **CREATE** — parents KPM-1.3, KPM-1.9 |
