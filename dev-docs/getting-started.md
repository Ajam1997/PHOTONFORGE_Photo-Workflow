# Getting Started

Quickstart for working on PHOTONForge (Profile A — software only). The
generic systems-first-template onboarding that used to live here was
trimmed in the 2026-07 docs overhaul (Phase 4); its EE/ME tooling sections
never applied to this project.

## 1. Read these first (~10 minutes)

1. [`CLAUDE.md`](../CLAUDE.md) — project constraints, agent roster, layout,
   build sequence, agent write-back protocol.
2. [`start-work-checklist.md`](start-work-checklist.md) — the ≈60-second
   session-start ritual.
3. [`architecture/system-architecture-contracts.md`](architecture/system-architecture-contracts.md)
   — module map and interface contracts.

## 2. Set up a dev environment

- **Windows dev box:** follow [`dev-machine-setup.md`](dev-machine-setup.md)
  (venv, models, Darktable Lua plugin deploy, `.mcp.json` note).
- **Linux / Yoga 910 target:** provisioning guide pending (UN-003, docs
  overhaul Phase 5). Until then: `python3.11 -m venv .venv`,
  `pip install -e ".[dev,docs]"`, `bash scripts/provision_models.sh`,
  `python scripts/provision_scoring_models.py`.

## 3. Verify the environment

```bash
python -m pytest -m "not slow"      # must be green
photo-workflow --help               # staged CLI present
python -m scripts.check_doc_references   # docs-to-code reference integrity
```

## 4. Where things live

| Area | Path |
|---|---|
| Pipeline engine | `src/photo_workflow/` (staged CLI: `pipeline.py`) |
| Darktable plugin (the GUI) | `lua/photonforge/` |
| Host/cartridge scripts | `scripts/` |
| CI | `.github/workflows/` (`tests.yml`, `docs-integrity.yml`, doc automation) |
| Requirements & ICDs | `requirements/` + GitHub Issues (canonical) |
| Developer docs (wiki source) | `dev-docs/` (`Archive/` = dated history) |

## 5. Working conventions

- GitHub Issues are the canonical requirement store; `dev-docs/` AUTO
  sections are regenerated — never hand-edit them
  (see [`architecture/doc-source-of-truth.md`](architecture/doc-source-of-truth.md)).
- PRs that change code must update affected docs — docs-impact matrix in
  the [docs overhaul plan §3.3](superpowers/plans/2026-07-09-docs-overhaul-plan.md).
- Agents post evidence via `scripts/github_comment.py`; every comment ends
  with a `**Next action:**` line.
