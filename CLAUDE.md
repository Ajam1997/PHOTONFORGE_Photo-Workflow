# Photo Workflow -- Autonomous Ingest-to-Edit System

## Context
Offline photography pipeline for Lenovo Yoga 920 Star Wars Edition (i7-8550U, 16GB RAM).
Ingests from SD/SSD, analyzes, scores, names, and syncs to Darktable.
All inference runs locally via INT8 ONNX on AVX2. Container OS: Debian Stable / Ubuntu 24.04.

## Agent Roster
- @architect (opus, read-only): architecture, interfaces, CLAUDE.md maintenance
- @engineer (sonnet): src/, tests/, models/
- @devops (sonnet): deploy/, scripts/

## Architecture Decisions
- Composition over inheritance. AnalysisPipeline delegates to module functions.
- No class hierarchies. Each module exposes a function-based API + click CLI entry point.
- onnxruntime CPU provider only. No GPU paths.

## Constraints
- NFR-2.1: 100% offline. No network calls anywhere.
- NFR-2.2: Total RSS <= 2 GB; CPU affinity capped at 80%.
- NFR-2.3: library.db + user config live on external SSD, not host.
- NFR-2.4: zenity dialog when SD inserted without SSD connected.
- Target CPU: i7-8550U with AVX2. All benchmarks run against this profile.

## FR Thresholds
- FR-1.3: dHash Hamming distance <= 2 for near-duplicate detection.
- FR-1.6: 11-zone luminance segmentation; entropy vs. IEA40K threshold.
- FR-1.7: Model is Florence-2-base-ft INT8 ONNX via onnxruntime AVX2.

## KPMs
- KPM-1.1: Ingest >= 80% USB 3.0 BW (@devops)
- KPM-1.2: Florence-2 inference <= 1.5s/image on i7-8550U (@engineer)
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
1. Scaffold (@architect): pyproject.toml, directory structure, empty modules
2. Core Engine (@engineer): grouping, dedup, sharpness, composition, exposure + tests
3. Inference + Bridge (@engineer): Florence-2-base-ft naming + Darktable SQLite/XMP
4. Host Integration (@devops): udev rules, SSD cartridge scripts, Dockerfile
5. Scaling + UI (@devops): Selkies 4K 200% scaling, zenity prompts
6. Integration (lead + @architect): wire pipeline.py, end-to-end test on Yoga 920

Full spec: docs/photo-workflow-architecture-v4.docx
