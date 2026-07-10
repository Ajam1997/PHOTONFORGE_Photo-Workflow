# Photo Workflow -- Autonomous Ingest-to-Edit System

## Context
Offline photography pipeline for Lenovo Yoga 910-13IKB Glass (i7-7500U, 8GB RAM).
Ingests from SD/SSD, analyzes, scores, names, and syncs to Darktable.
All inference runs locally via INT8 ONNX on AVX2. Container OS: Debian Stable / Ubuntu 24.04.

## Agent Roster

| Agent | Scope | Superpowers pairing |
|---|---|---|
| @systems_lead (opus, read-only) | requirements tree, architecture, interfaces (ICDs), CLAUDE.md maintenance | recommend: `brainstorming`, `writing-plans`, `subagent-driven-development` |
| @software_lead (haiku) | src/, tests/, models/ + host integration (deploy/, scripts/, udisks2 polling, polkit, SSD cartridge scripts) — the single implementation discipline (Profile A; absorbs the former @devops scope) | recommend: `test-driven-development`, `subagent-driven-development`, `systematic-debugging`, `verification-before-completion`, `using-git-worktrees` |
| @verification (inherit) | commit-level test enforcement, KPM benchmarks | **mandate**: `verification-before-completion` |
| @validation (inherit) | milestone E2E validation, user need compliance | **mandate**: `verification-before-completion` |
| @systemmaster (operator-only) | deep cross-cutting reviews | n/a |

> **Roster migrated 2026-05-29** to the systems-first-template naming:
> `@architect`→`@systems_lead`, `@engineer`→`@software_lead`, and the
> former `@devops` scope folded into `@software_lead` (Profile A has a
> single implementation discipline). See `dev-docs/Archive/migration-plan.md`.

Start every session with `dev-docs/start-work-checklist.md` (≈60s).
The full pairing rationale lives in
`dev-docs/SystemReviews/2026-05-26-architecture-and-docs-migration-review.md` §6.4.

## Architecture Decisions
- Composition over inheritance. AnalysisPipeline delegates to module functions.
- No class hierarchies. Each module exposes a function-based API + click CLI entry point.
- onnxruntime CPU provider only. No GPU paths.

## Constraints
- NFR-2.1: 100% offline at runtime. No network calls during pipeline execution. Initial machine provisioning (OS, packages, model downloads, quantization) may use the internet — see scripts/provision_models.sh.
- NFR-2.2: Total RSS <= 1.5 GB; CPU affinity capped at 80%.
- NFR-2.3: library.db + user config live on external SSD, not host.
- NFR-2.4: zenity dialog when SD inserted without SSD connected.
- Target CPU: i7-7500U with AVX2. All benchmarks run against this profile.

## FR Thresholds
- FR-1.3: dHash Hamming distance <= 2 for near-duplicate detection.
- FR-1.6: 11-zone luminance segmentation; entropy vs. IEA40K threshold.
- FR-1.7: Model is Florence-2-base-ft INT8 ONNX via onnxruntime AVX2.

## KPMs
- KPM-1.1: Ingest >= 80% USB 3.0 BW (@software_lead)
- KPM-1.2: Florence-2 inference <= 2.5s/image on i7-7500U (@software_lead)
- KPM-1.3: Analyzer RSS <= 1.5 GB (@software_lead)
- KPM-1.4: Zero SQLite corruption / 50 safe-eject cycles (@software_lead)

Full KPM tree (10 KPMs) with parents + targets: `requirements/requirement-map.yml`.

## Tool Stack
Profile A (software-only). No EE/ME/firmware tooling.
- **Language:** Python 3.11+, type hints on all public functions
- **CLI:** click entry points (`photo-workflow` console script)
- **Lint/format:** ruff
- **Test:** pytest (`tests/`)
- **Inference:** onnxruntime CPU provider (INT8, AVX2) — MobileCLIP, YOLO, Florence-2-base-ft
- **Editor integration:** Darktable Lua plugin (`lua/photonforge/`) ↔ CLI over subprocess (IF-1.1)
- **Shell:** bash, `set -euo pipefail`, ShellCheck clean

See `dev-docs/architecture/external-tools.md` for the template's full
stack rationale (most of it — EE/ME — is N/A for this project).

## Conventions
- Python 3.11+, type hints on all public functions; click for CLI entry points
- ruff for linting, pytest for testing
- Shell scripts: set -euo pipefail, ShellCheck clean
- Every module gets unit tests in tests/
- PRs that change code must update the affected docs — see the docs-impact matrix in `dev-docs/architecture/doc-maintenance-protocol.md` (banner convention, AUTO-section rules, and the "Docs impact" PR-description line live there too)

## Project Layout
src/photo_workflow/  (22 modules)
  pipeline.py, ingest.py, grouping.py, dedup.py,
  sharpness.py, composition.py, exposure.py,
  score_fusion.py, scoring_types.py, subject_context.py,
  genre_router.py, genre_adapter.py, genre_trainer.py,
  active_learning.py, training_weights_db.py,
  naming.py, raw_loader.py, darktable_bridge.py,
  photondb.py, cartridge.py, volume.py, provision.py
lua/photonforge/ -- Darktable Lua plugin (panel, runner, tag_manager, applicator, json, config)
scripts/   -- safe_eject.sh, manage_ssd.sh, install_polkit.sh, remote_test.sh, doc automation
deploy/    -- Dockerfile, docker-compose.yml
tests/     -- fixtures/, test_*.py
models/    -- florence2_int8/ (vendored, not downloaded)
dev-docs/  -- developer documentation (markdown source for the GitHub Wiki)
docs/      -- placeholder for future end-user documentation (currently empty)
.github/workflows/ -- CI: tests.yml (pytest -m "not slow" + ruff), docs-integrity.yml, regen-docs, nightly-drift, wiki-publish

## Build Sequence
1. Scaffold (@systems_lead): pyproject.toml, directory structure, empty modules ✓
2. Core Engine (@software_lead): grouping, dedup, sharpness, composition, exposure + tests ✓
3. Inference + Bridge (@software_lead): Florence-2-base-ft naming + Darktable SQLite/XMP ✓
4. Host Integration (@software_lead): udisks2 polling + polkit rules, SSD cartridge scripts, Dockerfile ✓
5. Integration (@software_lead + @systems_lead): wire pipeline.py — PipelineSummary telemetry, --model-dir CLI flag, SD→SSD staging path; 10 integration tests covering grouping→dedup→scoring→naming→Darktable flow with 6 synthetic fixture images ✓
6. Scoring System (as-built, complete): two-axis 15-Subject × 11-Photo-Type scoring inside `score_fusion.py` — subject/type weight profiles in SQLite (`aesthetic_weights` table), weight renormalization for not-applicable signals, hard-reject gates, master score with per-shoot percentile star rating. The originally planned five-module split (`region_router` → `sub_scores/*` → `technical_gate` + `aesthetic_weighter` → `fusion`) was superseded — see the banner on `dev-docs/Archive/architecture/scoring-module-contracts.md`. ✓

Full spec: dev-docs/Archive/photo-workflow-architecture-v4.docx

## Agent Write-back Protocol

**Canonical source of truth: GitHub Issues.** `dev-docs/` is a render target via
`scripts/generate_docs.py`; the wiki is a one-way export. Agents post evidence
as Issue comments. Agents do **not** edit `dev-docs/living-user-needs.md` or any
other AUTO-managed file by hand, and they do **not** move status labels — that
is `pr_rollup.py`'s job on PR merge. See `dev-docs/architecture/doc-source-of-truth.md`.

Agents write results via `scripts/github_comment.py`. **Never call the GitHub
API directly.** All commands read GITHUB_TOKEN from environment. Requirement
IDs (FR-X.Y, UN-XXX, KPM-X.Y) are resolved live via `gh issue list --search`;
no local map file is required.

Every comment **must** end with a `**Next action:** ...` line (HB-8 — enables
SOP-B "resume mid-flight work"). Every agent comment carries a `via: @<agent>`
footer so the writer's origin is legible to the next reader (HB-7).

**@verification** (after every commit to main, posts measurements only):
```bash
# On test pass:
python scripts/github_comment.py verify-fr FR-1.2 \
  "pytest: 5/5 passed, 1.8s avg" \
  --next-action "merge ready; @software_lead to open PR"
# On regression:
python scripts/github_comment.py regress-fr FR-1.2 \
  "test_sharpness failed: expected 0.85 got 0.72" \
  --next-action "@software_lead revisit blur kernel threshold"
# After benchmark:
python scripts/github_comment.py update-kpm KPM-1.2 \
  "1.8s on i7-7500U — 2026-05-23" passing \
  --next-action "no action; KPM still inside budget"
```

**@validation** (on milestone merge or manual invocation, posts evidence only):
```bash
# On E2E pass:
python scripts/github_comment.py validate-un UN-010 \
  "all 3 grouping scenarios passed" \
  --next-action "stage 2 closes; ready to start stage 3"
# On E2E failure:
python scripts/github_comment.py validation-failure UN-010 \
  "wrong clusters on burst shots — 4 grouped, expected 1" \
  --next-action "@systems_lead to reassess FR-1.1 dHash threshold"
```

## Remote Execution
Client-side testing runs via SSH to alex@<yoga-ip>. The Yoga 910 hosts the runtime environment with mounted PHOTON cartridges and SD reader. Use scripts/remote_test.sh as the standard entry point. Physical hardware actions (plug/unplug) require human intervention -- agents use prompt-and-wait pattern for these.
