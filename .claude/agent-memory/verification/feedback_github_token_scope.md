---
name: github-token-scope-gap
description: gh CLI token lacks read:project scope — KPM board field updates fail but issue comments succeed
metadata:
  type: feedback
---

The token retrieved via `gh auth token` has scopes: gist, read:org, repo, workflow. It does NOT have read:project.

This means `python scripts/github_comment.py update-kpm` will:
- Successfully post a comment to the KPM issue (repo scope covers this)
- Fail with a GraphQL INSUFFICIENT_SCOPES error when trying to update the KPM Dashboard board fields

**Why:** The GitHub Project board (PVT_kwHOAp7_Us4BYnas) requires read:project scope for GraphQL queries.

**How to apply:** When running update-kpm commands, expect the board field update to fail. The issue comment still lands. Flag this to @software_lead or @systems_lead to add read:project scope to the PAT. Do not treat the traceback as a verification failure — it is a token config issue.
