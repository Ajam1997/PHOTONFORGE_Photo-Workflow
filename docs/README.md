# User Documentation

This directory holds **end-user documentation** — installation guides, photo
workflow how-tos, troubleshooting.

## Guides

- [`install-yoga-linux.md`](install-yoga-linux.md) — Linux/Yoga 910 install &
  provisioning guide (UN-003): OS packages, venv, model provisioning, polkit
  rule, Darktable Lua plugin, cartridge layout, SD ingest flow, verification
  checklist. (Windows dev-box counterpart: `dev-docs/dev-machine-setup.md`.)

## Where developer documentation lives

Developer documentation is in `dev-docs/` and is rendered to the
**GitHub Wiki** by `sf-wiki` (from the `systems-first` package). Read it there:
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
