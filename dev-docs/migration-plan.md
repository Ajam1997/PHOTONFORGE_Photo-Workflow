# Migration Plan — Photo-Workflow → systems-first-template

> **Author:** @claude + @alex (2026-05-29)
> **Status:** decisions locked, Phase 1 in progress
> **Target template state:** `Ajam1997/systems-first-template@a7af30a` or later
>
> **Locked decisions (2026-05-29):**
> 1. **Agent roster:** use template names. Rename `architect.md` →
>    `systems_lead.md`, `engineer.md` → `software_lead.md`, fold
>    `devops.md` into `software_lead.md` (Profile A has no separate
>    devops lead). `verification`, `validation`, `systemmaster` keep
>    current names.
> 2. **Stage numbering:** match template's Profile A 5-stage default
>    (Discovery → Design → Implementation → Verification → Release).
>    Existing 6 stages remap.
> 3. **`github-issue-map.json`:** delete during Phase 9 cleanup.

This plan migrates photo-workflow into structural alignment with the
[systems-first-template](https://github.com/Ajam1997/systems-first-template)
that was extracted *from this project* during the PHOTONForge review. The
template incorporated photo-workflow's patterns; this plan brings
photo-workflow up to the template's current formal structure.

---

## Goal

A photo-workflow repo that:

1. Conforms to the template's directory layout (config/, requirements/,
   artifacts/, expanded dev-docs/architecture/, complete prompts/)
2. Has a `requirements/requirement-map.yml` reflecting all open work
3. Has Issue bodies normalized to the template's `**Verified By:**` /
   `**Validated By:**` / acceptance-criteria pattern
4. Has a `dev-docs/architecture/system-architecture-contracts.md` capturing
   the module decomposition (pipeline, scoring system, Darktable bridge,
   cartridge manager, lua plugin, GUI layer)
5. Renders cleanly through the template's `generate_docs.py`,
   `kpm_rollup.py`, `export_sysml.py`, `validate_artifacts.py`
6. Has an inception record (backfilled `prompts/bootstrap_alex.md`) that
   captures what this project IS in template terms

## Non-goals

- **Not** rewriting any application code (`src/photo_workflow/`,
  `lua/`, `models/`, `corpus/`).
- **Not** changing the GitHub repo URL or default branch.
- **Not** breaking active work. Migration runs in parallel; nothing
  active blocks on it.
- **Not** moving the project to a different language, tool stack, or
  Profile classification. This is and stays Profile A (software).

---

## Current state (assessed 2026-05-29)

| Surface | State |
|---|---|
| Directory layout | Substantial overlap (`dev-docs/architecture/`, `dev-docs/SystemReviews/`, `_wiki-nav.yml`, `.claude/agents/`) but missing `config/`, `requirements/`, `artifacts/`, `prompts/` |
| GitHub Issues | 67 total; labels use template namespaces (`type: fr`, `type: kpm`, `status: defined`) but Issue *bodies* use ad-hoc structure (`## Context`/`## Recommendation`/`## When`) not template format |
| Agent roster | 6 agents present: `architect`, `devops`, `engineer`, `systemmaster`, `validation`, `verification` — predates the template's discipline-lead naming (`systems_lead`, `software_lead`, etc.) |
| Scripts | Has 20 scripts incl. `generate_docs.py`, `github_client.py`, `github_comment.py`, `migrate_wiki.py`, `pr_rollup.py`, `check_drift.py`; missing template's `init_project.py`, `kpm_rollup.py`, `export_sysml.py`, `validate_artifacts.py`, `sync_labels.py` |
| CLAUDE.md | 120 lines, project-specific; mostly current; missing Tool Stack section, references obsolete agent names in places |
| Engineer briefs | Several exist in `dev-docs/architecture/` (gui-layer-handoff, stage-6, hb-3-wiki-refactor); format predates template's `## Open questions if you stop mid-step` requirement |
| Lua plugin | `lua/` directory holds Darktable plugin; no current artifact-manifest treatment |
| Models | `models/florence2_int8/` is vendored, large; needs an `artifacts/software/` manifest pointing at vault/git-LFS storage |

## Target state alignment

| Template feature | This project's equivalent |
|---|---|
| Profile | **A — Software** (systems + software disciplines) |
| Stages | Repurpose existing Stage 1–6 (Scaffold, Core Engine, Inference+Bridge, Host Integration, Integration, Scoring) — these are already in `CLAUDE.md` and map to GitHub Milestones |
| Active discipline leads | `systems_lead` (replacing `architect`), `software_lead` (replacing `engineer`). `devops` may stay or fold into `software_lead`. Universal: `verification`, `validation`, `systemmaster`. |
| Top-level discipline sources | `src/photo_workflow/` (already correct for Profile A) |
| Artifacts | `artifacts/software/` for Florence-2 model manifests; `artifacts/firmware/` N/A; no `artifacts/electrical|mechanical/` |

---

## Migration phases

Each phase has effort estimate (hours), dependencies (what must come
first), risk, and reversibility (how to back out).

### Phase 0 — Decisions + planning (NOW)

| Field | Value |
|---|---|
| Goal | Operator (you) confirms approach, agent roster mapping, stage numbering |
| Effort | ~30 min (review this doc + decision questions below) |
| Dependencies | None |
| Risk | Low — no file changes |
| Reversibility | Trivially |

**Decisions the operator must make before Phase 1:**

1. **Agent roster mapping.** The template uses `systems_lead`,
   `software_lead`, `verification`, `validation`, `systemmaster`. The
   project currently has `architect`, `engineer`, `devops`,
   `verification`, `validation`, `systemmaster`. Three options:
   - **(a) Rename in place** — `architect.md` → `systems_lead.md`,
     `engineer.md` → `software_lead.md`, fold `devops.md` into
     `software_lead.md` since Profile A doesn't have a dedicated DevOps
     lead in the template
   - **(b) Keep current names**, accept divergence from template
     vocabulary
   - **(c) Hybrid** — rename `architect`/`engineer`, keep `devops` as a
     project-specific addition
2. **Stage numbering.** Existing stages (1–6) don't match the template's
   default Profile A 5-stage flow. Keep existing 6 stages and update
   `config/stages.yml` to match, or remap to template's defaults?
3. **`github-issue-map.json`.** Obsolete once `requirement-map.yml`
   lands. Delete during migration, or keep as historical reference?

### Phase 1 — Scaffold structural files (low risk)

| Field | Value |
|---|---|
| Goal | Add missing directories and template scripts that don't conflict with existing work |
| Effort | ~2 hours |
| Dependencies | Phase 0 decisions |
| Risk | Low — additive only |
| Reversibility | Delete added files; revert is `git revert` |

**Files added (no existing-file changes):**

- `config/disciplines.yml` (Profile A preset, leads per Phase 0 decision)
- `config/stages.yml` (existing 6 stages or remapped per Phase 0)
- `config/evidence-kinds.yml` (trim to software-relevant: pytest, review, manual, inspection)
- `config/README.md`
- `requirements/requirement-map.yml` (empty skeleton — populated in Phase 3)
- `requirements/interfaces/` (empty — ICDs in Phase 6)
- `artifacts/README.md`
- `artifacts/software/` (with `.gitkeep`)
- `prompts/bootstrap.md` (template default)
- `prompts/bootstrap-faq.md`
- `prompts/README.md`
- `dev-docs/architecture/external-tools.md`
- `dev-docs/architecture/artifact-manifest.md`
- `dev-docs/architecture/architecture-contracts-format.md`
- `dev-docs/architecture/EXAMPLE-3d-printer-architecture-contracts.md`
- `dev-docs/architecture/sysml-export.md`
- `dev-docs/getting-started.md`
- `dev-docs/start-work-checklist.md`
- `dev-docs/_wiki-nav.yml` — UPDATE to add new doc entries (existing nav preserved)
- `scripts/init_project.py`
- `scripts/kpm_rollup.py`
- `scripts/export_sysml.py`
- `scripts/validate_artifacts.py`
- `scripts/sync_labels.py`
- `model/system.sysml` (initially empty; populated by export_sysml.py once requirement-map.yml has content)

**Files NOT touched:** all `src/`, `lua/`, `models/`, `corpus/`, `tests/`,
`deploy/`, `.claude/agents/`, existing `dev-docs/architecture/*.md`,
existing scripts.

### Phase 2 — Inception backfill (`bootstrap_alex.md`)

| Field | Value |
|---|---|
| Goal | Create a retrospective inception record so the project's origin is captured in the template's standard format |
| Effort | ~30 min |
| Dependencies | Phase 1 (bootstrap.md template needs to exist) |
| Risk | Low — single new file |
| Reversibility | Delete the file |

Backfill `prompts/bootstrap_alex.md` by copying `prompts/bootstrap.md`
and filling Section A with what we know retroactively:

- A1: "An offline photography pipeline that ingests SD-card content, scores and renames RAW files, and syncs to Darktable on a Lenovo Yoga 910"
- A2: Profile A (software-only)
- A3: ~8 UNs (to be enumerated in Phase 3)
- A4: "Hobby / personal use only"
- A5: `Ajam1997/PHOTONFORGE_Photo-Workflow`
- A6: Alex / 2026-05-29 (today; flag as retrospective)

This makes the project's CLAUDE.md provenance traceable through the
same mechanism every future project uses.

### Phase 3 — Build `requirement-map.yml` from existing Issues

| Field | Value |
|---|---|
| Goal | Extract UN/FR/NFR/IF/KPM tree from the 67 existing Issues |
| Effort | ~3-4 hours |
| Dependencies | Phase 1 (file exists), Phase 2 (inception record sets scope) |
| Risk | Medium — requires interpretation of existing Issues which weren't filed with template ontology |
| Reversibility | Revert the yaml file; Issues unchanged |

This is the hardest *intellectual* phase. The existing 67 Issues use
`type: fr` / `type: kpm` labels but not all are formally decomposed
under UNs. Many are sub-features or refactoring tasks rather than
user-needs. Process:

1. **Read all 67 Issues** in title order
2. **Classify each:**
   - UN candidates (user-visible outcomes): ~6-10 expected
   - FR candidates: most of the existing `type: fr`-labeled Issues
   - NFR candidates: performance/memory/offline constraints from CLAUDE.md
   - KPM candidates: existing `type: kpm` Issues
   - IF candidates: pipeline module boundaries (likely several)
   - Tasks/chores: deferrable; not in requirement map
3. **Draft `requirement-map.yml`** wiring UN → FR/NFR/IF/KPM with multi-parent FR support
4. **Diff against existing label set**; flag any Issues whose `type:` label
   doesn't match the assigned classification (some will need relabeling
   in Phase 4)

Output: a complete `requirement-map.yml`. Issues not yet modified.

### Phase 4 — Normalize Issue bodies + labels (the slog)

| Field | Value |
|---|---|
| Goal | Convert all 67 Issues to template body format and label hygiene |
| Effort | ~5-8 hours (mechanical but tedious; ~5 min per Issue average) |
| Dependencies | Phase 3 (need classifications) |
| Risk | Medium — destructive to existing Issue body content if done wrong |
| Reversibility | Each Issue's edit history is preserved; revert per-issue is possible |

Per Issue, convert to:

```markdown
**Parent:** UN-XXX (if FR/NFR/IF/KPM)
**Stage:** N (links to Milestone)
**Discipline:** systems / software / verification

**What:** <one-paragraph statement>
**Why:** <motivation>

**Acceptance criteria:**
- testable assertion 1
- testable assertion 2

**Verified By:**
- (empty until evidence arrives)

**Validated By:**
- (empty until parent UN's milestone closes)

**Next action:** <what comes next>
via: @<agent>
```

Existing content (`## Context`, `## Recommendation`, etc.) gets mapped:
- `## Context` → `**What:**` + `**Why:**`
- `## Recommendation` → `**Acceptance criteria:**` (testable rewrites)
- `## When` → `**Stage:**`
- `## Related` → keep as a separate section after the standard fields

**Risk mitigation:** do 5 Issues first as a pilot batch, review the
conversion quality, then proceed to the rest. Use a script that updates
via `gh issue edit --body-file <tempfile>` so the conversion is
auditable in git.

### Phase 5 — Author `system-architecture-contracts.md`

| Field | Value |
|---|---|
| Goal | Document photo-workflow's module decomposition per `architecture-contracts-format.md` |
| Effort | ~2 hours |
| Dependencies | Phase 1 (format spec available), Phase 3 (IFs identified) |
| Risk | Low — additive doc |
| Reversibility | Delete the file |

photo-workflow modules likely include:
- **Ingest** (SD card → SSD staging)
- **Pipeline** (grouping → dedup → scoring → naming)
- **Scoring system** (5-module pipeline: region_router → sub_scores → technical_gate + aesthetic_weighter → fusion)
- **Florence-2 inference** (INT8 ONNX runtime)
- **Darktable bridge** (XMP + SQLite writer)
- **Cartridge manager** (SSD eject, safe handling)
- **Lua plugin** (Darktable-side UI)
- **GUI layer** (cartridge_manager.spec)
- **CLI entry points** (click-based)

Cross-discipline boundaries are mostly **internal** (one discipline:
software). But some module-boundary contracts matter for verification:
the scoring system contracts already partly exist at
`dev-docs/architecture/scoring-module-contracts.md` — this becomes one
input to the system-level contracts doc.

### Phase 6 — Author ICDs for identified IFs

| Field | Value |
|---|---|
| Goal | One `requirements/interfaces/IF-X.Y.md` per IF Issue surfaced in Phase 3 |
| Effort | ~30 min per ICD × however many IFs (3-6 estimated) = 2-3 hours |
| Dependencies | Phase 3 (IFs filed as Issues), Phase 5 (modules named) |
| Risk | Low |
| Reversibility | Delete files |

Most photo-workflow IFs are internal API boundaries (e.g., scoring →
fusion, Florence-2 outputs → naming). The ICDs document the data
structure contracts (FusionResult, SubScoreBundle, etc.) — much of this
content already exists in `dev-docs/architecture/scoring-module-contracts.md`
and can be lifted into the formal ICD location.

### Phase 7 — CLAUDE.md + agent roster reconciliation

| Field | Value |
|---|---|
| Goal | Update CLAUDE.md to reflect new agent names + Tool Stack section; rename agent files per Phase 0 decision |
| Effort | ~1 hour |
| Dependencies | Phase 0 decision, Phase 1, Phase 2 |
| Risk | Medium — touches the agent harness directly |
| Reversibility | git revert |

- Update `CLAUDE.md` Agent Roster table to match renamed agents
- Add Tool Stack section (Profile A: Python 3.11+, ruff, pytest, click, onnxruntime)
- Update Build Sequence section to reflect existing 6 stages
- Rename `.claude/agents/<old>.md` files per Phase 0 decision (preserve content)

### Phase 8 — Run + validate the render chain

| Field | Value |
|---|---|
| Goal | Confirm all template automation works against migrated state |
| Effort | ~1-2 hours (mostly debugging) |
| Dependencies | Phases 1-7 complete |
| Risk | Medium — likely finds bugs in scripts vs project specifics |
| Reversibility | Forward-fix bugs as they appear; no rollback needed |

Steps:
1. `python scripts/init_project.py --dry-run` — confirm config valid
2. `python scripts/generate_docs.py` — fills AUTO sections in living docs
3. `python scripts/kpm_rollup.py --dry-run` — confirms KPM tree validates
4. `python scripts/export_sysml.py` — produces `model/system.sysml`
5. `python scripts/validate_artifacts.py` — likely a no-op for Profile A
6. `python scripts/migrate_wiki.py --dry-run` — confirms wiki publish plan
7. Open generated wiki preview; verify no broken links

Expected bugs:
- `kpm_rollup.py`'s `find_issue_by_title_prefix` may need tuning for any
  Issue titles that don't follow `<ID> — <short>` format
- `generate_docs.py` may not find AUTO sentinels in some existing docs
  — need to add them or accept rendering gaps

### Phase 9 — Cleanup + housekeeping

| Field | Value |
|---|---|
| Goal | Remove obsolete files, reconcile lingering inconsistencies |
| Effort | ~1 hour |
| Dependencies | Phase 8 verifies migration |
| Risk | Low |
| Reversibility | git revert |

- Delete `github-issue-map.json` (superseded by `requirement-map.yml`)
- Reconcile `github-issues/` directory (review contents; archive or
  delete)
- Update root README.md (currently 28 bytes — placeholder); use the
  template's README structure with project-specific content
- Update `_wiki-nav.yml` to include new dev-docs entries
- Final `git log --oneline | head -30` review to ensure history is clean

---

## Phase summary table

| Phase | Goal | Effort (h) | Blocking | Risk |
|---|---|---|---|---|
| 0 | Decide + plan (this doc + 3 decisions) | 0.5 | — | Low |
| 1 | Scaffold structural files | 2 | Phase 0 | Low |
| 2 | Backfill `bootstrap_alex.md` | 0.5 | Phase 1 | Low |
| 3 | Build `requirement-map.yml` from 67 Issues | 3-4 | Phases 1-2 | Med |
| 4 | Normalize Issue bodies + labels | 5-8 | Phase 3 | Med |
| 5 | Author `system-architecture-contracts.md` | 2 | Phases 1, 3 | Low |
| 6 | Author ICDs for identified IFs | 2-3 | Phases 3, 5 | Low |
| 7 | CLAUDE.md + agent roster reconciliation | 1 | Phases 0, 1-2 | Med |
| 8 | Run render chain + fix bugs | 1-2 | Phases 1-7 | Med |
| 9 | Cleanup + housekeeping | 1 | Phase 8 | Low |
| **Total** | | **18-24** | | |

Realistic across **3-5 sessions**: Phase 0 + 1 + 2 in session 1
(~3 hours), Phase 3 + 5 in session 2 (~5 hours), Phase 4 spread across
sessions 3-4 (the tedious one), Phase 6-9 in session 5.

---

## Decision points for the operator

Before Phase 1 starts:

1. **Agent roster rename?** (a/b/c per Phase 0 description)
2. **Stage numbering — keep 6 or remap to template's Profile A 5?**
3. **`github-issue-map.json` — delete during migration or archive?**

Before Phase 4 starts (after Phase 3 produces classifications):

4. **Issue body conversion strategy — manual per Issue, or scripted
   conversion (with pilot batch first)?**
5. **Status label normalization — leave existing labels, or migrate
   to template's `status: defined|in-progress|verified|validated`?**

Before Phase 7 starts:

6. **CLAUDE.md rewrite scope — additive only, or wholesale rewrite to
   match template structure exactly?**

---

## Rollback plan

This migration is gated and reversible per-phase:

- **Phases 1, 2, 5, 6:** purely additive — `git revert <commit>` removes added files
- **Phase 3:** additive — revert the requirement-map.yml file
- **Phase 4:** destructive to Issue bodies, but GitHub preserves edit history; per-Issue revert is `gh issue edit --body-file <previous-body>` from the audit log
- **Phase 7:** touches CLAUDE.md and renames agent files — `git revert` works
- **Phase 8-9:** mechanical fixes; revert is straightforward

If the migration goes badly at any phase, **stop, revert that phase's
commit, and consult**. The plan supports indefinite pause between
phases — none of the new structure breaks existing work.

---

## What this plan deliberately does NOT do

- **Doesn't enforce template purity over project pragmatism.** If
  photo-workflow has an idiom that doesn't match the template (e.g.,
  `lua/` is a custom plugin directory not in any template profile), we
  keep it and document the project-specific exception in CLAUDE.md.
- **Doesn't auto-close existing Issues.** Open Issues stay open through
  the migration; their bodies get normalized in Phase 4.
- **Doesn't migrate active branches.** Any active branches retain their
  current state; migration touches `main` only.
- **Doesn't change CI workflows.** Existing `.github/workflows/` keep
  running. Template workflows (`regen-docs.yml`, `kpm-rollup.yml`,
  `sysml-export.yml`, `wiki-publish.yml`, `pr-close-issues.yml`,
  `validate-artifacts.yml`) get added in Phase 1 but don't replace
  anything project-specific.

---

## Open questions for review

- Is the 3-5 session timeline acceptable, or do you want a more
  aggressive (single-session) migration that accepts more risk?
- Should I run Phase 3 (classification) as a `@systems_lead` agent
  invocation in Claude Code, or do it conversationally in this thread?
- Are there project-specific patterns I should preserve that this
  plan implicitly drops? (e.g., `corpus/`, `florence2_onnx/`,
  `cartridge_manager.spec`, `.worktrees/`)

---

## Next action

Operator reviews this doc, answers the 6 decision questions, then we
execute Phase 0 → Phase 1. If a phase needs adjustment based on
findings, we revise this plan rather than improvising.

---

## Phase 9 outcome + the github-issue-map deferral (2026-05-29)

Phase 9 done **except** the planned deletion of
`dev-docs/github-issue-map.json` (Decision #3 = delete).

**Why deferred:** inspection found the map is still **live-depended-upon
by 6 scripts** — `github_comment.py`, `pr_rollup.py`, `audit_boards.py`,
`populate_boards.py`, `seed_github.py`, `weekly_progress.py`. Deleting
it now would break all six. The "delete" decision assumed
`requirement-map.yml` had superseded it, but those scripts were never
migrated to read the new map.

**Done in Phase 9:**
- Root `README.md` written (was a 28-byte stub).
- `weekly_progress.py` stale path fixed (`docs/` → `dev-docs/`).
- github-issue-map.json **kept** (load-bearing).

**Phase 10 (new, deferred):** migrate the 6 scripts off
`github-issue-map.json` and onto `requirements/requirement-map.yml` +
live `gh` resolution, then delete the map. This is real refactoring
work, out of scope for a structural migration. Until then the map
stays as the legacy ID-resolution source.

## Migration status: Phases 1–9 COMPLETE (Phase 10 deferred)
