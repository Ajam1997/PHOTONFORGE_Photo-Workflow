# Standalone Cartridge Manager — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone Windows desktop app for cartridge-level operations that
don't belong inside a Darktable session: provisioning a fully dual-OS
portable drive from one Windows machine (via WSL), moving shoot folders and
already-ingested photos between cartridges with correct renaming and DB
migration, the existing backup/restore/verify/archive tools with a real UI
instead of panel buttons launching terminals, and a lightweight photo
viewer. Entirely separate from the Darktable Lua plugin and from
`make-portable`'s drive-build path — this app *provisions* and *manages*
cartridges; it never runs inside Darktable and never replaces the pipeline.

## Decisions made before this plan was written

Settled by the user up front, because each is expensive to reverse:

1. **Stack: Python + PySide6, importing `src/photo_workflow` directly** —
   not shelling out to the CLI, not a second implementation in another
   language. This is the load-bearing decision behind ADR-004's failure
   mode never repeating: the Tk Cartridge Manager that got deleted in PR
   #117 had *its own* DB layer with an incompatible schema. There is no
   second schema here — this app and the pipeline read and write the exact
   same `photondb.py`/`darktable_bridge.py`/`backup.py`/`volume.py`
   functions.
2. **Windows-only product**, at least for this app. The Yoga keeps using
   the CLI + the Lua plugin's Snapshot/Backup/Verify buttons; no Linux GUI
   is being built here. (The underlying modules stay cross-platform —
   nothing in `src/photo_workflow` should become Windows-only because of
   this app — only the PySide6 shell and the WSL provisioning feature are
   Windows-specific.)
3. **The move/migrate feature rewrites Darktable's own `library.db` rows**
   (not just `photonforge.db` + XMP), so a moved photo is never "missing"
   in Darktable. This is the highest-risk piece in the whole plan and gets
   its own task, its own safety design (below), and real tests against a
   real Darktable-generated schema before anything else in this plan is
   built.

## Context

Three things exist today and stay unchanged by this plan:

- `photo-cartridge` (`src/photo_workflow/cartridge.py`) already has
  `snapshot` / `backup` / `verify-backup` / `restore-backup` (real, tested)
  and `make-portable` (real, tested — see the
  [portable-drive plan](2026-07-17-portable-drive-plan.md)). This app is a
  GUI *in front of* those, not a reimplementation.
- `make-portable`, run on a Linux host, already builds a full dual-OS
  drive in one call — verified in that plan's Task 7. The gap this plan
  closes is the **Windows-only** host case: today that can only bundle the
  Windows half of Darktable natively (the Linux half needs to execute the
  downloaded AppImage, which Windows can't do without WSL — see
  `docs/portable-drive-setup.md`).
- Nothing today lets a user move a shoot folder — or a subset of
  already-scored, already-tagged photos — from one cartridge to another,
  or between shoot folders on the same cartridge, without hand-editing
  three things that must stay in lockstep: the file on disk, its row in
  `photonforge.db`, and its row (+ history/tags/color-labels, which key off
  the same row) in Darktable's `library.db`/`data.db`.

## Real schema research (done before writing this plan, not assumed)

`tests/fixtures/library.db` and `tests/conftest.py::make_darktable_db` are
**not** representative of a real Darktable catalog — they're a leftover
from the deleted Layout-A prototype (`images(id, filename, folder, flags,
caption)`, no `film_rolls`, no `group_id`, no history). The *production*
code path (`darktable_bridge.py::_open_dt` and friends) already only
touches columns that exist in the real schema, so nothing shipped is
broken — but a new feature that touches `images`/`film_rolls` cannot be
designed or tested against that fixture. Verified instead by installing
real Darktable (apt `darktable` 4.6.1, then the actual Darktable 5.6.0
AppImage from the portable-drive plan's Task 7 cache) and importing real
files under `xvfb-run`:

- **`film_rolls(id, access_timestamp, folder)`** — one row per imported
  directory. `images.film_id` is a foreign key into it. **A folder's
  identity in Darktable is this row, not a path stored per-image.**
- **`images`** — `filename` is the basename only (no path — the path comes
  from `film_rolls.folder` via `film_id`); `group_id` is a **self**-foreign
  key (`images.id`) used for RAW+JPEG pairs and Darktable's own
  "duplicate" feature; `version`/`max_version` are Darktable's duplicate
  versioning, a different concept from `photonforge.db`'s `is_duplicate`.
- **`history`, `history_hash`, `masks_history`, `tagged_images`,
  `color_labels`, `selected_images`** — every one of these keys off
  `imgid` (i.e. `images.id`), **never off filename or path**. This is the
  finding the whole safety design leans on: *renaming and relocating a
  photo needs only two `UPDATE`s — `images.filename` and `images.film_id`
  — on the existing row. Every edit, tag, and color label survives
  automatically because the row's identity never changes.* Delete+reinsert
  would orphan all of it; this plan never does that.
- **Tags live in `data.db`** (`tags(id, name, synonyms, flags)`,
  `tagged_images` in `library.db`, ATTACHed together) — confirmed against
  real 5.6.0, matching what `darktable_bridge.py` already assumes.
  `data.db`'s location is tied to `--configdir`, not to `--library`'s
  directory — a real difference from `_get_data_db_path`'s
  same-directory-as-library.db assumption in general, but this project
  never triggers that gap because every launcher (portable and host) points
  `--library` *inside* `--configdir`.

## Tasks

### Task 1 — Safe move/migrate core (`src/photo_workflow/relocate.py`) — **DONE (same-cartridge only)**

> Landed 2026-08-21. `move_photos()`, `move_shoot_folder()`, `resume_move()`
> — function-based API, no GUI, no click yet (the CLI wrapper is still
> Task 2). 18 tests, all against real SQLite (the `make_real_darktable_db`
> fixture from the schema research above, not mocks).
>
> **Scoped to same-cartridge moves only, on purpose.** `plan_move()` raises
> `CrossCartridgeNotSupportedError` if source and destination resolve to
> different cartridge roots, rather than attempt the harder copy-row-and-
> remap-tag-ids algorithm the plan's own research flagged as unverified.
> That stays open for a follow-up task.
>
> **A real gap turned up in the test that was supposed to prove the core
> safety claim.** `test_history_tags_and_color_labels_survive_byte_identical`
> originally queried `history`/`tagged_images`/`color_labels` by the
> *original* `imgid` and asserted the rows were unchanged — which passed
> even under a deliberately-reintroduced delete+reinsert mutation, because
> SQLite (with no `PRAGMA foreign_keys=ON` in the fixture, matching
> Darktable's own defaults) happily leaves those rows exactly as they were
> — now orphaned, pointing at an imgid nothing references any more. The
> test never checked that the moved photo's *current* imgid, looked up
> independently at its new location, was still the original one. Fixed by
> adding that lookup and asserting equality; re-ran the same mutation and
> confirmed the test now fails as it should, then reverted the mutation and
> confirmed 18/18 pass on the real code. Documented here because it's
> exactly the kind of test that looks like it proves the safety claim but
> doesn't, and is worth remembering to check for in Task 2/3's tests too.
>
> **Design decisions the plan's algorithm sketch didn't spell out, resolved
> during implementation:**
> - Darktable errors (`CartridgeBusy` from `backup.py`) are re-raised as
>   `relocate.RelocateError` rather than leaking `backup.py`'s exception
>   type — a caller of this module should only ever need to catch one
>   family of errors.
> - Grouped photos (RAW+JPEG pairs, Darktable "duplicates") default to
>   **refusing** the move with `GroupConflictError` naming the sibling not
>   included, rather than silently auto-expanding the move to cover the
>   whole group. `ungroup=True` explicitly splits the group instead,
>   repointing the remaining members to a valid leader. Silent auto-expand
>   would move more files than the caller asked for — exactly the kind of
>   surprise ADR-004's retired Tk manager should have made this project
>   allergic to.
> - `plan_move()` (used for both the real run and `dry_run=True`) has zero
>   side effects — no directory creation, nothing written — verified by a
>   dedicated test after catching that an early draft called `dest_dir.mkdir()`
>   during planning, which would have made "dry-run touches nothing" false.

Function-based API + click subcommands on `photo-cartridge`
(`move-photos`, `move-shoot`, `resume-move`), same convention as every
other module — no GUI code in this module at all, so it can be fully
tested from pytest and used from the CLI standalone before the app in
Task 4 ever imports it.

**Algorithm** (per photo, or per shoot-folder as a batch of photos):

1. **Preflight** (abort before touching anything if any check fails):
   destination not busy (reuse `backup.assert_cartridge_idle`), enough free
   space at the destination (`shutil.disk_usage`), neither library.db
   locked by a running Darktable (reuse `_open_dt`'s lock check), and the
   full "unit" being moved is resolved — a photo's `.xmp` sidecar and any
   `group_id` siblings (RAW+JPEG pairs, Darktable duplicates) move
   together unless the caller explicitly passes `--ungroup`.
2. **Snapshot first.** Tier-1 catalog snapshot (`backup.snapshot_databases`)
   of both the source and destination cartridge before anything destructive
   — cheap, offline, gives an immediate rollback point independent of
   whatever this module does.
3. **Write an intent log** (`.photonforge/move-in-progress.json` on the
   *destination*) before copying anything: what is moving, from where, to
   where, computed new filename, and a state machine (`planned` →
   `copied` → `verified` → `db-updated` → `source-deleted` → `done`). A
   crash between any two of those states must be resumable —
   `resume-move` reads this file and either finishes or safely aborts.
4. **Copy, never move-then-verify.** Stream-copy the file (and sidecar) to
   the destination under the new name, hashing as it goes (reuse
   `backup._copy_and_hash`'s pattern); read the destination back and
   compare hashes. Only advance the intent log to `verified` once that
   passes.
5. **One transaction per DB**, only after `verified`:
   - `photonforge.db`: `UPDATE photos SET folder=?, filename=? WHERE
     folder=? AND filename=?` — the row's other columns (scores, genres,
     stage state) are untouched.
   - Darktable (`library.db` + `data.db` ATTACHed): ensure a destination
     `film_rolls` row exists (`SELECT ... WHERE folder=?`, `INSERT` if not),
     then `UPDATE images SET filename=?, film_id=? WHERE id=?` for the
     photo and every `group_id` sibling being moved together. Nothing else
     is touched — `history`/`tagged_images`/`color_labels` follow for free
     because they key off `images.id`.
6. **Verify after commit**: re-read both DBs, confirm the rows read back
   as expected; only *then* delete the source file and advance the intent
   log to `done`. The source is never deleted before this.
7. Every move is appended to a plain-text/JSONL move log (source, dest,
   old/new filename, checksums, timestamp) — the audit trail and what a
   human reads if something needs to be manually untangled.

**Testing** (this is what the user asked to get right before anything
else): a new, *accurate* Darktable fixture builder in `tests/conftest.py`
— real `film_rolls`/`images`/`group_id`/`history`/`tagged_images` schema,
built the same way the plan's own research was (either replay the captured
`CREATE TABLE` statements from the real xvfb-run import, or — better —
add a `slow`-marked test that does the real `xvfb-run darktable` import
if a Darktable binary is present, skipped otherwise, so the fixture can be
regenerated against a real Darktable when one is available rather than
drifting from hand-maintained DDL). Test matrix, all against real SQLite
files (no mocking the DB layer — the whole point is these tables must
actually agree with each other after the operation):

- [x] Single-photo move within one cartridge (rename only, same film_roll after) — file, `photonforge.db` row, and Darktable row all correct.
- [ ] Single-photo move across cartridges — **deferred**, see the Task 1 annotation above; cross-cartridge raises `CrossCartridgeNotSupportedError` and is a future task, not this one.
- [x] Batch move of a whole shoot folder (`move_shoot_folder`, `test_move_shoot_folder_moves_every_photo`).
- [x] A RAW+JPEG group moves together and `group_id` stays internally consistent; moving one member with `ungroup=True` splits it correctly and repoints the remaining sibling to a valid leader.
- [x] History, tags, and color labels are byte-identical before and after — and the test proves it by imgid identity, not just content, after catching that content-only assertions pass even under a delete+reinsert mutation (see the Task 1 annotation above).
- [x] Destination filename collision — refuses cleanly. (Reachable only by forcing it in the test — `get_next_sequence` already avoids the normal case by design, so this is defense-in-depth, not dead code, confirmed by actually forcing the collision rather than assuming.)
- [x] Busy-cartridge refusal.
- [x] Insufficient disk space refusal, checked before any copy starts.
- [x] Simulated crash between `copied` and `db-updated` (raise from a monkeypatched step) — `resume_move` completes it correctly on the next run without duplicating or losing the file.
- [x] A second move started while one is already in-progress refuses with `MoveInProgressError` rather than silently racing it.
- [x] `dry_run=True` reports the exact plan and touches nothing — verified after catching an early draft that called `dest_dir.mkdir()` during planning.
- [x] The Tier-1 snapshot taken before the move is real and passes `verify_snapshot` (re-hashes every file against its manifest) — not literally round-tripped through `restore_snapshot`, but the byte-level check is the stronger claim of the two and matches what the backup runbook itself emphasizes ("Verifying — do not skip this").

### Task 2 — `move-photos` / `move-shoot` / `resume-move` CLI (`src/photo_workflow/cartridge.py`)

Thin click wrappers over Task 1, matching the existing `snapshot`/`backup`
command style (`--json` output, clean `ClickException` on failure, a
progress callback for batches). This is the CLI surface Task 4's GUI calls
into directly as a Python function — the CLI wrapper exists for headless
use and so the logic can be exercised without the GUI at all, not because
the GUI shells out to it.

### Task 3 — WSL-orchestrated dual-OS provisioning

Extends `make-portable` usage from a Windows host: the Windows half
bundles natively (innoextract has real Windows builds — see
`docs/portable-drive-setup.md`); the Linux half's AppImage extraction step
needs something that can execute a Linux ELF binary, which is what WSL is
for here.

- [ ] Detect WSL2 + a usable distro (`wsl.exe -l -v`); a clear, actionable
      error (not a stack trace) when WSL isn't installed or has no distro,
      since this app must not assume a dev-machine-grade WSL setup.
- [ ] Do **not** assume the distro has this repo checked out. The
      cleanest path: the Windows app calls `wsl.exe -d <distro> --
      python3 -m photo_workflow.cartridge make-portable --os linux ...`
      against a `photo_workflow` installed inside WSL (documented
      one-time setup step — `pip install` from a path Windows-side files
      are reachable at via `/mnt/c/...`), rather than trying to freeze a
      second Linux CLI build specifically for this. Open question to
      settle during implementation, not assumed here: whether to require
      a one-time `pip install` inside WSL, or have the Windows app ship a
      small bootstrap script that does it on first use.
- [ ] The Windows half (`--os win`) runs directly in the Windows app
      process (no WSL needed) using the same `portable.py` already built.
- [ ] Real end-to-end test: build a full dual-OS drive from a Windows-style
      driver of this feature — this repo's CI has no Windows+WSL runner,
      so this is manually verified on the dev machine and the result
      written up in `docs/portable-drive-setup.md`, the same honesty
      `scripts/build_portable_cli.ps1` already has about being
      Windows-unverified from this environment.

### Task 4 — PySide6 app shell (new package, layout TBD — see below)

- [ ] Cartridge list / detail view (label, id, free space, busy state —
      reuses `volume.py`/`backup.cartridge_layout`).
- [ ] Move UI over Task 2: select photos or a whole shoot folder, pick a
      destination cartridge/folder, dry-run preview before commit.
- [ ] Backup / Restore / Verify / (Archive, once Tier 3 exists) as real
      buttons over the existing `backup.py` functions — not launching a
      terminal, unlike the Lua plugin's current guarded buttons.
- [ ] Provision + the WSL-based make-portable from Task 3.
- [ ] Progress/cancel for anything long-running (batch moves, mirrors) —
      these functions already report progress via callback (`backup.py`'s
      `progress` parameter, `portable.py`'s `progress`), so this is wiring,
      not new plumbing.

### Task 5 — Lightweight viewer

- [ ] Thumbnail grid over a shoot folder or cartridge, RAW decode via the
      existing `raw_loader.py` (rawpy), cached thumbnails so re-opening a
      folder is fast.
- [ ] Shows `photonforge.db` state per photo (stars/score, stage, genre)
      and Darktable state (tags, color label) side by side — read-only in
      v1; this is a viewer, not a second editor. No history-stack
      rendering, no edits — Darktable stays the only place that edits.
- [ ] Explicit non-goal, worth stating so it doesn't creep: this is not a
      culling app and not a Darktable replacement. If that's ever wanted,
      ADR-004 says it plainly — that would be "a new decision, not a
      revival of the retired code," and not something this plan does.

## Files at a glance

**Create:** ~~`src/photo_workflow/relocate.py`~~ DONE (same-cartridge only),
~~`tests/test_relocate.py`~~ DONE (18 tests), ~~an accurate Darktable-schema
fixture builder in `tests/conftest.py`~~ DONE (`make_real_darktable_db`,
alongside — not replacing — the existing `make_darktable_db`, which
`test_pipeline.py` still uses), the new GUI package (path TBD — see Open
Questions), `docs/cartridge-manager-guide.md` (end-user guide, once Task 4
lands), a new ADR if the WSL-orchestration design in Task 3 turns out to
need one (likely — it's a real architecture decision, not just an
implementation detail).

**Modify:** `src/photo_workflow/cartridge.py` (new subcommands),
`pyproject.toml` (new `gui` extra: PySide6; a new console-script entry
point once Task 4's package layout is decided), `CLAUDE.md` (new
component, once it exists for real — don't pre-announce it), `tests/conftest.py`.

## Open questions (deliberately not decided here)

1. **GUI package layout.** Leaning `src/cartridge_manager/` (auto-discovered
   by the existing `[tool.setuptools.packages.find] where = ["src"]`, one
   venv, one repo, satisfies "entirely separate" as a real module/package
   boundary with its own entry point) over a second top-level
   `pyproject.toml`/repo. Worth confirming before Task 4 starts, since it's
   annoying to move later.
2. **WSL bootstrap UX** (Task 3) — one-time manual `pip install` inside WSL
   vs. an automated first-run bootstrap. Affects how much Task 3 has to
   build vs. document.
3. **Whether Task 3's design is ADR-worthy.** Probably yes — "how does a
   Windows-only app orchestrate a Linux subsystem for a build step" is
   exactly the kind of non-obvious decision ADRs exist for. Write it when
   Task 3's design actually settles, not speculatively now.
4. **@systems_lead / new UN/FR.** This is a genuinely new capability
   (cartridge-level data migration with cross-database consistency
   guarantees), not a portable-drive-plan extension. Whether it needs its
   own UN is a systems_lead call — flagging here rather than deciding it.

## Highest-risk parts (with mitigations)

1. **Cross-database consistency during a move** (the whole reason Task 1
   exists as its own task, first, with no GUI). Mitigated by: UPDATE
   in-place (never delete+reinsert, so history/tags/color-labels can never
   be orphaned), copy-verify-delete ordering (source never removed before
   the copy is proven byte-identical and the DB commits are confirmed), a
   resumable intent log so a crash mid-operation is a known, recoverable
   state rather than silent corruption, and a Tier-1 snapshot taken before
   any of it starts.
2. **The deleted Tk manager's actual failure mode was an unsafe delete
   path and a second, incompatible schema** (ADR-004). This plan's
   Decision #1 (reuse `src/photo_workflow` directly, no second schema) and
   Task 1's copy-verify-delete ordering are direct responses to that
   specific history, not generic caution.
3. **WSL orchestration is new territory for this codebase** — no existing
   pattern to lean on the way Task 1 could lean on `backup.py`'s verified-
   copy pattern. Budget real research time in Task 3, the same way the
   portable-drive plan's Task 7 budgeted real time to discover the
   innoextract/Inno-Setup-version gap instead of assuming the plan text
   was correct.
4. **The real-Darktable-schema research in this plan was done once, by
   hand, in a throwaway sandbox.** The regenerable-fixture approach in
   Task 1's testing section (re-derive from a real `xvfb-run` import when
   a Darktable binary is available, rather than hand-maintained DDL that
   can silently drift from what Darktable 5.x actually creates) is the
   mitigation — copying the DDL into a fixture once and never re-checking
   it would reproduce exactly the kind of staleness this plan found in the
   *existing* fixture.
