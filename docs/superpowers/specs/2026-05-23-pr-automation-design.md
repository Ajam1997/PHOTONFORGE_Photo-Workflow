# PR Automation Refinements — Design Spec

**Date**: 2026-05-23
**Status**: Approved
**Author**: Alex Meyer
**Sub-project**: 3 of 5 (GitHub Integration)

## Summary

Replace the inline Python heredoc in `pr-close-issues.yml` with a proper `scripts/pr_rollup.py` module that applies `status: verified` to closed FR/NFR Issues, rolls up to parent UNs when all siblings close, and promotes parent Epics to Done when all UNs under a stage are verified.

---

## 1. Problems with Current Implementation

| Problem | Detail |
|---|---|
| Security | PR body injected directly into Python heredoc — a PR with backticks or Python syntax could break the script |
| Incomplete rollup | Only sets `status: verified` on the directly closed FR/NFR; no sibling check, no UN promotion, no Epic promotion |
| Inefficient | Re-fetches all Issues once per closed Issue number — O(n) list API calls |
| Not testable | Logic lives inline in YAML; no unit tests possible |

---

## 2. Architecture

```
pr-close-issues.yml
  └── python -m scripts.pr_rollup
        ├── reads PR_BODY env var (safe — no heredoc injection)
        ├── loads docs/github-issue-map.json
        ├── loads scripts/requirement_map.yml
        ├── fetches all Issues once → cached dict
        └── rollup logic:
              FR/NFR closed → status: verified
              all FR/NFR siblings verified → UN: status: verified
              all UNs in stage verified → Epic: closed + status: validated
```

### 2.1 Status Label Replacement

GitHub's `POST /labels` adds labels; it doesn't replace them. Updating a status label requires:
1. GET current labels on the issue
2. Remove any `status: *` label from the list
3. Add the new status label
4. PUT the full updated label list

Add `replace_status_label(issue_number, new_status)` to `GitHubClient`.

### 2.2 Parent Lookup

Use `requirement_map.yml` to build in-memory reverse maps at startup:

- `fr_to_un`: `"FR-1.2"` → `"UN-010"`
- `nfr_to_un`: `"NFR-2.1"` → `"UN-030"`
- `un_to_stage`: `"UN-010"` → `2`
- `stage_to_epic_num`: `2` → GitHub Issue number from `github-issue-map.json`

### 2.3 Epic Promotion

When all UNs under a stage are `status: verified`:
- Close the Epic Issue (`PATCH state: closed`)
- Apply `status: validated` label to the Epic

Projects v2 board column moves are not implemented here — the `Done` column on the Roadmap board is a manual action for now (Sub-project 4 can automate it via GraphQL if needed).

### 2.4 Dry-run Mode

`--dry-run` flag prints all planned label changes and closures without touching GitHub. Used for local testing.

---

## 3. Workflow Changes

`pr-close-issues.yml`:
- Pass PR body via `PR_BODY` env var (not heredoc)
- Call `python -m scripts.pr_rollup` instead of inline script

---

## 4. Files

| Path | Change |
|---|---|
| `scripts/pr_rollup.py` | New — full rollup logic |
| `scripts/github_client.py` | Add `replace_status_label()` and `get_issue()` |
| `.github/workflows/pr-close-issues.yml` | Replace inline script with module call |

---

## 5. Out of Scope

- Re-opened Issue status reversion (Sub-project 4)
- Projects v2 board column moves via GraphQL (Sub-project 4)
- Unit tests for `pr_rollup.py` (Sub-project 4 or separate task)
