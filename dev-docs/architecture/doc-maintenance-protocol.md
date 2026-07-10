# Doc Maintenance Protocol — What to Update, When

**Status:** living (promoted from the 2026-07-09 docs overhaul plan §3.3)
**Owner:** @systems_lead
**Companion:** [doc-source-of-truth.md](doc-source-of-truth.md) (where facts live),
[ci-policy.md](ci-policy.md) (the gates that enforce this).

The 2026-07 docs overhaul found ~40 stale documents whose rot shared one
cause: code changed, and no rule said which docs change with it. This protocol
is that rule.

## Docs-impact matrix

When a PR touches the left column, the **same PR** must update the right
column:

| When a PR touches… | The same PR must update… |
|---|---|
| Deletes/renames any file | Every doc the reference-integrity check flags (`scripts/check_doc_references.py` — the blocking PR gate enforces this) |
| `src/photo_workflow/genre_router.py` taxonomy lists (`SUBJECTS`/`PHOTO_TYPES`) | [research/photonforge-labeling-quick-reference.md](../research/photonforge-labeling-quick-reference.md) (canonical taxonomy), `requirements/interfaces/IF-3.1.md`, the CLAUDE.md taxonomy line, and a data-migration script (pattern: `scripts/migrate_long_exposure_to_motion_blur.py`) |
| `src/photo_workflow/score_fusion.py` weights / gates / fusion | [scoring-architecture.md](scoring-architecture.md) (as-built reference), `requirements/interfaces/IF-2.1.md` |
| CLI commands/flags in `src/photo_workflow/pipeline.py` | `requirements/interfaces/IF-1.1.md` stage whitelist, `lua/photonforge/runner.lua` (the protocol pair) |
| XMP/tag format in `src/photo_workflow/darktable_bridge.py` | `requirements/interfaces/IF-3.2.md` (namespace reference), `lua/photonforge/tag_manager.lua` note |
| photondb schema (`src/photo_workflow/photondb.py`) | `requirements/interfaces/IF-4.1.md`, [dev-machine-setup.md](../dev-machine-setup.md) migration note |
| `lua/photonforge/*` | deploy note ("re-run `scripts/deploy_lua.ps1`" / re-copy on Linux, [docs/install-yoga-linux.md](../../docs/install-yoga-linux.md)), `requirements/interfaces/IF-1.1.md` if stages changed |
| Fixes a bug listed in a SystemReview | "Resolved-by" addendum line in that review (`dev-docs/SystemReviews/`) |
| Retires/supersedes a design | Supersession banner + move to `dev-docs/Archive/` + an ADR ([adr/index.md](adr/index.md)) if the decision is non-obvious |
| New module in `src/` | CLAUDE.md layout section, [system-architecture-contracts.md](system-architecture-contracts.md) module table |

## The three rules

### 1. Supersession banner convention

A superseded doc gets a top-of-file banner and moves to `dev-docs/Archive/`
(same relative path). Exact format:

```markdown
> **SUPERSEDED (YYYY-MM-DD, PR #N):** see <replacement doc or ADR>.
> Kept for history; do not implement from this document.
```

History is preserved, never load-bearing. `Archive/` is exempt from the
reference-integrity checks by design (frozen records legitimately cite
deleted code).

### 2. AUTO sections are never hand-edited

`scripts/generate_docs.py` owns everything between
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
