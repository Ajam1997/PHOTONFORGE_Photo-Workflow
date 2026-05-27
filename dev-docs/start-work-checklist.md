# Start-Work Checklist

Run this at the top of every session. ~60 seconds. Picks the right Superpowers
skill and the right agent **before** the first invocation.

Origin: §6.3 of `SystemReviews/2026-05-26-architecture-and-docs-migration-review.md`.

---

## 1. What kind of work is this session?

| Situation | Skill to invoke first |
|---|---|
| (a) New idea, no design yet | `superpowers:brainstorming` |
| (b) Design exists, need an implementation plan | `superpowers:writing-plans` (or hand to @architect) |
| (c) Plan exists, ready to implement | `superpowers:subagent-driven-development` (preferred) or `superpowers:executing-plans` |
| (d) Resuming mid-flight work | SOP-B below + `superpowers:systematic-debugging` if returning to a failing test |
| (e) Debugging a specific failure | `superpowers:systematic-debugging` |
| (f) About to claim "done" / merge | `superpowers:verification-before-completion` + `superpowers:requesting-code-review` + `superpowers:finishing-a-development-branch` |

## 2. Does this work deserve workspace isolation?

Multiple files, risk of half-done state, or parallel to other work in the tree
→ `superpowers:using-git-worktrees`.

## 3. Are there 2+ independent investigations to do?

Different test files, different subsystems, different bugs
→ `superpowers:dispatching-parallel-agents`.

## 4. Which @agent will I hand this to?

| If the work is… | Hand to… |
|---|---|
| Design / interfaces / CLAUDE.md | @architect |
| `src/` implementation, tests | @engineer |
| `scripts/`, `deploy/`, udev, container | @devops |
| Per-commit pytest + KPM run | @verification (or skip — pr_rollup.py handles label flip) |
| Per-milestone E2E pass | @validation |
| Cross-cutting system review | @systemmaster (operator-only) |

Agent ↔ skill pairings live in `CLAUDE.md` → Agent Roster.

## 5. Will the next person resuming this session find a breadcrumb?

Per HB-8:
- Every `github_comment.py` call already requires `--next-action "..."` —
  the CLI fails fast if you forget.
- Every brief authored by @architect or @engineer must end with an
  `## Open questions if you stop mid-step` section, even if empty.
  The template is in `docs/architecture/stage-6-engineer-brief.md`.

If you are about to stop mid-step, fill that section *before* you close the
session. Future-you will thank present-you.

---

## SOP-B — Resuming Mid-Flight Work

When picking up after a gap:

1. `git status` and `git log --oneline -10` — identify the in-flight feature
   and current branch.
2. Open the corresponding `docs/architecture/<feature>-engineer-brief.md`
   if one exists; otherwise the FR Issue body. Recover *intent*.
3. Read the FR Issue's most recent comments — especially the
   `**Next action:**` lines from @verification / @validation. Recover *state*.
4. Open the relevant test file (`tests/test_<module>.py`). Recover the
   *implementation surface*. If returning to a failing test, invoke
   `superpowers:systematic-debugging`.
5. If still unclear: invoke @systemmaster with `"resume context for FR-X.Y"` —
   review brief lands at `docs/SystemReviews/YYYY-MM-DD-resume-FR-X.Y.md`.

You should *not* need to read `src/` to figure out where you were. If you do,
the brief / Issue comments are missing a breadcrumb — fix the artifact before
continuing.

---

## See Also

- `CLAUDE.md` → Agent Roster (skill pairings per agent)
- `docs/architecture/doc-source-of-truth.md` (where things live)
- `docs/architecture/stage-6-engineer-brief.md` (the model brief format)
- `docs/SystemReviews/2026-05-26-architecture-and-docs-migration-review.md`
  (full rationale for this workflow)
