# Self-Contained Portable Drive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the PHOTON cartridge into a fully self-contained portable app — a drive that, plugged into **any Windows *or* Linux machine**, runs the whole workflow (Darktable **+** the `photo-workflow` CLI **+** ONNX models) with **nothing installed on the host**. Darktable is auto-downloaded at provisioning time (network allowed then; runtime stays 100% offline per NFR-2.1).

## Context

Today PHOTONForge assumes Darktable is **installed on the host** (apt on the Yoga, or a Docker/X11 build, or a Windows portable install the user maintains by hand). The Lua plugin loads *inside* a running Darktable and reads its catalog from `dt.configuration.config_dir/library.db` (host `~/.config/darktable`). The `photo-workflow` CLI + ONNX models are a host-installed venv. Nothing rides the drive except the pipeline's own state (`photonforge.db`, XMP sidecars, corpus).

**Why it's tractable:** the Python side never launches a Darktable binary — it only reads/writes `library.db`/`data.db` + XMP given a path (`src/photo_workflow/darktable_bridge.py`). And launching Darktable with `--configdir <DRIVE>/dt-config` makes `dt.configuration.config_dir` resolve to the drive, so `runner.lua`'s `config_dir/library.db` lines (`lua/photonforge/runner.lua:132,213`) already land on the drive with **zero Lua change**. That is the keystone.

## Dominant constraint: the filesystem must be exFAT

Windows cannot read `ext4`, which `provision.py` currently formats (`mkfs.ext4`). For **one partition, one shared `library.db`/`photonforge.db`, readable by both OSes with no host install**, the drive must be a single GPT **exFAT** partition. (A dual ext4+exFAT drive is rejected: it cannot share one library between the two OSes.) Consequences to design around:
- No POSIX exec bit / symlinks → launcher does best-effort `chmod +x`, never relies on symlinks.
- SQLite WAL on exFAT is unvalidated against **KPM-1.4** (zero corruption / 50 safe-eject cycles, validated on ext4). Re-run the soak; if WAL is flaky on exFAT, fall back to `journal_mode=DELETE` for `photonforge.db` and Darktable's `library.db`.
- Keep ext4 available behind a `--fs ext4` flag for Linux-only drives.

## Drive layout (canonical — reconciles the repo's Layout A vs B)

Canonicalize on **Layout B** (drive-root state, which `runner.lua` already uses) and relocate Darktable's own config/library into `<DRIVE>/dt-config/`. Retire Layout A (`<mount>/<id>/darktable/library.db` + `photos/`), which lives only in the unused `init_cartridge` and one BDD doc line.

```
<DRIVE>/                             # drive root = runner.lua get_drive_root()
├── PHOTONForge.bat / .ps1           # Windows launcher (double-click)
├── PHOTONForge.sh                   # Linux launcher
├── apps/darktable-win/              # portable Windows Darktable (zip / PortableApps tree)
├── apps/darktable-linux/            # AppImage + pre-extracted squashfs-root/AppRun (no runtime FUSE)
├── runtime/win/photo-workflow.exe   # frozen CLI (PyInstaller onedir, + _internal/)
├── runtime/linux/photo-workflow     # frozen CLI (onedir)
├── models/                          # EXTERNAL onnx models (florence2_int8/, scoring dirs, genre_prototypes.npy)
├── dt-config/                       # Darktable --configdir
│   ├── darktablerc  luarc  library.db  data.db
│   └── lua/photonforge/*.lua + .css
├── .photonforge/manifest.lock.json  # provenance: resolved versions, sha256, git SHA, timestamp
├── photonforge.db  training_weights.db  genre_labels.jsonl  secondary_feedback.jsonl  # runtime-created
└── ICELAND/ ...                     # shoot folders at root
```

## Launchers (drive-relative, never hard-code a mount/drive letter)

- **`PHOTONForge.ps1`** — `$root = $PSScriptRoot`; resolve the Darktable exe from the manifest's recorded relpath under `apps/darktable-win/`; launch `& $dt --configdir "$root\dt-config" --library "$root\dt-config\library.db"`. Do **not** set `cli_path`/`models_path` (self-location handles it). `PHOTONForge.bat` = one line `powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0PHOTONForge.ps1"`.
- **`PHOTONForge.sh`** — `ROOT="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"`; best-effort `chmod +x`; **prefer** `exec "$ROOT/apps/darktable-linux/squashfs-root/AppRun" --configdir "$ROOT/dt-config" --library "$ROOT/dt-config/library.db"` (pre-extracted → no runtime FUSE); fall back to `*.AppImage --appimage-extract-and-run ...` if squashfs is absent.
- Written from templates (`deploy/portable/*.tmpl`) containing only relative paths; a test asserts no absolute host path leaks in.

## Tasks

### Task 1 — Lua self-location (`lua/photonforge/runner.lua`, `config.lua`) — **DONE**

> Landed 2026-08-19. `cartridge_cli()` got the same treatment (it did not exist
> when this task was written), so `photo-cartridge` also resolves from
> `<root>/runtime/` on a portable drive. Covered by
> `tests/lua/test_runner_cartridge.lua`, which builds a real drive tree and
> asserts resolution, precedence of an explicit preference, unchanged
> host-install behaviour, and that a broken `darktable.configuration` cannot
> make `preview_cmd` throw.

Chosen over launcher-rewrite: Darktable rewrites `darktablerc` on clean exit, so baking absolute paths in would be clobbered. Self-location recomputes paths every run from `dt.configuration.config_dir` (the *current* real mount), so drive-letter/mount churn is irrelevant. Fully backward-compatible (only fires when the pref is blank AND the sibling dir exists). Keep all new helpers `pcall`-safe so `preview_cmd` never throws.
- [x] Add `config_parent()` — strip the last component of `dt.configuration.config_dir` (`<DRIVE>/dt-config`) → drive root (Win `\`, Linux `/` variants).
- [x] Modify `cli()` (lines 25-29): between the `cli_path`-set branch and the bare-name fallback, probe `<root>/runtime/{win/photo-workflow.exe | linux/photo-workflow}`; return it if present, else fall through to `return "photo-workflow"` (unchanged legacy).
- [x] Add `models_dir()` — return `config.read("models_path")` if set; else probe `<root>/models/florence2_int8` and return `<root>/models`; else `""` (CLI auto-detects). Replace the 5 inline `config.read("models_path")` reads (score ~104, name ~122, refresh-review ~150, recalibrate ~171, rescore ~198) with `models_dir()`; the existing `if models ~= "" then --model-dir` blocks stay.
- [x] `config.lua`: help-text only on `cli_path`/`models_path` (lines 18-19) — note blank auto-locates `../runtime` and `../models` relative to the Darktable config dir on a portable drive. No schema change.

### Task 2 — Builder core (new `src/photo_workflow/portable.py`) — **DONE**

> Landed 2026-08-20. Manifest load/verify, a content-addressed sha256-verified
> downloader (`download_verified`, cache keyed by the *expected* hash so a
> corrupt or interrupted prior run is never silently trusted — mismatches
> raise `DownloadError` and the bad file is discarded, no TOFU), an extractor
> (`extract_archive`: `zip` is real via stdlib `zipfile`; `appimage` and
> `innosetup` dispatch to `--appimage-extract`/`innoextract` and are
> dispatch-tested with `subprocess.run` mocked, since neither tool exists in
> this environment), `_deploy_plugin` (idempotent copy + luarc require-line,
> mirroring `scripts/deploy_lua.ps1`'s MD5-compare-before-overwrite logic
> cross-platform — verified idempotent across two real runs in
> `tests/test_portable.py`), `write_baseline_darktablerc` (leaves
> `cli_path`/`cartridge_path`/`models_path` blank — the deliberate opposite of
> `deploy_lua.ps1`'s host-venv auto-bake, since a portable drive's mount point
> changes between machines and only self-location survives that), launcher
> templating (`render_launchers`, copying `deploy/portable/*.tmpl` verbatim
> plus a best-effort exec bit on the `.sh`), and `build_portable_layout`, the
> orchestrator Task 3 calls.
>
> **The manifest is optional by design**, not a hard dependency on Task 7:
> `config/portable-manifest.yml` does not exist yet, so `build_portable_layout`
> accepts `manifest: PortableManifest | None` and skips only the
> Darktable-download step for an OS with no manifest target, rather than
> blocking runtime/models/plugin assembly on a file that isn't written yet.
> Verified end-to-end against a real zip archive (build one in the test,
> download it via an injected `fetch`, verify the sha256, extract it, confirm
> the binary lands at the manifest's `exe_relpath`) — not just schema-shape
> assertions.
>
> `PortableManifest`'s YAML schema (`win`/`linux` → `version`, `url`,
> `sha256`, `archive_type`, `exe_relpath`|`apprun_relpath`) is defined here
> since nothing else has defined it yet; Task 7 must produce a
> `config/portable-manifest.yml` conforming to this shape, not invent a new one.

### Task 3 — `make-portable` subcommand (`src/photo_workflow/cartridge.py`) — **DONE**

> Landed 2026-08-20 alongside Task 2. `photo-cartridge make-portable <drive>`
> is a thin click wrapper over `portable.build_portable_layout`: it verifies
> the volume label starts with `PHOTON` (and optionally matches `--id`) via
> `volume.py::get_volume_label`/`extract_cartridge_id` before touching the
> drive, loads `--manifest` if given, and reports either human-readable or
> `--json` output. `init`'s Layout-A scaffold is kept working but now prints a
> stderr deprecation notice pointing at `provision` + `make-portable`.
>
> One deliberate deviation from the one-line spec below: `--cache` has no
> default and is validated at build time (`ValueError` → clean
> `ClickException`) rather than required unconditionally, since a manifest-less
> build (the common case until Task 7 lands) has nothing to cache.
>
> **Addendum 2026-08-21 — launcher visibility, from a real PR review thread**
> (#151, "How does the portable build behave? does it auto launch darktable
> when the drive gets plugged in?"). Researched rather than assumed: Windows
> killed `autorun.inf`'s `open=`/`shellexecute=` for USB drives in Windows
> 7+ specifically to stop USB-malware, and that is still fully in effect —
> there is no way to make Windows prompt to run an arbitrary program off a
> drive anymore. GNOME/Nautilus still has a real equivalent
> (`nautilus-autorun-software`), but it is GNOME-only and gated by a setting
> some distros disable, so building it would be asymmetric across the two
> target OSes. Landed the zero-controversy alternative instead, all of it
> execution-free: the two launchers are now written as `!START_PHOTONForge.bat`
> / `!START_PHOTONForge.sh` (the `!` sorts before everything else at the
> drive root in every file manager's default sort — `PHOTONForge.ps1` keeps
> its old name since it's invoked by the `.bat`, not double-clicked
> directly), a `!README.txt` pointing at both, and a Windows-only
> `autorun.inf` carrying **only** `icon=`/`label=` (never `open=`/
> `shellexecute=` — verified by a test that greps the generated file for
> both directives and fails if either is present) pointing at a small
> multi-resolution `.ico` generated at build time with Pillow (already a
> core dependency, so this adds nothing new). A real bug surfaced writing
> the icon generator's test: Pillow's ICO writer filters every requested
> size against the *base* image passed to `.save()`, discarding anything
> larger, so passing the smallest frame as the base silently produced a
> 16x16-only .ico with every other size dropped — caught because the test
> actually decodes the file with Pillow and checks for (256, 256), not just
> that a file exists.

Runs on the **provisioning machine** (unfrozen `photo-cartridge` entry), assembles files onto an already-mounted drive (unelevated; partition/format stays in `provision.py`). Thin click wrapper over `portable.py`.
```
photo-cartridge make-portable <drive>
  --os {win,linux} (repeatable, default both)  --manifest config/portable-manifest.yml
  --models-src models  --cli-src runtime  --cache <dir>  --offline
```
Creates: `dt-config/` (plugin + luarc + baseline darktablerc with `cli_path`/`models_path` **blank**; does NOT seed `library.db`), `apps/darktable-{win,linux}/` (download+verify+extract), `runtime/{win,linux}/` (copy prebuilt frozen CLIs), `models/` (copytree with progress), launchers, `.photonforge/manifest.lock.json`. Reuse `volume.py::get_volume_label`/`extract_cartridge_id` to verify the `PHOTON-XXX` label. Deprecate `init_cartridge`'s Layout-A scaffold.

### Task 4 — exFAT provisioning (`src/photo_workflow/provision.py`) — **DONE**

> Landed 2026-08-19. `provision_cartridge(..., fs="exfat")` is the default;
> `fs="ext4"` remains for Linux-only drives. Three things the one-line spec did
> not anticipate:
>
> - **The partition type matters, not just the filesystem.** parted's fs-type
>   argument sets the GPT partition GUID, and Windows will not assign a drive
>   letter to a partition typed as Linux filesystem data. exFAT therefore passes
>   `ntfs` to parted (Microsoft Basic Data) — which reads wrong and is correct.
> - **exFAT caps volume labels at 11 characters.** `PHOTON-001` fits with one to
>   spare, but a longer label is now refused up front rather than failing at
>   `mkfs` after the partition table has already been rewritten.
> - **`mkfs.exfat` needs its own sudoers grant**, and must come from
>   **exfatprogs** rather than the older exfat-utils — the two take different
>   flags for the volume label (`-L` vs `-n`).
>
> The `mount_point` derivation was not just stale but wrong: it returned a
> hardcoded `/mnt/photon_ssd/<id>` that nothing ever mounted. It now asks the
> kernel and falls back to the udisks2 convention `/media/$USER/<LABEL>`.

Default `mkfs.exfat` (keep `--fs ext4`); update the `mount_point` derivation. Note: exFAT tools (`exfatprogs`/`mkfs.exfat`) must be present on the provisioning host.

### Task 4a — Cartridge backup/archive — PREREQUISITE for 4b — **moved out of this plan**

> **Moved 2026-08-17 (PR #144):** this task now lives in
> [`2026-08-17-cartridge-backup-archive-plan.md`](2026-08-17-cartridge-backup-archive-plan.md),
> Tasks 1–4. Implement it from there, not from the summary below.

The requirement is unchanged — a general backup/archive feature lands BEFORE any
migration runs, per operator direction (PR #141 review), and migration consumes it
instead of ad-hoc staging. Two things changed when it was reconciled with the
(then-unnoticed) 2026-07-11 backup plan, which proposed a different mechanism for the
same capability:

- **Home:** `src/photo_workflow/backup.py`, not `portable.py`. Backup is not a
  portable-drive concern; `portable.py` imports it.
- **Mechanism:** three tiers rather than one. Tier 1 is a `VACUUM INTO` catalog
  snapshot, **Tier 2 is the verified plain-tree mirror this task specified** (and the
  only tier `migrate-fs` may consume), Tier 3 is an optional restic archive for
  dedup/encryption/offsite. Everything this task asked for — dated snapshots,
  `snapshot-manifest.json`, `--state-only`, incremental copies, `verify-backup`,
  busy-guard, `--keep` retention, tests — is in Tier 2.

Two substantive corrections came out of the merge, both affecting this plan:

- **Hardlink incrementals do not work on exFAT** — the filesystem Task 4 makes the
  default. Link-dest is best-effort with a probe and a copy fallback; see the
  reconciled plan's "Two conflicts the merge forced into the open".
- **`models/` is included** in Tier-2 mirrors by default, so `migrate-fs` does not
  force a re-provision after every migration.

**Status gate:** Tasks 1–4 of the reconciled plan must be merged before 4b runs.

### Task 4b — Migration of existing ext4 cartridges (`photo-cartridge migrate-fs`) — **NOT NEEDED (2026-08-19)**

> The premise does not hold for the current fleet. `Get-Volume` on the only
> cartridge in existence (PHOTON-001, 4 TB) reports **exFAT** — it is already
> on the target filesystem, so there is nothing to migrate. Task 4a was built
> as a prerequisite for this and stands on its own merits regardless: it closed
> issue #131, an independent durability gap.
>
> Do NOT implement this unless an ext4 cartridge actually turns up. If one
> does, the spec below is still correct and its prerequisite is now satisfied.
> **Task 4 (exFAT provisioning) is still required either way** — `provision.py`
> would format the *next* cartridge as ext4 and recreate the problem.

**Requires a fresh verified Tier-2 mirror — `migrate-fs` refuses to run without one (`--backup <snapshot>` pointing at a snapshot whose manifest verifies and is newer than the cartridge's last write).** Reformatting is destructive, so migration is copy-out → reformat → copy-back; the copy-out step reuses the Tier-2 code path. Import `assert_cartridge_idle`, `mirror_cartridge`, `verify_snapshot`, and `snapshot_is_fresh` from `backup.py` — the gate is `verify_snapshot(snap) == [] and snapshot_is_fresh(snap, root)`; write no copy or checksum logic here. Note that Tier 2 mirrors are plain trees precisely so this step needs nothing installed beyond Python. All
cartridge state is plain files (shoot folders + XMP, `photonforge.db`,
`training_weights.db`, corpus JSONL, `dt-config/`) — nothing depends on ext4 semantics
(DBs are opened by path; POSIX perms are irrelevant to the pipeline). Keep the same
`PHOTON-XXX` label so `extract_cartridge_id` and existing naming continue unchanged.
- [ ] `photo-cartridge migrate-fs <device> --staging <dir>` (thin click wrapper, logic in
      `portable.py`): (1) refuse if the cartridge is mounted busy / mid-run (check
      `.pid` files + open WAL); (2) `rsync -a` cartridge → staging, then a `rsync -c`
      checksum verify pass; (3) reprovision the device via the Task-4 exFAT path with
      the **same label**; (4) `rsync -a` staging → cartridge; (5) `PRAGMA
      integrity_check` on `photonforge.db` (and `dt-config/library.db` if present) +
      compare file count/bytes vs staging; (6) leave staging in place until the user
      confirms (`--keep-staging` default on).
- [ ] Requires ≥1× cartridge-used-bytes free at `--staging`; error out up front if not
      (`shutil.disk_usage`). Cartridge-to-cartridge variant: point `--staging` at a
      second mounted PHOTON drive.
- [ ] Document in `docs/portable-drive-setup.md`: migrate one cartridge, run the KPM-1.4
      eject soak on it, then batch the rest.

### Task 5 — Frozen-aware model root (`src/photo_workflow/pipeline.py` + `naming.py`) — **DONE**

> Landed 2026-08-20. `_default_model_root()` in both modules: unfrozen
> (editable/dev install) climbs from `Path(__file__)` to the repo root, same
> as it always did; frozen (`getattr(sys, "frozen", False)`) climbs three
> parents from `Path(sys.executable)` instead, since a PyInstaller onedir
> freeze has no `pipeline.py`/`naming.py` on disk to climb from — the drive
> layout puts the executable at `<DRIVE>/runtime/<os>/photo-workflow(.exe)`,
> and three parents up from there lands at `<DRIVE>`, whose `models/` sibling
> is what's wanted.
>
> **Four call sites in `pipeline.py`, not three** — the plan's line numbers
> (score/name/refresh-review) missed `training recalibrate`'s fallback
> (originally ~1163), which has the identical `Path(__file__)...` bug. Fixed
> alongside the other three; a regression test AST-parses `pipeline.py` and
> asserts exactly 4 calls to `_default_model_root()`.
>
> **`naming.py`'s two sites were function-signature defaults, not
> `if is None` guards** — `warm_sessions(model_dir: Path = Path("models/florence2_int8"))`
> and `generate_name(..., model_dir: Path = Path("models/florence2_int8"))`.
> A literal relative `Path` default is resolved against the process's CWD
> the first time `.resolve()` runs on it, which is exactly the frozen bug in
> a different shape: CWD when Darktable subprocess-launches the frozen CLI is
> unpredictable, not necessarily the drive root. Changed both defaults to
> `None` with an `if model_dir is None: model_dir = _default_model_root() / "florence2_int8"`
> guard, matching `pipeline.py`'s pattern. All existing callers already
> passed `model_dir` explicitly, so this is not a behavior change for any
> current call site — only the never-actually-exercised default path changes.
>
> `naming.py` keeps its own 3-line copy of `_default_model_root()` rather than
> importing `pipeline.py`'s — `naming.py` has no other dependency on
> `pipeline.py` today, and duplicating three lines beats introducing one.
>
> Belt-and-suspenders unchanged: `runner.lua` always passes `--model-dir`
> explicitly regardless, so this fallback only matters for direct CLI /
> script use without that flag. Tests: `tests/test_frozen_model_root.py` (7
> tests, both modules' frozen/unfrozen resolution plus the call-site count
> guard).

### Task 6 — Build scripts (`scripts/build_portable_cli.{sh,ps1}` + `scripts/photonforge.spec`) — **DONE (Linux verified; Windows unverified)**

> Landed 2026-08-19. This was the highest-risk item in the whole plan --
> "PyInstaller freeze of onnxruntime/rawpy/tokenizers — Windows is
> unverified" -- and it was taken deliberately out of build order, ahead of
> Tasks 2/3, specifically to find out early whether the freeze works at all
> before building the drive-assembly machinery around it.
>
> **Actually verified on Linux, not just planned:** a real onedir build was
> run from a throwaway venv with a non-editable install, and a smoke-test
> executable exercised every collected package's native extension at
> runtime (constructing an onnxruntime session, decoding a raw file with
> rawpy, cv2 colour conversion, building a tokenizers Tokenizer, etc.) --
> not just confirming PyInstaller's static import-graph analysis found them.
> All eight passed. `tests/test_portable_build.py::test_real_freeze_build_end_to_end`
> (marked `slow`) automates this: fresh venv, real freeze, `--help` on both
> executables, and a relocation check (copy the build tree elsewhere and
> confirm it still runs -- the mount point changing between machines is the
> whole premise of a portable drive).
>
> **Two entry points, one shared runtime.** The plan's own drive-layout
> diagram only shows `photo-workflow`, but Task 1 (landed first) already
> probes for `photo-cartridge` too. Both are frozen from one spec and
> collected into a single output directory via one `COLLECT()` call spanning
> both `Analysis` objects, so ~450 MB of shared native libraries (onnxruntime,
> opencv) is written once rather than duplicated per executable -- `COLLECT`
> de-dupes by destination path, so this needs no `MERGE()`.
>
> **A real bug, not a hypothetical one:** giving `PYZ()` an explicit `name=`
> (to keep the two pure-Python archives from colliding) makes PyInstaller
> write that file relative to the **current directory**, bypassing
> `--workpath` entirely -- caught by running the build twice from different
> CWDs and finding a stray `.pyz` land at the repo root each time. Fixed by
> leaving PyInstaller's automatic naming alone (already collision-free
> across `Analysis` objects); pinned with a regression test that parses the
> spec's AST and asserts no `PYZ` call carries a `name` keyword.
>
> **`scripts/photonforge.spec`'s package list is Linux-confirmed working**,
> not merely copied from the plan text: `scipy` turned out to have zero
> direct callers anywhere in `src/photo_workflow/` (only
> `scripts/train_aesthetic_head.py`, a provisioning-time-only script that is
> never frozen) -- kept in `--collect-all` per the plan rather than removed,
> since a subtle transitive need is harder to prove absent than to keep
> collecting defensively, and the disk cost is irrelevant on a multi-TB
> cartridge.
>
> **What genuinely remains unverified: Windows.** There is no Windows
> machine in the environment that built this. `scripts/build_portable_cli.ps1`
> mirrors the bash script's logic (fresh venv, non-editable install of the
> new `build` extra, same spec, same smoke test) and is parse-clean under
> both PowerShell 7 and, via `tests/test_powershell_scripts.py`, the same
> ASCII / no-`$(if ...)` discipline that `update_install.ps1` needed the
> hard way -- but it has never actually run. The onnxruntime DLL-loading
> path, in particular, is known to differ enough between platforms that a
> clean Linux freeze does not predict a clean Windows one.

Fresh venv, `pip install .` (non-editable) + pyinstaller, build `photo-workflow` as **onedir** (not onefile — onefile re-extracts per invocation, fatal for per-step shell-outs) → `runtime/{linux,win}/`. Models stay **external** (no `--add-data models`). Spec needs `--collect-all` for `onnxruntime` (esp. `onnxruntime.capi._pybind_state`), `cv2`, `scipy`, `tokenizers`, `rawpy`, `Pillow`, `imagehash`, `exifread`.

### Task 7 — Provisioning manifest & offline guarantee (`config/portable-manifest.yml`) — **DONE (Linux verified end-to-end; Windows launch unverified)**

> Landed 2026-08-20. `config/portable-manifest.yml` pins Darktable **5.6.0**
> for both OSes. Both artifacts were **downloaded and hashed locally** rather
> than copying checksums out of the release notes, both were extracted, and
> both recorded relpaths were confirmed against the real extracted trees.
>
> **The plan's Windows preference is not available.** It says "prefer the
> official Darktable **zip** to avoid needing `innoextract`" — upstream ships
> no portable zip for Windows at all, only an Inno Setup installer. So
> `archive_type: innosetup` is forced, and the innoextract dependency the plan
> hoped to dodge is mandatory.
>
> **And the packaged innoextract cannot read it.** The 5.6.0 installer is built
> with **Inno Setup 6.7.0**, which uses *setup-loader revision 2*. innoextract
> **1.9** — the newest release, and what Debian stable / Ubuntu 24.04 package —
> predates that and fails with "Could not determine setup data version!",
> exiting 2 having written nothing. 7-Zip 23.01 cannot open it either. Both
> were tested against the real installer, not assumed.
>
> The fix, verified by actually doing it: upstream master (`6e9e34e`) plus the
> **MSYS2 patch series** (`MINGW-packages/mingw-w64-innoextract`, 14 patches,
> pinned to that same commit) adds loader-revision-2 and Inno Setup 6.5–7.0.2
> support. Built it, extracted the real installer: **3029 files, 715 MB, zero
> zero-byte files, all 540 PE binaries valid, all 358 `.mo` catalogs valid, and
> the 25 largest binaries (up to 102 MB) have complete section data** — i.e. no
> truncation. The 3029 "could not read back … to calculate output checksum"
> warnings are a verification step the patched multi-part path skips, not
> corruption. Procedure documented in `docs/portable-drive-setup.md`.
>
> **Real end-to-end build, not a mocked one:** `build_portable_layout` was run
> against the shipped manifest with `offline=True` and a `fetch` that raises,
> proving cache-only assembly, and it produced a full dual-OS drive. The
> extracted Linux Darktable **runs**: `AppRun --version` reports darktable
> 5.6.0 with **Lua ENABLED (API 9.7.0)** — load-bearing, since the whole
> PHOTONFORGE panel is a Lua plugin. `PHOTONForge.sh` was traced with `sh -x`
> and execs the right `squashfs-root/AppRun` with `--configdir <DRIVE>/dt-config`.
>
> **Two real bugs in the Task 2/3 code, both found only because real data was
> used:**
>
> - **`PHOTONForge.ps1` resolved the Darktable binary to the wrong place.**
>   `binary_relpath` is recorded relative to `apps/darktable-<os>/` (it is
>   `app/bin/darktable.exe`), but the launcher joined it straight onto
>   `$PSScriptRoot`, yielding `<DRIVE>\app\bin\darktable.exe` — a path that
>   does not exist. Fixed, and pinned with a regression test that was
>   mutation-checked by reintroducing the bug.
> - **The `.ps1` template carried an em dash** and was invisible to
>   `tests/test_powershell_scripts.py`, whose ASCII guard only globbed
>   `scripts/*.ps1`. That template is copied verbatim onto the drive and run by
>   whatever PowerShell the host has — 5.1 on a stock Windows box, which
>   decodes a BOM-less file as ANSI and mangles it. This is precisely the class
>   of bug that guard exists to catch, so the guard now covers
>   `deploy/portable/*.ps1.tmpl` too (also mutation-checked).
>
> Extraction failures no longer escape as a bare `CalledProcessError` (which is
> not a `RuntimeError`, so the `make-portable` handler would have let it
> through as a traceback): `_run_extractor` re-raises a `RuntimeError` carrying
> the tool's own stderr plus an actionable hint naming the innoextract version
> requirement.
>
> **Still unverified: launching on Windows.** The Windows half assembles and
> its layout checks out, but no Windows host exists in this environment, so
> neither `PHOTONForge.bat` nor `scripts/build_portable_cli.ps1` has ever been
> run there.
>
> **Correction to the paragraph below: a single Linux host builds both OSes.**
> The plan text says building a dual-OS drive needs both toolchains on
> separate hosts. That is not what was found — `build_portable_layout(oses=
> ["win", "linux"])` was run as **one call on one Linux container** in this
> session and both extracted successfully. innoextract is a format parser,
> not an installer executor: it never runs the Windows `.exe`, so a
> Linux-built innoextract reads the Windows installer fine. Only the Linux
> half is genuinely host-locked, because bundling it runs the downloaded
> AppImage itself (`--appimage-extract`) as a subprocess, which needs
> something that can execute a Linux ELF binary. Since the Yoga 910 (the
> actual target machine, per `CLAUDE.md`) runs Ubuntu 24.04, the common case —
> provision from the Yoga, get both OSes — already works in one run. Building
> the Linux half from a Windows-only host (no WSL) remains the one real gap;
> see `docs/portable-drive-setup.md`.

Version-controlled: per-OS `version`, `url`, `sha256`, `archive_type` (`zip`/`portableapps`/`innosetup`/`appimage`), and resolved binary relpath (`exe_relpath` / `apprun_relpath`). Downloader streams to `--cache`, verifies sha256 (abort on mismatch — no TOFU). Windows: prefer the official Darktable **zip** to avoid needing `innoextract`. Linux AppImage extracted to `squashfs-root/` (needs a Linux host). Building a **dual-OS** drive from one host needs both toolchains → document per-OS provisioning as the reliable path. Downloads happen **only** in `make-portable`; nothing in `runtime/`, launchers, or `runner.lua` touches the network (NFR-2.1). `--offline` = cache-only, error on miss. `.photonforge/manifest.lock.json` is the audit record.

### Task 8 — Tests
- [x] `tests/test_portable.py` — landed with Task 2 (29 tests). Manifest
      schema/sha256 validation; downloader verify-pass/verify-fail/offline
      (an injected `fetch` callable, not the `responses` library — no HTTP
      client exists in `portable.py` to intercept, since `urllib.request` is
      only reached by the *default* fetch, which the tests never exercise);
      `extract_archive` real against an actual zip; layout builder against a
      real `tmp_path` drive tree (both with and without a manifest) asserting
      the tree, single idempotent luarc require line, models copied,
      launchers present, lockfile contents; launcher templates asserted to
      contain `$PSScriptRoot`/`%~dp0`/`readlink -f` and the AppImage
      `--appimage-extract-and-run` fallback, plus a regex assertion that no
      absolute host path (`/home/*`, `/root`, `C:\Users\*`) leaked into any
      rendered launcher; `_deploy_plugin` idempotency verified across two
      real runs. `tests/test_cartridge_make_portable_cli.py` covers the click
      surface (label/id checks, manifest-less assembly, error wrapping, the
      `init` deprecation notice).
- [ ] `tests/lua/test_runner_selflocate.lua` run via `lua5.4` in CI: stub the global `darktable` table and assert `cli()`, `models_dir()`, and `M.preview_cmd("score")` yield drive-relative paths under `<root>/runtime/...` and `<root>/models`. (`preview_cmd` already resolves `build_cmd` without executing — the natural seam.)
- [ ] Per-OS CI smoke of the frozen CLI (models external): `--help`, `dedup`/`ingest` on fixtures, then `score --model-dir models ...` (onnxruntime — #1 freeze risk) and `name --model-dir models/florence2_int8 <RAW fixture>` (Florence-2 + tokenizers + rawpy — #2).

### Task 9 — Docs (per docs-impact convention; do NOT hand-edit AUTO files — post NFR evidence via `sf-comment`)
- [ ] New `docs/portable-drive-setup.md` (end-user build + plug-and-run guide; exFAT + AppImage/FUSE caveats; dev-mode `preview_cmd` verification checklist).
- [ ] New `dev-docs/architecture/adr/ADR-00X-exfat-cross-os-cartridge.md` (filesystem decision).
- [ ] Update `docs/install-yoga-linux.md` §5/§6 (dt-config-on-drive, `--configdir`, declare Layout B canonical, exFAT note); `dev-docs/dev-machine-setup.md` (build scripts + make-portable); `CLAUDE.md` Project Layout (`apps/`, `runtime/`, `dt-config/`, `config/portable-manifest.yml`, new scripts); `dev-docs/architecture/module-bdd.md:150` (Layout A → reconciled); `dev-docs/glossary.md` + `house-style/glossary.yml` ("PHOTON cartridge" = self-contained bundle); `system-architecture-contracts.md` (NFR-2.3 spans CLI+models+Darktable; reaffirm NFR-2.1). Add the **"Docs impact"** line to the PR; flag @systems_lead that a new UN/FR for "cross-OS self-contained drive" may be warranted.

## Files at a glance

**Create:** ~~`config/portable-manifest.yml`~~ DONE (darktable 5.6.0, both OSes, locally-verified hashes), ~~`src/photo_workflow/portable.py`~~ DONE, ~~`scripts/build_portable_cli.{sh,ps1}`~~ DONE, ~~`scripts/photonforge.spec`~~ DONE (plus `scripts/portable/freeze_entry_photo_{workflow,cartridge}.py` and `tests/test_portable_build.py`, not originally listed), ~~`deploy/portable/PHOTONForge.{ps1,bat,sh}.tmpl`~~ DONE, ~~`tests/test_portable.py`~~ DONE (plus `tests/test_cartridge_make_portable_cli.py`, not originally listed), `tests/lua/test_runner_selflocate.lua` (superseded by `tests/lua/test_runner_cartridge.lua`, landed with Task 1), `docs/portable-drive-setup.md`, `dev-docs/architecture/adr/ADR-00X-exfat-cross-os-cartridge.md`.

**Modify:** `lua/photonforge/runner.lua`, `lua/photonforge/config.lua`, ~~`src/photo_workflow/cartridge.py`~~ DONE (`make-portable` + `init` deprecation notice), `src/photo_workflow/provision.py`, ~~`src/photo_workflow/pipeline.py`~~ DONE, ~~`src/photo_workflow/naming.py`~~ DONE, ~~`pyproject.toml`~~ DONE (added `provision` extra: PyYAML; `build`/pyinstaller landed with Task 6), `scripts/deploy_lua.ps1` + `deploy/entrypoint.sh` (delegate to shared `_deploy_plugin` — **not done**: `_deploy_plugin` is Python, and wiring a PowerShell dev-machine script through it would add a runtime dependency beyond what Task 2/3 needed; left as explicit future work rather than silently dropped), plus the docs above.

## Highest-risk parts (with mitigations)

1. **exFAT** (whole goal hinges on it; loses exec bit/symlinks; SQLite WAL + KPM-1.4 unvalidated) → single exFAT partition, best-effort `chmod +x`, re-run the 50-cycle soak, fall back to `journal_mode=DELETE` if WAL is flaky.
2. **PyInstaller freeze of onnxruntime/rawpy/tokenizers — Windows is still unverified; Linux is now real, not just planned** (see Task 6). A frozen build actually ran, and a dedicated smoke executable exercised every collected package's native extension at runtime (`tests/test_portable_build.py::test_real_freeze_build_end_to_end`, `slow`), not just PyInstaller's static import-graph analysis. `--collect-all` covers the plan's package list; per-OS CI smoke of `score`/`name` against real models is still open, and needs a Windows runner this environment does not have.
3. **AppImage FUSE** on arbitrary hosts → pre-extract `squashfs-root/AppRun`; `--appimage-extract-and-run` fallback.
4. **Pinned Darktable URLs/hashes rot** → manifest + cache + `--offline` + provenance lock + documented refresh procedure (all landed in Task 7). **A sharper form of this risk turned out to be real and is only half-mitigated:** it is not just the URL that rots but the *extractor*. Upstream ships no Windows zip, so the drive depends on innoextract keeping pace with Inno Setup, and the packaged innoextract (1.9) is already too old for the current installer (Inno Setup 6.7). Today's answer is a patched build from upstream master + the MSYS2 patch series, documented in `docs/portable-drive-setup.md` — which means the Windows path depends on a hand-built tool, and will need re-checking whenever Darktable bumps its installer.
5. **darktablerc clobber on Darktable exit** → self-location (never bake absolute paths); write `darktablerc` only while Darktable is closed; keep `cli_path`/`models_path` blank.

## Android companion (continuity note, 2026-07-17)

The same cartridge is also the target of the **Android Direct-Attach app** (PR #141,
`dev-docs/architecture/android-port-brief.md`): a Kotlin app that runs the sorting
pipeline + a cull/review/export UI when the drive or an SD card plugs straight into a
phone. Points of contact with this plan:

- **The exFAT decision above is load-bearing for Android too** — Android mounts
  exFAT/FAT32 only, never ext4. Fold Android into the ADR's justification
  (`ADR-00X-exfat-cross-os-cartridge`): one filesystem unblocks Windows, macOS, *and*
  the phone.
- **KPM-1.4 re-validation on exFAT** should include the phone as a host (SAF-mediated
  writes count toward the 50 safe-eject cycles).
- **Layout compatibility:** the Android app reads shoot folders at root, `models/`
  (ONNX files are data — loadable from the drive under W^X), and `photonforge.db`;
  it writes **XMP sidecars only** and never touches `dt-config/library.db` — desktop
  darktable reconciles phone culls from `xmp:Rating`/`lr:hierarchicalSubject` in the
  sidecars. `apps/`, `runtime/`, and `dt-config/` are desktop-only payloads the phone
  ignores. No task in this plan changes for Android; this note pins the contract so
  neither plan drifts.

## Verification (end-to-end)

1. `pytest tests/test_portable.py` and the CI matrix smoke of the frozen CLI (both OSes).
2. `lua5.4 tests/lua/test_runner_selflocate.lua` (drive-relative resolution).
3. Build the drive: `scripts/build_portable_cli.{sh,ps1}` then `photo-cartridge make-portable <mounted-exfat-drive>`; confirm the tree + `manifest.lock.json`.
4. **Manual cross-host** (the real acceptance): plug the same drive into a fresh Windows box and a fresh Linux box; double-click `PHOTONForge.bat` / run `PHOTONForge.sh`; Darktable opens with the panel loaded; enable the `dev_mode` pref and confirm the resolved-command preview points at the **current** mount's `runtime/` + `models/`; run ingest→dedup→score→name→sync-tags on fixture photos and confirm tags land in the on-drive `dt-config/library.db`.
5. Re-run the safe-eject soak (KPM-1.4) on exFAT before declaring done.
