# Agent Write-back Integration — Design Spec

**Date**: 2026-05-23
**Status**: Approved
**Author**: Alex Meyer
**Sub-project**: 5 of 5 (GitHub Integration)

## Summary

Wire `@verification` and `@validation` agents to write results back to GitHub Issues after every run using `scripts/github_comment.py`. The key gap: the existing CLI takes raw Issue numbers, but agents know requirement IDs (FR-1.2, KPM-1.1, UN-010). Add ID-based commands that do the Issue number lookup internally. Fix the KPM board field update (currently broken because `project_items` is empty) by doing the board item lookup at write time.

---

## 1. New CLI Commands

Agents always invoke via: `python scripts/github_comment.py <command> <args>`

### `verify-fr <FR-ID> <summary>`
- Looks up FR Issue number from `github-issue-map.json`
- Posts comment with pytest summary
- Calls `replace_status_label` → `status: verified`

```
python scripts/github_comment.py verify-fr FR-1.2 "pytest: 5/5 passed, 1.8s"
```

### `regress-fr <FR-ID> <reason>`
- Posts comment with regression details  
- Calls `replace_status_label` → `status: defined`

```
python scripts/github_comment.py regress-fr FR-1.2 "test_sharpness failed: expected 0.85 got 0.72"
```

### `update-kpm <KPM-ID> <last_measured> <passing|failing|untested>`
- Looks up KPM Issue number and node_id from issue map
- Posts comment with measurement result
- Queries KPM Dashboard board at write time to find the project item ID
- Updates `Last Measured` (text field) and `KPM Status` (select field) on the board

```
python scripts/github_comment.py update-kpm KPM-1.2 "1.8s on i7-7500U — 2026-05-23" passing
```

### `validate-un <UN-ID> <summary>`
- Looks up UN Issue number from issue map
- Posts comment with E2E summary
- Calls `replace_status_label` → `status: validated`

```
python scripts/github_comment.py validate-un UN-010 "E2E: all 3 scenarios passed"
```

### `validation-failure <UN-ID> <reason>`
- Posts comment on UN Issue
- Opens a new Issue labelled `type: validation-failure` with the reason
- Does NOT change the UN status label (remains `status: in-progress`)

```
python scripts/github_comment.py validation-failure UN-010 "Grouping wrong on burst shots"
```

---

## 2. KPM Board Item Lookup

`project_items.kpm_dashboard` in `github-issue-map.json` is empty — the seed script created the board but didn't record item IDs. Rather than a separate populate script, `update-kpm` queries the board at write time:

```graphql
query($projectId: ID!, $after: String) {
  node(id: $projectId) {
    ... on ProjectV2 {
      items(first: 100, after: $after) {
        nodes {
          id
          content { ... on Issue { number } }
        }
      }
    }
  }
}
```

Find the item whose `content.number` matches the KPM Issue number → use that item ID for field updates.

Add `find_project_item_by_issue_number(project_id, issue_number) -> str | None` to `GitHubClient`.

---

## 3. Agent Protocol (CLAUDE.md update)

Add to CLAUDE.md:

```
## Agent Write-back Protocol

@verification (after every commit to main):
  python scripts/github_comment.py verify-fr <FR-ID> "<pytest summary>"
  python scripts/github_comment.py regress-fr <FR-ID> "<failure detail>"   # on regression
  python scripts/github_comment.py update-kpm <KPM-ID> "<value + date>" <passing|failing>

@validation (on milestone merge or manual invocation):
  python scripts/github_comment.py validate-un <UN-ID> "<E2E summary>"
  python scripts/github_comment.py validation-failure <UN-ID> "<reason>"   # on failure

All commands read GITHUB_TOKEN from environment. Never call the GitHub API directly.
```

---

## 4. Files

| Path | Change |
|---|---|
| `scripts/github_client.py` | Add `find_project_item_by_issue_number()` |
| `scripts/github_comment.py` | Add 5 new ID-based commands |
| `CLAUDE.md` | Add agent write-back protocol section |
