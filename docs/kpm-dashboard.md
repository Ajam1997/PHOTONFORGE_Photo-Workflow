# KPM Dashboard

> Auto-generated from GitHub Issues. Source of truth: [PHOTONForge KPM Dashboard board](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/projects).

<!-- AUTO:kpm_table -->
| KPM | Metric | Target | Owner | Verified By | Last Measured | Status |
|:---|:---|:---|:---|:---|:---|:---|
| [KPM-1.1](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/64) | Ingest Latency | >= 80% USB 3.0 bandwidth | @devops | @verification | untested | untested |
| [KPM-1.10](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/74) | Session Grouping Precision | >= 90% F1 score on session boundary detection against labeled fixture corpus | @engineer | @verification | untested | untested |
| [KPM-1.2](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/63) | Inference Speed | <= 2.5s per image (Florence-2 INT8) | @engineer | @verification | untested | untested |
| [KPM-1.3](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/68) | Analyzer Peak RSS | <= 1.5 GB peak RSS during full scoring pipeline | @engineer | @verification | untested | untested |
| [KPM-1.4](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/65) | Data Integrity | Zero SQLite corruption over 50 eject cycles | @devops | @validation | untested | untested |
| [KPM-1.5](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/69) | End-to-End Pipeline Throughput | >= 10 photos/min on i7-7500U (full ingest → score → name pipeline) | @engineer | @verification | untested | untested |
| [KPM-1.6](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/70) | Dedup False-Positive Rate | <= 1% false-positive rate on known-distinct image corpus | @engineer | @verification | untested | untested |
| [KPM-1.7](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/71) | Naming Output Validity Rate | >= 95% of outputs are non-trivial semantic captions (not 'yes', 'no', or 'answering does not require reading') | @engineer | @verification | untested | untested |
| [KPM-1.8](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/72) | Scoring Determinism | Score variance <= 0.01 on identical image run twice (sharpness, composition, exposure, master) | @engineer | @verification | untested | untested |
| [KPM-1.9](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/73) | CPU Cap Compliance | Peak CPU utilisation <= 80% of available cores during full pipeline run | @devops | @verification | untested | untested |
<!-- /AUTO:kpm_table -->
