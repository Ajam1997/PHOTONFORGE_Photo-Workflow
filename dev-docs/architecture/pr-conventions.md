# PR Scoping Conventions

**Status:** living
**Owner:** @systems_lead (policy) / @software_lead (practice)

How work is split across pull requests. The goal is reviewable, low-risk PRs:
trivial fixes should not each spawn ceremony, and a genuinely risky change
should not hide inside a pile of unrelated one-liners.

Doc-side PR conventions (docs-impact matrix, supersession banner, glossary,
templates) live in [`dev-docs/house-style/`](../house-style/house-style.md)
and are enforced by `sf-style`.

There are three PR classes.

## 1. Minor-bug roundup PR (rolling, shared)

One open PR at a time acts as a catch-all for small, low-risk, easily-fixed
bugs. Land several unrelated minor fixes here instead of opening a PR each.

Rules for the rolling PR:
- **Title:** `fix: minor bug roundup` (keep it stable while open).
- **Description:** a running checklist — one line per bug with a one-sentence
  root cause and the file(s) touched.
- **One commit per bug**, self-contained, conventional-commit message. A
  reviewer (or `git revert`) can act on a single fix without disturbing the
  others.
- **Keep it mergeable at all times.** Don't let it grow unreviewable — cap it
  at roughly 5–8 fixes or a few days, then merge and open a fresh roundup.
- **Each fix still honors the Docs-impact rule** (see
  [doc-maintenance-protocol.md](doc-maintenance-protocol.md)); note per-bug doc
  updates in the checklist line.
- **Split on escalation.** If a fix that looked minor trips a major trigger
  (below) mid-work, pull it into its own PR. Never hold the whole roundup
  hostage to one risky or contested fix.

## 2. Major-bug PR (independent, one per bug)

A bug gets its **own** PR when it is not safely reviewable as a one-off. Open an
independent PR if **any** of these triggers fire:

- **Cross-cutting:** spans multiple modules, or changes a module boundary /
  interface (an `IF-*` ICD).
- **Contract change:** adds/renames/removes a CLI flag, changes a persisted
  format, or changes a function signature other modules depend on.
- **Schema/migration:** needs a DB schema change or data migration.
- **New surface:** adds a runtime dependency or a new config knob.
- **Design needed:** requires an ADR, a design doc, or a requirement change —
  i.e. the fix isn't purely mechanical.
- **Requirement impact:** touches a KPM/NFR budget or needs an @validation
  milestone re-run.
- **Blast radius:** large or hard-to-reason-about diff (rule of thumb: more
  than ~50 changed lines or more than ~3 files), or high regression risk.
- **Security-sensitive.**
- **Uncertain fix:** likely to need iteration/review rounds.

If **none** fire and the fix is small, confined to one module, mechanically
understood, and independently verifiable → it belongs in the roundup (class 1).

**When unsure, err toward an independent PR.** A too-granular PR is cheap; an
unreviewable omnibus is not.

## 3. Enhancement PR (independent, one per change)

Any change that alters *intended* behavior — new features, behavior changes,
non-trivial refactors — gets its **own** PR regardless of size. Enhancements
usually carry requirement/doc/validation implications and must not ride inside
a bug PR, where they'd escape that scrutiny.

## Quick decision

```
Is it a bug (restores intended behavior)?
├─ No  → Enhancement → its own PR (class 3).
└─ Yes → Any major trigger above fire?
         ├─ Yes → its own PR (class 2).
         └─ No  → add to the rolling minor-bug roundup (class 1).
```

See also the merge checklist in
[ci-policy.md](ci-policy.md#what-a-merged-pr-is-expected-to-have).
