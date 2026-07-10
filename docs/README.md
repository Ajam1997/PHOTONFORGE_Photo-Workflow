# User Documentation (placeholder)

This directory is reserved for **end-user documentation** — installation
guides, photo workflow how-tos, troubleshooting — that will be written when
the project is ready to be used by people other than the operator.

It is intentionally empty for now.

## Where developer documentation lives

Developer documentation is in `dev-docs/` and is rendered to the
**GitHub Wiki** by `scripts/migrate_wiki.py`. Read it there:
<https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/wiki>

To author or edit dev docs, edit the markdown files under `dev-docs/`
and merge to `main`; the wiki updates automatically via
`.github/workflows/wiki-publish.yml`.

## See also

- `CLAUDE.md` — top-level project map
- `dev-docs/start-work-checklist.md` — session start procedure
- `dev-docs/architecture/doc-source-of-truth.md` — where things live
- `dev-docs/Archive/architecture/hb-3-wiki-refactor-brief.md` — the brief that
  established this split
