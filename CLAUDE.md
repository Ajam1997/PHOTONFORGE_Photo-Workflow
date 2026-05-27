# Photo Workflow -- Autonomous Ingest-to-Edit System

## Context
Offline photography pipeline for Lenovo Yoga 910-13IKB Glass (i7-7500U, 8GB RAM).
Ingests from SD/SSD, analyzes, scores, names, and syncs to Darktable.
All inference runs locally via INT8 ONNX on AVX2. Container OS: Debian Stable / Ubuntu 24.04.

## Agent Roster
- @architect (opus, read-only): architecture, interfaces, CLAUDE.md maintenance
- @engineer (sonnet): src/, tests/, models/
- @devops (sonnet): deploy/, scripts/
- @verification (sonnet): commit-level test enforcement, KPM benchmarks
- @validation (sonnet): milestone E2E validation, user need compliance

## Architecture Decisions
- Composition over inheritance. AnalysisPipeline delegates to module functions.
- No class hierarchies. Each module exposes a function-based API + click CLI entry point.
- onnxruntime CPU provider only. No GPU paths.

## Constraints
- NFR-2.1: 100% offline at runtime. No network calls during pipeline execution. Initial machine provisioning (OS, packages, model downloads, quantization) may use the internet — see scripts/provision_models.sh.
- NFR-2.2: Total RSS <= 1.5 GB; CPU affinity capped at 80%.
- NFR-2.3: library.db + user config live on external SSD, not host.
- NFR-2.4: zenity dialog when SD inserted without SSD connected.
- Target CPU: i7-8550U with AVX2. All benchmarks run against this profile.

## FR Thresholds
- FR-1.3: dHash Hamming distance <= 2 for near-duplicate detection.
- FR-1.6: 11-zone luminance segmentation; entropy vs. IEA40K threshold.
- FR-1.7: Model is Florence-2-base-ft INT8 ONNX via onnxruntime AVX2.

## KPMs
- KPM-1.1: Ingest >= 80% USB 3.0 BW (@devops)
- KPM-1.2: Florence-2 inference <= 2.5s/image on i7-7500U (@engineer)
- KPM-1.3: Analyzer RSS <= 1.5 GB (@engineer)
- KPM-1.4: Zero SQLite corruption / 50 safe-eject cycles (@devops)

## Conventions
- Python 3.11+, type hints on all public functions; click for CLI entry points
- ruff for linting, pytest for testing
- Shell scripts: set -euo pipefail, ShellCheck clean
- Every module gets unit tests in tests/

## Project Layout
src/photo_workflow/
  pipeline.py, ingest.py, grouping.py, dedup.py,
  sharpness.py, composition.py, exposure.py,
  naming.py, darktable_bridge.py, cartridge.py
scripts/   -- safe_eject.sh, manage_ssd.sh, install_udev.sh
deploy/    -- Dockerfile, docker-compose.yml, udev/
tests/     -- fixtures/, test_*.py
models/    -- florence2_int8/ (vendored, not downloaded)

## Build Sequence
1. Scaffold (@architect): pyproject.toml, directory structure, empty modules ✓
2. Core Engine (@engineer): grouping, dedup, sharpness, composition, exposure + tests ✓
3. Inference + Bridge (@engineer): Florence-2-base-ft naming + Darktable SQLite/XMP ✓
4. Host Integration (@devops): udev rules, SSD cartridge scripts, Dockerfile ✓
5. Integration (@engineer + @architect): wire pipeline.py — PipelineSummary telemetry, --model-dir CLI flag, SD→SSD staging path; 10 integration tests covering grouping→dedup→scoring→naming→Darktable flow with 6 synthetic fixture images ✓
6. Scoring System Modularization (@engineer, in progress): replace the monolithic `score_fusion.py` with a five-module pipeline (`region_router` → `sub_scores/*` → `technical_gate` + `aesthetic_weighter` → `fusion`) driven by the 16-Subject × 12-Photo-Type taxonomy. Subject is the region router; Type is the aesthetic weighter; master score is `min(technical, aesthetic)` with a swappable fusion strategy. Per-Type weights live in SQLite (`aesthetic_weights` table) bootstrapped from `docs/research/scoring-redesign.md §5`. Interfaces are locked in `docs/architecture/scoring-module-contracts.md`; execute the 6-step migration checklist at the bottom of that doc, one independently revertable step per PR. Backward compatibility for `pipeline.py` / `darktable_bridge.py` / XMP writer is preserved via `FusionResult`'s existing flat fields and `SubScoreBundle.as_flat_dict()`. Step 1 brief: `docs/architecture/stage-6-engineer-brief.md`.

Full spec: docs/photo-workflow-architecture-v4.docx

## Agent Write-back Protocol

Agents write results back to GitHub Issues via `scripts/github_comment.py`.
**Never call the GitHub API directly.** All commands read GITHUB_TOKEN from environment.
Issue numbers are resolved automatically from `docs/github-issue-map.json`.

**@verification** (after every commit to main):
```bash
# On test pass:
python scripts/github_comment.py verify-fr FR-1.2 "pytest: 5/5 passed, 1.8s avg"
# On regression:
python scripts/github_comment.py regress-fr FR-1.2 "test_sharpness failed: expected 0.85 got 0.72"
# After benchmark:
python scripts/github_comment.py update-kpm KPM-1.2 "1.8s on i7-7500U — 2026-05-23" passing
```

**@validation** (on milestone merge or manual invocation):
```bash
# On E2E pass:
python scripts/github_comment.py validate-un UN-010 "all 3 grouping scenarios passed"
# On E2E failure:
python scripts/github_comment.py validation-failure UN-010 "wrong clusters on burst shots — 4 grouped, expected 1"
```

## Remote Execution
Client-side testing runs via SSH to alex@<yoga-ip>. The Yoga 910 hosts the runtime environment with mounted PHOTON cartridges and SD reader. Use scripts/remote_test.sh as the standard entry point. Physical hardware actions (plug/unplug) require human intervention -- agents use prompt-and-wait pattern for these.
