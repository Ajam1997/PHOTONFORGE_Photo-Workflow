# Doc Maintenance Protocol — What to Update, When

**Status:** living (promoted from the 2026-07-09 docs overhaul plan §3.3)
**Owner:** @systems_lead
**Companion:** [doc-source-of-truth.md](doc-source-of-truth.md) (where facts live),
[ci-policy.md](ci-policy.md) (the gates that enforce this).

The 2026-07 docs overhaul found ~40 stale documents whose rot shared one
cause: code changed, and no rule said which docs change with it. This protocol
is that rule.

## Docs-impact matrix

**Now data:** the matrix lives in
[`dev-docs/house-style/conventions/docs-impact-matrix.yml`](../house-style/conventions/docs-impact-matrix.yml)
and is checked by `sf-style` on every PR.

## The three rules

### 1. Supersession banner convention

A superseded doc gets a top-of-file banner and moves to `dev-docs/Archive/`
(same relative path). Exact format:

```markdown
> **SUPERSEDED (2026-01-01, PR #123):** see <replacement doc or ADR>.
> Kept for history; do not implement from this document.
```

(dates/PR number above are illustrative — use the real supersession date and PR.)

History is preserved, never load-bearing. `Archive/` is exempt from the
reference-integrity checks by design (frozen records legitimately cite
deleted code).

**Now enforced as data:** this is the `supersession-banner` convention in
[`dev-docs/house-style/conventions/supersession-banner.yml`](../house-style/conventions/supersession-banner.yml)
(blocking — checked by `sf-style` on every PR).

### 2. AUTO sections are never hand-edited

`sf-docs` (from the `systems-first` package) owns everything between
`<!-- AUTO:key -->` … `<!-- /AUTO:key -->` sentinels; hand edits there are
overwritten on the next regen. Edit the GitHub Issue instead (Issues are the
source of truth — [doc-source-of-truth.md](doc-source-of-truth.md)). Marker
inventory:

| Marker | File | Renderer |
|---|---|---|
| `AUTO:user_needs` | `dev-docs/living-user-needs.md` | `render_user_needs_section` |
| `AUTO:fr_table` / `AUTO:nfr_table` / `AUTO:kpm_table` / `AUTO:vv_matrix` | `dev-docs/photonforge-architecture.md` | respective renderers |
| `AUTO:roadmap` | `dev-docs/roadmap.md` | `render_roadmap_section` |
| `AUTO:kpm_table` | `dev-docs/kpm-dashboard.md` | `render_kpm_table` |

(All four files are committed by `regen-docs.yml` since the Phase-1 fix —
`roadmap.md`/`kpm-dashboard.md` were previously regenerated but never
committed.)

### 3. PR descriptions carry a "Docs impact" line

Every PR description states either the doc files it updated or an explicit
`Docs impact: none`. Cheap to review, and it gives the automated drift
checker a human counterpart.

## Enforcement

- **`docs-integrity.yml`** (every PR): the **diff-aware** reference check is
  **blocking** — it flags only references broken by *this PR's own*
  deletions/renames, so it never blames a PR for pre-existing rot. The
  full-repo scan runs in the same workflow as informational.
- **`nightly-drift.yml`**: the nightly report (committed to
  `dev-docs/drift-reports/`) includes broken doc→file references; the job
  **fails on findings** (the old `|| true` swallow was removed).
- **`validate_generated_docs`** (`scripts/validate_generated_docs.py`) gates
  regen commits in `regen-docs.yml`: corrupted renderer output (CRLF capture
  bleed, `(none yet)` counted as evidence, unparseable living doc) fails the
  workflow instead of being committed and exported to the wiki.

Full CI rationale: [ci-policy.md](ci-policy.md).
