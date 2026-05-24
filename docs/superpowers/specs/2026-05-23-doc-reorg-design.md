# Doc Reorganisation — Design Spec

**Date**: 2026-05-23
**Status**: Approved
**Author**: Alex Meyer
**Sub-project**: 2 of 5 (GitHub Integration)

## Summary

Clean up the `docs/` directory so the MkDocs site is tidy, every spec has consistent metadata, and no orphaned files sit on disk. No content is lost — deleted files are already preserved in git history.

---

## 1. File Deletions

### 1.1 Orphaned Report Directories

These directories exist on disk but are not linked in the nav. Delete entirely.

| Directory | Files | Reason |
|---|---|---|
| `docs/ValidationReports/` | `2026-04-18-stage7.1-validation.md`, `soak-test-log.md` | Old E2E reports, superseded by GitHub Issue write-back (Sub-project 5) |
| `docs/VerificationReports/` | `2026-04-17-verification-report.md`, `2026-04-18-14-00-verification.md`, `2026-04-18-failure-843e109.md` | Old commit-level reports, superseded by GitHub Issue write-back (Sub-project 5) |

### 1.2 Stale Planning File

| File | Reason |
|---|---|
| `docs/PlanningBriefs/APPROVAL_PENDING.md` | One-liner from 2026-04-17, no longer actionable |

Remove from `mkdocs.yml` nav and delete from disk.

---

## 2. Notes.md Cleanup

`docs/Notes.md` currently contains raw debugging notes from the Florence-2 fix session. Convert to a structured **Engineering Notes** document with:

- A **Known Issues** section capturing the Florence-2 KPM-1.2 performance gap (6.7s vs 2.5s target) and the open investigation path (KV-cache via `decoder_with_past_model_int8.onnx`)
- A **Naming Output Issues** section capturing the known bad output (yes / no / "answering does not require reading") and the two open bugs: file not renamed on disk, only XMP updated
- Clean markdown formatting (no escaped underscores, no raw HTML)

---

## 3. Spec Frontmatter Standardisation

Every spec in `docs/superpowers/specs/` should have these four fields in the header:

```markdown
**Date**: YYYY-MM-DD
**Status**: Approved | Draft | Superseded
**Author**: Alex Meyer
**Scope**: one-line description of what this spec covers
```

Specs currently missing fields:

| File | Missing |
|---|---|
| `2026-04-17-ssh-key-update-design.md` | Author |
| `2026-04-17-stage-7-1-gui-scaffold-design.md` | Author, Scope |
| `2026-04-19-stage-7-2-ingest-cartridge-design.md` | Date, Status, Author, Scope (no header at all) |
| `2026-04-20-cartridge-provisioning-design.md` | Date, Status, Author, Scope |
| `2026-04-20-ingest-pipeline-design.md` | Date, Status, Author, Scope |
| `2026-04-23-cartridge-identity-redesign.md` | Author |
| `2026-05-12-stage-based-cli-design.md` | Author |
| `2026-05-13-darktable-lua-plugin-design.md` | Author |
| `2026-05-14-terminal-flash-bugfix-design.md` | Status, Author |
| `2026-05-20-pipeline-v2-design.md` | Date, Status, Author, Scope |
| `2026-05-21-genre-aware-scoring-design.md` | Author |
| `2026-05-23-github-scaffolding-design.md` | Author |

Plans do not require individual frontmatter — their `**Goal:**` line serves the same purpose.

---

## 4. Out of Scope

- Content changes to any spec or plan (frontmatter only)
- Restructuring the nav beyond removing the deleted file
- Auto-generating `superpowers/index.md` (already manually maintained)
