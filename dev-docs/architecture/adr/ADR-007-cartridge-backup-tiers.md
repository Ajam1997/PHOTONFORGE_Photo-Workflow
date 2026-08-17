# ADR-007 — Cartridge backup in three tiers, ordered by dependency-freedom

**Status:** Accepted (PR #144 decision, PR #145 Tiers 1–2, 2026-08-17) — Tier 3 not yet built

## Context

`photonforge.db` is the only record of the pipeline's derived work — scoring,
semantic names, stage state — and it lives on removable media (NFR-2.3), the
*more* failure-prone location. There was no backup of it ([issue #131](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/131)).
Distinct from KPM-1.4, which protects a single write cycle but not drive loss.

Two plans proposed incompatible mechanisms for the same capability, neither
implemented. The [2026-07-11 plan](../../Archive/superpowers/plans/2026-07-11-cartridge-backup-plan.md)
wrapped **restic** (dedup, compression, encryption, cloud). Task 4a of the
[portable-drive plan](../../superpowers/plans/2026-07-17-portable-drive-plan.md)
specified an **rsync-style verified mirror** and made it a hard prerequisite
for `migrate-fs`. The second was written after an audit that found no backup
*code* but did not surface the first *plan*.

Two facts decide between them:

- **A restic repo is not a browsable tree.** `migrate-fs` reformats the
  cartridge; its copy-out staging is the only thing between the user and total
  loss during that window. Requiring an external binary to read the safety net
  back is the wrong dependency at the worst moment.
- **A plain mirror has no dedup, no encryption, and no offsite story**, and it
  strands the `backup_repo` / `backup_pwfile` prefs the panel already ships.

The payload is mostly incompressible RAW, so dedup-across-snapshots is the
lever that matters and compression is secondary.

## Decision

Three tiers in one module (`src/photo_workflow/backup.py`), ordered by
dependency-freedom, sharing one `VACUUM INTO` primitive and one
`snapshot-manifest.json` schema:

| Tier | What | Deps | Status |
|---|---|---|---|
| 1 — catalog snapshot | `VACUUM INTO` the catalogs → rotating `.photon-snapshots/` on the cartridge | stdlib | built |
| 2 — cartridge mirror | Whole cartridge (or `--state-only`) → dated tree + verified sha256 manifest | stdlib | built |
| 3 — offsite archive | restic: dedup + zstd, encrypted, local repo or cloud via rclone | `restic` | **not built** |

**Tier 2 is mandatory and the only tier `migrate-fs` may consume.** Tier 3 is
optional, blocks nothing, and honours the existing restic-shaped prefs.

Every DB copy in every tier goes through `VACUUM INTO` — never a file copy,
which can be torn mid-write. Tier 1 flattens DB names (a rescue copy you grab
by hand); Tier 2 preserves the source-relative path, because flattening
`dt-config/library.db` to the root produces a restored cartridge Darktable
cannot read.

**Encryption split:** Tiers 1–2 unencrypted (matches the accepted local stance
in [data-security-posture.md](../data-security-posture.md) — the data stays on
devices the user physically holds). Tier 3 always encrypted, because data may
leave the device. Do not "simplify" by encrypting Tier 1: it would need a key
present at safe-eject time, defeating the offline/instant property that makes
Tier 1 worth having.

**`models/` asymmetry**, deliberate: Tier 2 includes it (excluding it makes
every migration force a re-provision); Tier 3 excludes it (rotating/offsite,
where GB are expensive and re-provisioning is documented).

## Alternatives considered

- **restic-only** — rejected: puts an external binary in the path of the
  destructive-migration safety net.
- **Mirror-only** — rejected: no dedup, no encryption, no offsite, and orphans
  shipped prefs.
- **Kopia** — better UX and a web UI, but would mean reworking the
  restic-shaped prefs and flags. Rejected for churn, not merit.
- **Borg** — no native cloud, no Windows. Rejected: the panel runs on Windows.
- **tar + zstd** — no dedup across snapshots, which is the main lever here.
- **rclone sync only** — no versioning, no dedup.

## Consequences

- The DR gap closes **without restic installed**: Tiers 1–2 are stdlib-only,
  so `pip install` is the whole dependency story for the supported path.
- NFR-2.1 is unaffected: backup is maintenance-time, never a pipeline
  operation, and nothing in `pipeline.py` imports `backup.py`. Tiers 1–2 are
  fully offline; only Tier 3 may touch the network.
- **Hardlink incrementals degrade on exFAT/FAT32**, which the portable-drive
  plan makes the default filesystem. `supports_hardlinks()` probes with a real
  `os.link` and falls back to full copies, recording `"hardlinks": false`.
- **Mirrors share inodes for unchanged files, so N mirrors is not N
  independent copies** — one corrupted file affects every mirror holding it.
  This is inherent to link-dest (rsync has it too) and is why `verify-backup`
  exists and why the runbook prescribes a verify cadence.
- Tier 3 will require an external binary resolved at runtime and a CI install
  for its round-trip test to actually run rather than skip.
- Restoring a Tier-3 archive will need a models re-provision, since `models/`
  is excluded there.

## Related

- Plan: [2026-08-17 cartridge backup & archive](../../superpowers/plans/2026-08-17-cartridge-backup-archive-plan.md)
- Runbook: [backup-and-restore-guide.md](../../backup-and-restore-guide.md)
- Interface: [IF-1.1](../../../requirements/interfaces/IF-1.1.md) sub-contract 4
