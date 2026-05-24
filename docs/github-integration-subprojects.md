# GitHub Integration — Sub-project Tracker

Five sub-projects to build out the full GitHub + documentation integration for PHOTONForge.
Source of truth: [Sub-project 1 spec](superpowers/specs/2026-05-23-github-scaffolding-design.md)

---

## Sub-project 1 — GitHub Scaffolding ✅ DONE

Seed the full requirement hierarchy into GitHub Issues and Projects boards, establish automated doc regeneration, and serve docs as a MkDocs Material site on GitHub Pages.

**Delivered:**
- Label taxonomy (type / stage / status labels)
- Three GitHub Projects boards: Roadmap, Requirements, KPM Dashboard
- `scripts/seed_github.py` — one-time idempotent Issue seeder
- `scripts/generate_docs.py` — regenerates living docs from Issue state
- `scripts/check_drift.py` — nightly stale-requirement drift detection
- `scripts/github_comment.py` — agent-safe GitHub API wrapper
- `docs/github-issue-map.json` — maps UN/FR/NFR/KPM IDs → Issue numbers
- `mkdocs.yml` + MkDocs Material site deployed to GitHub Pages
- Three GitHub Actions workflows: `regen-docs.yml`, `nightly-drift.yml`, `pr-close-issues.yml`

---

## Sub-project 2 — Doc Reorganisation ✅ DONE

Clean up and consolidate the docs directory so the site is tidy and nothing is orphaned.

**Scope:**
- Remove stale files no longer referenced in the nav (ValidationReports/, VerificationReports/ on disk but not linked)
- Superpowers specs/plans cleanup — verify all files have correct frontmatter and are up to date
- Add any missing metadata (dates, status, author) to spec/plan files that lack it
- Ensure `docs/superpowers/index.md` stays in sync with actual files (consider auto-generation)
- Update `Notes.md` or migrate its content into a cleaner structure

---

## Sub-project 3 — PR Automation Refinements ✅ DONE

Extend the basic Issue closure automation (`pr-close-issues.yml`) with smarter rollup logic.

**Scope:**
- When a PR is merged: apply `status: verified` to referenced FR/NFR Issues
- Check sibling FR/NFR completion under a parent UN — promote UN to `status: verified` when all children close
- Check UN completion under a parent Epic — move Epic to `Done` column on Roadmap board when all UNs verified
- Handle edge cases: partial merges, re-opened Issues, PRs that reference multiple FRs

---

## Sub-project 4 — Scheduled Automation Enhancements 🔲 UP NEXT

Harden the nightly drift check and keep the architecture doc narrative current.

**Scope:**
- Improve `check_drift.py`: open a GitHub Issue labelled `type: drift-report` when stale FRs are found (currently only writes a Markdown file)
- Add drift report pages to the MkDocs nav automatically (currently orphaned)
- Update the architecture doc narrative sections (executive summary, hardware specs, intelligence engine design) to reflect the current system — these are human-edited and have drifted
- Scheduled automation: consider adding a weekly summary comment on the Roadmap Epic Issues showing overall stage progress

---

## Sub-project 5 — Agent Write-back Integration 🔲

Wire `@verification` and `@validation` agents to post results back to GitHub Issues after every run.

**Scope:**
- `@verification`: after every commit to main, post pytest results and KPM benchmark values as comments on the relevant FR/NFR/KPM Issues; set `status: verified` on pass, revert to `status: defined` on regression; update `Last Measured` and `Status` fields on KPM Dashboard
- `@validation`: after milestone merge or manual invocation, post E2E results on UN Issues; set `status: validated` on pass; open a `type: validation-failure` Issue assigned to `@architect` on failure
- Ensure `github-issue-map.json` stays current so agents can look up Issue numbers by FR/KPM ID
- Test the full loop: engineer commits → verification posts → KPM Dashboard updates automatically
