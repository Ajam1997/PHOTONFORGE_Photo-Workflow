# Backup & restore runbook

How to protect a PHOTON cartridge, and how to get it back. For *why* it is
built this way, see [ADR-007](architecture/adr/ADR-007-cartridge-backup-tiers.md).

**What is at stake.** The photos are replaceable from the SD card until you
format it. What is not replaceable is the *derived* work: scores, star
ratings, semantic filenames, stage state, genre corrections, and your
Darktable edits. That lives in `photonforge.db`, `training_weights.db`,
`dt-config/library.db` and the XMP sidecars — all on the cartridge, which is
the most failure-prone thing in the system.

## The two tiers you have today

| | **Snapshot** (Tier 1) | **Backup** (Tier 2) |
|---|---|---|
| Copies | catalog databases only | everything — databases *and* photos |
| Goes to | the cartridge itself (`.photon-snapshots/`) | a second drive you choose |
| Takes | seconds | as long as copying the drive takes |
| Needs | nothing | a second drive |
| Protects against | corruption, a bad run, accidental deletion | all of that, **plus losing the drive** |

A snapshot does **not** protect against losing the cartridge — it is on the
cartridge. It is the cheap thing you can always do; Backup is the one that
actually survives a dead drive. Use both.

A third tier (encrypted off-site archives via restic) is designed but **not
implemented**. The panel's Archive/Restore buttons are gated off and say so.

## Everyday use

```bash
# Tier 1 — seconds, no second drive, run it often
photo-cartridge snapshot /media/alex/PHOTON-001

# Tier 2 — full verified mirror to a second drive
photo-cartridge backup /media/alex/PHOTON-001 --dest /media/alex/BACKUP --keep 10
```

Or press **Snapshot** / **Backup** in the panel's CARTRIDGE strip, having set
*Backup destination* in Preferences → Lua options.

Snapshots rotate (`--keep`, default 7) and land in
`/media/alex/PHOTON-001/.photon-snapshots/<timestamp>/`. Mirrors land in
`<dest>/<cartridge label>/<timestamp>/` and are excluded from each other, so
backups never nest.

**Automatic snapshot on eject.** Set `PHOTONFORGE_SNAPSHOT_ON_EJECT=1` and
`scripts/safe_eject.sh` takes a catalog snapshot before unmounting. A failure
only warns — it never blocks the eject, because a backup problem must not
strand your drive.

### Cheap frequent backups

`--state-only` copies the databases, corpus JSONL, `dt-config/` and XMP
sidecars, skipping the RAWs entirely. Use it between full mirrors when only
your edits and ratings have changed:

```bash
photo-cartridge backup /media/alex/PHOTON-001 --dest /media/alex/BACKUP --state-only
```

`--exclude-models` skips the vendored ONNX models (~GB, reproducible from
provisioning) when you want a smaller full mirror. Leave it off before a
migration, or you will have to re-provision models afterwards.

## Verifying — do not skip this

```bash
photo-cartridge verify-backup /media/alex/BACKUP/PHOTON-001/<timestamp>
# or, the newest one for this cartridge:
photo-cartridge verify-backup --dest /media/alex/BACKUP --root /media/alex/PHOTON-001
```

Exit code is non-zero and every discrepancy is printed if anything fails.

Two reasons this matters more than it looks:

1. **Repeat mirrors share unchanged files via hardlinks.** Ten mirrors of a
   library whose RAWs never change is close to *one* copy of those RAWs, not
   ten. That is what makes repeat backups fast — and it means **one corrupted
   file is corrupted in every mirror holding it.** Verify catches that;
   counting your backup folders does not.
2. **Hardlinks do not exist on exFAT or FAT32.** On those destinations every
   mirror is a full independent copy — slower, larger, but immune to the above.
   Check `"hardlinks"` in `snapshot-manifest.json` to see which you have.

A sensible cadence: verify the newest mirror monthly, and always immediately
before you rely on one (migration, reformat, restore).

## Restoring

There is deliberately no restore button in the panel: restoring needs an
explicit snapshot path, and guessing at a destructive operation is worse than
typing it.

```bash
# 1. ALWAYS verify before you trust it
photo-cartridge verify-backup /media/alex/BACKUP/PHOTON-001/2026-08-17T14-03-22

# 2. Restore (use a scratch dir first if the target still has data you want)
photo-cartridge restore-backup /media/alex/BACKUP/PHOTON-001/2026-08-17T14-03-22 \
    --to /media/alex/PHOTON-001
```

`restore-backup` refuses a non-empty target unless you pass `--force`. The
restored tree is a working cartridge: `photonforge.db` at the root,
`dt-config/library.db` back in place, photos and sidecars where they were.

**From a Tier-1 snapshot instead.** A catalog snapshot is a flat folder of
databases. Copy them back by hand, minding that Darktable's catalog belongs in
`dt-config/` (or `darktable/` on a pre-migration cartridge):

```bash
cp .photon-snapshots/<ts>/photonforge.db  /media/alex/PHOTON-001/
cp .photon-snapshots/<ts>/library.db      /media/alex/PHOTON-001/dt-config/
```

Restoring a snapshot recovers your *analysis*, not your photos.

### Practise the drill

Do this once, before you need it, on a scratch directory:

```bash
photo-cartridge backup /media/alex/PHOTON-001 --dest /tmp/drill
photo-cartridge restore-backup "$(ls -d /tmp/drill/*/* | tail -1)" --to /tmp/drill-restored
sqlite3 /tmp/drill-restored/photonforge.db "SELECT count(*) FROM photos;"
```

If that count matches your library, your backup path works end to end. The
automated equivalent runs in CI (`tests/test_backup_mirror.py`), but a drill
you have personally run is the one you will trust at 2am.

## Before migrating or reformatting a drive

`migrate-fs` (ext4 → exFAT, not yet implemented) reformats the cartridge, which
is destructive and irreversible. It will refuse to run without a **fresh
verified mirror**: one whose manifest verifies *and* postdates the cartridge's
last write. Make that mirror yourself first, including models:

```bash
photo-cartridge backup /media/alex/PHOTON-001 --dest /media/alex/BACKUP
photo-cartridge verify-backup --dest /media/alex/BACKUP --root /media/alex/PHOTON-001
```

Do not use `--state-only` or `--exclude-models` for this one.

## When a cartridge is busy

Backup refuses to run while something is writing to the cartridge — a live
pipeline, or Darktable holding the catalog — because a mirror taken mid-write
captures a database and a photo tree that disagree:

```
Error: Cartridge at /media/alex/PHOTON-001 looks busy: photonforge.db is
write-locked (database is locked). Close Darktable and any running pipeline,
or pass --force.
```

Close Darktable and let any run finish. `--force` exists for the case where you
know the lock is stale; a backup taken with it is not trustworthy for migration.

## What is in a snapshot

Every snapshot carries `snapshot-manifest.json`: schema version, tool version,
cartridge label/id, start/finish timestamps, per-database sha256, whether
hardlinks were used, totals, and a sha256 for every mirrored file. It is what
`verify-backup` checks against and what `migrate-fs` will read to decide
whether a mirror is fresh enough to trust.

Excluded everywhere: `.photon-snapshots/` (Tier-1 output — backups must not
nest), `*__preview.jpg` and `*.mcp.json` (DarktableMCP litter), `*.tmp`, and
`*.db-wal` / `*.db-shm` (the databases are captured with `VACUUM INTO`, which
folds the WAL in; copying a stale sidecar next to a vacuumed database would
corrupt the restore).
