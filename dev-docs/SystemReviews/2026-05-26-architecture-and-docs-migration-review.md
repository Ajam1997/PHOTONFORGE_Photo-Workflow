# System Review — Architecture + Docs/Migration — 2026-05-26

## Project
PHOTONForge / photo-workflow — offline ingest-to-edit pipeline for a Lenovo Yoga 910. Solo operator. Repo at `E:\PHOTONForge\photo-workflow`. Current branch `feature/cartridge-manager`.

## Invocation Context
Operator is mid-flight on (a) Stage 6 scoring modularization and (b) a GitHub docs/issues migration that has gone sideways. Wants a deep system + docs review, a diagnosis of the migration friction, and lean agile SOPs that *reduce* ceremony rather than add gates.

### Scope clarification (2026-05-26 revision)
Operator clarified after first draft:
1. **Wiki audience is the operator alone.** The wiki is a memory aid + systems-engineering exercise, not an external artifact. Keep it. The dual-sink problem stays open, but reframed: *which sink is canonical?*, not *which sink dies?*
2. **Some ceremony is welcome.** This is a learning project. Per-commit verification, multi-agent roster, write-back protocol can stay as engineering ritual even when not load-bearing. Do not cut on "ceremony" grounds.
3. **The real goal is human↔agent collaboration ergonomics.** The friction is not "too much process" — it is that the docs and automations make it awkward to hand work *back and forth* between operator and agents. Friction items must be re-scored against the question "does this help or hurt handoff?"

§3, §4, §5, §6 below are rewritten under this lens. §1 (System Map) and §2 (Migration Failure Diagnosis) are diagnostic and remain valid as-is.

## Scope of Analysis
Read: `CLAUDE.md`, all 6 agent files in `.claude/agents/`, `mkdocs.yml`, `docs/index.md`, `docs/roadmap.md`, `docs/Notes.md`, `docs/photonforge-architecture.md` (head), `docs/living-user-needs.md` (head), `docs/github-integration-subprojects.md`, `docs/github-issue-map.json`, `docs/architecture/scoring-module-contracts.md`, `docs/architecture/stage-6-engineer-brief.md`, `docs/PlanningBriefs/2026-04-17-planning-brief.md`, `docs/superpowers/index.md`, `docs/drift-reports/index.md`, all `scripts/github_*.py`, `scripts/migrate_wiki.py`, `scripts/seed_github.py` (head), `scripts/generate_docs.py` (head), `scripts/check_drift.py` (head), `scripts/pr_rollup.py` (head), `.github/workflows/*` (list + pr-close-issues.yml). Directory listings for `src/`, `scripts/`, `docs/`.

`src/` code was **not** read per scope constraint.

---

## 1. System Map

### Code Surface (src/photo_workflow/)
24 modules. Pipeline backbone: `pipeline.py` → `ingest`/`grouping`/`dedup`/`sharpness`/`composition`/`exposure`/`naming`/`darktable_bridge`. Stage 6 scaffolding already present alongside: `score_fusion.py` (monolith being replaced), `scoring_types.py`, `subject_context.py`, `genre_router.py`, `genre_trainer.py`, `training_weights_db.py`. Cartridge stack: `cartridge.py`, `provision.py`, `manifest.py`, `volume.py`. Support: `progress.py`, `raw_loader.py`, `sidecar_cli.py`, `photondb.py`.

### Agent Roster (`.claude/agents/`)
| Agent | Model | Tools | Purpose | Activation |
|---|---|---|---|---|
| architect | inherit | R/G/Glob | Interfaces, CLAUDE.md, build sequence | manual |
| engineer | haiku | R/W/E/Bash/G/Glob | src/, tests/, models/ | manual |
| devops | sonnet | R/W/E/Bash/G/Glob | deploy/, scripts/, udev, cartridge | manual |
| verification | inherit | R/W/E/Bash/G/Glob | per-commit pytest+KPM via SSH to Yoga | per-commit |
| validation | inherit | R/W/E/Bash/G/Glob | E2E black-box via SSH | per-milestone |
| systemmaster | (this) | full | Operator-only deep review | operator-only |

### Documentation Surface (docs/, ~60 files)
Grouped by purpose:

| Bucket | Files | Status |
|---|---|---|
| Top-level living docs | `index.md`, `roadmap.md`, `living-user-needs.md`, `photonforge-architecture.md`, `kpm-dashboard.md`, `Notes.md`, `github-integration-subprojects.md` | All AUTO-managed via Issues — pulled by `generate_docs.py` |
| Architecture (current) | `architecture/scoring-module-contracts.md`, `architecture/stage-6-engineer-brief.md`, `architecture/subject-enabled-subscores.md` | Hand-written, current |
| Research | `research/*.md` (3 files) | Current |
| Superpowers specs | `superpowers/specs/*.md` (17 files, dated 2026-04-16 → 2026-05-25) | Mostly historical |
| Superpowers plans | `superpowers/plans/*.md` (15 files) | 1:1 with specs |
| Planning briefs / build logs | `PlanningBriefs/*.md` (5 files, all 2026-04-15→17) | **Frozen / stale** (last entry 2026-04-17, six weeks old) |
| Drift reports | `drift-reports/index.md` only | Empty placeholder |
| GitHub issue snapshots | `github-issues/*.md` (2 files) | Duplicate of Issue bodies |
| Archive | `Archive/*.docx` (4 files) | Inert |

### Automation Scripts (scripts/)
| Script | Purpose | In .github/workflows? |
|---|---|---|
| `seed_github.py` | One-time idempotent Issue seeder | no (manual) |
| `generate_docs.py` | Regenerates AUTO sections from Issues | `regen-docs.yml` |
| `check_drift.py` | Nightly stale-FR detector | `nightly-drift.yml` |
| `pr_rollup.py` | PR-merge → status: verified rollup | `pr-close-issues.yml` |
| `weekly_progress.py` | Weekly summary | `weekly-progress.yml` |
| `github_comment.py` | Agent-safe comment/label CLI | invoked by verification/validation |
| `github_client.py` | GraphQL+REST wrapper | library |
| `audit_boards.py`, `populate_boards.py` | Project board maintenance | manual |
| `doc_parser.py` | Markdown→Issue extractor | library |
| `migrate_wiki.py` | **NEW, UNTRACKED**: docs/ → Wiki migrator | manual |
| `requirement_map.yml` | UN↔FR mapping | data |

### Source-of-truth situation
This is the crux. The same data exists in **three places**, with three opposing arrows:

```
docs/living-user-needs.md   ◄── generate_docs.py ◄── GitHub Issues (UN-*)
docs/photonforge-architecture.md  ◄── generate_docs.py ◄── GitHub Issues (FR-*, NFR-*)
docs/roadmap.md             ◄── generate_docs.py ◄── GitHub Issues (Epics)
docs/kpm-dashboard.md       ◄── generate_docs.py ◄── KPM Issues + KPM Dashboard project board

       ▲                                                      ▲
       │ (seed_github.py — one-shot, idempotent)              │
       │                                                      │
   docs/* (hand-authored, original)                  agents post comments + labels
                                                     via github_comment.py
                                                     (verification, validation)

       AND ALSO:
   docs/* (hand-authored, current)  ──migrate_wiki.py──►  github.com/.../wiki (flat ns)
                                                            ▲
                                                            └── _Sidebar.md hand-curated
                                                                in migrate_wiki.py source
```

### Orphans / Duplication
- `docs/github-issues/*.md` — two files that are also Issues. Pure duplicates with no auto-sync.
- `docs/PlanningBriefs/` — frozen on 2026-04-17. Roadmap status table inside the brief disagrees with `docs/roadmap.md` (brief: stages 1-6 COMPLETE; roadmap.md: all In Progress).
- `docs/drift-reports/index.md` — placeholder, never written into; `check_drift.py` is supposed to populate but no reports exist after weeks of nightly runs.
- `docs/Archive/*.docx` — superseded specs in binary format, unreachable from any nav.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` — every implemented feature has a paired spec+plan. ~75% are landed and never referenced again.
- `docs/Notes.md` — operator's personal scratch about KPM-1.2 + naming bugs; not auto-managed, sits in the public MkDocs nav.
- `VerificationReports/` and `ValidationReports/` — referenced by agent definitions and by `Notes.md`, **do not exist on disk** (confirmed). Either nothing has been written, or they were once written and removed.

---

## 2. Migration Failure Diagnosis

### Root causes (ranked by pain)

**R1 — Three sinks, one source. No single source of truth.**
`docs/` is simultaneously: (a) the seed input to GitHub Issues (`seed_github.py` reads doc_parser.py output); (b) the *render target* of GitHub Issues (`generate_docs.py` writes AUTO sections back into those same files); (c) the source for MkDocs Material (served on GitHub Pages); (d) the source for the GitHub Wiki via `migrate_wiki.py`. Issues are both downstream of docs (seeded) and upstream of docs (render back). Any edit by hand can be silently clobbered.

**R2 — Wiki migration is one-shot, lossy, and competes with MkDocs.**
`scripts/migrate_wiki.py:13` is a clone→wipe→copy→push pipeline. Lines 213-214 delete every `.md` in the cloned wiki before copying. There is no diff mode, no per-page dirty check, and no reverse path. The wiki and the MkDocs site serve the same audience from the same content — there is no reason to maintain both. The wiki sidebar (`migrate_wiki.py:90-180`) is **hand-curated inside the migration script**, so every new spec/plan requires editing Python. The script also uses a fragile `sys.platform == "win32"` branch on a path-separator (`migrate_wiki.py:50`) — works, but smells.

**R3 — Page name collisions.** `PAGE_MAP` (`migrate_wiki.py:24-42`) plus the auto-prefixing loop (45-52) flatten 4 nested directories into one Wiki namespace. Any new spec named `2026-XX-YY-foo-design.md` will mint `Spec-2026-XX-YY-foo-design`. Two specs with identical stems in different folders would silently overwrite. The collision risk is low today, but the script gives no warning.

**R4 — Stale `_Sidebar.md` ≠ `mkdocs.yml` nav.** `migrate_wiki.py:90-180` lists 17 specs and 15 plans by hand; `mkdocs.yml:27-80` lists the same by hand. Two parallel hand-curated navs. They have already drifted: `2026-05-23-doc-reorg-design.md` appears in mkdocs.yml line 42 and in the wiki sidebar (line 130) but the file path uses `superpowers/specs/2026-05-23-doc-reorg-design.md` only in the mkdocs nav; `multi-genre-and-back-training-design.md` (file exists, dated 2026-05-25) is in the wiki sidebar (line 114) but **absent from `mkdocs.yml`**.

**R5 — Issue map is a manual artifact.** `docs/github-issue-map.json` (231 lines) was generated by `seed_github.py` but is committed verbatim. Any agent that calls `github_comment.py verify-fr FR-1.7.1` depends on the map being current. A new requirement seeded after the last commit means the agent script `KeyError`s (`github_comment.py:65`). Today the map already shows `FR-1.7.1` and `FR-1.7.2` only because someone re-ran `seed_github.py` and re-committed. This is bookkeeping churn that defeats the purpose of "ID-based" lookup.

**R6 — Status authority is ambiguous.** Three writers can set `status: verified` on an FR Issue: (i) `pr_rollup.py` on PR merge; (ii) `github_comment.py verify-fr` invoked by `@verification`; (iii) a human in the GitHub UI. There is no precedence rule. `pr_rollup.py:30+` is invoked from PR-close workflow without checking whether the FR was already manually marked.

**R7 — Living user needs document write-paths conflict.**
- `generate_docs.py` overwrites the AUTO section in `docs/living-user-needs.md` from Issues.
- `@verification` (verification.md:264-281) writes the same file locally with a regex `re.sub` to advance `DEFINED → VERIFIED` and commits it.
- `@validation` does the same for `→ VALIDATED` (validation.md:251-273).
- `seed_github.py` originally seeded from this file.

These three write paths each assume they are the only author. On the next `regen-docs.yml` run, the agent's local edit is overwritten by the Issue-state regeneration — unless `github_comment.py verify-fr` *also* updated the Issue label, in which case the regen will re-derive `VERIFIED`. The fact that this *kind of* works is incidental, not designed.

**R8 — `_Sidebar.md` and `_Footer.md` are not source-controlled in the main repo.** They live only in the wiki repo after push. Editing them requires checking out the wiki repo separately, or re-running `migrate_wiki.py` (which clobbers other wiki state). No diff visibility on PRs.

**R9 — `docs/PlanningBriefs/` stopped being maintained on 2026-04-17.** Nothing in the system enforced "keep this current." The brief's status table (stages 1-6 COMPLETE) conflicts with `docs/roadmap.md` (all "In Progress" because that label was never updated on the Epic issues). Two human-readable statuses, both wrong, both in the published site.

**R10 — Untracked work in scripts/migrate_wiki.py.** The file is uncommitted (per session-start `git status`). The operator is iterating on it without a checkpoint. If it gets deleted, recovery is manual.

---

## 3. Friction Inventory (handoff-ergonomics lens)

Re-scored: every item asks **"does this help or hurt a human↔agent handoff?"** Pure ritual that does not impede handoff is kept. Items that block, obscure, or duplicate handoff artifacts are flagged.

Legend: **KEEP** (helps or neutral), **RESHAPE** (load-bearing but currently awkward), **CUT** (actively impedes handoff).

| Mechanism | Source | Verdict | Handoff impact |
|---|---|---|---|
| `@verification` per-commit SSH+pytest+KPM | CLAUDE.md "Agent Write-back Protocol"; `verification.md:4-10` | **KEEP** (ritual) | Operator confirmed ceremony is welcome. Per-commit is a forcing function and a learning loop. Does not block handoff. |
| `@verification` writes Verification Report .md (`verification.md` Step 5) | verification.md | **RESHAPE** | The *intent* (durable record the operator can read between sessions) is correct. The *path* (`VerificationReports/`, doesn't exist) means reports vanish. Either create the dir and write there, OR make Issue comments the canonical record and stop pretending there's a file. Pick one and document it. |
| `@verification` updates LUN with `re.sub` (Step 6) | verification.md:264-281 | **CUT** | Three writers contend for the same file (§2 R7). When the operator opens `docs/living-user-needs.md` to brief the next agent, they cannot tell which writer last touched it. This is the canonical "awkward handoff" symptom. |
| `@verification` generates new pytest cases (Step 3) | verification.md | **RESHAPE** | Tests live next to code; @engineer wrote the code; the handoff "engineer→verification→author tests→back to engineer" is a U-turn. Move test authoring to @engineer; verification asserts the test exists and runs. Same agents, shorter loop. |
| `@validation` per-milestone E2E | validation.md | **KEEP** | Clean handoff: operator hits milestone, invokes @validation, gets pass/fail. Good shape. |
| `@validation` writes Validation Report .md | validation.md Step 5 | **RESHAPE** | Same as verification reports — pick a real path or commit to Issue comments. |
| `@validation` updates LUN locally (Step 6) | validation.md:251-273 | **CUT** | Same handoff-confusion problem as verification. |
| KPM-1.4 soak (50 cycles, prompt-and-wait) | validation.md Step 4 | **KEEP** | Real human-in-loop. The prompt-and-wait pattern is exactly the right shape for "agent needs operator to do a physical thing." |
| `pr_rollup.py` on PR merge | `.github/workflows/pr-close-issues.yml` | **KEEP** | Best handoff trigger in the repo. Code merge → status updates automatically → operator and agents both see the same state next session. |
| `check_drift.py` nightly | `.github/workflows/nightly-drift.yml` | **RESHAPE** | Has produced zero reports in ~6 weeks. Either fix it (it would help cross-session memory — "what got stale while I was away") or hibernate. Currently producing neither signal nor noise. |
| `weekly_progress.py` | `.github/workflows/weekly-progress.yml` | **KEEP** (ritual, low cost) | Self-comments are noise to a team but a useful diary for a solo operator returning to the project. Cheap, keep. |
| `generate_docs.py` AUTO sections | regen-docs.yml | **RESHAPE** | This is where the dual-sink pain lives. AUTO regen of LUN and architecture FR table clobbers hand edits made *during* an agent session. Either narrow to roadmap+kpm-dashboard (low-edit-rate docs), or add a sentinel pattern so hand-written sections survive regen. See HB-1. |
| `migrate_wiki.py` | scripts/, untracked | **RESHAPE** (was CUT — reversed) | Wiki is the operator's private memory aid. Keep it. But §2 R2-R4 are real: lossy one-shot push, hand-curated sidebar in Python, drift vs. mkdocs nav, untracked file. Needs: (a) commit the script, (b) generate sidebar from `mkdocs.yml`, (c) make it diff-mode rather than wipe-and-copy so the operator can edit the wiki directly between migrations. |
| Per-spec + per-plan superpowers files | convention | **KEEP for new work** | The spec/plan pair *is* a handoff artifact — operator reads it before invoking @engineer. Keep the pattern. Archive landed ones so the live folder stays scannable. |
| `docs/PlanningBriefs/` | convention | **CUT** | Frozen on 2026-04-17. When the operator opens this dir to find current status, they find six-week-old fiction. Roadmap + Issues already serve this. |
| `docs/Notes.md` | convention | **CUT (move to Issues)** | These are bug notes. When the operator picks up a session, "open Notes.md vs. open Issues" is exactly the kind of decision that should not exist. One inbox. |
| `docs/github-issues/*.md` | convention | **CUT** | Frozen duplicates of Issue bodies. Reading them gives stale data; agents don't read them; pure noise. |
| `seed_github.py` re-runs + map commit | manual | **RESHAPE** | `github-issue-map.json` is a handoff bottleneck: any agent that resolves an ID stalls if the map is stale. Auto-refresh or eliminate. |
| `audit_boards.py` / `populate_boards.py` | manual | **AUDIT** | Unknown last use. One-line operator confirmation needed. |
| Status labels: `defined / verified / validated / in-progress` | seed_github.py | **KEEP** (ritual) | Four states is fine if ceremony is welcome. The *confusion* is that three writers can set them (§2 R6); fix the writer ambiguity, not the label count. See HB-7. |
| `docs/architecture/stage-6-engineer-brief.md` per-step pattern | convention | **PROMOTE** | This is the *best handoff artifact in the repo* — owner, reviewer, source-of-truth link, scope (in/out), acceptance. Use as the template for new multi-step features. |
| Agent prompt prose tone | `.claude/agents/*.md` | **RESHAPE** | Verification/validation agent definitions read as machine specs (token-optimization rules, diff-only context, "never read X"). The operator also reads these files when deciding which agent to invoke. Add a short human-facing preamble ("when to call me, what I'll hand back to you") above the machine-facing operating rules. See HB-4. |
| Superpowers plugin (installed, unwired) | `C:\Users\Alexa\.claude\plugins\...\superpowers\5.1.0` | **RESHAPE** | Plugin is installed and pinned to this project, and the operator uses it culturally (`docs/superpowers/specs/`, `plans/` are skill artifacts). But no agent definition cites a skill, so the operator cannot see the pairing at agent-selection time and the agent does not know which skill to invoke on activation. See §6 and HB-9. |

---

## 4. Proposed SOPs — Handoff Scripts

Each SOP is structured as a collaboration script. Every step names **who picks it up next**, **what artifact they read for context**, and **what artifact they produce**. The artifact is the handoff token.

### SOP-A — Add a New Feature (FR-X.Y)

| # | Actor | Reads (context in) | Does | Produces (handoff out) | SP cue | Next |
|---|---|---|---|---|---|---|
| 1 | Operator | rough idea | Open GH Issue `[FR-X.Y] <line>`, labels `type:fr` + `status:defined` + stage. | Issue body | `superpowers:brainstorming` if the idea is still fuzzy — turns a rough thought into a structured Issue body before you file it | self or @architect |
| 2 | Operator (optional, only if cross-module) | Issue, `docs/architecture/scoring-module-contracts.md` (as model) | Invoke @architect with the Issue # | — | — | @architect |
| 3 | @architect | Issue, current contracts docs | Author `docs/architecture/<feature>-contracts.md` and a Step-1-style brief if the feature has phases | `docs/architecture/<feature>-contracts.md`, optional `<feature>-engineer-brief.md` | `superpowers:writing-plans` — this is literally what the skill produces; should be auto-invoked by @architect (see HB-9) | operator |
| 4 | Operator | Architect's brief | Read the brief, label Issue `status:in-progress`, branch, invoke @engineer with the brief path | branch | `superpowers:using-git-worktrees` if the feature deserves isolation from current workspace | @engineer |
| 5 | @engineer | The engineer-brief (single doc, not the whole repo) | Implement in `src/`, write tests in `tests/`, run `pytest tests/test_<module>.py` | code + tests + a PR description that names the brief and the Issue | `superpowers:test-driven-development` (tests-first), `superpowers:subagent-driven-development` when the brief has 3+ independent tasks, `superpowers:systematic-debugging` if anything goes sideways | operator |
| 6 | Operator | PR diff | Review PR locally, merge | merged PR | `superpowers:requesting-code-review` *before* merge (dispatches a reviewer subagent against the diff); `superpowers:finishing-a-development-branch` to drive the merge/PR flow | `pr_rollup.py` |
| 7 | `pr_rollup.py` (auto) | PR labels | Close Issue, set `status:verified`, roll up parent | Issue comment | — | @verification (per-commit) or operator |
| 8 | @verification (per-commit ritual; or on-demand for KPM) | `git diff HEAD~1`, the engineer brief | Run pytest+KPM via SSH on Yoga | Issue comment via `github_comment.py verify-fr` ending with `Next action: ...` | `superpowers:verification-before-completion` — the *philosophical match* for this agent; consider folding the skill's "evidence before claims" rubric into verification.md | operator |
| 9 | @validation (milestone only) | The roadmap + recently-merged FRs | Run E2E suite | Issue comment via `github_comment.py validate-un` | `superpowers:verification-before-completion` (same reason) | operator |

**Handoff artifacts in this SOP:** the Issue, the architect brief, the engineer brief, the PR description, the rollup comment, the verification comment. Each one is something the *next* actor can read in isolation and pick up the work. No actor reads `src/` to figure out "where are we" — that information lives in the artifact chain.

### SOP-B — Resume Mid-Flight Work (the "I came back after 3 days" path)

This SOP did not exist in v1. It is the handoff-from-past-self case — the most important ergonomics path in a solo project.

| # | Actor | Reads | Does | Produces | SP cue |
|---|---|---|---|---|---|
| 1 | Operator | `git status`, `git log --oneline -10`, current branch name | Identify the in-flight feature | — | run the Start-Work Checklist (see §7) before anything else |
| 2 | Operator | `docs/architecture/<feature>-engineer-brief.md` if one exists; otherwise the FR Issue body | Recover *intent* | — | — |
| 3 | Operator | the FR Issue's most recent comments (especially from @verification / @validation) | Recover *state* — what was last tried, what passed/failed | — | — |
| 4 | Operator | `tests/test_<module>.py` last-modified | Recover *implementation surface* | — | `superpowers:systematic-debugging` if you're returning to a failing test |
| 5 | Operator | — | If still unclear: invoke @systemmaster with `"resume context for FR-X.Y"` | review brief at `docs/SystemReviews/YYYY-MM-DD-resume-FR-X.Y.md` | — |

**System requirements to make this SOP cheap (drives HB-8):**
- Every engineer-brief must include an `## Open questions if you stop mid-step` section the engineer fills in *before* stopping work.
- Every agent comment posted via `github_comment.py` must end with a `**Next action:** <text>` line — so the Issue comment is itself a handoff token, not just a status report.

### SOP-C — Doc Edit

Four doc kinds, four handoffs:

**C1 — Architecture / contracts (`docs/architecture/*.md`):** edits land in the same PR as the code. Reader is the next agent invocation. No separate review gate. The architect agent owns these; @engineer reads them.

**C2 — Auto-managed (`roadmap.md`, `living-user-needs.md`, `kpm-dashboard.md`, `photonforge-architecture.md`):** the *Issue* is the handoff token, not the file. Operator/agent edits the Issue label or body; `regen-docs.yml` propagates to the doc. Hand edits *outside* AUTO sentinels (see HB-1) are safe and survive regen; edits *inside* are clobbered. If a needed edit doesn't fit outside the sentinel, the AUTO source is wrong — fix the Issue.

**C3 — Wiki (operator-only memory aid):** edits flow *operator → `docs/` → `migrate_wiki.py --diff` → `--push`*. The wiki is downstream of `docs/`. Hand edits made directly on the wiki are preserved via a `WIKI:LOCAL-ONLY` front-matter flag (see HB-3); otherwise they get overwritten on next push.

**C4 — Notes, research (`docs/research/*.md`):** free-form. Not auto-managed. Not in nav unless promoted to architecture.

Retire from the operator's "where do I look?" choice space: `docs/PlanningBriefs/`, `docs/Notes.md`, `docs/github-issues/`, `docs/drift-reports/` (placeholder).

---

## 5. Handoff Briefs

Drafted, **not executed**. Operator copies into the named agent's session when ready. (HB-2 from v1 — delete wiki — is dropped per scope clarification.)

### HB-1 — @architect: Pick a canonical sink and sentinel AUTO sections

**Problem:** `docs/` is simultaneously seed input *and* render target for GitHub Issues, plus a wiki migration target. When the operator hand-edits a doc to brief an agent, `generate_docs.py` may overwrite it on next push. The handoff "operator updates doc → next agent reads doc" silently fails. See §2 R1, R7.

**Decision the operator must make first:** of `docs/`, GitHub Issues, and the wiki — *which is canonical for status*? Recommend **Issues**. Docs become a rendering of Issues; wiki is a one-way export with a local-only escape hatch.

**Files to touch:**
- `docs/architecture/doc-source-of-truth.md` (new) — diagram + precedence rule + a one-screen "where does X live?" cheat-sheet so the operator never derives the answer twice.
- `scripts/generate_docs.py` — wrap regenerated regions with `<!-- AUTO:BEGIN req=FR-X -->` / `<!-- AUTO:END -->` sentinels; refuse to overwrite content outside sentinels.
- `docs/living-user-needs.md`, `docs/photonforge-architecture.md`, `docs/roadmap.md`, `docs/kpm-dashboard.md` — add sentinels around the regenerated portions.
- `CLAUDE.md` "Agent Write-back Protocol" — declare Issues canonical; agents must use `github_comment.py`, never `re.sub` on docs.
- `.claude/agents/verification.md` Step 6 — remove LUN edit.
- `.claude/agents/validation.md` Step 6 — remove LUN edit.

**Acceptance criteria:**
- A doc with hand-written content outside AUTO sentinels survives `generate_docs.py`.
- LUN write contention eliminated: only `generate_docs.py` writes; agents post to Issues.
- Operator can edit `docs/photonforge-architecture.md` mid-session to brief the next agent and trust the edit will persist.

**Complexity:** S (docs + small script change).

### HB-3 — @devops: Make the wiki a proper export, not a wipe-and-copy

**Problem:** Wiki is kept (operator's memory aid) but `scripts/migrate_wiki.py:213-214` wipes the wiki clone before copying, the sidebar is hand-curated in Python at `migrate_wiki.py:90-180`, and the script itself is untracked (§2 R2-R4, R8, R10). Operator cannot edit the wiki between migrations without losing work; cannot tell which docs are out of sync; cannot diff what the next push will do.

**Files to touch:**
- Commit `scripts/migrate_wiki.py` first (currently untracked — one `git clean` and it's gone).
- Refactor `migrate_wiki.py`:
  - `--diff` mode: print what would change, no writes.
  - `--push` mode: per-file content hash compare; only overwrite changed files; leave unmapped wiki pages alone.
  - Generate `_Sidebar.md` from `mkdocs.yml` nav (one curated nav, not two).
  - Replace the `sys.platform == "win32"` branch (`migrate_wiki.py:50`) with `pathlib`.
  - Add a `WIKI:LOCAL-ONLY` front-matter flag agents/operator can set on a wiki page to prevent it from being overwritten by the next push.
- `docs/architecture/doc-source-of-truth.md` — append the wiki's role: operator-only memory aid, downstream of `docs/`, with the local-only escape hatch.

**Acceptance criteria:**
- `migrate_wiki.py --diff` is non-destructive and shows a clean preview.
- Operator can edit a wiki page directly, run `migrate_wiki.py --push`, and the edit survives if marked LOCAL-ONLY.
- Sidebar drift vs. `mkdocs.yml` is impossible (one source).
- Script is committed.

**Complexity:** M.

### HB-4 — @architect: Rewrite agent definitions for two readers

**Problem:** Agent definition files (`.claude/agents/verification.md`, `validation.md`, `engineer.md`, etc.) are read by *both* the agent (as system prompt) and the operator (when deciding who to invoke and what to expect back). They currently read as pure machine specs — "token optimization rules", "diff-only context", "never read X". When the operator opens `verification.md` to figure out "what does invoking this agent get me, and what do I hand it?", they have to derive the answer from operating rules written for a machine. See §3 last row.

**Files to touch:** every file in `.claude/agents/` except `systemmaster.md` (which already has the right shape).

**Per file, add at the top, above the existing operating rules:**

```markdown
## When to invoke me
<1-3 bullets — concrete situations, e.g. "after every commit to main", "when KPM-1.2 might have regressed", "at stage-close milestones">

## What I need from you
<the handoff token the operator must hand me — an Issue #, a brief path, a diff range, a stage name>

## What you get back
<the artifact I produce — Issue comment via github_comment.py, a file path, a review brief — with the exact location named>

## What I will not do
<scope boundary, short, 2-3 bullets>
```

The existing system prompt and operating rules stay below as `## Operating Rules`. The agent reads the whole file; the operator reads only the top four headings.

**Acceptance criteria:**
- Operator can decide whether to invoke any agent by reading only the top of its definition file.
- Each agent's "What you get back" matches an artifact named in SOP-A or SOP-B.
- Verification & validation "What you get back" agree with HB-1 (Issue comments are canonical, not LUN edits).
- `systemmaster.md` is committed (currently untracked) and stays the model for the rewrite.

**Complexity:** S.

### HB-5 — @devops: Garbage-collect the operator's choice space

**Problem:** When the operator opens `docs/` to start a session, they see ~60 files across 8 subdirs. Most are stale, frozen, or duplicates. The cognitive load of "which doc do I open to brief the next agent?" is the central ergonomics complaint. See §1 Orphans.

**Files to touch:**
- `docs/PlanningBriefs/*` → `docs/Archive/PlanningBriefs/` (frozen 2026-04-17, contradicts roadmap.md).
- `docs/Notes.md`: KPM-1.2 perf note already lives on KPM-1.2 Issue; file two new bug Issues for the naming bugs; archive the file.
- `docs/github-issues/*` → delete (frozen Issue-body duplicates).
- `docs/superpowers/plans/*` for landed features → `docs/superpowers/archive/`.
- `docs/drift-reports/index.md` → delete if `check_drift.py` is hibernated; otherwise leave.
- `mkdocs.yml` — prune nav of archived/deleted paths.
- `docs/superpowers/index.md` — autogenerate from live specs/plans only.

**Acceptance criteria:**
- Top of `docs/` contains only live, currently-authoritative files.
- Operator can name, in one breath, what each remaining top-level doc is for.
- No file in nav is older than 30 days unless explicitly marked `[reference]`.

**Constraint:** do this *after* Stage 6 lands, so plans like `docs/superpowers/plans/multi-genre-and-back-training-design.md` can be confidently classified as landed-or-not.

**Complexity:** M (judgment per file).

### HB-6 — @architect: Decide the issue-map's fate

**Problem:** `docs/github-issue-map.json` (231 lines) is a bookkeeping artifact regenerated by `seed_github.py` and committed manually. Every new requirement → re-run → commit. Agents `KeyError` on stale maps (`github_comment.py:65`). See §2 R5. This is a handoff hazard: an agent fails partway through because the map is N hours stale.

**Two options. Operator picks; agent executes.**

**Option A (recommended — eliminate bookkeeping):** Delete the map. Modify `github_comment.py` to resolve `req_id → issue number` via a live GitHub API search (`gh issue list --search "FR-X.Y in:title"`). One round-trip per call; agents are already network-bound when posting. Pros: no bookkeeping, no churn. Cons: one extra API call per agent invocation.

**Option B (preserve the ritual):** Keep the map. Add `.github/workflows/refresh-issue-map.yml` triggered on Issue create/edit; runs `seed_github.py --sync-map-only` and auto-commits. Pros: fast local lookup. Cons: another scheduled workflow, another commit-noise source.

**Acceptance criteria:**
- Agents never `KeyError` on a missing ID.
- Operator never manually runs `seed_github.py` to refresh the map.

**Complexity:** S (A) / M (B). Recommend **A**.

### HB-7 — @architect: Pick a single status writer

**Problem:** Three writers can set `status:verified` on an Issue: `pr_rollup.py`, `github_comment.py verify-fr` (called by @verification), or a human in the GitHub UI. No precedence. See §2 R6. At handoff time this shows up as: operator returns to a session, looks at an Issue label, cannot tell whether the label reflects code state, agent assertion, or hand-flip.

**Files to touch:**
- `scripts/pr_rollup.py` — designate as the canonical status writer for `verified`. On PR merge, sets `status:verified`.
- `scripts/github_comment.py verify-fr` — keep the *comment* (KPM numbers, test results) but stop writing the label. Add a comment-footer line `via: @verification` so the source is visible.
- `scripts/github_comment.py validate-un` — same, for `status:validated`.
- `.claude/agents/verification.md` and `validation.md` — reflect: "post measurements; do not move labels."
- All ritual labels (`defined`, `in-progress`, `verified`, `validated`) stay — this is a writer-precedence fix, not a label-count cut.

**Acceptance criteria:**
- One bot is the sole label writer per state transition.
- Every Issue comment from an agent ends with `via: @<agent>` so its origin is legible to the next reader.
- A human flipping a label by hand is detectable by absence of the `via:` footer in surrounding comments — allowed, but visible.

**Complexity:** S.

### HB-8 — @engineer: Make every handoff token end with a breadcrumb (new)

**Problem:** SOP-B (resume mid-flight) only works if every agent reply and every brief leaves a breadcrumb the *next* reader can pick up. Today, agent Issue comments end mid-thought, and engineer briefs do not have an "if you stop here, what's unanswered" section. This is the single highest-leverage ergonomics change for solo-operator handoffs.

**Files to touch:**
- `scripts/github_comment.py` — every comment template (`verify-fr`, `validate-un`, `regress-fr`, `update-kpm`, `validation-failure`) appends a final `**Next action:** <text>` line. Caller must pass `--next-action "..."`; CLI fails fast if missing.
- `docs/architecture/stage-6-engineer-brief.md` — add a final section `## Open questions if you stop mid-step` (initially empty) as the template. This becomes the pattern for future briefs.
- `.claude/agents/engineer.md`, `architect.md` — instruct: every brief authored by these agents ends with an "Open questions on resume" section, even if empty.

**Acceptance criteria:**
- Every agent-authored Issue comment ends with a `Next action:` line.
- Every engineer/architect brief has an "Open questions on resume" section.
- Operator can resume work via SOP-B reading only the most recent Issue comment + the brief; no code-spelunking required.

**Complexity:** S.

### HB-9 — @architect: Wire Superpowers cues into agent definitions

**Problem:** Superpowers 5.1.0 is installed and pinned to this project, and the operator uses the skills culturally (the `docs/superpowers/specs/` and `plans/` directories are the artifacts). But zero references to `superpowers:*` appear in any `.claude/agents/*.md`. When the operator opens an agent definition to decide whether to invoke it, they cannot see which Superpowers skill the agent pairs with — and the agent, on activation, does not know either. The plugin's auto-trigger fires on session start, but agents invoked as subordinates don't carry the cue forward. See §6.2.

**Files to touch:** every file in `.claude/agents/` except `systemmaster.md` (already operator-only; no skill pairing needed).

**Per file, add to the human-facing preamble created by HB-4:**

```markdown
## Superpowers I pair with
- `superpowers:<skill-name>` — <one line: when this skill fires during my work>
- `superpowers:<skill-name>` — <when>
```

Concretely (from §6.4 table):

- `architect.md`: pairs with `writing-plans`, `brainstorming`
- `engineer.md`: pairs with `test-driven-development`, `subagent-driven-development`, `systematic-debugging`, `verification-before-completion`
- `devops.md`: pairs with `verification-before-completion`, `systematic-debugging`
- `verification.md`: pairs with `verification-before-completion` (mandatory — fold the skill's rubric into the agent's operating rules)
- `validation.md`: pairs with `verification-before-completion` (mandatory)

The exact recommend-vs-mandate posture per agent is OQ-11; default per §6.4 is mandate for verification/validation, recommend for the others.

Also add to `CLAUDE.md` under "Agent Roster": a one-line `Superpowers: <skill list>` per agent so the project-level overview reflects the wiring.

**Acceptance criteria:**
- Each non-systemmaster agent definition has a "Superpowers I pair with" section visible to both the operator and the agent.
- `CLAUDE.md` Agent Roster table includes Superpowers pairing column.
- A fresh session that invokes @engineer auto-invokes the paired skill (per Superpowers' own design — the cue in the system prompt should be enough).
- Start-Work Checklist step 4 ("read the 'Superpowers I pair with' line") is non-empty for every agent.

**Depends on:** HB-4 (the preamble structure has to exist first; HB-9 adds one section to it).

**Complexity:** S (text-only edit to 5 files + CLAUDE.md).

---

## 6. Superpowers Integration

Third-pass scope. The operator uses the Superpowers plugin globally but suspects this repo's agent roster does not leverage it. **Confirmed: gap is real.** This section maps what Superpowers actually provides in *this* repo, where the SOPs above should cue it, and proposes a Start-Work Checklist.

### 6.1 What Superpowers provides in *this* repo

Installation verified at `C:\Users\Alexa\.claude\plugins\cache\claude-plugins-official\superpowers\5.1.0\` — pinned to this project (`projectPath: E:\PHOTONForge\photo-workflow` in `installed_plugins.json`). Plugin version 5.1.0, installed 2026-05-23. No project-local `.superpowers/` directory, no project hooks; the plugin is fully external.

The plugin ships 14 skills under `skills/<name>/SKILL.md`:

| Skill | Trigger / Purpose | Maps to (in this repo) |
|---|---|---|
| `superpowers:using-superpowers` | Bootstrap — auto-loaded at session start; teaches the agent to invoke other skills when applicable | Should fire on every session start. Operator's responsibility: trust the auto-trigger. |
| `superpowers:brainstorming` | Turn fuzzy ideas into structured designs *before* code | SOP-A step 1 (filing a new FR Issue from a rough thought) |
| `superpowers:writing-plans` | Author comprehensive multi-step implementation plans | SOP-A step 3 — this *is* what @architect already does for `stage-6-engineer-brief.md`. The skill formalizes the pattern. |
| `superpowers:executing-plans` | Drive an implementation plan to completion in a single session | SOP-A step 5 (alternative to subagent-driven when no subagents available) |
| `superpowers:subagent-driven-development` | Execute plan by dispatching fresh subagent per task with two-stage review | SOP-A step 5 — directly enables multi-PR Stage 6 style work without context bloat |
| `superpowers:dispatching-parallel-agents` | Parallel investigation of independent problems | OQ-8 (Stage 6 has 6 independently revertable steps — some can parallelize) |
| `superpowers:test-driven-development` | Tests-first, watch them fail, then implement | SOP-A step 5 — currently @engineer writes code then tests; TDD flips the order |
| `superpowers:systematic-debugging` | Root-cause before patch | SOP-B step 4 (resuming a failing test) and any @engineer debugging |
| `superpowers:verification-before-completion` | "Evidence before claims" — run verification, paste output, then claim success | Direct philosophical match for @verification. The skill's rubric should be folded into `verification.md`. |
| `superpowers:requesting-code-review` | Dispatch reviewer subagent with crafted context (not session history) | SOP-A step 6 — pre-merge review without polluting operator's context |
| `superpowers:receiving-code-review` | Evaluate review feedback technically; verify before implementing | When the operator (or @engineer) responds to PR comments |
| `superpowers:finishing-a-development-branch` | Structured merge/PR/cleanup options at end-of-work | SOP-A step 6 |
| `superpowers:using-git-worktrees` | Isolated workspace for feature work | SOP-A step 4, and for parallel Stage 6 steps |
| `superpowers:writing-skills` | TDD applied to skill authoring | Out of scope for this project unless operator decides to author project-specific skills |

### 6.2 Gap diagnosis

Comparing what Superpowers offers against what the repo currently invokes:

- **Cultural use exists, structural use does not.** `docs/superpowers/specs/` (17 files) and `docs/superpowers/plans/` (15 files) are the *outputs* of `brainstorming` + `writing-plans`. The operator has been using the skills — the artifacts prove it. But no agent definition mentions any Superpowers skill by name, so the connection is invisible to the agents themselves and to the operator at agent-selection time.
- **No skill names appear in `.claude/agents/*.md`.** Grep confirms: zero references to `superpowers:` in any agent definition. The roster was authored before Superpowers was installed (agent files dated 2026-04-24; plugin installed 2026-05-23). The agents are unaware the skills exist.
- **@verification duplicates a skill.** `verification-before-completion` and the `verification.md` agent overlap heavily — both enforce "show evidence, don't just claim." The agent adds SSH-to-Yoga + KPM specifics, which the skill does not have. They are complementary, not redundant — but verification.md should *cite* the skill so the agent invokes it.
- **@architect underuses `writing-plans`.** The architect already produces brief-shaped docs (`stage-6-engineer-brief.md`) that the `writing-plans` skill would systematize. The brief is a model — but it's a one-off; the skill would make it a default behavior.
- **@engineer has no TDD cue.** Per `engineer.md`, tests live next to code with no ordering enforced. `test-driven-development` would invert that. Reshape from §3 ("move test authoring to @engineer; verification asserts the test exists") is the natural home for this skill.
- **No agent uses `requesting-code-review` or `subagent-driven-development`.** These are the two highest-leverage skills for a solo operator running Stage 6's multi-PR plan and are currently dark.

### 6.3 Start-Work Checklist (the operator's deliverable)

Run this at the top of every work session. ~60 seconds. Picks the right Superpowers skill before the first agent invocation.

```
START-WORK CHECKLIST (operator, ~60s)

[ ] 1. What kind of work is this session?
      (a) New idea, no design yet            → superpowers:brainstorming
      (b) Design exists, need a plan         → superpowers:writing-plans (or @architect)
      (c) Plan exists, ready to implement    → superpowers:subagent-driven-development
                                               (preferred) or executing-plans
      (d) Resuming mid-flight work           → SOP-B + superpowers:systematic-debugging
                                               if returning to a failing test
      (e) Debugging a specific failure       → superpowers:systematic-debugging
      (f) About to claim "done" / merge      → superpowers:verification-before-completion
                                               + superpowers:requesting-code-review
                                               + superpowers:finishing-a-development-branch

[ ] 2. Does this work deserve workspace isolation?
      (multiple files, risk of half-done state, parallel to other work)
      → superpowers:using-git-worktrees

[ ] 3. Are there 2+ independent investigations to do?
      (different test files, different subsystems, different bugs)
      → superpowers:dispatching-parallel-agents

[ ] 4. Which @agent will I hand this to?
      Open .claude/agents/<agent>.md and read the "Superpowers I pair with"
      line (added by HB-9). If absent, this is the gap HB-9 closes.

[ ] 5. Will the next person resuming this session find a breadcrumb?
      (HB-8: Issue comments end with "Next action:"; briefs end with
      "Open questions on resume")
```

Tape this to the top of the wiki sidebar after HB-3 lands.

### 6.4 Agent-to-skill pairing table

Drives HB-9. Each agent's definition file gets a one-line "Superpowers I pair with" entry:

| Agent | Pair with | Rationale |
|---|---|---|
| @architect | `writing-plans`, `brainstorming` | Architect output *is* a plan; brainstorming is the upstream step when scope is fuzzy |
| @engineer | `test-driven-development`, `subagent-driven-development`, `systematic-debugging`, `verification-before-completion` | Implement, debug, and self-verify |
| @devops | `verification-before-completion`, `systematic-debugging` | Scripts and infra need evidence-based completion; failures need root-cause |
| @verification | `verification-before-completion` | Direct philosophical match — fold the skill's rubric in |
| @validation | `verification-before-completion` | Same |
| @systemmaster | none mandatory | Review brief format already overlaps with the philosophy; no skill is a closer fit |

---

## 7. Risks & Open Questions — Collaboration Ergonomics

**OQ-1 — Canonical sink decision (blocks HB-1).** Of `docs/`, GitHub Issues, and the wiki, which is canonical for *status*? Recommend Issues. Operator confirms or overrides. Without this answer, HB-1 cannot be drafted concretely.

**OQ-2 — Wiki write direction.** Should the wiki be (a) read-only from the operator's perspective, regenerated from `docs/` only, or (b) operator edits the wiki directly and `migrate_wiki.py` reconciles bi-directionally? Affects HB-3 complexity (b is harder). Recommend (a) with a `WIKI:LOCAL-ONLY` escape hatch.

**OQ-3 — Verification/validation report path.** Either create `docs/VerificationReports/` and `docs/ValidationReports/` for real and write structured reports there, OR commit fully to Issue comments and remove the file path from agent definitions. Currently neither — reports go nowhere. Recommend Issue comments + remove the file path.

**OQ-4 — Agent prompt audience.** Confirm HB-4's premise: do you actually re-read `.claude/agents/*.md` when deciding which agent to invoke? If no, the human-facing preamble is wasted; if yes, it's the highest-leverage ergonomics change in this brief.

**OQ-5 — Stage 6 brief pattern as default.** `stage-6-engineer-brief.md` is the model handoff artifact in the repo (owner, reviewer, source-of-truth link, scope in/out, acceptance). Should every multi-step feature get this treatment? Cost is ~30 min of architect time per feature; benefit is SOP-B becoming trivial. Recommend yes for any feature ≥2 PRs.

**OQ-6 — Per-commit verification: ritual vs. signal.** Operator confirmed ceremony is welcome. But per-commit SSH is the heaviest operation in the system. Is the value the *ritual* (think before merging) or the *signal* (catch regressions)? If ritual, a local pre-commit hook is cheaper. If signal, keep SSH. Either is defensible; pick deliberately rather than by inertia. Recommend pre-commit hook for ritual + on-demand SSH for KPM-touching work.

**OQ-7 — `populate_boards.py` / `audit_boards.py` lifecycle.** One-line operator answer: still used? If one-shot, archive. If recurring, document the cadence in CLAUDE.md.

**OQ-8 — Stage 6 PR granularity.** Six independently-revertable PRs is itself a learning ritual (each step a clean checkpoint). For pure efficiency, 2-3 PRs would do. For pedagogy, 6 is right. Operator picks; default keep 6.

**OQ-9 — `@systemmaster` commit.** Currently untracked at `.claude/agents/systemmaster.md`. Commit it: it is now load-bearing for SOP-B step 5 (resume context).

**OQ-10 — Taxonomy research doc.** `docs/research/photo-tag-taxonomy-research-brief.md` is cited in `scoring-module-contracts.md:10` but I could not locate it via glob. Verify it exists; if not, either write a stub or remove the citation so future agents don't dead-end reading their brief.

**OQ-11 — Superpowers default posture (blocks HB-9 wording).** Should the agent definitions *recommend* or *mandate* the paired Superpowers skill? Two postures:
- **Recommend (opt-in):** "When implementing, consider `superpowers:test-driven-development`." Soft cue; operator still decides per session. Lower friction, may be ignored.
- **Mandate (default-on):** "Begin every implementation by invoking `superpowers:test-driven-development` unless the operator says otherwise." Hard cue; aligns with the plugin's own design philosophy (skills are meant to auto-trigger). Higher friction if the skill is wrong for the task.
Recommend **mandate for @verification + @validation** (the skill is a near-perfect fit), **recommend for @engineer + @architect** (more judgment-dependent).

**OQ-12 — Should `superpowers:brainstorming` be the canonical front door for new FRs?** Currently SOP-A step 1 says "open a GH Issue." A more honest version: "if the idea is fuzzy, invoke `superpowers:brainstorming` *first*, then open the Issue from the design output." This makes the spec/plan dance the operator already does *the* official path rather than an informal one. Cost: brainstorming is conversational and slow; not every FR needs it. Recommend make it explicit but optional in SOP-A.

---

## Risks if No Action Taken

- **Handoff confusion compounds.** Every session, the operator spends N minutes reconstructing "where was I" because breadcrumbs are split across Issues, docs, wiki, and PR comments with no precedence rule. SOP-B never gets cheap.
- **The dual-sink (`docs/` ↔ Issues) silently destroys hand edits** made mid-session to brief the next agent. The agent will get blamed for "not reading the latest context" when the system overwrote it.
- **`migrate_wiki.py` untracked** → one `git clean` and the operator's private memory aid pipeline is gone, weeks of nav curation with it.
- **Agent definition files remain machine-only**; operator continues to derive "which agent does what" from operating-rules prose each session rather than from a stable contract at the top of the file.
- **Stage 6 progresses, but each step's resume cost stays high** because briefs end without "open questions" footers and Issue comments end without "next action" lines.

---

## Next Action for Operator

Two decisions unlock everything else:

1. **OQ-1 (canonical sink):** answer "Issues, docs, or wiki?" — recommend Issues. Drives HB-1.
2. **OQ-4 (agent prompt audience):** confirm you re-read `.claude/agents/*.md` when invoking. Drives HB-4.

With those two answered, the recommended execution order is **HB-1 → HB-7 → HB-8 → HB-4 → HB-9 → HB-3 → HB-6 → HB-5**.

HB-9 slots in directly after HB-4 because it appends one section to the preamble HB-4 introduces; doing them in the same PR is reasonable.

- HB-1 + HB-7 together eliminate the LUN/label write contention that makes mid-session handoffs feel haunted.
- HB-8 reshapes the comment + brief surface so every handoff leaves a breadcrumb by default — this is the SOP-B enabler.
- HB-4 reshapes the prompt files for the operator's eye.
- HB-3 fixes the wiki pipeline (the operator's memory aid stays alive).
- HB-6 removes the issue-map bookkeeping hazard.
- HB-5 is the cosmetic finish; do it last and only after Stage 6 lands so `superpowers/plans/` can be classified accurately.

None of this blocks Stage 6 in progress. HB-8 (Next action + Open questions footers) can be applied retroactively to the existing `stage-6-engineer-brief.md` as the first proof, on the current branch, in one small PR.
