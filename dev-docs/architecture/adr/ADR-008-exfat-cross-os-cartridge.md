# ADR-008 — exFAT as the cartridge filesystem; Layout B canonical

**Status:** Accepted (Tasks 1/4 landed PR #147, Task 6 PR #148, Task 2/3 PR
#149, Task 5 PR #150, Task 7 PR #151, 2026-08-19 — 2026-08-21)

## Context

The [portable-drive plan](../../superpowers/plans/2026-07-17-portable-drive-plan.md)'s
goal: a PHOTON cartridge that runs Darktable + the `photo-workflow` CLI +
ONNX models on **any** Windows or Linux machine with nothing installed on the
host. Before this work, `provision.py` formatted cartridges `ext4` and the
Lua plugin assumed a host-installed Darktable reading its catalog from
`~/.config/darktable` — Layout A (`<mount>/<id>/darktable/library.db` +
`photos/`) and Layout B (drive-root state, which `runner.lua` had already
drifted onto) coexisted undocumented.

Two things force a single decision here:

- **Windows cannot read ext4.** For one shared `library.db`/`photonforge.db`
  readable by both OSes with no host install, the drive must be a single
  filesystem both OSes can mount natively.
- **The Android Direct-Attach companion app** (PR #141; see the portable-drive
  plan's "Android companion" continuity note) mounts removable storage via
  Android's Storage Access Framework, which supports exFAT/FAT32, never ext4.
  Whatever this ADR picks, the phone inherits it too.

## Decision

**Single GPT exFAT partition, Layout B canonical.** `provision.py` defaults
to `mkfs.exfat` (`fs="ext4"` stays available for a drive that will provably
never leave Linux). Darktable's own config/catalog moves to
`<DRIVE>/dt-config/`; Layout A is retired — kept working only as a stderr-
deprecated fallback in `cartridge.py`'s `init` command, never as something
new tooling writes.

## Alternatives considered

- **Dual-partition (ext4 + exFAT)** — rejected outright: the whole point is
  one shared `library.db`, and two partitions cannot share one file.
- **FAT32** — rejected: exFAT was designed as FAT32's successor specifically
  to remove FAT32's per-file 4 GiB ceiling, which the DB files and any raw
  video sidecar the pipeline touches can approach over a cartridge's life;
  exFAT has no such limit and is natively read/write on Windows, macOS,
  Linux (kernel driver since 5.4), and Android.
- **NTFS** — natively read/write on Windows only; Linux write support
  (`ntfs-3g`) is a FUSE layer with weaker crash-consistency guarantees than
  exFAT's native kernel driver, and NTFS's POSIX permission bits invite a
  false sense of exec-bit portability that exFAT's total absence of one does
  not.

## Consequences

- **No POSIX exec bit or symlinks.** Every launcher does a best-effort
  `chmod +x` and never relies on one existing; `_deploy_plugin` and
  `extract_archive` never create symlinks. See
  [`docs/portable-drive-setup.md`](../../../docs/portable-drive-setup.md).
- **SQLite WAL on exFAT is unvalidated against KPM-1.4** (zero corruption /
  50 safe-eject cycles — validated on ext4 only). **This has not been
  re-run yet and remains the plan's open risk item #1** — re-run the soak
  before treating an exFAT cartridge as production-ready; fall back to
  `journal_mode=DELETE` if it proves flaky.
- **Hardlink incrementals degrade on exFAT/FAT32** — already the subject of
  [ADR-007](ADR-007-cartridge-backup-tiers.md); `supports_hardlinks()`
  probes with a real `os.link` and falls back to full copies rather than
  assuming.
- **The exec-bit-free constraint compounds with how Darktable itself gets
  onto the drive.** Windows Darktable ships only an Inno Setup installer (no
  portable zip), and the Debian/Ubuntu-packaged `innoextract` predates the
  Inno Setup version that installer uses — a real gap found building Task 7,
  documented in `docs/portable-drive-setup.md` rather than papered over.
  This is a consequence of bundling Darktable at all (which exFAT's
  no-host-install goal requires), not of exFAT specifically, but it would not
  exist under the old host-installed-Darktable model.
- **The Android companion app is unblocked by the same decision** — it reads
  shoot folders, `models/`, and `photonforge.db` from the cartridge and
  writes XMP sidecars only, never touching `dt-config/library.db`; desktop
  Darktable reconciles phone culls from the sidecars on next open. No task in
  the portable-drive plan changes for Android; this ADR is what pins the
  filesystem choice both plans share.

## Related

- Plan: [2026-07-17 portable drive](../../superpowers/plans/2026-07-17-portable-drive-plan.md) (see also its "Android companion" note)
- Setup guide: [docs/portable-drive-setup.md](../../../docs/portable-drive-setup.md)
- [ADR-007](ADR-007-cartridge-backup-tiers.md) (hardlink degradation on exFAT)
