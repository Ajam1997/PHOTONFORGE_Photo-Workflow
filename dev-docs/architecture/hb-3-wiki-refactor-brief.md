# HB-3 Engineer Brief — Wiki Becomes Primary Dev Doc Surface

**Owner:** @devops
**Reviewer on completion:** operator (no automated verification — this is infra)
**Source-of-truth for decisions:** `docs/SystemReviews/2026-05-26-architecture-and-docs-migration-review.md` §5 HB-3 + the 2026-05-27 operator answers below
**Step:** 1 of 4 (this brief = the whole plan; execution split into 4 sequential commits/PRs)

---

## Operator decisions locked

| Question | Answer |
|---|---|
| OQ-2 wiki direction | One-way: `dev-docs/` → wiki, with `WIKI:LOCAL-ONLY` escape hatch |
| Sidebar source | Generated from `mkdocs.yml` nav |
| Pages site fate | Disabled now (option b + c). MkDocs scaffolding stays; will be repurposed later for user-facing docs |
| Run trigger | Auto on merge to main |
| AUTO chain (Q4) | Two-hop: Issues → `generate_docs.py` writes to `dev-docs/` → `migrate_wiki.py` pushes to wiki |
| Source-of-truth path | `docs/` renamed to `dev-docs/`; fresh empty `docs/` reserved for future user-facing site |

---

## Goal

Make the GitHub Wiki the canonical surface for *reading* developer documentation
while keeping `dev-docs/` as the canonical surface for *authoring* it.
Deprecate the GitHub Pages render of dev docs (it currently leaks out of
`nightly-drift.yml` and `regen-docs.yml`). Reserve the top-level `docs/`
folder for future user-facing documentation.

After this brief lands, the steady-state dev-doc flow is:

```
operator edits a .md in dev-docs/
        |
        v
PR merge to main
        |
        +--> generate_docs.py runs (regen-docs.yml)
        |       Issues -> dev-docs/{living-user-needs, photonforge-architecture,
        |                            roadmap, kpm-dashboard}.md (AUTO sections)
        |
        +--> migrate_wiki.py runs (wiki-publish.yml, NEW)
                dev-docs/* -> github.com/.../wiki/*
                  (skips files tagged WIKI:LOCAL-ONLY on wiki side)
```

Reading: open the wiki. Writing: edit `dev-docs/`, open a PR.

---

## Scope (in)

### Step 1 — Disable Pages publishing (smallest, lowest risk; do first)

- `.github/workflows/nightly-drift.yml` — remove the `run: mkdocs gh-deploy --force` step.
- `.github/workflows/regen-docs.yml` — same removal.
- Leave the `gh-pages` branch on GitHub alone. It will go stale until user docs revive it.
- Leave `mkdocs.yml` in place — it still works for local `mkdocs serve` preview if needed, and stays as scaffolding for the future user-facing site (operator's choice 2b).

**Acceptance Step 1:**
- `grep -r "gh-deploy" .github/` returns nothing.
- A push to main does not trigger a Pages deploy.

### Step 2 — Rename `docs/` → `dev-docs/`

This is wide but mechanical. Do it as one commit so `git log --follow` works cleanly.

- `git mv docs dev-docs`
- Create empty `docs/` with a placeholder README (`# User Documentation (placeholder) — will be populated when end-user docs land`).
- Path updates across the repo:
  - `scripts/generate_docs.py:12` — `DOCS = Path("dev-docs")`
  - `scripts/check_drift.py` — if it references `docs/`, swap to `dev-docs/`
  - `scripts/pr_rollup.py:21` — `ISSUE_MAP_PATH = REPO_ROOT / "dev-docs" / "github-issue-map.json"`
  - `scripts/doc_parser.py` — any `docs/` paths
  - `scripts/seed_github.py` — same
  - `scripts/audit_boards.py`, `populate_boards.py` — same
  - `scripts/migrate_wiki.py` — source path (handled fully in Step 3 anyway)
  - `mkdocs.yml` — either delete or update `docs_dir: dev-docs`. Operator said scaffolding stays for user docs later; recommend **delete `mkdocs.yml` and `mkdocs-requirements.txt` (if present)** since their nav is dev-doc-centric. When user docs land, a fresh mkdocs.yml that points at `docs/` is the right move.
  - `CLAUDE.md` — every `docs/...` reference (~15 of them) updated to `dev-docs/...`. The "Project Layout" section keeps `docs/` (user docs placeholder) and adds `dev-docs/`.
  - `.claude/agents/*.md` — every reference (verification.md, validation.md, architect.md, etc.) updated.
  - `README.md` — update any pointers.
  - `pyproject.toml` — check for `include` / `package_data` paths.
- `.github/workflows/regen-docs.yml` — change checkout filters / commit paths if they pin `docs/`.
- `.github/workflows/nightly-drift.yml` — same.
- `.github/workflows/pr-close-issues.yml` — check.
- `.github/workflows/weekly-progress.yml` — check.

**Acceptance Step 2:**
- `git grep -nE '(^|[^-/])docs/' -- ':!docs/' ':!*.spec'` returns only intentional user-docs-placeholder refs.
- `python scripts/generate_docs.py` (against a live Issue tree) writes to `dev-docs/`, not `docs/`.
- `pytest` collects no errors due to path changes (no tests should reference `docs/` paths; verify).
- The placeholder `docs/README.md` is the only file in `docs/`.

### Step 3 — Refactor `migrate_wiki.py`

Rewrite the migration script:

- **Source:** `dev-docs/` (was `docs/`).
- **Per-file hash compare:** read existing wiki page, `sha256` compare to source, skip if unchanged.
- **`WIKI:LOCAL-ONLY` escape hatch:** before pushing, read each *existing* wiki page; if its YAML front-matter (or HTML comment header) contains `wiki-local-only: true` (or simpler: an `<!-- WIKI:LOCAL-ONLY -->` marker on line 1), skip it.
- **`--diff` mode:** print per-file action (`OVERWRITE`, `SKIP-UNCHANGED`, `SKIP-LOCAL-ONLY`, `NEW`, `DELETED-IN-SOURCE`); make no writes.
- **`--push` mode:** apply the actions from `--diff`.
- **Sidebar generation:** parse `mkdocs.yml` nav (if it still exists) OR a new `dev-docs/_wiki-nav.yml` config to generate `_Sidebar.md`. **Decision needed:** since Step 2 may delete `mkdocs.yml`, recommend creating `dev-docs/_wiki-nav.yml` as the curated nav, owned by the operator, used by migrate_wiki.py only. Single source for sidebar; not entangled with the future user-docs mkdocs.yml.
- **Page-name collisions:** before push, detect two source files that would map to the same wiki page name. Fail loudly with both source paths.
- **Replace `sys.platform == "win32"` branch** with `pathlib.Path` operations.
- **Drop the wipe-and-copy.** No `rm *.md` step on the cloned wiki.

**Acceptance Step 3:**
- `migrate_wiki.py --diff` runs without writes and produces a readable per-file action list.
- A wiki page with `<!-- WIKI:LOCAL-ONLY -->` on line 1 is skipped on `--push` even if the source file in `dev-docs/` changed.
- A test source file renamed to collide with another reports the collision and exits non-zero.
- Sidebar is generated from `dev-docs/_wiki-nav.yml` (or `mkdocs.yml` if that's where the operator wants it).

### Step 4 — Auto-publish workflow

- New `.github/workflows/wiki-publish.yml`:
  - Trigger: `on: push: branches: [main]`.
  - Steps: checkout, install deps, run `python scripts/migrate_wiki.py --push` with a wiki-write token.
  - Concurrency group `wiki-publish` to prevent overlapping runs.
- Use the default `GITHUB_TOKEN` if it has wiki-write permission; otherwise document the PAT setup in the workflow comments.

**Acceptance Step 4:**
- A PR merged to main triggers `wiki-publish.yml`.
- The wiki reflects the merged state within ~2 min.
- Two PRs merged in quick succession do not race (concurrency group enforces serial).

---

## Scope (out)

- HB-5 (doc GC) — defer until Stage 6 lands.
- Anything in `src/`.
- The future user-facing docs site — left as empty `docs/` with placeholder; design it when it's needed.
- Bi-directional wiki edits — explicitly out (operator chose one-way).

---

## Risks

- **Step 2 is a big diff.** Anything outside this repo that points at `docs/...` URLs (the deprecated Pages site, any external bookmarks, the GitHub repo description's "Docs" link) breaks. Acceptable cost since dev audience is just the operator + agents.
- **`wiki-publish.yml` token permissions.** GitHub's default `GITHUB_TOKEN` may or may not have wiki-write; verify before committing the workflow.
- **`generate_docs.py` and `migrate_wiki.py` running in the same minute.** If `regen-docs.yml` is still merging by the time `wiki-publish.yml` reads `dev-docs/`, the wiki gets a stale snapshot. Mitigation: chain `wiki-publish.yml` to run *after* `regen-docs.yml` via `workflow_run` trigger, not on plain `push`.

---

## Execution order

Each step is a separate commit (or PR) on a single branch — independently
revertable. Recommended order: **Step 1 → Step 2 → Step 3 → Step 4**.

- Step 1 alone is safe to merge immediately (1-line removals × 2).
- Step 2 should land before Step 3 so the wiki refactor targets the renamed
  path from the start.
- Step 3 and Step 4 can be in the same PR if you want; Step 4 is a small
  workflow file but it depends on Step 3's `--push` mode being trustworthy.

---

## Open questions if you stop mid-step

Resolved 2026-05-27:
- `mkdocs.yml` → **delete in Step 2** (recreate fresh when user docs land).
- Sidebar source → **new `dev-docs/_wiki-nav.yml`**, decoupled from future user-docs config.
- Wiki-write auth → **dedicated PAT** stored as `WIKI_PUSH_TOKEN` secret; do not rely on default `GITHUB_TOKEN`.

Still open:
- After Step 1 lands, is the deprecated `gh-pages` branch deleted, kept stale, or 301-redirected somewhere? No urgent answer needed; safe to leave.

---

## Pointers

- System review: `docs/SystemReviews/2026-05-26-architecture-and-docs-migration-review.md` §5 HB-3.
- Existing wiki migrator: `scripts/migrate_wiki.py` (untracked at session start, committed in 0898142).
- AUTO sentinel mechanism: `scripts/generate_docs.py:137-142`.
- Doc source-of-truth precedence: `docs/architecture/doc-source-of-truth.md`.
- Pages publish offenders: `.github/workflows/nightly-drift.yml` and `.github/workflows/regen-docs.yml` (search for `gh-deploy`).
