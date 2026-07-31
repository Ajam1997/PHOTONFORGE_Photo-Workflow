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

### Task 1 — Lua self-location (`lua/photonforge/runner.lua`, `config.lua`)
Chosen over launcher-rewrite: Darktable rewrites `darktablerc` on clean exit, so baking absolute paths in would be clobbered. Self-location recomputes paths every run from `dt.configuration.config_dir` (the *current* real mount), so drive-letter/mount churn is irrelevant. Fully backward-compatible (only fires when the pref is blank AND the sibling dir exists). Keep all new helpers `pcall`-safe so `preview_cmd` never throws.
- [ ] Add `config_parent()` — strip the last component of `dt.configuration.config_dir` (`<DRIVE>/dt-config`) → drive root (Win `\`, Linux `/` variants).
- [ ] Modify `cli()` (lines 25-29): between the `cli_path`-set branch and the bare-name fallback, probe `<root>/runtime/{win/photo-workflow.exe | linux/photo-workflow}`; return it if present, else fall through to `return "photo-workflow"` (unchanged legacy).
- [ ] Add `models_dir()` — return `config.read("models_path")` if set; else probe `<root>/models/florence2_int8` and return `<root>/models`; else `""` (CLI auto-detects). Replace the 5 inline `config.read("models_path")` reads (score ~104, name ~122, refresh-review ~150, recalibrate ~171, rescore ~198) with `models_dir()`; the existing `if models ~= "" then --model-dir` blocks stay.
- [ ] `config.lua`: help-text only on `cli_path`/`models_path` (lines 18-19) — note blank auto-locates `../runtime` and `../models` relative to the Darktable config dir on a portable drive. No schema change.

### Task 2 — Builder core (new `src/photo_workflow/portable.py`)
Unit-testable, no click. Manifest load/verify, downloader (mockable), extractor (zip / innoextract / appimage-extract), `_deploy_plugin(dt_config, repo_lua_dir)` (copies `lua/photonforge/*.lua`+`.css`, idempotent `require "photonforge/main"` in luarc — reuses `scripts/deploy_lua.ps1` logic cross-platform), launcher templating, and the layout builder.

### Task 3 — `make-portable` subcommand (`src/photo_workflow/cartridge.py`)
Runs on the **provisioning machine** (unfrozen `photo-cartridge` entry), assembles files onto an already-mounted drive (unelevated; partition/format stays in `provision.py`). Thin click wrapper over `portable.py`.
```
photo-cartridge make-portable <drive>
  --os {win,linux} (repeatable, default both)  --manifest config/portable-manifest.yml
  --models-src models  --cli-src runtime  --cache <dir>  --offline
```
Creates: `dt-config/` (plugin + luarc + baseline darktablerc with `cli_path`/`models_path` **blank**; does NOT seed `library.db`), `apps/darktable-{win,linux}/` (download+verify+extract), `runtime/{win,linux}/` (copy prebuilt frozen CLIs), `models/` (copytree with progress), launchers, `.photonforge/manifest.lock.json`. Reuse `volume.py::get_volume_label`/`extract_cartridge_id` to verify the `PHOTON-XXX` label. Deprecate `init_cartridge`'s Layout-A scaffold.

### Task 4 — exFAT provisioning (`src/photo_workflow/provision.py`)
Default `mkfs.exfat` (keep `--fs ext4`); update the `mount_point` derivation. Note: exFAT tools (`exfatprogs`/`mkfs.exfat`) must be present on the provisioning host.

### Task 4b — Migration of existing ext4 cartridges (`photo-cartridge migrate-fs`)
Reformatting is destructive, so migration is copy-out → reformat → copy-back. All
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

### Task 5 — Frozen-aware model root (`src/photo_workflow/pipeline.py` + `naming.py`)
Add `_default_model_root()`: when `getattr(sys, "frozen", False)`, resolve models relative to `Path(sys.executable)` (→ `<DRIVE>/models`) instead of `Path(__file__)...` (which breaks when frozen). Wire into the 5 `model_dir is None` fallbacks (pipeline.py ~490/727/907, naming.py ~446/463). Belt-and-suspenders with `runner.lua` always passing `--model-dir`.

### Task 6 — Build scripts (`scripts/build_portable_cli.{sh,ps1}` + `scripts/photonforge.spec`)
Fresh venv, `pip install .` (non-editable) + pyinstaller, build `photo-workflow` as **onedir** (not onefile — onefile re-extracts per invocation, fatal for per-step shell-outs) → `runtime/{linux,win}/`. Models stay **external** (no `--add-data models`). Spec needs `--collect-all` for `onnxruntime` (esp. `onnxruntime.capi._pybind_state`), `cv2`, `scipy`, `tokenizers`, `rawpy`, `Pillow`, `imagehash`, `exifread`.

### Task 7 — Provisioning manifest & offline guarantee (`config/portable-manifest.yml`)
Version-controlled: per-OS `version`, `url`, `sha256`, `archive_type` (`zip`/`portableapps`/`innosetup`/`appimage`), and resolved binary relpath (`exe_relpath` / `apprun_relpath`). Downloader streams to `--cache`, verifies sha256 (abort on mismatch — no TOFU). Windows: prefer the official Darktable **zip** to avoid needing `innoextract`. Linux AppImage extracted to `squashfs-root/` (needs a Linux host). Building a **dual-OS** drive from one host needs both toolchains → document per-OS provisioning as the reliable path. Downloads happen **only** in `make-portable`; nothing in `runtime/`, launchers, or `runner.lua` touches the network (NFR-2.1). `--offline` = cache-only, error on miss. `.photonforge/manifest.lock.json` is the audit record.

### Task 8 — Tests
- [ ] `tests/test_portable.py` (mock net via `responses`): manifest schema/sha256 validation; downloader verify-pass/verify-fail + `--offline`; layout builder against a `tmp_path` drive (fetch/extract monkeypatched to drop placeholders) asserting the tree, single idempotent luarc require line, models copied, launchers present, lockfile hashes; launcher templates contain `$PSScriptRoot`/`%~dp0`/`readlink -f` and the AppImage fallback, with a regex assertion that **no absolute host path** leaked; `_deploy_plugin` idempotent across two runs.
- [ ] `tests/lua/test_runner_selflocate.lua` run via `lua5.4` in CI: stub the global `darktable` table and assert `cli()`, `models_dir()`, and `M.preview_cmd("score")` yield drive-relative paths under `<root>/runtime/...` and `<root>/models`. (`preview_cmd` already resolves `build_cmd` without executing — the natural seam.)
- [ ] Per-OS CI smoke of the frozen CLI (models external): `--help`, `dedup`/`ingest` on fixtures, then `score --model-dir models ...` (onnxruntime — #1 freeze risk) and `name --model-dir models/florence2_int8 <RAW fixture>` (Florence-2 + tokenizers + rawpy — #2).

### Task 9 — Docs (per docs-impact convention; do NOT hand-edit AUTO files — post NFR evidence via `sf-comment`)
- [ ] New `docs/portable-drive-setup.md` (end-user build + plug-and-run guide; exFAT + AppImage/FUSE caveats; dev-mode `preview_cmd` verification checklist).
- [ ] New `dev-docs/architecture/adr/ADR-00X-exfat-cross-os-cartridge.md` (filesystem decision).
- [ ] Update `docs/install-yoga-linux.md` §5/§6 (dt-config-on-drive, `--configdir`, declare Layout B canonical, exFAT note); `dev-docs/dev-machine-setup.md` (build scripts + make-portable); `CLAUDE.md` Project Layout (`apps/`, `runtime/`, `dt-config/`, `config/portable-manifest.yml`, new scripts); `dev-docs/architecture/module-bdd.md:150` (Layout A → reconciled); `dev-docs/glossary.md` + `house-style/glossary.yml` ("PHOTON cartridge" = self-contained bundle); `system-architecture-contracts.md` (NFR-2.3 spans CLI+models+Darktable; reaffirm NFR-2.1). Add the **"Docs impact"** line to the PR; flag @systems_lead that a new UN/FR for "cross-OS self-contained drive" may be warranted.

## Files at a glance

**Create:** `config/portable-manifest.yml`, `src/photo_workflow/portable.py`, `scripts/build_portable_cli.{sh,ps1}`, `scripts/photonforge.spec`, `deploy/portable/PHOTONForge.{ps1,bat,sh}.tmpl`, `tests/test_portable.py`, `tests/lua/test_runner_selflocate.lua`, `docs/portable-drive-setup.md`, `dev-docs/architecture/adr/ADR-00X-exfat-cross-os-cartridge.md`.

**Modify:** `lua/photonforge/runner.lua`, `lua/photonforge/config.lua`, `src/photo_workflow/cartridge.py`, `src/photo_workflow/provision.py`, `src/photo_workflow/pipeline.py`, `src/photo_workflow/naming.py`, `pyproject.toml` (add `build`/`provision` extras: pyinstaller, PyYAML), `scripts/deploy_lua.ps1` + `deploy/entrypoint.sh` (delegate to shared `_deploy_plugin`), plus the docs above.

## Highest-risk parts (with mitigations)

1. **exFAT** (whole goal hinges on it; loses exec bit/symlinks; SQLite WAL + KPM-1.4 unvalidated) → single exFAT partition, best-effort `chmod +x`, re-run the 50-cycle soak, fall back to `journal_mode=DELETE` if WAL is flaky.
2. **PyInstaller freeze of onnxruntime/rawpy/tokenizers — Windows is unverified** (CLI is Linux-validated only) → `--collect-all` + explicit hooks + per-OS CI smoke of `score`/`name`.
3. **AppImage FUSE** on arbitrary hosts → pre-extract `squashfs-root/AppRun`; `--appimage-extract-and-run` fallback.
4. **Pinned Darktable URLs/hashes rot** → manifest + cache + `--offline` + provenance lock + documented refresh procedure.
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
