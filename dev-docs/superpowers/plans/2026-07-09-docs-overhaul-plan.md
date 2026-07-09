# Documentation Overhaul Plan — 2026-07-09

**Status: DRAFT — awaiting operator review. No implementation until approved.**

**Scope:** every documentation surface in the repo (README, CLAUDE.md, dev-docs/,
requirements/, docs/, prompts/, config/, .claude/agents + agent-memory, deploy
READMEs) plus the documentation *automation* (generate_docs.py, check_drift.py,
pr_rollup.py, kpm_rollup.py, github_comment.py, the four doc workflows, and the
wiki export).

**Method:** full re-read of all ~120 documentation files against HEAD
(`d321b0e`, post PRs #112–#118), plus a code-level root-cause review of the doc
pipeline. Baseline: `dev-docs/SystemReviews/2026-07-08-full-codebase-review.md` §5.

---

## 1. The problem in one paragraph

The repo has three documentation failure modes compounding each other:
**(a) the automation corrupts even correct inputs** — four renderer/workflow
bugs make the AUTO docs (living-user-needs, roadmap, V&V matrix, KPM dashboard)
actively wrong, so the "source of truth" pipeline emits garbage;
**(b) content drift** — this session retired the Tk cartridge manager, the
Tauri chain, `manifest.py`/`progress.py`, changed the XMP convention, and fixed
the scoring bugs, but ~40 documents (including CLAUDE.md, the architecture
entry-point doc, and 4 of 5 ICDs) still describe the old world, on top of
pre-existing drift (16×12 taxonomy, udev, i7-8550U, the never-built Stage-6
module split); and **(c) no feedback loop** — nothing detects that a doc
references a deleted file, the nightly drift check swallows its own failure
signal (`|| true`), and agents have no written rule for which docs to touch
when they change code. This plan fixes the machine first, then the content,
then installs the feedback loop so it doesn't rot again.

---

## 2. Issue inventory

### 2.A Broken automation (root causes confirmed in code)

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| A1 | `living-user-needs.md`: every UN block duplicated, stray `Stage: ?` | `generate_docs.py:32` `_body_field()` lookahead `(?=\n\n|\Z)` never matches GitHub's CRLF bodies (`\r\r\n`), so lazy capture runs to end-of-body and re-renders the tail fields; `:74` reads stage from a `stage: N` label that the label migration deleted | Normalize `\r\n?`→`\n` at entry of `_body_field`/`_body_list_field` (same latent bug in `export_sysml.py:104`); read Stage from the body field or milestone |
| A2 | `roadmap.md`: "Done 0/10", shipped stages "Not Started" | `generate_docs.py:230-239` derives progress from issue open/closed counts, but **no automation ever closes requirement issues** — completion lives in `status:` labels (`pr_rollup.py:148,189`); plus two stage-numbering schemes: `requirement-map.yml` (5-stage) vs live milestones (7-stage), bridged by bare stage number in `pr_rollup.py:104-117` — actively wrong milestone closure | Compute progress from `status: verified|validated` labels; reconcile the stage registries (§6 decision D2) |
| A3 | V&V matrix: "(none yet)" counted as evidence; "38/48 verified" vs reality of 0 validated | `generate_docs.py:46-55` returns the literal placeholder bullet as evidence; `coverage()` (`:162-173`) treats any non-empty list as covered. The evidence-kind validation documented in `config/evidence-kinds.yml` was never implemented | Filter `(none yet)`/`N/A` placeholders; implement evidence validation (path-exists check per evidence kind) |
| A4 | KPM dashboard all "untested" despite measurements existing as issue comments | Renderer (`generate_docs.py:139-140`) reads issue-body fields nothing ever writes; `github_comment.py`'s board update silently no-ops (`projects:` key missing from requirement-map.yml since the Phase-10 migration); `kpm_rollup.py` is a no-op (all 10 KPMs `aggregation: independent`) and isn't scheduled | Make `render_kpm_table` fall back to the latest `## KPM Update` comment (primitive exists: `kpm_rollup.fetch_latest_measurement`) — §6 decision D3 |
| A5 | roadmap.md + kpm-dashboard.md permanently stale in-repo/wiki | `regen-docs.yml:38` commits only 2 of the 4 files `generate_docs.py` writes | `git add dev-docs/` |
| A6 | Nightly drift check can never fail | `nightly-drift.yml:30` pipes `check_drift.py` through `\|\| true`, so the intended red-flag exit code (`check_drift.py:151`) is swallowed | Remove `\|\| true`; commit report first, then fail the job on findings |
| A7 | Green tests, corrupted output | `tests/test_generate_docs.py` uses idealized LF-only fixtures; no test against a real (CRLF, placeholder-bearing) GitHub payload; no sanity check that generated docs still parse (`doc_parser.parse_user_needs()` currently **crashes** on the live corrupted doc) | Add a CRLF golden fixture; add a post-generation sanity gate in regen-docs.yml |
| A8 | Silent no-op automation accumulating | KPM board path (dead config key), kpm_rollup (no-op tree), evidence validation (documented, unimplemented), `type: drift-report`/`type: validation-failure` labels absent from labels.yml so `sync_labels.py` deletes them | Fix or delete each dead path; add the two labels |

### 2.B Stale content — highest-impact corrections (top 20)

1. `CLAUDE.md:37` — "Target CPU: i7-8550U" → **i7-7500U** (contradicts its own header, README, every KPM).
2. `CLAUDE.md:89` — Stage-6 paragraph describes the never-built five-module split, "16-Subject × 12-Photo-Type" (actual: **15×11**), and `SubScoreBundle.as_flat_dict()` which does not exist anywhere in `src/`. Rewrite as complete/as-built.
3. `CLAUDE.md:13,76-77` — udev scope + `scripts/install_udev.sh` + `deploy/udev/` (none exist; actual mechanism: `install_polkit.sh` + udisks2 polling); layout lists 10 of 22 src modules; no mention of the CI gate.
4. `dev-docs/architecture/system-architecture-contracts.md:35-86` — the doc README sends newcomers to: module table cites deleted `manifest.py`/`sidecar_cli.py`/`progress.py`, the unbuilt Stage-6 modules, 16×12, `as_flat_dict()`, pre-rename agent names.
5. `dev-docs/architecture/scoring-module-contracts.md` — whole doc (16×12, NIMA, depth model, unimplemented API, wrong `aesthetic_weights` schema). Needs the supersession banner PR #102 promised.
6. `requirements/interfaces/IF-3.1.md:10,17-28` — 16×12; `GenreResult` schema doesn't match `scoring_types.py` (`type_confidence`/`type_distribution`/`needs_review`; no `top_subjects`); subject label is `people` not `person`.
7. `requirements/interfaces/IF-3.2.md` — cites deleted `sidecar_cli.py`; says semantic name is a file-rename target (it now writes the DT description only); missing the new `IMG.ARW.xmp` + XML-escaping convention — which should live exactly here.
8. `requirements/interfaces/IF-4.1.md` — contract built on deleted `manifest.py`; resume state lives in photondb.
9. `requirements/interfaces/IF-1.1.md:29-31,64,75` — stage whitelist missing `suggest-training-set`, `refresh-review`, `rescore`, `training recalibrate` (all invoked by `panel.lua`); `tags.lua` → `tag_manager.lua`; deleted `test_progress.py`.
10. `dev-docs/photonforge-architecture.md §7` — project tree of a repo that no longer exists (pre-rename agents, deleted modules, udev scripts, JSX mockups).
11. `dev-docs/photonforge-architecture.md:316` — "38/48 verified" (renderer bug A3) + nonexistent `tests/test_cartridge_manager.py` cited as FR-1.9 evidence.
12. `dev-docs/roadmap.md` — corrupt AUTO output (A2).
13. `dev-docs/living-user-needs.md` — corrupt AUTO output (A1); UN-002 lists `@software_lead` twice.
14. `dev-docs/github-issues/multi-genre-tagging.md:66` — deleted `compute_color_label()`; table-per-folder DDL obsolete.
15. `dev-docs/architecture/system-state-machine.md` — udev add/remove events → udisks2/polling.
16. `dev-docs/architecture/module-bdd.md:26,61,62` — deleted modules in the diagram.
17. `.claude/agent-memory/validation/project_overview.md` — "GUI layer is a Tauri + Svelte app in the repo root" (Tauri fully retired); `validation.md:137` documents the old `IMG.xmp` sidecar naming; `:188-193` udev soak events.
18. `.claude/agent-memory/verification/project_test_suite_state.md` — counts for deleted test files; suite state months out of date; `agents/software_lead.md`/`systems_lead.md` carry udev + pre-rename persona text.
19. `dev-docs/research/photo-tag-taxonomy-research-brief.md` — 16/12/`T-10 Long Exposure`/"192 pairings" → 15/11/`motion-blur`/165; banner to `photonforge-labeling-quick-reference.md` (the one accurate taxonomy doc, declare it canonical).
20. Both recent SystemReviews need **resolved-by addenda** — the 2026-06-19 audit and the 2026-07-08 review present bugs as open that PRs #111–#118 fixed; readers will re-chase fixed bugs.

Code-side stragglers found while verifying: `genre_router.py:4-5` docstring still says "16 classes"; `scoring_types.py:129-130` `GenreResult` docstring lists the old 6+8 taxonomy.

### 2.C Superseded / orphaned docs (archive or delete)

- **Archive to `dev-docs/Archive/`:** `migration/` (~150 one-shot files, migration completed 2026-05-29); all `superpowers/plans/` + `superpowers/specs/` (32 dated files, nearly all referencing deleted code — keep `index.md` as a pointer); `architecture/scoring-module-contracts.md`, `stage-6-engineer-brief.md`, `subject-enabled-subscores.md` (or rewrite — see Phase 5), `gui-layer-handoff-brief.md`, `hb-3-wiki-refactor-brief.md`, `EXAMPLE-3d-printer-architecture-contracts.md`; `github-integration-subprojects.md` (describes the retired Projects/MkDocs model); both `github-issues/` drafts (superseded by the two-axis taxonomy).
- **Delete:** `cartridge_manager.spec` (PyInstaller spec for the deleted Tk app) + stray `tools/cartridge_manager/__pycache__`.
- **Trim:** `getting-started.md` (references nonexistent `METHODOLOGY.md` and `requirements.txt`; ~60% EE/ME boilerplate) → a photo-workflow-specific quickstart; `start-work-checklist.md` (EE/ME leads).
- **Agent memory:** rename `.claude/agent-memory/engineer/` → `software_lead/` (content still valuable); purge/rewrite the Tauri-era validation memories; refresh `verification/project_test_suite_state.md`.
- Every archived file gets a **supersession banner** (see §5 convention) — history preserved, never load-bearing.

### 2.D Missing docs

1. **As-built scoring architecture** — the only written designs are the unimplemented contracts doc and the audits. Needs: SubjectContext build → two-axis routing → sub-scores/weights/hard gates in `score_fusion.py` → percentile stars → `hard_reject` in genres JSON. (Absorbs a corrected `subject-enabled-subscores`.)
2. **ADRs** (short, one file each): Stage-6 split bypassed; taxonomy evolution 8→16×12→13×11→15×11→motion-blur; udev→udisks2/polkit; Tauri/Tk retirement; Florence-2→LFM2 R2 decision; per-Type weights vs SceneRecord (undecided — flag as OPEN).
3. **XMP/tag namespace reference** — `photon:*` fields, `photon|subject|*`/`photon|type|*`, `IMG.ARW.xmp`, XML escaping (home: rewritten IF-3.2).
4. **Training-loop operator guide** — collect-corrections → recalibrate → rescore / suggest-training-set / refresh-review (panel buttons exist, no doc).
5. **Linux/Yoga install & provisioning guide** (UN-003; `docs/` is empty; dev-machine-setup covers only the Windows box) + Lua plugin install for Linux.
6. **CI/test policy note** — tests.yml, `-m "not slow"`, the opencv `<5` pin rationale.
7. **The prescribed re-measurement SystemReview** — post-fix re-score vs the June baseline (needs the Yoga; placeholder doc with the procedure now, results when hardware is available).

---

## 3. Automation improvements (the feedback loop)

### 3.1 Make the generators trustworthy (prerequisite for everything)
Fixes A1–A8. Plus a **regeneration sanity gate** in `regen-docs.yml`: after
`generate_docs.py`, run `doc_parser.parse_user_needs()` and assert AUTO
sections contain no `\r`, no duplicated field labels, no literal `(none yet)`
evidence — fail the workflow instead of committing garbage. Add one pytest
fixture captured from the real API (CRLF body) so the suite can't be green
while output is corrupt.

### 3.2 Reference-integrity checker (code-reality drift)
New check, wired into `check_drift.py` and run **as a PR check too** (pure
filesystem, no token needed, cheap):
- Extract every repo path mentioned in `dev-docs/**/*.md`, `requirements/**`,
  `README.md`, `CLAUDE.md`, `.claude/agents/*.md` (regex
  `\b(?:src|scripts|tests|deploy|lua|tools|config|docs)/[\w./-]+\.(?:py|sh|lua|yml|md|css)\b`)
  and flag paths that don't exist. This single check would have caught ~15 of
  the top-20 issues above the moment PRs #117/#118 merged.
- Same for evidence lines in issue bodies (implements the documented-but-missing
  `evidence-kinds.yml` validation).
- Extend `migrate_wiki.py`'s existing link parser into a relative-link
  resolver check (broken doc links currently become broken wiki pages silently).
- Symbol-level (optional, later): flag `module.symbol` doc references absent
  from a `def |class ` index.
- Nightly report gains sections: *stale requirements* / *broken doc→file
  references* / *broken evidence references*; PR check fails only on
  references broken **by that PR's deletions** (diff-aware) to avoid blocking
  unrelated work during the backlog burn-down.

### 3.3 Agent doc-maintenance protocol ("what and when to change docs")
A new short doc, `dev-docs/architecture/doc-maintenance-protocol.md`,
referenced from CLAUDE.md, containing a **docs-impact matrix**:

| When a PR touches… | The same PR must update… |
|---|---|
| Deletes/renames any file | Every doc the reference-integrity check flags (the check enforces this) |
| `genre_router.py` taxonomy lists | `photonforge-labeling-quick-reference.md` (canonical), IF-3.1, CLAUDE.md taxonomy line, migration script note |
| `score_fusion.py` weights/gates/fusion | as-built scoring-architecture doc, IF-2.1 |
| CLI commands/flags in `pipeline.py` | IF-1.1 stage whitelist, `runner.lua` (protocol pair) |
| XMP/tag format in `darktable_bridge.py` | IF-3.2 (namespace reference), `tag_manager.lua` note |
| photondb schema | IF-4.1, dev-machine-setup migration note |
| `lua/photonforge/*` | deploy note ("re-run deploy_lua.ps1"), IF-1.1 if stages changed |
| Fixes a bug listed in a SystemReview | "Resolved-by" addendum line in that review |
| Retires/supersedes a design | Supersession banner + move to Archive/ + ADR if the decision is non-obvious |
| New module in `src/` | CLAUDE.md layout, system-architecture-contracts module table |

Plus three rules: (1) **banner convention** — superseded docs get a
top-of-file `> **SUPERSEDED (date, PR #N):** see <replacement>` and move to
`Archive/`; (2) **AUTO sections are never hand-edited** (already policy —
restate with the marker inventory); (3) **PR description carries a "Docs
impact" line** — either the updated files or an explicit "none" (cheap to
review, and gives the drift checker a human counterpart). CLAUDE.md gets a
3-line pointer to this protocol; the agent role files get the same pointer.

### 3.4 Larger options (deferred; listed for completeness)
- Bidirectional auto-update: PR-merge hook maps changed files → FR issues
  (the FR-ID-in-source convention `check_drift.py` already greps) and comments
  "code touched, issue body not updated" on the affected issues; optionally an
  LLM pass drafting issue-body updates for human approval. Only worth doing
  after §3.1–3.2 — today the pipeline corrupts even correct inputs. (Effort: L)
- Wiki round-trip test in CI (publish to a temp dir, assert nav completeness). (S)

---

## 4. Phased implementation (one PR per phase, each independently valuable)

| Phase | Content | Effort | Risk |
|---|---|---|---|
| **1. Fix the machine** | A1–A8 one-liners + sanity gate + CRLF golden test; add missing labels; then trigger regen and verify the four AUTO docs render correctly | S–M | Low (renderers have tests; output diff is reviewable) |
| **2. Reference-integrity checker** | §3.2 filesystem checks in `check_drift.py`, PR-check workflow (diff-aware), nightly sections, un-swallow the exit code | M | Low (read-only checks) |
| **3. High-impact content fixes** | Top-20 list: CLAUDE.md, system-architecture-contracts, the five ICDs, README, photonforge-architecture §6–7 purge, state-machine/module-bdd, agent files + memories, the two code docstrings, resolved-by addenda on both SystemReviews | M | Low (text only; reference checker from Phase 2 verifies) |
| **4. Archive sweep** | §2.C moves with banners, deletions, getting-started/start-work trim, `_wiki-nav.yml` regeneration (+ 7 missing pages), wiki republish | S–M | Low (git preserves history; nav regenerated) |
| **5. New docs** | §2.D: as-built scoring architecture, ADR set, IF-3.2 rewrite as namespace reference, training-loop guide, Linux install guide, CI policy note, doc-maintenance protocol (§3.3) + CLAUDE.md pointer | M–L | Low |
| **6. Ledger unification** | The D1–D3 decisions below (roadmap-from-labels, stage registry reconciliation, KPM loop) — small code changes with process implications | M | Medium (touches the Issues workflow you use) |

Suggested order: 1 → 2 → 3 → 4 → 5 → 6. Phases 1–2 make everything after them
verifiable; Phase 6 last because it needs your decisions.

---

## 5. Decisions requested (blocking specific items only)

- **D1 — completion ledger:** derive roadmap progress from `status:` labels
  (recommended — no process change), or make `pr_rollup.py` close verified
  issues so open/closed state becomes meaningful?
- **D2 — stage registry:** rewrite `requirement-map.yml` stages to match the
  live 7 GitHub milestones 1:1 (recommended), or renumber the milestones to the
  5-stage template model? (`config/stages.yml` folds into whichever wins.)
- **D3 — KPM loop:** renderer reads the latest `## KPM Update` comment
  (recommended — zero workflow change), or `update-kpm` starts patching issue
  bodies so the current renderer works? The dead Projects-board path: restore
  (add `projects:` metadata) or delete the code?
- **D4 — `subject-enabled-subscores.md`:** archive as superseded, or rewrite
  against `score_fusion.py` as part of the new scoring-architecture doc?
  (Recommend: fold into the new doc.)
- **D5 — PR gate strictness:** should the Phase-2 reference-integrity PR check
  be blocking from day one (after Phase 3/4 clears the backlog), or
  informational-only like the current ruff step?

Everything not listed above proceeds as described on your approval of this plan.

---

## Appendix A — Per-file verdict summary

Verdicts: **C**URRENT · **S**TALE (fixable in place) · **X** SUPERSEDED (banner + archive) · **O**RPHAN (archive/delete) · counts per directory.

| Area | C | S | X/O | Notes |
|---|---|---|---|---|
| Repo root (README, CLAUDE.md, .mcp.json, cartridge_manager.spec) | 1 | 2 | 1 | CLAUDE.md is the single highest-impact stale file |
| dev-docs/ top level (13) | 5 | 6 | 2 | roadmap + living-user-needs corrupt (automation); getting-started + github-integration-subprojects archive |
| dev-docs/architecture/ (18) | 9 | 4 | 5 | system-architecture-contracts = top content fix; contracts/stage-6/subject-subscores/gui-handoff/hb-3/EXAMPLE archive |
| dev-docs/research/ (6) | 3 | 2 | 1 | labeling-quick-reference is the canonical taxonomy doc |
| dev-docs/SystemReviews/ (4) | 4 | — | — | Two need resolved-by addenda |
| dev-docs/design/ (2) | 2 | — | — | handoff README: mark cartridge strip as design intent |
| dev-docs/github-issues/ (2) | — | — | 2 | Superseded by two-axis taxonomy |
| dev-docs/superpowers/ (33) | 1 | — | 32 | Archive plans+specs wholesale; keep index as pointer |
| dev-docs/migration/ (~150) | — | — | all | Archive wholesale |
| requirements/ (map + 5 ICDs) | 1 | 4 | 1 | IF-2.1 superseded; IF-1.1/3.1/3.2/4.1 stale |
| docs/, deploy/, prompts/, config/ (11) | 9 | 2 | — | config/stages.yml + start-work-checklist minor |
| .claude/ agents + memory + misc (16) | 9 | 6 | 1 | engineer/ memory dir orphaned; validation memories Tauri-era |

Full per-file findings with line numbers live in the audit transcripts backing
this plan; Phase 3/4 PRs will carry them file-by-file.

## Appendix B — AUTO-marker inventory (owner: `scripts/generate_docs.py`)

| Marker | File | Renderer |
|---|---|---|
| `AUTO:user_needs` | dev-docs/living-user-needs.md | `render_user_needs_section` |
| `AUTO:fr_table` / `AUTO:nfr_table` / `AUTO:kpm_table` / `AUTO:vv_matrix` | dev-docs/photonforge-architecture.md | respective renderers |
| `AUTO:roadmap` | dev-docs/roadmap.md | `render_roadmap_section` — **not committed by CI (A5)** |
| `AUTO:kpm_table` | dev-docs/kpm-dashboard.md | `render_kpm_table` — **not committed by CI (A5)** |
