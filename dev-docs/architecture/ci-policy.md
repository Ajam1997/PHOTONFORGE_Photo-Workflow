# CI Policy

**Status:** living
**Owner:** @software_lead (workflows) / @systems_lead (policy)

What each workflow in `.github/workflows/` gates, and why.

## tests.yml — every push to main + every PR

- `python -m pytest -m "not slow"` — **blocking**. The `slow` marker excludes
  hardware-bound and long-runtime tests (those run on the Yoga via
  `scripts/remote_test.sh`); `integration` fixture tests are included.
- `ruff check src/ tests/` — **non-blocking** (`continue-on-error`) until the
  ~60 pre-existing findings are burned down; don't add new ones.
- Dependency note: `opencv-python-headless>=4.9,<5` is pinned in
  `pyproject.toml` because cv2 5.x changes `HoughLinesP` output handling
  (`composition.py`) — an unpinned install broke 13 tests.

## docs-integrity.yml — every PR

- **Diff-aware reference check** (`scripts/check_doc_references.py
  --pr-mode`) — **blocking** since 2026-07-10 (decision D5; backlog cleared
  by overhaul Phases 3–4). Flags docs that reference files *this PR* deletes
  or renames; it can never blame a PR for pre-existing rot.
- **Full-repo scan** — informational (`continue-on-error`), same script
  without `--pr-mode`. Dated-history dirs (`Archive/`, `SystemReviews/`,
  `drift-reports/`, `superpowers/`, `migration/`) are exempt by design.

## regen-docs.yml — push to main, issue events, manual

Regenerates the four AUTO docs from GitHub Issues (`scripts/generate_docs.py`),
then runs the **sanity gate** `scripts/validate_generated_docs.py` — CR
characters, `(none yet)` placeholders rendered as evidence, leaked `**Field:**`
markup, or an unparseable living-user-needs doc **fail the workflow instead of
committing garbage**. On pass it commits `dev-docs/` (all four generated
files). Auth uses the **built-in `github.token`** — the old PAT secret went
stale and an expired PAT defeats any `||` fallback.

## nightly-drift.yml — 02:00 UTC + manual

Runs `scripts/check_drift.py` (stale requirements, FR-ID/source drift, broken
doc→file references), commits the dated report to `dev-docs/drift-reports/`,
**then fails the job if the check reported findings** — the exit code is
captured and surfaced, not swallowed (the historical `|| true` is banned).
Red nightly = the report has actionable rows.

## wiki-publish.yml — after regen-docs, on dev-docs pushes, manual

One-way export of `dev-docs/` to the GitHub Wiki (`scripts/migrate_wiki.py
--push`; sidebar from `dev-docs/_wiki-nav.yml`). **Requires the
`WIKI_PUSH_TOKEN` secret to be a classic PAT with the `repo` scope** —
fine-grained PATs and the built-in `GITHUB_TOKEN` cannot push to wiki repos
(HTTP 403). Setup: generate a classic token (scope `repo`, ~1 y expiry) →
save as repo secret `WIKI_PUSH_TOKEN` → run the workflow manually once to
verify (full checklist in the workflow file's header comment). Concurrency
group serializes back-to-back merges.

## What a merged PR is expected to have

1. The full suite green (`tests.yml`) — no merging on red.
2. The diff-aware docs-integrity check green.
3. A **"Docs impact"** line in the description — updated files or an explicit
   "none" (rule 3 of
   [doc-maintenance-protocol.md](doc-maintenance-protocol.md)).
