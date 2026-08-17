# Cartridge Backup & Archive Implementation Plan (reconciled)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the disaster-recovery gap ([issue #131](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/131)) *and* supply the verified-snapshot artifact that `migrate-fs` gates on ([portable-drive plan](2026-07-17-portable-drive-plan.md) Task 4b), with one backup module instead of two.

**Supersedes** `dev-docs/Archive/superpowers/plans/2026-07-11-cartridge-backup-plan.md` (restic-only, two tiers) and **replaces** Task 4a of the portable-drive plan (rsync-mirror-only, in `portable.py`). Neither was implemented; this plan is the single source for the feature.

## Why the two plans conflicted, and how this resolves it

| | 2026-07-11 plan | portable-drive Task 4a (2026-07-31) |
|---|---|---|
| Mechanism | restic (dedup, zstd, encrypted, cloud via rclone) | rsync-style dated tree + sha256 manifest |
| Home | new `backup.py` | `portable.py` |
| Scope | catalog DBs (Tier 1) + whole cartridge (Tier 2) | whole cartridge, `--state-only` mode |
| Consumer | operator DR | operator DR **+** `migrate-fs` copy-out |

The Task-4a author audited `src/` and `scripts/`, found no backup *code*, and wrote a
second design without seeing the first plan's *document*. Both are partly right, and
the disagreement is real rather than cosmetic:

- **A restic repo is not a browsable tree.** `migrate-fs` reformats the cartridge; its
  copy-out staging is the only thing standing between the user and total loss during
  that window. Requiring an external binary to read the safety net back is the wrong
  dependency at the worst moment. Task 4a is right that migration wants a plain tree.
- **A plain mirror has no dedup, no encryption, and no offsite story.** For rotating
  and off-device copies the 07-11 plan is right that restic earns its keep.

They are answering different questions, so the reconciliation is not "pick one" —
it is **three tiers ordered by dependency-freedom**, sharing one DB-copy primitive
and one manifest schema, in one module.

## Architecture — three tiers, one module

All logic lives in a new `src/photo_workflow/backup.py`. `cartridge.py` keeps only the
thin click layer; `portable.py` (portable-drive plan Task 2) **imports** from
`backup.py` rather than reimplementing any of it.

| Tier | What | Deps | Target | Encrypted |
|---|---|---|---|---|
| **1 — catalog snapshot** | `VACUUM INTO` the cartridge's SQLite DBs into a rotating `<root>/.photon-snapshots/<ts>/` | stdlib | on-cartridge | no |
| **2 — cartridge mirror** | Whole cartridge (or `--state-only`) copied to a plain dated tree + verified sha256 manifest | stdlib | second local drive | no |
| **3 — offsite archive** | restic: content-defined dedup + zstd, local repo or cloud via rclone | `restic` (+ `rclone`) | local repo or cloud | always |

**Tier 1** is the cheap, always-available answer to issue #131 — it protects the
expensive-to-recompute derived work (scoring, naming, stage state) even when nothing
else is plugged in, and it is safe to hook into `safe_eject.sh`.

**Tier 2** is the primary supported backup and the **only tier `migrate-fs` may
consume**. Pure stdlib, so the destructive-migration safety net never depends on a
binary that might not be installed on the host doing the migration.

**Tier 3** is optional and lands last. It is what the panel's existing `backup_repo` /
`backup_pwfile` prefs already assume, so those prefs are honoured rather than orphaned.

### Ordering consequence (this is a scheduling output, not a detail)

Tiers 1 and 2 **block** the portable-drive plan's Task 4b (`migrate-fs`). Tier 3 does
not block anything and may land in a later PR. Implement in tier order.

### The one shared primitive

Both Tier 1 and Tier 2 copy DBs through `snapshot_databases()` (`VACUUM INTO`), never
through a file copy. A plain copy of a SQLite file mid-write can be torn; `VACUUM INTO`
writes a defragmented, self-contained, immediately-queryable copy while readers stay
live. Tier 2 copies everything *else* (photos, XMP, JSONL corpus, `dt-config/`) as
ordinary files. This is the substantive unification of the two plans.

**Tech Stack:** Python 3.11, `sqlite3` (`VACUUM INTO`), `hashlib`, `os.link`, click,
pytest. Tier 3 only: the **restic** binary (≥ 0.16, repo format v2 for compression) and
optionally **rclone** — both resolved at runtime via `shutil.which` or a configured
path, never bundled. Darktable Lua panel buttons.

## Global Constraints

- **NFR-2.1 (100% offline at runtime):** backup is a *maintenance* operation, never a
  pipeline operation. Tiers 1 and 2 are fully offline. Tier 3 may use the network (same
  category as provisioning). No pipeline code path may call any backup function — assert
  this in the ADR and keep `pipeline.py` free of `backup` imports.
- **NFR-2.3 (DB + config on the external SSD):** the cartridge root is the parent of the
  plugin's destination folder. Backup reads the SSD; Tier-1 snapshots default to a hidden
  dir *on the same cartridge* unless `--dest` is given.
- **NFR-2.2 (RSS ≤ 1.5 GB):** stream file copies and hashing in chunks (64 KiB); never
  read a RAW or a DB fully into memory. A mirror of a full cartridge must not move the
  RSS needle.
- **Cross-platform:** commands run from Windows (panel launches `Start-Process cmd`) *and*
  the Debian/Ubuntu runtime. No bash-only constructs in Python; resolve binaries per-OS;
  no `rsync` shell-out (it is absent on stock Windows) — Tier 2 is implemented in Python.
- **Encryption posture:** Tiers 1–2 are unencrypted (matches the accepted local stance in
  `data-security-posture.md` — the data stays on devices the user physically holds).
  Tier 3 is always encrypted (restic default) because data may leave the device; the key
  comes from the existing `backup_pwfile` pref / `--password-file`.
- PRs that change code must update affected docs (docs-impact matrix in
  `dev-docs/architecture/doc-maintenance-protocol.md`) and carry the **"Docs impact"** line.

## Two conflicts the merge forced into the open

**1. `models/` — excluded or not?** The 07-11 plan excludes `models/` from archives
(vendored, ~GB, reproducible from provisioning). Task 4a does not mention it. Both
defaults are correct for their own tier and wrong for the other:

- **Tier 2 includes `models/` by default** (`--exclude-models` opts out). `migrate-fs`
  reformats the drive — excluding models there means every migration is followed by a
  re-provision, which is exactly the friction migration is supposed to avoid. `migrate-fs`
  always includes them regardless of the flag.
- **Tier 3 excludes `models/` always.** It is the rotating/offsite tier where GB are
  expensive, and re-provisioning after a disaster restore is documented and acceptable.

**2. Hardlink-incremental mirrors do not work on exFAT.** Task 4a specifies rsync
link-dest-style incrementals so repeat backups do not duplicate unchanged RAWs. **exFAT
and FAT32 do not support hardlinks** — and the portable-drive plan's whole premise is
moving cartridges (and therefore, commonly, their backup drives) to exFAT. This was
latent in Task 4a and would have surfaced as a runtime failure on the first exFAT
destination. Resolution: link-dest is **best-effort**. `backup.py` probes the destination
once per run with a real `os.link` attempt in a temp file; on failure it falls back to
full copies, logs the reason once, and records `"hardlinks": false` in the manifest. On
an exFAT destination, `--state-only` is the cheap frequent mode and full mirrors are
periodic. Do not silently produce a mirror the user believes is incremental.

## Cartridge layout (the contract every task shares)

```
<root>/                         # cartridge root = parent of the plugin dest folder
  photonforge.db                # analysis catalog (scores, names, stages, embeddings)
  training_weights.db           # genre prototypes / adapter / aesthetic_weights (may be absent)
  darktable/                    # Layout A (legacy, host-installed Darktable)
    library.db  data.db
  dt-config/                    # Layout B (portable drive — see portable-drive plan)
    library.db  data.db  darktablerc  luarc  lua/
  *.jsonl                       # genre_labels, secondary_feedback (corpus)
  photos/ or <SHOOT>/ ...       # RAW + JPEG originals + XMP sidecars (the bulk)
  models/                       # vendored ONNX — Tier 2 includes, Tier 3 excludes
  .photon-snapshots/            # Tier-1 output (EXCLUDED from Tiers 2 and 3)
    2026-08-17T14-03-22/
      photonforge.db  training_weights.db  library.db  data.db
      snapshot-manifest.json
```

`backup.cartridge_layout(root)` returns the DB paths that actually exist, so no tier
hard-codes a DB a given cartridge lacks. It must probe **both** `darktable/` (Layout A)
and `dt-config/` (Layout B) — the portable-drive plan canonicalizes on B but existing
cartridges are all A, and migration is precisely when backup matters most.

## One manifest schema for both snapshot tiers

Written as `snapshot-manifest.json` by Tier 1 and Tier 2 alike. (The 07-11 plan called
Tier 1's file `MANIFEST.json`; unified here — one reader, `verify-backup`, handles both.)

```json
{
  "schema": 1,
  "kind": "catalog | mirror",
  "state_only": false,
  "cartridge": { "label": "PHOTON-004", "id": "004", "root": "/media/alex/PHOTON-004" },
  "tool_version": "photo-workflow 0.4.1",
  "started_at":  "2026-08-17T14:03:22Z",
  "finished_at": "2026-08-17T14:19:51Z",
  "hardlinks": true,
  "link_dest": "2026-08-10T09-00-00",
  "totals": { "files": 4127, "bytes": 391284736, "linked": 3990, "copied": 137 },
  "dbs": {
    "photonforge":  { "source": "...", "snapshot": "photonforge.db", "bytes": 2129920,
                      "sha256": "…" }
  },
  "files": [ { "path": "ICELAND/DSC0001.ARW", "bytes": 25349120, "mtime": 1755439402.0,
               "sha256": "…" } ]
}
```

`files[]` carries a sha256 for every mirrored file (Tier 2). Tier 1 omits `files[]` and
`totals.linked/copied`; its DBs still carry sha256. `dbs[].sha256` is computed on the
**snapshot copy**, not the source — the source is live and may change under us.

---

### Task 1: cartridge layout + Tier-1 snapshot core

**Files:**
- Create: `src/photo_workflow/backup.py`
- Test: `tests/test_backup_snapshot.py`

**Interfaces — produces:**
- `@dataclass CartridgeLayout: root: Path; dbs: dict[str, Path]` — keys `photonforge`,
  `training_weights`, `dt_library`, `dt_data`; only those present on disk.
- `cartridge_layout(root: Path) -> CartridgeLayout` — probes Layout A *and* B.
- `sha256_file(path: Path, chunk: int = 65536) -> str` — streaming (NFR-2.2).
- `snapshot_timestamp() -> str` — colon-free UTC, sorts chronologically, filename-safe.
- `snapshot_databases(root, dest_dir, *, manifest=True) -> Path` — `VACUUM INTO` every
  present DB into `dest_dir`; write `snapshot-manifest.json` (`kind: "catalog"`) when
  `manifest=True`; return `dest_dir`. Raises `FileNotFoundError` if no DBs found.
  Tier 2 calls it with `manifest=False` and merges the DB entries into its own manifest.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backup_snapshot.py
import json
import sqlite3
import pytest
from photo_workflow.backup import (
    cartridge_layout, snapshot_databases, sha256_file, snapshot_timestamp,
)


def _db(path, value=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (?)", (value,))
    conn.commit()
    conn.close()


def _cartridge_layout_a(root):
    for rel in ("photonforge.db", "training_weights.db",
                "darktable/library.db", "darktable/data.db"):
        _db(root / rel)
    return root


def test_layout_finds_present_dbs(tmp_path):
    layout = cartridge_layout(_cartridge_layout_a(tmp_path / "cart"))
    assert set(layout.dbs) == {"photonforge", "training_weights", "dt_library", "dt_data"}


def test_layout_finds_portable_dt_config(tmp_path):
    """Layout B (portable drive) puts the DT catalog under dt-config/."""
    root = tmp_path / "cart"
    _db(root / "photonforge.db")
    _db(root / "dt-config/library.db")
    layout = cartridge_layout(root)
    assert set(layout.dbs) == {"photonforge", "dt_library"}
    assert layout.dbs["dt_library"].parent.name == "dt-config"


def test_layout_omits_absent_dbs(tmp_path):
    root = tmp_path / "cart"
    _db(root / "photonforge.db")
    assert set(cartridge_layout(root).dbs) == {"photonforge"}


def test_snapshot_copies_and_manifests(tmp_path):
    root = _cartridge_layout_a(tmp_path / "cart")
    dest = tmp_path / "snap"
    assert snapshot_databases(root, dest) == dest
    assert (dest / "photonforge.db").exists()
    assert (dest / "library.db").exists()          # basename, not the darktable/ path
    # VACUUM INTO produces a clean, queryable copy
    conn = sqlite3.connect(dest / "photonforge.db")
    assert conn.execute("SELECT x FROM t").fetchone()[0] == 1
    conn.close()
    manifest = json.loads((dest / "snapshot-manifest.json").read_text())
    assert manifest["kind"] == "catalog"
    assert manifest["schema"] == 1
    entry = manifest["dbs"]["photonforge"]
    assert entry["bytes"] > 0
    assert entry["sha256"] == sha256_file(dest / "photonforge.db")
    assert manifest["started_at"] and manifest["finished_at"]


def test_snapshot_raises_when_no_dbs(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        snapshot_databases(empty, tmp_path / "snap")


def test_timestamp_is_filename_safe_and_sortable():
    ts = snapshot_timestamp()
    assert ":" not in ts and len(ts) == 19
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_backup_snapshot.py -v`
Expected: FAIL with `ModuleNotFoundError: photo_workflow.backup`

- [ ] **Step 3: Implement**

```python
# src/photo_workflow/backup.py
"""Cartridge backup: catalog snapshots, cartridge mirrors, offsite archives.

Three tiers, ordered by dependency-freedom:

  Tier 1  snapshot_databases()  VACUUM INTO the SQLite catalogs (stdlib, offline)
  Tier 2  mirror_cartridge()    whole-cartridge plain tree + verified manifest (stdlib)
  Tier 3  archive()             restic repo, dedup + encrypted, local or cloud

Tiers 1-2 have no external dependencies: the disaster-recovery gap closes without
restic installed, and `migrate-fs` (portable-drive plan Task 4b) can read its own
safety net back with nothing but Python. See ADR-007 and the 2026-08-17 plan.

Nothing in this module may be imported by the pipeline (NFR-2.1) — backup is a
maintenance operation, never a pipeline operation.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

MANIFEST_NAME = "snapshot-manifest.json"
SCHEMA_VERSION = 1
SNAPSHOT_DIRNAME = ".photon-snapshots"

# key -> candidate paths relative to the cartridge root, first match wins.
# Layout A is the legacy host-Darktable tree; Layout B is the portable drive.
_DB_LAYOUT: dict[str, tuple[str, ...]] = {
    "photonforge":      ("photonforge.db",),
    "training_weights": ("training_weights.db",),
    "dt_library":       ("dt-config/library.db", "darktable/library.db"),
    "dt_data":          ("dt-config/data.db", "darktable/data.db"),
}


@dataclass
class CartridgeLayout:
    root: Path
    dbs: dict[str, Path]


def cartridge_layout(root: Path) -> CartridgeLayout:
    """The DBs that actually exist on this cartridge (Layout A or B)."""
    root = Path(root)
    dbs: dict[str, Path] = {}
    for key, candidates in _DB_LAYOUT.items():
        for rel in candidates:
            if (root / rel).exists():
                dbs[key] = root / rel
                break
    return CartridgeLayout(root=root, dbs=dbs)


def sha256_file(path: Path, chunk: int = 65536) -> str:
    """Streaming sha256 — never load a RAW or a DB fully into memory (NFR-2.2)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def snapshot_timestamp() -> str:
    """Colon-free UTC stamp: sorts chronologically and is filename-safe on exFAT."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


def _tool_version() -> str:
    try:
        from importlib.metadata import version
        return f"photo-workflow {version('photo-workflow')}"
    except Exception:      # not installed as a dist (editable/frozen) — best effort
        return "photo-workflow unknown"


def snapshot_databases(root: Path, dest_dir: Path, *, manifest: bool = True) -> Path:
    """VACUUM INTO every present DB under dest_dir.

    VACUUM INTO writes a defragmented, self-contained copy while readers stay live;
    a plain file copy of a DB mid-write can be torn. Snapshot filenames are basenames,
    so library.db/data.db land flat next to photonforge.db.
    """
    started = _utcnow()
    layout = cartridge_layout(root)
    if not layout.dbs:
        raise FileNotFoundError(f"No PHOTONForge/Darktable DBs found under {root}")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    entries: dict[str, dict] = {}
    for key, src in layout.dbs.items():
        out = dest_dir / src.name
        conn = sqlite3.connect(str(src))
        try:
            # VACUUM INTO takes no bind parameters; quote the path by doubling quotes.
            conn.execute("VACUUM INTO '{}'".format(str(out).replace("'", "''")))
        finally:
            conn.close()
        entries[key] = {
            "source": str(src),
            "snapshot": out.name,
            "bytes": out.stat().st_size,
            "sha256": sha256_file(out),      # hash the copy: the source is live
        }

    if manifest:
        write_manifest(dest_dir, {
            "kind": "catalog",
            "state_only": False,
            "cartridge": describe_cartridge(root),
            "started_at": started,
            "finished_at": _utcnow(),
            "dbs": entries,
        })
    logger.info("Snapshotted %d DB(s) into %s", len(entries), dest_dir)
    return dest_dir if manifest else entries      # Tier 2 wants the entries


def write_manifest(dest_dir: Path, body: dict) -> Path:
    path = Path(dest_dir) / MANIFEST_NAME
    payload = {"schema": SCHEMA_VERSION, "tool_version": _tool_version(), **body}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def describe_cartridge(root: Path) -> dict:
    """Label/id for the manifest; degrades gracefully off a real cartridge."""
    from .volume import extract_cartridge_id, get_volume_label
    try:
        label = get_volume_label(Path(root)) or ""
    except Exception:
        label = ""
    return {"label": label, "id": extract_cartridge_id(label) if label else "",
            "root": str(root)}
```

> **Note the dual return of `snapshot_databases`** — returning `dest_dir` with a manifest
> and the entries dict without one is the seam Tier 2 needs. If that reads badly during
> implementation, split into `_vacuum_dbs()` (returns entries) + `snapshot_databases()`
> (wraps it and writes the manifest); the tests above only pin the public behaviour.
> Check `volume.py`'s actual `get_volume_label`/`extract_cartridge_id` signatures before
> wiring `describe_cartridge` — adapt to what is there rather than to this sketch.

- [ ] **Step 4: Run tests, commit**

Run: `pytest tests/test_backup_snapshot.py -v` — Expected: PASS

```bash
git add src/photo_workflow/backup.py tests/test_backup_snapshot.py
git commit -m "feat(backup): cartridge layout + Tier-1 SQLite snapshot core"
```

---

### Task 2: `photo-cartridge snapshot` + rotation + safe-eject hook

**Files:**
- Modify: `src/photo_workflow/backup.py` (`rotate_snapshots`)
- Modify: `src/photo_workflow/cartridge.py` (`snapshot` subcommand)
- Modify: `scripts/safe_eject.sh` (optional pre-eject snapshot)
- Test: `tests/test_backup_snapshot.py`, `tests/test_cartridge_cli.py`

**Interfaces — produces:**
- `rotate_snapshots(snapshots_root: Path, keep: int) -> list[Path]` — delete oldest
  timestamped dirs beyond `keep`; return deleted paths. `keep <= 0` deletes nothing.
- CLI: `photo-cartridge snapshot <root> [--dest DIR] [--keep N] [--json]`.
  Default `--dest` is `<root>/.photon-snapshots`; default `--keep 7`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backup_snapshot.py (append)
from photo_workflow.backup import rotate_snapshots


def test_rotate_keeps_newest_n(tmp_path):
    snaproot = tmp_path / ".photon-snapshots"
    snaproot.mkdir()
    for name in ["2026-07-01T00-00-00", "2026-07-02T00-00-00",
                 "2026-07-03T00-00-00", "2026-07-04T00-00-00"]:
        (snaproot / name).mkdir()
    deleted = rotate_snapshots(snaproot, keep=2)
    assert sorted(p.name for p in snaproot.iterdir()) == [
        "2026-07-03T00-00-00", "2026-07-04T00-00-00"]
    assert len(deleted) == 2


def test_rotate_keep_zero_is_a_noop(tmp_path):
    snaproot = tmp_path / "s"
    (snaproot / "2026-07-01T00-00-00").mkdir(parents=True)
    assert rotate_snapshots(snaproot, keep=0) == []
    assert len(list(snaproot.iterdir())) == 1


def test_rotate_missing_root_is_a_noop(tmp_path):
    assert rotate_snapshots(tmp_path / "nope", keep=3) == []
```

```python
# tests/test_cartridge_cli.py
import json
import sqlite3
from click.testing import CliRunner
from photo_workflow.cartridge import main


def _cartridge(tmp_path):
    root = tmp_path / "cart"
    root.mkdir()
    conn = sqlite3.connect(root / "photonforge.db")
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()
    return root


def test_snapshot_command_creates_timestamped_dir(tmp_path):
    root = _cartridge(tmp_path)
    result = CliRunner().invoke(main, ["snapshot", str(root), "--keep", "3"])
    assert result.exit_code == 0, result.output
    snaps = list((root / ".photon-snapshots").iterdir())
    assert len(snaps) == 1
    assert (snaps[0] / "photonforge.db").exists()
    assert (snaps[0] / "snapshot-manifest.json").exists()


def test_snapshot_json_output_is_machine_readable(tmp_path):
    root = _cartridge(tmp_path)
    result = CliRunner().invoke(main, ["snapshot", str(root), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok" and payload["step"] == "snapshot"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_backup_snapshot.py tests/test_cartridge_cli.py -v`
Expected: FAIL (ImportError, then `no such command 'snapshot'`)

- [ ] **Step 3: Implement**

```python
# backup.py (append)
import shutil


def rotate_snapshots(snapshots_root: Path, keep: int) -> list[Path]:
    """Keep the newest `keep` timestamped snapshot dirs; delete the rest."""
    snapshots_root = Path(snapshots_root)
    if not snapshots_root.exists() or keep <= 0:
        return []
    dirs = sorted((p for p in snapshots_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    to_delete = dirs[:-keep]
    for d in to_delete:
        shutil.rmtree(d, ignore_errors=True)
        logger.info("Pruned old snapshot %s", d.name)
    return to_delete
```

```python
# cartridge.py (add to the existing `main` group)
@main.command("snapshot")
@click.argument("root", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--dest", type=click.Path(path_type=Path), default=None,
              help="Snapshot dir (default: <root>/.photon-snapshots)")
@click.option("--keep", default=7, show_default=True, help="Rotating snapshots to retain")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
def snapshot_cmd(root: Path, dest: Path | None, keep: int, as_json: bool) -> None:
    """Tier 1: VACUUM-copy the cartridge DBs into a rotating local snapshot."""
    import json as _json
    from .backup import SNAPSHOT_DIRNAME, rotate_snapshots, snapshot_databases, snapshot_timestamp
    snaproot = Path(dest) if dest else root / SNAPSHOT_DIRNAME
    target = snaproot / snapshot_timestamp()
    snapshot_databases(root, target)
    pruned = rotate_snapshots(snaproot, keep)
    if as_json:
        click.echo(_json.dumps({"step": "snapshot", "status": "ok",
                                "path": str(target), "pruned": len(pruned)}))
    else:
        click.echo(f"Snapshot written to {target} (pruned {len(pruned)} old).")
```

- [ ] **Step 4: Safe-eject hook**

Add an opt-in pre-eject snapshot to `scripts/safe_eject.sh`, guarded so a snapshot
failure never blocks the unmount (the whole point of safe-eject is getting the drive
out cleanly — a backup problem must not strand it):

```bash
# Best-effort catalog snapshot before unmount. Never blocks the eject.
if [ "${PHOTONFORGE_SNAPSHOT_ON_EJECT:-0}" = "1" ]; then
  photo-cartridge snapshot "$MOUNT_POINT" --keep "${PHOTONFORGE_SNAPSHOT_KEEP:-7}" \
    || echo "WARNING: pre-eject snapshot failed; continuing with unmount" >&2
fi
```

Keep ShellCheck clean. Read the real variable names in `safe_eject.sh` first — the
`$MOUNT_POINT` above is illustrative.

- [ ] **Step 5: Run tests, full suite, commit**

Run: `pytest tests/test_backup_snapshot.py tests/test_cartridge_cli.py -v && pytest -m "not slow" -q && ruff check .`

```bash
git add src/photo_workflow/backup.py src/photo_workflow/cartridge.py \
        scripts/safe_eject.sh tests/test_backup_snapshot.py tests/test_cartridge_cli.py
git commit -m "feat(backup): photo-cartridge snapshot with rotation + safe-eject hook"
```

---

### Task 3: busy-guard (shared with `migrate-fs`)

**Files:** Modify `src/photo_workflow/backup.py`; test `tests/test_backup_guard.py`

Backing up a cartridge mid-pipeline yields a mirror whose DB and photo tree disagree.
`migrate-fs` needs the identical check before a destructive reformat, so it lives here
and Task 4b imports it — do not write a second copy in `portable.py`.

**Interfaces — produces:**
- `class CartridgeBusy(RuntimeError)`
- `cartridge_busy_reason(root: Path) -> str | None` — first reason found, else `None`:
  a `.photonforge.pid` / `*.pid` lock file whose PID is alive; a DB that will not grant
  `BEGIN IMMEDIATE` within a short timeout; a non-empty `-wal` beside a catalog DB.
- `assert_cartridge_idle(root: Path, *, force: bool = False) -> None` — raises
  `CartridgeBusy` unless `force`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backup_guard.py
import sqlite3
import pytest
from photo_workflow.backup import CartridgeBusy, assert_cartridge_idle, cartridge_busy_reason


def _cart(tmp_path):
    root = tmp_path / "cart"
    root.mkdir()
    conn = sqlite3.connect(root / "photonforge.db")
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()
    return root


def test_idle_cartridge_passes(tmp_path):
    root = _cart(tmp_path)
    assert cartridge_busy_reason(root) is None
    assert_cartridge_idle(root)          # must not raise


def test_live_pid_file_blocks(tmp_path):
    import os
    root = _cart(tmp_path)
    (root / ".photonforge.pid").write_text(str(os.getpid()))
    assert "pid" in cartridge_busy_reason(root).lower()
    with pytest.raises(CartridgeBusy):
        assert_cartridge_idle(root)


def test_stale_pid_file_does_not_block(tmp_path):
    """A crashed run leaves a pid file behind; it must not strand the user."""
    root = _cart(tmp_path)
    (root / ".photonforge.pid").write_text("999999")     # not a live PID
    assert cartridge_busy_reason(root) is None


def test_write_locked_db_blocks(tmp_path):
    root = _cart(tmp_path)
    holder = sqlite3.connect(root / "photonforge.db")
    holder.execute("BEGIN IMMEDIATE")
    try:
        assert cartridge_busy_reason(root) is not None
        with pytest.raises(CartridgeBusy):
            assert_cartridge_idle(root)
        assert_cartridge_idle(root, force=True)          # --force overrides
    finally:
        holder.rollback()
        holder.close()
```

- [ ] **Step 2–3: Run (FAIL), then implement**

Notes for the implementer: probe liveness with `os.kill(pid, 0)` on POSIX and
`OpenProcess`/`tasklist` on Windows — or just treat an unparseable/unreachable PID as
stale, which is the safe direction (a stale lock must never permanently block backups).
Open the DB with `sqlite3.connect(..., timeout=0.5)` and catch `sqlite3.OperationalError`.

- [ ] **Step 4: Commit**

```bash
git add src/photo_workflow/backup.py tests/test_backup_guard.py
git commit -m "feat(backup): cartridge busy-guard shared with migrate-fs"
```

---

### Task 4: Tier-2 cartridge mirror (`backup` / `verify-backup` / `restore-backup`)

**This is the task that unblocks the portable-drive plan's Task 4b.**

**Files:**
- Modify: `src/photo_workflow/backup.py`
- Modify: `src/photo_workflow/cartridge.py`
- Test: `tests/test_backup_mirror.py`

**Interfaces — produces:**
- `STATE_ONLY_PATTERNS` / `ALWAYS_EXCLUDE` — see below.
- `supports_hardlinks(dest: Path) -> bool` — one real `os.link` probe in a temp file.
- `mirror_cartridge(root, dest, *, state_only=False, exclude_models=False, link_dest=None, keep=None, force=False, progress=None) -> Path`
  — copy into `<dest>/<label-or-'cartridge'>/<ts>/`, DBs via `snapshot_databases`,
  everything else by streaming copy (or `os.link` from `link_dest` when size+mtime match
  and hardlinks work), write `snapshot-manifest.json`, verify, then rotate. Returns the
  snapshot dir. Calls `assert_cartridge_idle` first.
- `verify_snapshot(snapshot: Path, *, against: Path | None = None) -> list[str]` —
  re-hash every manifest entry; return a list of discrepancy strings (empty = clean).
  With `against`, additionally compare to the live cartridge.
- `latest_snapshot(dest: Path, label: str | None = None) -> Path | None`
- `snapshot_is_fresh(snapshot: Path, root: Path) -> bool` — manifest `finished_at` is
  newer than the newest mtime on the cartridge. **This is the predicate `migrate-fs` gates on.**
- CLI:
  - `photo-cartridge backup <root> --dest DIR [--state-only] [--exclude-models] [--keep N] [--no-incremental] [--force] [--json]`
  - `photo-cartridge verify-backup <snapshot> [--against ROOT] [--json]`
  - `photo-cartridge restore-backup <snapshot> --to ROOT [--force] [--json]`

**File-set rules:**

```python
ALWAYS_EXCLUDE = (SNAPSHOT_DIRNAME, "*__preview.jpg", "*.mcp.json", "*.tmp",
                  "*.db-wal", "*.db-shm", "lost+found", "System Volume Information",
                  "$RECYCLE.BIN", ".Trash-*")
# --state-only: the small mutable state, no RAWs
STATE_ONLY_PATTERNS = ("*.db", "*.jsonl", "dt-config/**", "darktable/**", "**/*.xmp")
```

`*.db-wal` / `*.db-shm` are excluded because the DBs are captured by `VACUUM INTO`,
which folds the WAL in — copying a stale sidecar next to a vacuumed DB would corrupt
the restore. `restore-backup` must therefore never write a `-wal` into the target.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backup_mirror.py
import json
import sqlite3
import pytest
from photo_workflow import backup


def _cartridge(tmp_path):
    root = tmp_path / "PHOTON-004"
    (root / "ICELAND").mkdir(parents=True)
    (root / "models").mkdir()
    (root / "dt-config").mkdir()
    conn = sqlite3.connect(root / "photonforge.db")
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()
    (root / "ICELAND" / "DSC0001.ARW").write_bytes(b"rawdata" * 1000)
    (root / "ICELAND" / "DSC0001.xmp").write_text("<x:xmpmeta/>")
    (root / "ICELAND" / "DSC0001__preview.jpg").write_bytes(b"litter")
    (root / "genre_labels.jsonl").write_text('{"a":1}\n')
    (root / "models" / "big.onnx").write_bytes(b"0" * 5000)
    return root


def test_mirror_copies_tree_and_writes_manifest(tmp_path):
    root = _cartridge(tmp_path)
    snap = backup.mirror_cartridge(root, tmp_path / "backups")
    assert (snap / "ICELAND" / "DSC0001.ARW").read_bytes() == b"rawdata" * 1000
    assert (snap / "models" / "big.onnx").exists()        # models INCLUDED by default
    assert not (snap / "ICELAND" / "DSC0001__preview.jpg").exists()   # litter excluded
    conn = sqlite3.connect(snap / "photonforge.db")       # DB via VACUUM INTO
    assert conn.execute("SELECT x FROM t").fetchone()[0] == 42
    conn.close()
    manifest = json.loads((snap / backup.MANIFEST_NAME).read_text())
    assert manifest["kind"] == "mirror"
    assert manifest["state_only"] is False
    assert manifest["totals"]["files"] > 0
    assert manifest["dbs"]["photonforge"]["sha256"]


def test_mirror_verifies_clean(tmp_path):
    snap = backup.mirror_cartridge(_cartridge(tmp_path), tmp_path / "backups")
    assert backup.verify_snapshot(snap) == []


def test_verify_detects_tampering(tmp_path):
    snap = backup.mirror_cartridge(_cartridge(tmp_path), tmp_path / "backups")
    (snap / "ICELAND" / "DSC0001.ARW").write_bytes(b"corrupted")
    problems = backup.verify_snapshot(snap)
    assert problems and any("DSC0001.ARW" in p for p in problems)


def test_verify_detects_deletion(tmp_path):
    snap = backup.mirror_cartridge(_cartridge(tmp_path), tmp_path / "backups")
    (snap / "ICELAND" / "DSC0001.ARW").unlink()
    assert backup.verify_snapshot(snap)


def test_state_only_skips_raws_but_keeps_state(tmp_path):
    root = _cartridge(tmp_path)
    snap = backup.mirror_cartridge(root, tmp_path / "backups", state_only=True)
    assert not (snap / "ICELAND" / "DSC0001.ARW").exists()
    assert not (snap / "models" / "big.onnx").exists()
    assert (snap / "ICELAND" / "DSC0001.xmp").exists()
    assert (snap / "genre_labels.jsonl").exists()
    assert (snap / "photonforge.db").exists()
    assert json.loads((snap / backup.MANIFEST_NAME).read_text())["state_only"] is True


def test_exclude_models_flag(tmp_path):
    snap = backup.mirror_cartridge(_cartridge(tmp_path), tmp_path / "backups",
                                   exclude_models=True)
    assert not (snap / "models" / "big.onnx").exists()
    assert (snap / "ICELAND" / "DSC0001.ARW").exists()


def test_incremental_links_unchanged_files_when_supported(tmp_path):
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    first = backup.mirror_cartridge(root, dest)
    if not backup.supports_hardlinks(dest):
        pytest.skip("destination filesystem has no hardlinks")
    second = backup.mirror_cartridge(root, dest, link_dest=first)
    raw1, raw2 = first / "ICELAND/DSC0001.ARW", second / "ICELAND/DSC0001.ARW"
    assert raw2.stat().st_ino == raw1.stat().st_ino          # linked, not re-copied
    assert json.loads((second / backup.MANIFEST_NAME).read_text())["totals"]["linked"] > 0
    # the DB is re-vacuumed every run, never linked
    assert (second / "photonforge.db").stat().st_ino != (first / "photonforge.db").stat().st_ino


def test_no_hardlink_support_falls_back_to_copy(tmp_path, monkeypatch):
    """exFAT/FAT32 destinations: copy instead, and say so in the manifest."""
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    first = backup.mirror_cartridge(root, dest)
    monkeypatch.setattr(backup, "supports_hardlinks", lambda _dest: False)
    second = backup.mirror_cartridge(root, dest, link_dest=first)
    manifest = json.loads((second / backup.MANIFEST_NAME).read_text())
    assert manifest["hardlinks"] is False
    assert manifest["totals"]["linked"] == 0
    assert (second / "ICELAND/DSC0001.ARW").read_bytes() == b"rawdata" * 1000
    assert backup.verify_snapshot(second) == []


def test_retention_prunes_but_never_the_new_snapshot(tmp_path):
    root = _cartridge(tmp_path)
    dest = tmp_path / "backups"
    snaps = [backup.mirror_cartridge(root, dest, keep=2) for _ in range(4)]
    assert snaps[-1].exists()
    assert len(list(snaps[-1].parent.iterdir())) == 2


def test_mirror_refuses_when_busy(tmp_path):
    root = _cartridge(tmp_path)
    holder = sqlite3.connect(root / "photonforge.db")
    holder.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(backup.CartridgeBusy):
            backup.mirror_cartridge(root, tmp_path / "backups")
    finally:
        holder.rollback()
        holder.close()


def test_snapshot_is_fresh_predicate(tmp_path):
    """The gate migrate-fs uses: stale once the cartridge is written again."""
    root = _cartridge(tmp_path)
    snap = backup.mirror_cartridge(root, tmp_path / "backups")
    assert backup.snapshot_is_fresh(snap, root)
    (root / "ICELAND" / "DSC0002.ARW").write_bytes(b"new")
    assert not backup.snapshot_is_fresh(snap, root)


def test_restore_backup_round_trips(tmp_path):
    root = _cartridge(tmp_path)
    snap = backup.mirror_cartridge(root, tmp_path / "backups")
    target = tmp_path / "restored"
    backup.restore_snapshot(snap, target)
    conn = sqlite3.connect(target / "photonforge.db")
    assert conn.execute("SELECT x FROM t").fetchone()[0] == 42
    conn.close()
    assert (target / "ICELAND" / "DSC0001.ARW").read_bytes() == b"rawdata" * 1000
    assert not list(target.rglob("*.db-wal"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_backup_mirror.py -v` — Expected: FAIL (AttributeError)

- [ ] **Step 3: Implement**

Implementation notes rather than a full listing (this is the one genuinely new body of
code; write it test-first against the contract above):

- **Walk once**, building the file list with `os.walk` and pruning excluded dirs in
  place so `models/` and `.photon-snapshots/` are never descended into.
- **DBs first**, via `snapshot_databases(root, snap, manifest=False)`, and add their
  paths to a skip-set so the tree walk does not copy them again as ordinary files.
- **Copy** with `shutil.copyfile` + `shutil.copystat` (preserves mtime, which the
  incremental comparison depends on). Hash while copying rather than in a second pass —
  one read of each RAW, not two.
- **Link** when `link_dest` is given, `supports_hardlinks(dest)` is true, and the
  previous snapshot has the same relative path with matching size and mtime. Hash the
  linked file from the previous manifest entry instead of re-reading it — that is where
  the incremental speed actually comes from.
- **Verify before declaring success**: after writing the manifest, run
  `verify_snapshot(snap)` and raise if non-empty. A backup that was never verified is
  not a backup. `--keep` prunes only *after* a clean verify, and never the snapshot
  just written (`rotate_snapshots` on the sibling list minus the new dir).
- **Progress**: accept a `progress` callback so the CLI can print `n/total` without
  `backup.py` importing click.
- `restore_snapshot(snapshot, target, *, force=False)` copies the tree back, refuses a
  non-empty target without `--force`, and skips `snapshot-manifest.json` itself.

- [ ] **Step 4: CLI wiring**

```python
# cartridge.py (add)
@main.command("backup")
@click.argument("root", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--dest", required=True, type=click.Path(path_type=Path),
              help="Backup destination directory (a second drive)")
@click.option("--state-only", is_flag=True, help="DBs, corpus, dt-config and XMP only")
@click.option("--exclude-models", is_flag=True, help="Skip models/ (regenerable)")
@click.option("--keep", default=None, type=int, help="Prune to N snapshots after a clean verify")
@click.option("--no-incremental", is_flag=True, help="Do not hardlink against the previous snapshot")
@click.option("--force", is_flag=True, help="Proceed even if the cartridge looks busy")
@click.option("--json", "as_json", is_flag=True)
def backup_cmd(root, dest, state_only, exclude_models, keep, no_incremental, force, as_json):
    """Tier 2: verified whole-cartridge mirror to a second drive."""
    ...
```

`verify-backup` exits non-zero and prints each discrepancy when the list is non-empty —
it is meant to be usable from a script and from `migrate-fs`'s gate.

- [ ] **Step 5: Run tests, full suite, commit**

Run: `pytest tests/test_backup_mirror.py -v && pytest -m "not slow" -q && ruff check .`

```bash
git add src/photo_workflow/backup.py src/photo_workflow/cartridge.py tests/test_backup_mirror.py
git commit -m "feat(backup): Tier-2 verified cartridge mirror + verify/restore commands"
```

> **Gate:** with Tasks 1–4 merged, the portable-drive plan's Task 4b is unblocked.
> Task 4b must import `assert_cartridge_idle`, `mirror_cartridge`, `verify_snapshot`,
> and `snapshot_is_fresh` from `backup.py` — it writes no copy logic of its own.

---

### Task 5: Tier-3 restic builders (pure, no binary needed)

**Files:** Modify `src/photo_workflow/backup.py`; test `tests/test_backup_restic.py`

Splitting the pure argument/env builders from the subprocess layer keeps most of Tier 3
testable on a machine with no restic installed — only the round-trip in Task 6 needs the
binary.

**Interfaces — produces:**
- `resolve_restic(configured: str | None = None) -> str` — configured path, else
  `shutil.which("restic")`, else `RuntimeError` with an install hint.
- `restic_env(password_file: Path | None) -> dict[str, str]`
- `write_exclude_file(dest: Path) -> Path`
- `normalize_repo(repo: str, rclone_remote: str | None) -> str`
- `build_init_args` / `build_backup_args` / `build_restore_args` / `build_forget_args`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_backup_restic.py
import pytest
from photo_workflow import backup


def test_exclude_file_has_regenerable_patterns(tmp_path):
    text = backup.write_exclude_file(tmp_path / "ex.txt").read_text()
    for pat in ("models/", ".photon-snapshots/", "*__preview.jpg", "*.mcp.json"):
        assert pat in text


def test_build_backup_args_local(tmp_path):
    args = backup.build_backup_args("/mnt/repo", tmp_path, tmp_path / "ex.txt")
    assert args[:2] == ["-r", "/mnt/repo"]
    assert "backup" in args and str(tmp_path) in args
    assert "--compression" in args and "auto" in args
    assert "--exclude-file" in args


def test_normalize_repo_rclone_bridge():
    assert backup.normalize_repo("mydrive:photon", "gdrive") == "rclone:gdrive:mydrive:photon"
    assert backup.normalize_repo("/mnt/repo", None) == "/mnt/repo"
    assert backup.normalize_repo("s3:s3.amazonaws.com/bucket", None) == "s3:s3.amazonaws.com/bucket"


def test_resolve_restic_missing(monkeypatch):
    monkeypatch.setattr(backup.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="restic"):
        backup.resolve_restic(None)
```

- [ ] **Step 2: Run (FAIL: AttributeError), then implement**

```python
# backup.py (append)
import os

_EXCLUDE_PATTERNS = [
    "models/", SNAPSHOT_DIRNAME + "/", "*__preview.jpg", "*.mcp.json", "*.tmp",
    "*.db-wal", "*.db-shm",
]


def resolve_restic(configured: str | None = None) -> str:
    if configured:
        return configured
    found = shutil.which("restic")
    if not found:
        raise RuntimeError(
            "restic not found. Install it (https://restic.net) or set the restic "
            "path in the plugin's Lua options. Tiers 1-2 (snapshot/backup) work "
            "without it.")
    return found


def restic_env(password_file: Path | None) -> dict[str, str]:
    env = dict(os.environ)
    if password_file:
        env["RESTIC_PASSWORD_FILE"] = str(password_file)
    return env


def write_exclude_file(dest: Path) -> Path:
    dest = Path(dest)
    dest.write_text("\n".join(_EXCLUDE_PATTERNS) + "\n", encoding="utf-8")
    return dest


def normalize_repo(repo: str, rclone_remote: str | None) -> str:
    """Prefix rclone:<remote>: when a consumer-cloud remote is named."""
    if rclone_remote and not repo.startswith(("rclone:", "s3:", "b2:", "sftp:",
                                              "azure:", "gs:", "rest:")):
        return f"rclone:{rclone_remote}:{repo}"
    return repo


def build_init_args(repo: str) -> list[str]:
    return ["-r", repo, "init", "--repository-version", "2"]


def build_backup_args(repo: str, root: Path, exclude_file: Path,
                      compression: str = "auto") -> list[str]:
    return ["-r", repo, "backup", str(root),
            "--exclude-file", str(exclude_file), "--compression", compression]


def build_restore_args(repo: str, target: Path, snapshot: str = "latest") -> list[str]:
    return ["-r", repo, "restore", snapshot, "--target", str(target)]


def build_forget_args(repo: str, keep_last: int) -> list[str]:
    return ["-r", repo, "forget", "--keep-last", str(keep_last), "--prune"]
```

- [ ] **Step 3: Run tests, commit**

```bash
git add src/photo_workflow/backup.py tests/test_backup_restic.py
git commit -m "feat(backup): restic command/env builders + rclone repo normalization"
```

---

### Task 6: Tier-3 archive / restore / verify / forget + round-trip test

**Files:** Modify `src/photo_workflow/backup.py`, `src/photo_workflow/cartridge.py`;
test `tests/test_backup_restic.py`

**Interfaces — produces:**
- `run_restic(restic, args, env, echo=print) -> int` — stream output, return exit code.
- `repo_exists(restic, repo, env) -> bool` — `restic -r REPO cat config` exit 0.
- `archive(root, repo, *, password_file=None, restic_path=None, rclone_remote=None, init=False, keep_last=None, echo=print) -> int`
- `restore_archive(repo, target, *, snapshot="latest", ...) -> int`
- `verify_archive(repo, ...) -> int` (`restic check`); `forget_archive(repo, keep_last, ...) -> int`
- CLI: `archive`, `restore-archive`, `verify-archive`, `forget-archive` — all sharing a
  `_repo_opts` decorator (`--repo/-r`, `--password-file`, `--restic-path`, `--rclone-remote`).

- [ ] **Step 1: Write the failing round-trip test**

```python
# tests/test_backup_restic.py (append)
import shutil as _shutil
import sqlite3
import pytest
from photo_workflow import backup

restic_missing = _shutil.which("restic") is None


@pytest.mark.skipif(restic_missing, reason="restic binary not installed")
def test_archive_restore_round_trip(tmp_path):
    cart = tmp_path / "cart"
    (cart / "photos").mkdir(parents=True)
    (cart / "models").mkdir()
    conn = sqlite3.connect(cart / "photonforge.db")
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()
    (cart / "photos" / "IMG_1.ARW").write_bytes(b"rawdata" * 1000)
    (cart / "models" / "big.onnx").write_bytes(b"0" * 5000)

    repo = tmp_path / "repo"
    pw = tmp_path / "pw.txt"
    pw.write_text("test-password")

    assert backup.archive(cart, str(repo), password_file=pw, init=True) == 0

    dest = tmp_path / "restored"
    assert backup.restore_archive(str(repo), dest, password_file=pw) == 0

    # restic reconstructs the absolute source path under --target, and that path
    # differs per-OS; locate the DB rather than predicting where it landed.
    found = list(dest.rglob("photonforge.db"))
    assert found, "photonforge.db not restored"
    conn = sqlite3.connect(found[0])
    assert conn.execute("SELECT x FROM t").fetchone()[0] == 42
    conn.close()
    assert not list(dest.rglob("big.onnx"))          # models/ excluded from Tier 3


@pytest.mark.skipif(restic_missing, reason="restic binary not installed")
def test_verify_archive_passes_on_fresh_repo(tmp_path):
    ...
```

- [ ] **Step 2–3: Run (FAIL or SKIP), then implement**

```python
# backup.py (append)
import subprocess
import tempfile


def run_restic(restic: str, args: list[str], env: dict, echo=print) -> int:
    proc = subprocess.Popen([restic, *args], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        echo(line.rstrip())
    return proc.wait()


def repo_exists(restic: str, repo: str, env: dict) -> bool:
    return subprocess.run([restic, "-r", repo, "cat", "config"], env=env,
                          capture_output=True, text=True).returncode == 0


def archive(root, repo, *, password_file=None, restic_path=None, rclone_remote=None,
            init=False, keep_last=None, echo=print) -> int:
    restic = resolve_restic(restic_path)
    repo = normalize_repo(repo, rclone_remote)
    env = restic_env(password_file)
    if init and not repo_exists(restic, repo, env):
        rc = run_restic(restic, build_init_args(repo), env, echo)
        if rc != 0:
            return rc
    with tempfile.TemporaryDirectory() as td:
        ex = write_exclude_file(Path(td) / "exclude.txt")
        rc = run_restic(restic, build_backup_args(repo, Path(root), ex), env, echo)
    if rc == 0 and keep_last:
        rc = run_restic(restic, build_forget_args(repo, keep_last), env, echo)
    return rc
```

`restore_archive`, `verify_archive`, and `forget_archive` follow the same shape.

- [ ] **Step 4: CI must install restic**

Add restic to the test job in `.github/workflows/tests.yml` so the round-trip actually
runs instead of silently skipping — a skipped restore test proves nothing:

```yaml
      - name: Install restic (Tier-3 backup tests)
        run: sudo apt-get update && sudo apt-get install -y restic
```

Verify the packaged version is ≥ 0.16 (repo format v2 / compression); if the runner's
distro ships something older, download the release binary instead.

- [ ] **Step 5: Run tests, full suite, commit**

```bash
git add src/photo_workflow/backup.py src/photo_workflow/cartridge.py \
        tests/test_backup_restic.py .github/workflows/tests.yml
git commit -m "feat(backup): Tier-3 restic archive/restore/verify/forget + round-trip test"
```

---

### Task 7: Lua per-command gating + panel wiring

**Files:** Modify `lua/photonforge/runner.lua`, `lua/photonforge/panel.lua`,
`lua/photonforge/config.lua`

Today `runner.lua:343` has a single `CARTRIDGE_CMDS_IMPLEMENTED = false` that gates
provision, archive, and restore together. Flipping it would expose the still-stubbed
`provision` button, so it becomes a per-command table.

- [ ] **Step 1: Per-command gating**

```lua
-- Which photo-cartridge subcommands are implemented. provision is still stubbed.
local CARTRIDGE_IMPLEMENTED = {
  snapshot = true, backup = true, ["verify-backup"] = true,
  archive = true, ["restore-archive"] = true, ["verify-archive"] = true,
  provision = false,
}

local function cartridge_cmd_unavailable(name, log_fn)
  if CARTRIDGE_IMPLEMENTED[name] then return false end
  log_fn(string.format("[%s] photo-cartridge %s is not implemented yet.", name, name))
  dt.print("PHOTONForge: cartridge " .. name .. " is not available yet")
  return true
end
```

- [ ] **Step 2: New prefs in `config.lua`**

Add alongside the existing `backup_repo` / `backup_pwfile` (lines 22–23):

| name | label |
|---|---|
| `backup_dest` | Backup destination (second drive, for verified mirrors) |
| `snapshot_keep` | Catalog snapshots to keep |
| `restic_path` | restic binary path (blank = find on PATH) |
| `rclone_remote` | rclone remote name (cloud archives) |

- [ ] **Step 3: Fix the command strings and add the new launchers**

`backup_flags()` currently emits `-r <repo>`; extend it to pass `--restic-path` and
`--rclone-remote`, and keep the flag spellings **exactly** in step with Task 6's CLI —
these strings are the interface, and a typo here surfaces as "No such option" in a
terminal the user cannot scroll back. Add `M.launch_snapshot` (Tier 1, no repo needed),
`M.launch_backup` (Tier 2, uses `backup_dest`), and `M.launch_verify` (Tier 2 verify of
the newest snapshot). Point `launch_restore` at `restore-archive` and set
`elevated=false` — restore writes to an already-mounted cartridge; only `provision`
(volume-label set) needs elevation.

- [ ] **Step 4: Panel buttons**

In `panel.lua`'s cartridge strip, add **Snapshot** (📸, Tier 1) and **Backup** (💾,
Tier 2) next to the existing Provision/Archive/Restore, plus **Verify** (✔). Register
them in `cartridge_btns` so they disable mid-run. Tooltips must make the tier ordering
legible to a user who has never read this plan — e.g. Snapshot: *"Fast local copy of
the catalog databases. No second drive or extra software needed."*; Backup: *"Full
verified copy of the cartridge to another drive. The one to use before migrating."*

- [ ] **Step 5: Manual verification**

Per `dev-docs/architecture/doc-maintenance-protocol.md`, Lua changes require a re-deploy
(`scripts/deploy_lua.ps1` on Windows / re-copy on Linux). Confirm: Provision still
refuses; Snapshot writes `.photon-snapshots/<ts>/`; Backup writes a verified mirror to
`backup_dest`; Verify reports clean; Archive/Restore round-trip against a local repo.

- [ ] **Step 6: Commit**

```bash
git add lua/photonforge/runner.lua lua/photonforge/panel.lua lua/photonforge/config.lua
git commit -m "feat(panel): Snapshot/Backup/Verify buttons; per-command cartridge gating"
```

---

### Task 8: ADR + docs + issue close-out

**Files:**
- Create: `dev-docs/architecture/adr/ADR-007-cartridge-backup-tiers.md`
- Modify: `dev-docs/architecture/adr/index.md`
- Modify: `dev-docs/architecture/data-security-posture.md` (line 62 row)
- Create: `dev-docs/backup-and-restore-guide.md`
- Modify: `dev-docs/getting-started.md`, `CLAUDE.md` (Project Layout: `backup.py`),
  `dev-docs/architecture/system-architecture-contracts.md` (module table)

> **ADR numbering:** the 07-11 plan said "ADR-005", but 005 (`r2-captioner-lfm2`) and
> 006 (`per-type-weights-vs-scenerecord`) both exist. This is **ADR-007**. The
> portable-drive plan's `ADR-00X-exfat-cross-os-cartridge` is unnumbered and will
> collide — whichever merges second takes 008.

- [ ] **Step 1: Write ADR-007**, following `ADR-004`'s format:
  - **Context:** issue #131's DR gap; `migrate-fs` needs a plain-tree safety net; two
    plans proposed incompatible mechanisms; the payload is mostly incompressible RAW, so
    dedup-across-snapshots is the lever that matters and compression is secondary.
  - **Decision:** three tiers ordered by dependency-freedom (table above); one module;
    `VACUUM INTO` for every DB copy in every tier; Tier 2 mandatory and consumed by
    `migrate-fs`, Tier 3 optional.
  - **Alternatives considered:** restic-only (rejected — puts an external binary in the
    path of the destructive-migration safety net); mirror-only (rejected — no dedup, no
    encryption, no offsite, and orphans the shipped `backup_repo` prefs); Kopia (better
    UX, but would mean reworking the restic-shaped prefs and flags — rejected for churn);
    Borg (no native cloud, no Windows); plain tar+zstd (no dedup).
  - **Consequences:** Tier 3 needs an external binary (runtime-resolved, install step in
    the guide) and CI must install it; Tier 3 excludes `models/`, so an offsite restore
    is followed by a re-provision; hardlink incrementals degrade to full copies on exFAT;
    NFR-2.1 unaffected (maintenance-time only, no pipeline import).

- [ ] **Step 2: Flip the posture row.** `data-security-posture.md:62` currently reads
  *"**Open** — no automated backup today; tracked in issue #131"*. Replace with the
  three-tier mitigation, linking ADR-007 and the runbook.

- [ ] **Step 3: Write `backup-and-restore-guide.md`** — the runbook, tier by tier:
  Tier 1 (nothing to install; what it does and does not protect); Tier 2 as **the
  primary supported backup** (second-drive example, `--state-only` cadence vs full
  cadence, `verify-backup`, the exFAT/no-hardlinks note, and the restore drill); Tier 3
  (installing restic, optional `rclone config` for Google Drive/OneDrive, `archive` /
  `verify-archive` / `forget-archive` cadence, and the re-provision step for `models/`).
  Include the restore drill as a procedure the user can actually re-run — the Task-4 and
  Task-6 round-trip tests are its automated counterpart.

- [ ] **Step 4: Reopen and then close issue #131 properly.** It was auto-closed by
  PR #138 (which merged only the *plan document*) while all three of its acceptance
  boxes — an ADR, a test proving a restore round-trips, and the posture row — were
  still open. Reopen it, link this PR, and close it when Tasks 1–4 and 8 have landed.
  Post evidence via `sf-comment`, never by hand-editing AUTO-managed docs.

- [ ] **Step 5: Commit**

```bash
git add dev-docs/architecture/adr/ADR-007-cartridge-backup-tiers.md \
        dev-docs/architecture/adr/index.md \
        dev-docs/architecture/data-security-posture.md \
        dev-docs/architecture/system-architecture-contracts.md \
        dev-docs/backup-and-restore-guide.md dev-docs/getting-started.md CLAUDE.md
git commit -m "docs(backup): ADR-007, close issue #131 posture row, backup/restore runbook"
```

---

## Files at a glance

**Create:** `src/photo_workflow/backup.py`, `tests/test_backup_snapshot.py`,
`tests/test_backup_guard.py`, `tests/test_backup_mirror.py`,
`tests/test_backup_restic.py`, `tests/test_cartridge_cli.py`,
`dev-docs/architecture/adr/ADR-007-cartridge-backup-tiers.md`,
`dev-docs/backup-and-restore-guide.md`.

**Modify:** `src/photo_workflow/cartridge.py`, `scripts/safe_eject.sh`,
`lua/photonforge/{runner,panel,config}.lua`, `.github/workflows/tests.yml`,
`dev-docs/architecture/{data-security-posture,system-architecture-contracts}.md`,
`dev-docs/architecture/adr/index.md`, `dev-docs/getting-started.md`, `CLAUDE.md`.

## Verification (end-to-end)

1. `pytest -m "not slow" -q` green, `ruff check .` clean.
2. `pytest tests/test_backup_restic.py -v` — round-trip **runs** (not skips) in CI.
3. On a real cartridge: `photo-cartridge snapshot` → `.photon-snapshots/<ts>/` with a
   queryable `photonforge.db`; `photo-cartridge backup --dest <second drive>` →
   verified mirror; tamper with one file → `verify-backup` reports it and exits non-zero.
4. Restore drill: `restore-backup` into a scratch dir, open the restored
   `photonforge.db`, confirm scores/names/stage state intact.
5. Panel: Provision still refuses; the four implemented buttons resolve real commands.
6. **Only then** run the portable-drive plan's Task 4b against a real cartridge.

## Self-Review Notes

- **Both source plans are represented, neither wholesale.** The 07-11 plan contributed
  Tier 1, the restic tier, and the module boundary; Task 4a contributed the verified
  mirror, `--state-only`, the busy-guard, retention, and the `migrate-fs` gate. What is
  new here is the ordering, the shared `VACUUM INTO` primitive, and the unified manifest.
- **The exFAT/hardlink collision is a real bug caught in the merge**, not a nicety.
  Task 4a's incremental design would have failed on the first exFAT destination — which
  the portable-drive plan makes the *default* filesystem. Do not "simplify" the probe
  away.
- **Do not encrypt Tiers 1–2.** It would need a key present at safe-eject time,
  defeating the offline/instant property that makes Tier 1 worth having.
- **`models/` asymmetry is deliberate** (included in Tier 2, excluded in Tier 3) and
  is the kind of thing a later reader will try to "fix". The reason is in the ADR.
- **Tier 3 is genuinely optional.** If it slips a release, the DR gap is still closed
  and migration is still unblocked. Sequence accordingly; do not let restic packaging
  problems hold Tasks 1–4.
- **`provision` stays stubbed.** The per-command gate means enabling four commands does
  not expose the fifth. Implementing `provision` (volume-label set, elevated) is a
  separate small follow-up.
- **Verify-before-success is load-bearing.** `mirror_cartridge` verifies and only then
  prunes. An unverified copy that pruned the last good snapshot is worse than no backup.
- **Restore path reconstruction differs across OSes** for Tier 3 (restic rebuilds the
  absolute source path inside `--target`); the round-trip test locates the DB with
  `rglob` rather than predicting the path, so it passes on Windows and Linux alike.
