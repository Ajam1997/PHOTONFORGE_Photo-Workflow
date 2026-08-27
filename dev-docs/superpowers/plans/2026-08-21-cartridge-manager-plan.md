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

### Task 2 — `move-photos` / `move-shoot` / `resume-move` CLI (`src/photo_workflow/cartridge.py`) — **DONE**

Thin click wrappers over Task 1, matching the existing `snapshot`/`backup`
command style (`--json` output, clean `ClickException` on failure, a
progress callback for batches). This is the CLI surface Task 4's GUI calls
into directly as a Python function — the CLI wrapper exists for headless
use and so the logic can be exercised without the GUI at all, not because
the GUI shells out to it.

> **Built as:** three new `cartridge.py` subcommands (`move-photos`,
> `move-shoot`, `resume-move`), all thin — they resolve `--cart-id` (falls
> back to the volume label via `_resolve_cart_id`, a clean `ClickException`
> if neither is given and no label exists) and the trip code (falls back to
> `derive_trip_code(dest_dir.name)`), call straight into `relocate.py`, and
> format the result via a shared `_report_relocate_result` (human or
> `--json`). Every `relocate.RelocateError` is caught and re-raised as a
> `ClickException` — no tracebacks leak to the terminal. 9 CLI tests in
> `tests/test_cartridge_move_cli.py`, `click.testing.CliRunner` throughout.
>
> Three of the nine tests were wrong on the first pass, in a pattern worth
> flagging for Task 3/4's tests too: **a test that doesn't set up the
> condition it claims to exercise passes for the wrong reason.**
> `test_move_photos_json_output` asserted `snapshot is not None` against a
> bare fixture cartridge with no `photonforge.db` — there was nothing to
> snapshot, so `snapshot` was correctly `None` and the assertion was simply
> testing the wrong thing; fixed by pre-creating a real `photonforge.db` row
> so a snapshot actually happens. `test_move_photos_group_conflict_is_a_clean_error`
> moved a single ungrouped `.jpg` (no Darktable DB in the fixture at all) and
> asserted a "collision" error that came from an unrelated pre-existing
> destination file, not from `GroupConflictError` — fixed by building a real
> RAW+JPEG group via `make_real_darktable_db`/`_darktable`, matching the
> Task 1 fixture pattern, so the group-conflict path is what's actually
> under test. `test_resume_move_completes_an_interrupted_move` asserted the
> renamed destination filename without passing `--trip-code`, so the CLI's
> `derive_trip_code(dest_dir.name)` fallback produced a different (correct,
> but unexpected-by-the-test) name — fixed by passing `--trip-code IC2`
> explicitly, matching the other rename-asserting tests. None of these were
> bugs in `cartridge.py` — all three were caught by actually running the
> tests and reading *why* they failed rather than assuming a red first run
> meant the implementation was wrong. Full suite (459 tests), ruff, and
> `check_doc_references` all clean after the fixes.

### Task 3 — WSL-orchestrated dual-OS provisioning — **DONE (code + tests; real-Windows verification still pending)**

Extends `make-portable` usage from a Windows host: the Windows half
bundles natively (innoextract has real Windows builds — see
`docs/portable-drive-setup.md`); the Linux half's AppImage extraction step
needs something that can execute a Linux ELF binary, which is what WSL is
for here.

- [x] Detect WSL2 + a usable distro (`wsl.exe --list --verbose`); a clear,
      actionable error (not a stack trace) when WSL isn't installed or has
      no distro, since this app must not assume a dev-machine-grade WSL
      setup.
- [x] Do **not** assume the distro has this repo checked out. Settled the
      open question the way the plan's default leaned: the Windows app
      calls `wsl.exe -d <distro> -- python3 -m photo_workflow.cartridge
      make-portable --os linux ...` against a `photo_workflow` installed
      inside WSL, and **requires the one-time `pip install -e .`** rather
      than auto-bootstrapping it — silently running `pip install` inside a
      user's WSL distro on their behalf is exactly the kind of
      hard-to-reverse, unrequested action CLAUDE.md's execution-care
      section says to avoid, so a missing install surfaces as an
      actionable `WslError` naming the exact command to run, not a
      background side effect.
- [x] The Windows half (`--os win`) runs directly in the Windows app
      process (no WSL needed) using the same `portable.py` already built —
      unchanged; `make_portable_cmd` only splits `--os linux` out to WSL
      when `sys.platform == "win32"`, so non-Windows behavior (including
      every existing test) is untouched.
- [ ] Real end-to-end test: build a full dual-OS drive from a Windows-style
      driver of this feature — **still not done**. This repo's CI has no
      Windows+WSL runner, and this agentic session itself runs inside a
      Linux sandbox with no Windows or WSL access either, so "manually
      verified on the dev machine" from the original plan text has not
      actually happened yet — it needs a human with a real Windows+WSL2
      machine. `docs/portable-drive-setup.md` is written to describe the
      new automated path honestly as unit-tested-but-not-yet-verified, the
      same pattern `scripts/build_portable_cli.ps1` already uses.

> **Built as:** `src/photo_workflow/wsl_bridge.py` (`detect_wsl`,
> `windows_path_to_wsl`, `run_make_portable_linux`, `WslError`) — pure
> function-based API, every `subprocess.run`/`shutil.which` call mockable,
> so all 24 `tests/test_wsl_bridge.py` tests run without any real `wsl.exe`
> present (this sandbox has none). Real `wsl.exe --list --verbose` output
> is UTF-16LE with a BOM (Windows console output through a pipe) —
> `_decode_wsl_output` handles that with a UTF-8 fallback, tested against
> actual UTF-16LE-encoded sample bytes, not just plain strings. 5 more
> tests added to `tests/test_cartridge_make_portable_cli.py` covering the
> `make_portable_cmd` split (win half in-process, linux half dispatched to
> a monkeypatched `wsl_bridge.run_make_portable_linux`, `WslError` surfacing
> as a clean `ClickException`, and the `--json` output's `linux_via_wsl`
> marker), plus a same-as-before-on-Linux regression test.
>
> **A known, accepted rough edge, not a bug:** when the Linux half is
> built purely via WSL (no `--os win` in the same run), the CLI's
> human/JSON output for that half is reconstructed by re-reading
> `.photonforge/manifest.lock.json` after the WSL call returns, rather
> than getting a real `PortableBuildResult` back from the WSL-side
> process — so fields like `plugin`/`launchers`/`models_copied` are
> reported as empty/false in that output even though the actual files
> those describe were genuinely written to the drive by the WSL-side
> `build_portable_layout` call (only the *local* process's view of them
> is incomplete). This affects reporting only, not the drive's contents.
> Full suite (487 tests), ruff, and manual review of the diff (this was
> implemented by a Haiku-class agent; reviewed line-by-line against the
> real `PortableBuildResult` field names and the real
> `MANIFEST_LOCK_NAME`/`apps/darktable-<os>` layout in `portable.py`
> before accepting) all clean.

### Task 4 — PySide6 app shell (`src/cartridge_manager/` — layout settled, see Open Questions) — **IN PROGRESS, sliced**

Being delivered as separate vertical slices (same reasoning as Tasks 1-3:
one real, fully-tested thing per PR rather than one giant GUI drop), not
as a single Task 4 PR.

- [x] **Slice 4a — DONE.** Cartridge list / detail view (label, id, free
      space, busy state — reuses `photo_workflow.backup.describe_cartridge`
      / `cartridge_busy_reason` / `cartridge_layout`, not reimplemented).
- [x] **Slice 4b — DONE.** Move UI over Task 2: select photos or a whole
      shoot folder, pick a destination cartridge/folder, dry-run preview
      required before Move is even enabled.
- [x] **Slice 4c — DONE.** Backup / Restore / Verify / (Archive, once
      Tier 3 exists) as real buttons over the existing `backup.py`
      functions — not launching a terminal, unlike the Lua plugin's
      current guarded buttons.
- [ ] Provision + the WSL-based make-portable from Task 3.
- [x] **Progress — DONE (as part of slice 4b).** `src/cartridge_manager/workers.py`:
      a `QThread` wrapper (`Worker`/`WorkerSignals`) that runs one
      `photo_workflow` call off the GUI thread and normalizes whatever
      shape its `progress` callback receives into one `(index, total,
      label)` Qt signal — genuinely wired to `relocate.move_photos`/
      `move_shoot_folder`'s existing `progress` parameter, exactly the
      "wiring, not new plumbing" the plan predicted. **Cancel is
      deliberately NOT built** — `relocate.py` has no cooperative-
      cancellation hook, and hard-killing a `QThread` mid-copy
      (`terminate()`) can leave a partial file or an open sqlite
      connection in an inconsistent state, which conflicts directly with
      this plan's own "build in safety checks to prevent data corruption"
      mandate. Progress display works today; true cancel needs a
      cooperative-cancellation hook added to `relocate.py` itself first —
      that's core-safety-module work deserving Task 1's level of rigor
      (tests, careful review), not something to bolt on inside a GUI
      slice. Tracked here as still open, not silently dropped.

> **Slice 4a built as:** `src/cartridge_manager/` — `cartridges.py`
> (`CartridgeInfo` dataclass + `describe(root)`, pure Python, no Qt import,
> composes existing `backup.py` functions rather than reimplementing them),
> `cartridge_list_widget.py` (`CartridgeListWidget(QWidget)`: table + detail
> panel + Add/Remove/Refresh, `QSettings`-backed persistence of cartridge
> roots, dependency-injectable settings object so tests never touch a real
> user's settings file), `main_window.py`, `app.py` (the `cartridge-manager`
> console-script entry point — `QApplication` created only inside `main()`,
> never at import time, so tests can own their own `QApplication`/`qtbot`).
> 11 new tests (5 backend, no PySide6 import at all so they always run even
> without the `gui` extra; 6 widget tests via `pytest-qt`'s `qtbot`) —
> genuinely instantiate real widgets and assert on real table/label state,
> not mocked. Tested headlessly via `QT_QPA_PLATFORM=offscreen` (works in
> this sandbox once `libegl1` is installed;
> `tests/conftest.py` sets it via `os.environ.setdefault` so it's automatic
> for any contributor without a real display) and wired into CI's
> `tests.yml` (`gui` extra installed, `libegl1` apt-installed, env var set
> for the pytest step). Manually smoke-tested the actual `cartridge-manager`
> console script end-to-end (launches, shows the right window title and
> central widget, quits cleanly) — not just unit tests in isolation.
> Implementation drafted by a Haiku-class agent per current cost guidance,
> reviewed line-by-line against `backup.py`'s real function signatures and
> `cartridge_layout`'s real dict keys before accepting, then independently
> re-verified (full suite, ruff, doc-reference check, and the console-script
> smoke test) before commit. Full suite: 498 passed, 1 skipped, 2
> deselected.

> **Slice 4b built as:** `src/cartridge_manager/workers.py`
> (`Worker`/`WorkerSignals` — see the "Progress" checklist item above for
> the design) and `src/cartridge_manager/move_view.py` (`MoveView(QWidget)`:
> photos-vs-shoot-folder mode toggle, source/destination pickers with
> test-friendly setters bypassing the file dialogs, `Ungroup`/`Force`
> checkboxes at parity with the CLI, a preview table, and a **safety
> property enforced in code**: the Move button is disabled until a
> successful dry-run preview has just run, and disabled again the instant
> source/destination/mode changes — you cannot move something you have not
> just previewed). **No `QMessageBox` anywhere** — all status/error text
> goes to an inline `status_label` instead, both because a modal `.exec()`
> would hang this project's headless (`QT_QPA_PLATFORM=offscreen`) test
> environment forever, and because it keeps every error path directly
> assertable in a test rather than needing dialog-interaction machinery.
> Wired into `main_window.py` as a `QTabWidget` ("Cartridges" / "Move").
> Along the way, factored the CLI's `_resolve_cart_id` helper into a
> reusable `photo_workflow.volume.resolve_cart_id(dest, cart_id) ->
> str` (raises `ValueError`, no click dependency) so the GUI and the CLI
> share one implementation instead of the GUI reimplementing the
> auto-detect-from-volume-label fallback — `cartridge.py`'s CLI wrapper now
> just catches `ValueError` and re-raises as `ClickException`, identical
> user-facing behavior, verified against the existing CLI test suite (no
> regressions) plus 4 new direct unit tests for `resolve_cart_id` itself.
> 13 new tests (3 for the worker's signal normalization and exception
> handling, 10 for the Move view against real fixtures — including a real
> RAW+JPEG Darktable group to prove the `GroupConflictError`/`ungroup`
> safety path actually works end-to-end through the GUI, not mocked).
> Manually re-verified one test the agent wrote too weakly before
> accepting: the original progress-bar test only checked that the move
> finished, not that the bar's value ever actually moved — rewrote it to
> record every `progress_bar.valueChanged` emission and assert it reaches
> the real photo count, which would have caught a broken progress wire-up
> that the original version could not. Implementation drafted by a
> Haiku-class agent per current cost guidance, reviewed line-by-line
> (worker thread-affinity pattern, `move_photos`/`move_shoot_folder`
> argument wiring against `relocate.py`'s real signatures) before
> accepting, then independently re-verified (full suite: 515 passed, 1
> skipped; ruff; doc-reference check; a manual smoke test launching the
> full two-tab app shell headlessly) before commit.

> **Slice 4c built as:** `src/cartridge_manager/backup_view.py`
> (`BackupView(QWidget)`: four sections — Snapshot, Backup, Verify,
> Restore — each a thin wrapper over one `backup.py` function
> (`snapshot_databases`, `mirror_cartridge`, `verify_snapshot`,
> `restore_snapshot`), matching the CLI's `snapshot`/`backup`/
> `verify-backup`/`restore-backup` commands one-to-one, including the
> "newest snapshot under `--dest`, scoped to `--root`" fallback Verify
> uses when no explicit snapshot path is given. Snapshot runs synchronously
> on the GUI thread (it's a couple of sqlite VACUUM-copies, not a
> whole-cartridge mirror); Backup/Verify/Restore go through `Worker`, and
> only one operation can run at a time (a shared `is_running()` guard —
> you can't mirror and restore the same drive simultaneously). 17 new
> tests, all against real filesystem/sqlite state — including a real
> busy-cartridge refusal (a live-PID `.pid` lock file, not mocked) and a
> real corrupted-mirror detection (a byte actually flipped on disk inside
> a real Tier-2 mirror, then re-verified for real).
>
> **A real bug found and fixed during review, not by the agent:**
> `restore_snapshot` has no `progress` parameter at all (unlike the other
> three functions), and the original `Worker` unconditionally passed
> `progress=`, which would have raised `TypeError` the first time Restore
> was ever clicked. Fixed in `workers.py` itself (inspects the wrapped
> function's signature and only forwards `progress` if it's actually
> declared) before delegating this slice, so the agent built against a
> `Worker` that already handled it — covered by a new
> `test_worker_does_not_pass_progress_to_a_function_without_it` test.
>
> **A second, more serious bug — and three attempts before it was actually
> fixed, not one.** Found only by running the full suite repeatedly, never
> by this slice's own tests in isolation: a real PySide6 crash —
> `Fatal Python error: Aborted`, and on later attempts a segfault —
> reproduced first in 3 `pytest -m "not slow"` runs, "QThread: Destroyed
> while thread is still running", the same fatal, uncatchable-in-Python
> abort described below. This bug was already present in the merged
> Task 4b code, not something this slice introduced — it just took enough
> `QThread` churn across a larger test run to hit the race window.
>
> *Attempt 1:* theorized the cause was `_on_finished`/`_on_failed` dropping
> the last Python reference to a `Worker` (`self._worker = None`) without
> confirming the OS thread had actually joined. Fixed by calling
> `self._worker.wait()` first, documented as a caller contract in
> `Worker`'s docstring, covered by a `test_worker_is_joined_before_being_released`
> regression test that spies on `Worker.wait`, and "verified" by re-running
> the full suite 5 times clean — **which was not enough runs to catch that
> this fix was incomplete.** Pushed anyway; CI caught it on the very next
> run, crashing inside `test_worker_does_not_pass_progress_to_a_function_without_it`
> — a test that creates a bare `Worker` directly, not through a view's
> `_on_finished` at all, proving the bug wasn't only reachable through the
> code path the first fix addressed.
>
> *Attempt 2:* `Worker.signals` holds a strong reference to the connected
> bound slot (`self._on_finished`), whose `self` is the view, which holds
> `self._worker` back — a genuine reference cycle, which Python's cyclic
> GC (not simple refcounting) collects at an unpredictable later time,
> explaining why the crash's stack trace kept showing an unrelated later
> test as the "current" thread. Fixed by explicitly disconnecting the
> worker's signals before dropping the reference. This surfaced a second,
> smaller bug immediately in local testing (not CI): PySide6's
> `QObject.disconnect()` has no zero-argument "disconnect everything" form
> — that's PyQt-only — so the first version of this fix raised `TypeError`
> inside every `_on_finished`/`_on_failed` call, caught locally before
> ever pushing. Fixed to disconnect each bound signal individually. Stress
> ran 40 iterations of the isolated GUI test files: still crashed twice.
>
> *Attempt 3 (the one that actually held):* switched from relying on
> Python object lifetime at all to Qt's own: `Worker.__init__` now connects
> `QThread`'s *native* `finished` signal (distinct from the custom
> `WorkerSignals.finished` used for the wrapped call's result — the native
> one is guaranteed by Qt to fire only once the OS thread has truly
> terminated) to `self.deleteLater()`, so Qt's own event loop deletes the
> underlying C++ object at a Qt-determined safe point, independent of
> Python refcounting/GC entirely — the standard, most-cited fix for this
> class of bug. Even this needed one more piece: a queued `deleteLater()`
> call left unprocessed can still fire much later, inside a *completely
> unrelated* test's own event loop — which is exactly the "stale event"
> pattern attempt 2's stack traces kept showing. Added `Worker.settle()`
> (`wait()` plus two explicit `QCoreApplication.processEvents()` calls) as
> the one method every caller — views and bare-`Worker` tests alike — now
> calls instead of bare `wait()`, forcing that teardown to happen
> immediately rather than being deferred to an unpredictable moment. Only
> *this* attempt was actually stress-tested at a scale that means
> something: 100 consecutive full-suite runs (535 passed each time), zero
> failures — not 3, not 5. The first two "fixes" also looked clean at 3-5
> runs; that was the actual lesson here, not the specific Qt mechanism.
>
> Implementation drafted by a Haiku-class agent per current cost guidance;
> the `Worker` progress-kwarg fix and the QThread-lifecycle fix (plus their
> tests) were both done directly, not delegated — the first because it was
> a prerequisite the agent needed to build on, the second because it's a
> genuine crash bug in shared thread-safety plumbing found during
> verification, exactly the kind of thing "trust but verify" exists to
> catch rather than something to hand back for a re-delegation round trip.

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
`test_pipeline.py` still uses), ~~`src/photo_workflow/wsl_bridge.py`~~ DONE
(see the Task 3 annotation above), ~~`tests/test_wsl_bridge.py`~~ DONE (24
tests), ~~`src/cartridge_manager/`~~ slices 4a+4b+4c DONE (`cartridges.py`,
`cartridge_list_widget.py`, `workers.py`, `move_view.py`, `backup_view.py`,
`main_window.py`, `app.py` — see the Task 4 annotations above; Provision
still to come as a later slice), ~~`tests/test_cartridge_manager_cartridges.py`~~
DONE (5 tests), ~~`tests/test_cartridge_manager_widget.py`~~ DONE (6
tests), ~~`tests/test_cartridge_manager_workers.py`~~ DONE (5 tests —
including `test_dropping_a_worker_right_after_finished_does_not_crash`, a
25-iteration stress test for the QThread-lifecycle bug documented above),
~~`tests/test_cartridge_manager_move_view.py`~~ DONE (11 tests),
~~`tests/test_cartridge_manager_backup_view.py`~~ DONE (17 tests),
`docs/cartridge-manager-guide.md` (end-user guide, once Task 4 is further
along — a three-view app still doesn't need one yet), a new ADR if the
WSL-orchestration design in Task 3 turns out to need one on reflection
after real-Windows verification — not written yet; the design is
documented in the Task 3 annotation and `docs/portable-drive-setup.md`
instead, and can graduate to an ADR later if it proves durable.

**Modify:** ~~`src/photo_workflow/cartridge.py` (new subcommands)~~ DONE
(`move-photos`/`move-shoot`/`resume-move` — Task 2; WSL dispatch wiring in
`make_portable_cmd` — Task 3; `_resolve_cart_id` now delegates to
`volume.resolve_cart_id` — Task 4b), ~~`src/photo_workflow/volume.py`~~
DONE (new `resolve_cart_id(dest, cart_id)`, shared by the CLI and
`cartridge_manager`; 4 new direct tests in `tests/test_volume.py`),
~~`tests/test_cartridge_move_cli.py`~~ DONE
(9 tests), ~~`tests/test_cartridge_make_portable_cli.py`~~ DONE (5 new WSL
tests), ~~`docs/portable-drive-setup.md`~~ DONE (Task 3's "From Windows
only" section), ~~`pyproject.toml`~~ DONE (`gui` extra: `PySide6>=6.6`;
`pytest-qt` in `dev`; `cartridge-manager` console-script entry point),
~~`CLAUDE.md`~~ DONE (new `src/cartridge_manager/` layout entry; also
caught and fixed `relocate.py`/`wsl_bridge.py` missing from the
`src/photo_workflow/` module list and the stale "24 modules" count — now
26), ~~`tests/conftest.py`~~ DONE (`QT_QPA_PLATFORM=offscreen` default),
~~`.github/workflows/tests.yml`~~ DONE (`gui` extra + `libegl1` install for
headless Qt tests).

## Open questions (deliberately not decided here)

1. ~~**GUI package layout.**~~ **Settled: `src/cartridge_manager/`** —
   auto-discovered by the existing `[tool.setuptools.packages.find] where =
   ["src"]`, its own `gui` optional-dependency extra (`PySide6>=6.6`) and
   its own `cartridge-manager` console-script entry point in
   `pyproject.toml`. Went with the plan's own leaning rather than a second
   top-level repo — one venv, one repo, and the package boundary alone
   already satisfies "entirely separate" (it imports `photo_workflow`,
   `photo_workflow` never imports it). Tested headlessly via
   `QT_QPA_PLATFORM=offscreen` (works in this sandbox once `libegl1` is
   installed) with `pytest-qt`, wired into CI's `tests.yml`.
2. ~~**WSL bootstrap UX** (Task 3)~~ **Settled — see the Task 3 annotation
   above:** one-time manual `pip install -e .` inside WSL, not an automated
   bootstrap.
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
