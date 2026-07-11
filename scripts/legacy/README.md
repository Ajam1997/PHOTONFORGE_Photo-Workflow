# scripts/legacy/

Quarantined during migration Phase 10 (2026-05-29). These scripts are
tied to the **GitHub Projects boards + Epic Issues** model that was
superseded by **GitHub Milestones + `requirements/requirement-map.yml`**.

They are kept for reference (git history + here) but are **not wired
into any workflow** and **not maintained**. They read the deleted
`dev-docs/github-issue-map.json`.

| Script | Was | Superseded by |
|---|---|---|
| `seed_github.py` | one-time Issue seeder that created the issue map | Issues already exist; `requirement-map.yml` is canonical |
| `audit_boards.py` | audited GitHub Projects boards | Milestones (no Projects boards) |
| `populate_boards.py` | populated GitHub Projects boards | Milestones |
| `weekly_progress.py` | posted weekly per-Epic progress comments | Epics removed; revive under Milestones is future work |

To revive any of these, migrate it off `github-issue-map.json` onto
`requirements/requirement-map.yml` + live `gh` resolution first.

Note: these scripts also `import scripts.github_client`, which no longer exists (moved to the systems-first package in the 2026-07 migration) — they are doubly non-runnable as-is.
