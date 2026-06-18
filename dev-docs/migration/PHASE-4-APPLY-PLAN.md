# Phase 4 — Apply Plan (GitHub mutations)

**Status:** awaiting operator review. NOTHING below has run yet.

When you approve, the apply step executes these GitHub mutations in
order. Every body comes from `issue-bodies-new/<NNN>.md`. Rollback
source is `issue-bodies-original/<NNN>.md`.

---

## 1. Label sync (add 2 missing template labels)

The repo has `status: defined` and `status: verified`. The template
adds two more. Non-destructive:

```bash
gh label create "status: in-progress" --color 0e8a16 --description "Implementation in flight"
gh label create "status: validated"   --color 1d76db --description "Integrated demonstration of the user need"
```

## 2. Body edits (67 Issues)

For each Issue, apply its converted body:

```bash
gh issue edit <N> --body-file dev-docs/migration/issue-bodies-new/<NNN>.md
```

All 67 in number order. No title/label change except the special
cases in §4.

## 3. Create new Issue — NFR-2.2 Resource Budget

```bash
gh issue create \
  --title "[NFR-2.2] Resource Budget" \
  --body-file dev-docs/migration/issue-bodies-new/NEW-NFR-2.2.md \
  --label "type: nfr,status: defined,discipline: software"
```

**Post-create:** capture the assigned Issue number and write it into
`requirements/requirement-map.yml` (NFR-2.2 `issue: null` → real number).

## 4. Special cases (structural decisions)

| Issue | Mutation | Reason |
|---|---|---|
| #62 | `gh issue edit 62 --title "[NFR-2.5] Eject Notification"` + body (already retitled in staged body's spec) | Was a duplicate NFR-2.4 label; renumbered to NFR-2.5, spec refined to match parent UN-041 |
| #75 | `gh issue edit 75 --remove-label "type: fr"` + body | Reclassified from FR to verification fixture (it's a labeled reference image set, not a functional requirement) |

> Note: #62's title change is a label-in-title convention
> (`[NFR-2.4]` → `[NFR-2.5]`). The GitHub `type: nfr` label is
> unchanged (it was already nfr).

## 5. Post-apply verification

```bash
# Confirm bodies took
gh issue view 32 --json body | head
# Re-run the requirement-map cross-check
python -c "import yaml; yaml.safe_load(open('requirements/requirement-map.yml'))"
# Phase 8 will run the full render chain (generate_docs, kpm_rollup, etc.)
```

---

## Summary of GitHub writes

- **2** label creations
- **67** body edits
- **1** Issue creation (NFR-2.2)
- **2** title/label tweaks (#62 title, #75 label removal)

Total: 72 GitHub API mutations. All reversible (original bodies cached;
new Issue can be closed; labels can be removed).

## What is NOT in this apply

- **Agent-handle renames** (`@architect`→`@systems_lead`, etc.) —
  deferred to Phase 7, done as one global sweep across Issues +
  CLAUDE.md + `.claude/agents/`.
- **Status-label transitions** — `pr_rollup.py` owns those; this
  migration does not move requirements between defined/verified.
- **The render chain** — Phase 8.
