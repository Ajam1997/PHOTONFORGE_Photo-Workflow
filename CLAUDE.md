# Photo Workflow -- Autonomous Ingest-to-Edit System

## Context
Offline photography pipeline for Lenovo Yoga 910-13IKB Glass (i7-7500U, 8GB RAM).
Ingests from SD/SSD, analyzes, scores, names, and syncs to Darktable.
All inference runs locally via INT8 ONNX on AVX2. Container OS: Debian Stable / Ubuntu 24.04.

## Agent Roster

Agents ship via the PHOTONFORGE marketplace (systems-first-core + systems-first-software plugins); local .claude/agents/ copies were removed 2026-07.

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
- PR scoping: small low-risk bugfixes land in the rolling **minor-bug roundup** PR; a bug that trips any complexity trigger gets its own PR; enhancements always get their own PR. Full policy: `dev-docs/architecture/pr-conventions.md`
- Documentation conventions (docs-impact matrix, supersession banner, glossary, templates) are data-driven and enforced by `sf-style` — see `dev-docs/house-style/`

## Project Layout
src/photo_workflow/  (26 modules)
  pipeline.py, ingest.py, grouping.py, dedup.py,
  sharpness.py, composition.py, exposure.py,
  score_fusion.py, scoring_types.py, subject_context.py,
  genre_router.py, genre_adapter.py, genre_trainer.py,
  active_learning.py, training_weights_db.py,
  naming.py, raw_loader.py, darktable_bridge.py,
  photondb.py, cartridge.py, volume.py, provision.py, backup.py,
  portable.py -- self-contained portable-drive assembly (make-portable); see ADR-008
  relocate.py -- safe move/migrate of ingested photos between shoot folders/cartridges
  (same-cartridge only; UPDATE-in-place on photonforge.db + Darktable's library.db,
  never delete+reinsert); CLI: `photo-cartridge move-photos`/`move-shoot`/`resume-move`
  wsl_bridge.py -- WSL2 orchestration for make-portable --os linux from a native
  Windows host (AppImage extraction needs a Linux ELF-execution capability)
src/cartridge_manager/ -- standalone PySide6 desktop app for cartridge management
  (list/detail, move, backup/restore/provision, a lightweight viewer) -- entirely
  separate from the Darktable Lua plugin and the portable-drive build; imports
  photo_workflow directly (not a second implementation, not a CLI-shelling wrapper);
  Windows-only target, developed/tested headlessly via QT_QPA_PLATFORM=offscreen;
  console script: `cartridge-manager`. See
  dev-docs/superpowers/plans/2026-08-21-cartridge-manager-plan.md.
lua/photonforge/ -- Darktable Lua plugin (panel, runner, tag_manager, applicator, json, config)
scripts/   -- safe_eject.sh, manage_ssd.sh, install_polkit.sh, remote_test.sh,
              build_portable_cli.{sh,ps1} + photonforge.spec (PyInstaller onedir freeze),
              portable/freeze_entry_photo_{workflow,cartridge}.py
              (doc machinery now in the systems-first package, sf-* CLIs)
deploy/    -- Dockerfile, docker-compose.yml, portable/PHOTONForge.{ps1,bat,sh}.tmpl (drive launchers)
config/    -- portable-manifest.yml (pinned per-OS Darktable downloads, sha256-verified, no TOFU)
tests/     -- fixtures/, test_*.py
models/    -- florence2_int8/ (vendored, not downloaded)
dev-docs/  -- developer documentation (markdown source for the GitHub Wiki)
docs/      -- end-user documentation: install-yoga-linux.md, portable-drive-setup.md
.github/workflows/ -- CI: tests.yml (pytest -m "not slow" + ruff), docs-integrity.yml, regen-docs, wiki-publish

Note: `apps/`, `runtime/`, `dt-config/` are **drive-layout** directories
`make-portable` writes onto a portable cartridge (see ADR-008) — they are
never present in this repo tree, only in `deploy/portable/*.tmpl` (source)
and `docs/portable-drive-setup.md` (the layout diagram).

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
`sf-docs`; the wiki is a one-way export. Agents post evidence
as Issue comments. Agents do **not** edit `dev-docs/living-user-needs.md` or any
other AUTO-managed file by hand, and they do **not** move status labels — that
is `sf-pr-rollup`'s job on PR merge. See `dev-docs/architecture/doc-source-of-truth.md`.

Agents write results via `sf-comment`. **Never call the GitHub
API directly.** All commands read GITHUB_TOKEN from environment. Requirement
IDs (FR-X.Y, UN-XXX, KPM-X.Y) are resolved live via `gh issue list --search`;
no local map file is required.

Every comment **must** end with a `**Next action:** ...` line (HB-8 — enables
SOP-B "resume mid-flight work"). Every agent comment carries a `via: @<agent>`
footer so the writer's origin is legible to the next reader (HB-7).

**@verification** (after every commit to main, posts measurements only):
```bash
# On test pass:
sf-comment verify-fr FR-1.2 \
  "pytest: 5/5 passed, 1.8s avg" \
  --next-action "merge ready; @software_lead to open PR"
# On regression:
sf-comment regress-fr FR-1.2 \
  "test_sharpness failed: expected 0.85 got 0.72" \
  --next-action "@software_lead revisit blur kernel threshold"
# After benchmark:
sf-comment update-kpm KPM-1.2 \
  "1.8s on i7-7500U — 2026-05-23" passing \
  --next-action "no action; KPM still inside budget"
```

**@validation** (on milestone merge or manual invocation, posts evidence only):
```bash
# On E2E pass:
sf-comment validate-un UN-010 \
  "all 3 grouping scenarios passed" \
  --next-action "stage 2 closes; ready to start stage 3"
# On E2E failure:
sf-comment validation-failure UN-010 \
  "wrong clusters on burst shots — 4 grouped, expected 1" \
  --next-action "@systems_lead to reassess FR-1.1 dHash threshold"
```

## Remote Execution
Client-side testing runs via SSH to alex@<yoga-ip>. The Yoga 910 hosts the runtime environment with mounted PHOTON cartridges and SD reader. Use scripts/remote_test.sh as the standard entry point. Physical hardware actions (plug/unplug) require human intervention -- agents use prompt-and-wait pattern for these.
