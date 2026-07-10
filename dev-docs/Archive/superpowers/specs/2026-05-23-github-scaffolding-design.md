# GitHub Scaffolding Design — Sub-project 1

**Date**: 2026-05-23
**Status**: Approved
**Author**: Alex Meyer
**Approach**: Native Sub-issues hierarchy (Approach A)

## Summary

Migrate PHOTONForge's requirements hierarchy (Epics → UN-XXX → FR/NFR → KPMs) into GitHub Issues and Projects, establish three GitHub Projects boards for roadmap/requirements/KPM tracking, auto-generate `living-user-needs.md` and the architecture FR/NFR tables from Issue state, and serve all documentation as a MkDocs Material site on GitHub Pages. Automation runs on PR merge, Issue change, push to main, and nightly schedule. Agents (`@verification`, `@validation`) write results back to Issues after every run.

This is Sub-project 1 of 5 in the broader GitHub integration initiative. Sub-projects 2–5 (doc reorganisation, PR automation, scheduled automation, agent integration) are tracked separately and depend on this scaffolding being in place first.

---

## 1. Issue Hierarchy & Label Taxonomy

### 1.1 Hierarchy

GitHub sub-issues represent the full requirement decomposition:

```
Epic Issue  (type: epic)
  └── UN-XXX Issue  (type: user-need)
        └── FR-X.X Issue   (type: fr)
        │     └── KPM-X.X Issue  (type: kpm)
        └── NFR-X.X Issue  (type: nfr)
              └── KPM-X.X Issue  (type: kpm)
```

- **Epics** represent a roadmap stage (e.g. "Stage 2 — Core Analysis Engine"). One Epic per stage.
- **User Needs (UN-XXX)** are the items currently in `living-user-needs.md`. One Issue per UN entry.
- **Functional Requirements (FR-X.X)** and **Non-Functional Requirements (NFR-X.X)** are decomposed from their parent UN. One Issue per FR/NFR entry in `photonforge-architecture.md`.
- **KPMs** are performance measures attached to one or more FR/NFR Issues. Each KPM is a sub-issue of its *primary* FR/NFR (the one most directly measured). Where a KPM measures multiple FRs (e.g. KPM-1.1 measures both FR-1.1 and UN-040), the additional FRs are referenced in the KPM Issue body with `Also measures: #N`.

GitHub's sub-issue completion percentage automatically rolls up from FR/NFR → UN → Epic, giving live progress visibility at every level.

### 1.2 Label Taxonomy

Three label groups. Every Issue carries exactly one label from each group that applies.

**Type labels** (required on every Issue):

| Label | Colour | Meaning |
|---|---|---|
| `type: epic` | Purple `#6f42c1` | Roadmap stage grouping |
| `type: user-need` | Blue `#0075ca` | UN-XXX item |
| `type: fr` | Green `#2ea44f` | Functional requirement |
| `type: nfr` | Teal `#1d9fa6` | Non-functional requirement |
| `type: kpm` | Orange `#e08000` | Key performance measure |

**Stage labels** (applied to Epics, UNs, FRs, and NFRs):

`stage: 1` through `stage: 7` — hex colour graduates from light to dark blue. The seed script explicitly applies the stage label to every FR/NFR based on its parent UN's stage. KPM Issues are not stage-labelled (they appear only on the KPM Dashboard).

**Status labels** (mirrors `living-user-needs.md` status values):

| Label | Colour | Meaning |
|---|---|---|
| `status: defined` | Grey `#888888` | Requirement written, not yet implemented |
| `status: in-progress` | Yellow `#d4a017` | Active development |
| `status: verified` | Light green `#a8d8a8` | `@verification` has passed tests |
| `status: validated` | Dark green `#196127` | `@validation` has confirmed E2E |

---

## 2. Board Designs

### 2.1 Roadmap Board

**Purpose:** High-level stage progress visible at a glance.
**Items:** Epics and UN-XXX Issues only.

**Columns:**
```
Backlog | Stage 1 | Stage 2 | Stage 3 | Stage 4 | Stage 5 | Stage 6 | Stage 7 | Done
```

**Custom fields:**
- `Stage` (single select: 1–7) — drives column placement
- `Owner` (single select: architect / engineer / devops)

A stage column is considered complete when all its Epic Issues show 100% sub-issue completion. The Epic Issue is then moved to the `Done` column manually or by automation (Layer 1).

### 2.2 Requirements Board

**Purpose:** Track decomposition and verification status of all UN/FR/NFR items.
**Items:** UN-XXX, FR, and NFR Issues.

**Three saved views:**

1. **By UN** — grouped by parent UN Issue. FR/NFR sub-issues appear beneath each UN row. Default view.
2. **By Stage** — grouped by `stage:` label. Used for sprint planning.
3. **By Status** — columns are `defined` / `in-progress` / `verified` / `validated`.

**Custom fields:**
- `UN ID` (text, e.g. `UN-010`)
- `FR ID` (text, e.g. `FR-1.2`) — blank for UN-level Items
- `Acceptance Criteria` (text) — copied from `living-user-needs.md` at migration
- `Owner` (single select: engineer / devops / architect)

### 2.3 KPM Dashboard

**Purpose:** Live performance measure tracking — target vs actual.
**Items:** KPM Issues only.
**Layout:** Table view (no columns).

**Custom fields:**
- `KPM ID` (text, e.g. `KPM-1.2`)
- `Target` (text, e.g. `<= 2.5s / image`)
- `Last Measured` (text, e.g. `1.8s — 2026-05-20`)
- `Status` (single select: `passing` / `failing` / `untested`)
- `Measured By` (text, e.g. `@verification`)

`Last Measured` and `Status` are updated by `@verification` after every benchmark run via `scripts/github_comment.py`.

---

## 3. Migration Plan

### 3.1 Seeding Script — `scripts/seed_github.py`

A one-time (idempotent) script that reads the existing Markdown docs and creates Issues in the correct order so sub-issue links resolve.

**Execution order:**
1. Create all labels (type, stage, status)
2. Create Epic Issues (one per stage)
3. Create UN-XXX Issues, linked as sub-issues to their Epic; apply stage + status labels; populate custom fields
4. Create FR/NFR Issues, linked as sub-issues to their parent UN; populate custom fields
5. Create KPM Issues, linked to their FR/NFR; populate KPM Dashboard fields
6. Add all Issues to the correct board and set field values
7. Write `docs/github-issue-map.json` mapping UN/FR/NFR/KPM IDs to Issue numbers

**Idempotency:** Before creating any Issue, the script searches for an existing open Issue whose title contains the requirement ID (e.g. `UN-010`, `FR-1.2`). If found, it skips creation and records the existing Issue number in the map. Safe to re-run after partial failures.

**Dry-run mode:** `--dry-run` flag prints all planned operations without touching GitHub.

### 3.2 Source Mapping

| Source document | Section | Creates |
|---|---|---|
| `living-user-needs.md` | Each `UN-XXX` block | `type: user-need` Issue |
| `photonforge-architecture.md` | FR table (§3.1) | `type: fr` Issues |
| `photonforge-architecture.md` | NFR table (§3.2) | `type: nfr` Issues |
| `photonforge-architecture.md` | KPM table (§3.3) | `type: kpm` Issues |
| Roadmap stages 1–7 | Stage groupings | `type: epic` Issues |

### 3.3 Doc Retirement

After seeding:

- `living-user-needs.md` gets a header banner: `> Source of truth: [GitHub Projects — Requirements Board](link). This file is auto-generated — do not edit manually.`
- The FR/NFR/KPM tables in `photonforge-architecture.md` are replaced by an auto-generated block (see §4).
- Both files are regenerated on every trigger (§5.1). Manual edits will be overwritten.

---

## 4. Auto-Generated Docs & GitHub Pages

### 4.1 Source of Truth Flow

```
GitHub Issues  →  scripts/generate_docs.py  →  docs/ Markdown  →  MkDocs build  →  gh-pages branch
```

`generate_docs.py` queries the GitHub API, reconstructs the requirement hierarchy from Issue labels and sub-issue relationships, and writes the auto-generated sections of each doc.

### 4.2 What Gets Generated vs Maintained

| File | Auto-generated | Manually maintained |
|---|---|---|
| `docs/living-user-needs.md` | All UN-XXX entries, status, acceptance criteria, KPM refs | Header, format description |
| `docs/photonforge-architecture.md` | FR/NFR tables (§3.1–3.2), KPM table (§3.3), stage completion status | All narrative sections (§1–§2, §4–§5) |

The architecture narrative — executive summary, hardware specs, intelligence engine design, agent roster — is never auto-generated. It remains human-edited and reflects the current system design.

### 4.3 MkDocs Material Site

**Tool:** MkDocs with the Material theme.
**Deployment:** `mkdocs gh-deploy` pushes the built site to the `gh-pages` branch. Source Markdown stays on `main`.

**Site navigation:**
```
Home
├── Roadmap          ← auto-generated from Epic Issue stage status
├── User Needs       ← living-user-needs.md (auto-generated body)
├── Architecture     ← photonforge-architecture.md (hybrid)
├── KPM Dashboard    ← auto-generated from KPM Issues
└── Specs & Plans    ← docs/superpowers/ (organised in Sub-project 2)
```

**Config file:** `mkdocs.yml` at repo root.
**Theme settings:** Material theme, dark/light toggle, search enabled, repo link in header pointing to `Ajam1997/PHOTONFORGE_Photo-Workflow`.

---

## 5. Automation Design

### 5.1 Trigger Matrix

| Event | Workflow | Actions |
|---|---|---|
| PR merged (references Issue) | `pr-close-issues.yml` | Close referenced FR/NFR; set `status: verified`; check UN sibling completion; advance Roadmap board if Epic complete |
| Issue labeled / closed / edited | `regen-docs.yml` | Run `generate_docs.py`; commit updated Markdown; rebuild + deploy MkDocs site |
| Push to `main` | `regen-docs.yml` | Same as above |
| Nightly 02:00 UTC | `nightly-drift.yml` | Run `check_drift.py`; write `docs/drift-reports/YYYY-MM-DD.md` if drift found; rebuild + deploy MkDocs site |

### 5.2 Layer 1 — PR/Commit Automation (`pr-close-issues.yml`)

When a PR is merged:
1. GitHub natively closes any Issue referenced with `Closes #N` or `Fixes #N` in the PR body.
2. The workflow reads the closed Issue numbers, applies `status: verified` label.
3. For each closed FR/NFR: check whether all sibling FR/NFR sub-issues under the same parent UN are now closed. If yes, apply `status: verified` to the UN Issue.
4. For each updated UN: check whether all UN sub-issues under the parent Epic are verified. If yes, move the Epic to the `Done` column on the Roadmap board.

### 5.3 Layer 2 — Nightly Drift Check (`nightly-drift.yml`)

`scripts/check_drift.py` runs nightly:
- Fetches all `status: defined` and `status: in-progress` FR Issues from GitHub
- Greps `src/photo_workflow/` for any comment or docstring referencing the FR ID
- Flags FRs with no linked merged PR in the last 90 days and no `status: verified` as **stale**
- If stale items found: writes `docs/drift-reports/YYYY-MM-DD.md` and opens a GitHub Issue labelled `type: drift-report` summarising the findings
- Always rebuilds and deploys the MkDocs site regardless of drift findings

### 5.4 Layer 3 — Agent Workflow Integration

Agents use `scripts/github_comment.py` to write back to Issues. They never call the GitHub API directly; the script holds the token and accepts `(issue_number, body, [labels])` as arguments.

**`@verification` (after every commit to main):**
- Looks up FR/NFR Issue numbers from `docs/github-issue-map.json`
- Posts pytest results and KPM benchmark values as a comment on the relevant Issues
- Sets `status: verified` on passing Issues; reverts to `status: defined` on regression
- Updates `Last Measured` and `Status` fields on KPM Issues

**`@validation` (on milestone merge / manual invocation):**
- Posts E2E test results as a comment on UN Issues
- Sets `status: validated` on passing UNs
- On failure: opens a new Issue labelled `type: validation-failure` and assigns it to `@architect` for requirement reassessment

---

## 6. New Files & Scripts

| Path | Purpose |
|---|---|
| `scripts/seed_github.py` | One-time idempotent Issue seeding from existing docs |
| `scripts/generate_docs.py` | Regenerates auto-generated doc sections from GitHub Issues |
| `scripts/check_drift.py` | Nightly stale-requirement drift detection |
| `scripts/github_comment.py` | Agent-safe GitHub API wrapper (comment + label + field update) |
| `docs/github-issue-map.json` | Maps UN/FR/NFR/KPM IDs → GitHub Issue numbers (written by seed script) |
| `mkdocs.yml` | MkDocs Material site configuration |
| `.github/workflows/pr-close-issues.yml` | Layer 1 PR automation |
| `.github/workflows/regen-docs.yml` | Doc regeneration + MkDocs deploy |
| `.github/workflows/nightly-drift.yml` | Nightly drift check |

---

## 7. Out of Scope for This Sub-project

The following are addressed in later sub-projects:

- **Sub-project 2**: Doc reorganisation, superpowers specs/plans cleanup, stale file removal
- **Sub-project 3**: PR automation refinements (beyond basic Issue closure)
- **Sub-project 4**: Scheduled automation enhancements, architecture doc narrative update
- **Sub-project 5**: Full `@verification` / `@validation` agent integration with GitHub write-back

The seeding script and `github_comment.py` wrapper are built here so later sub-projects have a foundation to build on.
