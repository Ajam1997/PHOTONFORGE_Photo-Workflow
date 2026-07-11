# Doc Source-of-Truth — Where Things Live

Canonical sink decision (2026-05-26, per HB-1 of the architecture review):

**GitHub Issues are the source of truth for status.**
`dev-docs/` is a *render target* of Issues, not a competing source. The wiki is a
one-way export of `dev-docs/` for the operator's offline memory aid.

---

## Precedence Rule (resolves conflicts in one line)

> When a fact about an FR/UN/NFR/KPM appears in more than one place, **Issues win**.
> Docs reflect Issues; the wiki reflects docs. Nothing reflects back upstream.

---

## Where Does X Live?

| Thing | Canonical location | Rendered into | Notes |
|---|---|---|---|
| FR / UN / NFR / IF / KPM status (`defined`, `in-progress`, `verified`, `validated`) | GitHub Issue labels | `dev-docs/living-user-needs.md`, `dev-docs/photonforge-architecture.md`, `dev-docs/roadmap.md`, `dev-docs/kpm-dashboard.md` (AUTO sections) | Only `sf-pr-rollup` writes the `verified`/`validated` labels — see HB-7. Agents post comments via `sf-comment` but never move labels. |
| FR acceptance criteria, KPM target | GitHub Issue body | `dev-docs/photonforge-architecture.md` (FR/NFR/KPM tables), `dev-docs/living-user-needs.md` | Edit the Issue body, then run `sf-docs`. |
| Roadmap stage / stage assignment | GitHub Issue label `stage: N` + Epic Issue | `dev-docs/roadmap.md` | One Epic Issue per stage. |
| Architecture contracts (module interfaces) | `dev-docs/architecture/<feature>-contracts.md` | n/a (hand-authored, no AUTO) | These are *design* docs, not status docs. Edit freely. |
| Engineer briefs (per-feature plans) | `dev-docs/architecture/<feature>-engineer-brief.md` | n/a | Authored by @systems_lead, consumed by @software_lead. Must include an "Open questions if you stop mid-step" section (HB-8). |
| Research / scratch notes | `dev-docs/research/*.md` | n/a | Free-form. Not in AUTO regen. |
| Verification / validation measurements (KPM numbers, pass/fail) | GitHub Issue comment via `sf-comment` ending in `**Next action:** ...` | n/a | Reports as Issue comments — not as `dev-docs/VerificationReports/*.md` files. See OQ-3 resolution. |
| System reviews | `dev-docs/SystemReviews/<date>-<topic>.md` | n/a | Operator-invoked deep reviews. |
| Operator's offline memory aid | GitHub Wiki | one-way exported from `dev-docs/` via `sf-wiki` | Wiki is downstream of docs. Direct edits to the wiki survive only if front-matter-tagged `WIKI:LOCAL-ONLY` (post-HB-3). |

---

## AUTO Sentinels — How Hand Edits Survive Regen

`sf-docs` (from the `systems-first` package) only replaces content between sentinels:

```
<!-- AUTO:key_name -->
...generated content...
<!-- /AUTO:key_name -->
```

Anything **outside** these markers is preserved. If you need to add context to a
living doc, write it outside the sentinels.

If a needed edit doesn't fit outside the sentinel, the *Issue* is the wrong
source — fix the Issue, not the doc.

---

## What Agents May Write

| Actor | May write | May not write |
|---|---|---|
| @verification | Issue comments (with `Next action:` and `via:` footers) via `sf-comment` | `dev-docs/living-user-needs.md` (any section); status labels |
| @validation | Issue comments via `sf-comment`; `tests/e2e/*` | `dev-docs/living-user-needs.md`; status labels; `src/`; `tests/test_*` |
| @software_lead | `src/`, `tests/test_*`, `scripts/`, `deploy/`, `.github/workflows/`, PR descriptions | Status labels |
| @systems_lead | `dev-docs/architecture/*`, `CLAUDE.md` | Status labels; status-bearing AUTO sections |
| `sf-pr-rollup` (workflow) | `verified` label on PR merge | `validated` label (that's @validation's domain, on milestone) |
| `sf-docs` (workflow) | AUTO sections of the four living docs | Anything outside AUTO sentinels |

If you find an agent writing outside this table, that's the bug — fix the agent,
not the doc.

---

## See Also

- `dev-docs/SystemReviews/2026-05-26-architecture-and-docs-migration-review.md` — full rationale
- `CLAUDE.md` → "Agent Write-back Protocol" — operational details
- HB-1, HB-7, HB-8 in the system review
