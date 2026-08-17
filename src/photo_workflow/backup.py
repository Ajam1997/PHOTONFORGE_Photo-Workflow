"""Cartridge backup: catalog snapshots, cartridge mirrors, offsite archives.

Three tiers, ordered by dependency-freedom:

  Tier 1  snapshot_databases()  VACUUM INTO the SQLite catalogs (stdlib, offline)
  Tier 2  mirror_cartridge()    whole-cartridge plain tree + verified manifest (stdlib)
  Tier 3  archive()             restic repo, dedup + encrypted, local or cloud

Tiers 1-2 have no external dependencies: the disaster-recovery gap closes without
restic installed, and ``migrate-fs`` (portable-drive plan Task 4b) can read its own
safety net back with nothing but Python. See ADR-007 and the 2026-08-17 plan.

Nothing in this module may be imported by the pipeline (NFR-2.1) — backup is a
maintenance operation, never a pipeline operation.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

MANIFEST_NAME = "snapshot-manifest.json"
SCHEMA_VERSION = 1
SNAPSHOT_DIRNAME = ".photon-snapshots"

# key -> candidate paths relative to the cartridge root, first match wins.
# Layout A is the legacy host-Darktable tree; Layout B is the portable drive
# (canonical per the portable-drive plan). A migrated cartridge may carry both,
# so dt-config/ is probed first.
_DB_LAYOUT: dict[str, tuple[str, ...]] = {
    "photonforge": ("photonforge.db",),
    "training_weights": ("training_weights.db",),
    "dt_library": ("dt-config/library.db", "darktable/library.db"),
    "dt_data": ("dt-config/data.db", "darktable/data.db"),
}


@dataclass
class CartridgeLayout:
    """The PHOTONForge/Darktable databases present on a cartridge."""

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
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def utcnow() -> str:
    """ISO-8601 UTC instant, for manifest timestamps."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def snapshot_timestamp() -> str:
    """Colon-free UTC stamp: sorts chronologically and is filename-safe on exFAT."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")


def tool_version() -> str:
    """Best-effort version string for the manifest's provenance record."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return f"photo-workflow {version('photo-workflow')}"
    except PackageNotFoundError:  # not installed as a dist (frozen) — best effort
        return "photo-workflow unknown"


def describe_cartridge(root: Path) -> dict[str, str]:
    """Label/id for the manifest; degrades gracefully off a real cartridge."""
    from .volume import extract_cartridge_id, get_volume_label

    try:
        label = get_volume_label(Path(root)) or ""
    except Exception as exc:  # noqa: BLE001 - provenance, never a reason to fail a backup
        logger.debug("Could not read volume label for %s: %s", root, exc)
        label = ""
    return {
        "label": label,
        "id": extract_cartridge_id(label) if label else "",
        "root": str(root),
    }


def write_manifest(dest_dir: Path, body: dict) -> Path:
    """Write snapshot-manifest.json, stamping schema + tool version."""
    path = Path(dest_dir) / MANIFEST_NAME
    payload = {"schema": SCHEMA_VERSION, "tool_version": tool_version(), **body}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _vacuum_dbs(root: Path, dest_dir: Path, *, flatten: bool = True) -> dict[str, dict]:
    """VACUUM INTO every present DB under dest_dir; return the manifest entries.

    VACUUM INTO writes a defragmented, self-contained copy while readers stay live;
    a plain file copy of a DB mid-write can be torn.

    `flatten` controls placement, and the two tiers genuinely differ:

    * Tier 1 flattens to basenames, so library.db/data.db land next to
      photonforge.db — a rescue copy you grab by hand.
    * Tier 2 must NOT flatten. Its mirror is what migrate-fs copies back onto a
      reformatted cartridge; moving dt-config/library.db to the root would
      leave Darktable unable to find its catalog.
    """
    root = Path(root)
    layout = cartridge_layout(root)
    if not layout.dbs:
        raise FileNotFoundError(f"No PHOTONForge/Darktable DBs found under {root}")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    entries: dict[str, dict] = {}
    for key, src in layout.dbs.items():
        rel = Path(src.name) if flatten else src.relative_to(root)
        out = dest_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(src))
        try:
            # VACUUM INTO takes no bind parameters; quote the path by doubling quotes.
            conn.execute("VACUUM INTO '{}'".format(str(out).replace("'", "''")))
        finally:
            conn.close()
        entries[key] = {
            "source": str(src),
            "snapshot": rel.as_posix(),
            "bytes": out.stat().st_size,
            "sha256": sha256_file(out),  # hash the copy: the source is live
        }
    logger.info("Snapshotted %d DB(s) into %s", len(entries), dest_dir)
    return entries


def snapshot_databases(root: Path, dest_dir: Path) -> Path:
    """Tier 1: VACUUM-copy the cartridge catalogs into dest_dir with a manifest."""
    started = utcnow()
    entries = _vacuum_dbs(root, dest_dir)
    write_manifest(
        dest_dir,
        {
            "kind": "catalog",
            "state_only": False,
            "cartridge": describe_cartridge(root),
            "started_at": started,
            "finished_at": utcnow(),
            "dbs": entries,
        },
    )
    return Path(dest_dir)


class CartridgeBusy(RuntimeError):
    """The cartridge is mid-pipeline; backing it up would capture a torn state."""


def _pid_is_alive(pid: int) -> bool:
    """Best-effort liveness probe. Unknown => treat as dead.

    A stale lock file must never permanently block backups, so every
    uncertainty resolves toward "not running".
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, check=False,
        )
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except OSError:
        return False
    return True


def cartridge_busy_reason(root: Path) -> str | None:
    """Why this cartridge is busy, or None if it is idle.

    Two independent signals: a lock file naming a live process, and a catalog
    DB that will not grant a write transaction.
    """
    root = Path(root)
    for lock in sorted(root.glob("*.pid")):
        try:
            pid = int(lock.read_text().strip())
        except (ValueError, OSError):
            continue  # unparseable lock is a stale lock
        if _pid_is_alive(pid):
            return f"pid file {lock.name} names live process {pid}"

    for src in cartridge_layout(root).dbs.values():
        conn = None
        try:
            conn = sqlite3.connect(str(src), timeout=0.5)
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
        except sqlite3.OperationalError as exc:
            return f"{src.name} is write-locked ({exc})"
        finally:
            if conn is not None:
                conn.close()
    return None


def assert_cartridge_idle(root: Path, *, force: bool = False) -> None:
    """Raise CartridgeBusy unless the cartridge is idle (or force is set)."""
    reason = cartridge_busy_reason(root)
    if reason is None:
        return
    if force:
        logger.warning("Proceeding on a busy cartridge (--force): %s", reason)
        return
    raise CartridgeBusy(
        f"Cartridge at {root} looks busy: {reason}. "
        "Close Darktable and any running pipeline, or pass --force."
    )


def rotate_snapshots(snapshots_root: Path, keep: int,
                     protect: Path | None = None) -> list[Path]:
    """Keep the newest `keep` timestamped snapshot dirs; delete the rest.

    Sorting is lexicographic, which is chronological for snapshot_timestamp()
    names. Loose files are ignored — only directories are candidates.

    `protect` is never deleted regardless of where it sorts. Callers pass the
    snapshot they just wrote: a backup that pruned the last known-good copy
    and kept only itself is worse than no backup at all.
    """
    snapshots_root = Path(snapshots_root)
    if not snapshots_root.exists() or keep <= 0:
        return []
    dirs = sorted((p for p in snapshots_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    to_delete = dirs[:-keep]
    if protect is not None:
        protect = Path(protect)
        to_delete = [p for p in to_delete if p != protect]
    for path in to_delete:
        shutil.rmtree(path, ignore_errors=True)
        logger.info("Pruned old snapshot %s", path.name)
    return to_delete


# ---------------------------------------------------------------------------
# Tier 2 — verified whole-cartridge mirror
# ---------------------------------------------------------------------------

# Directory names never worth mirroring: our own Tier-1 output plus OS litter.
_EXCLUDE_DIRS = frozenset({
    SNAPSHOT_DIRNAME, "lost+found", "System Volume Information", "$RECYCLE.BIN",
})
# Glob patterns for files never worth mirroring. The -wal/-shm sidecars are
# excluded because the DBs are captured by VACUUM INTO, which folds the WAL in;
# copying a stale sidecar next to a vacuumed DB would corrupt the restore.
_EXCLUDE_FILES = ("*__preview.jpg", "*.mcp.json", "*.tmp", "*.db-wal", "*.db-shm")
# --state-only: the small mutable state, no RAWs.
_STATE_ONLY_SUFFIXES = frozenset({".db", ".jsonl", ".xmp"})
_STATE_ONLY_DIRS = frozenset({"dt-config", "darktable"})


def supports_hardlinks(dest: Path) -> bool:
    """Probe the destination filesystem with a real os.link attempt.

    exFAT and FAT32 have no hardlinks, and exFAT is the portable-drive
    default, so link-dest incrementals must degrade rather than fail.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    probe = dest / ".photon-link-probe"
    linked = dest / ".photon-link-probe-2"
    try:
        probe.write_bytes(b"")
        linked.unlink(missing_ok=True)
        os.link(probe, linked)
        return True
    except (OSError, NotImplementedError):
        return False
    finally:
        probe.unlink(missing_ok=True)
        linked.unlink(missing_ok=True)


def _is_excluded_file(name: str) -> bool:
    return any(fnmatch.fnmatch(name, pat) for pat in _EXCLUDE_FILES)


def _wanted_for_state_only(rel: Path) -> bool:
    if rel.suffix.lower() in _STATE_ONLY_SUFFIXES:
        return True
    return bool(rel.parts) and rel.parts[0] in _STATE_ONLY_DIRS


def _iter_payload(root: Path, *, state_only: bool, exclude_models: bool,
                  skip: set[Path]) -> Iterator[tuple[Path, Path]]:
    """Yield (absolute, relative) for every file that belongs in the mirror."""
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        rel_dir = here.relative_to(root)
        # prune in place so excluded trees are never descended into
        dirnames[:] = [
            d for d in dirnames
            if d not in _EXCLUDE_DIRS
            and not d.startswith(".Trash-")
            and not (exclude_models and rel_dir == Path(".") and d == "models")
            and not (state_only and rel_dir == Path(".") and d == "models")
        ]
        dirnames.sort()
        for name in sorted(filenames):
            src = here / name
            rel = rel_dir / name if rel_dir != Path(".") else Path(name)
            if src in skip or _is_excluded_file(name):
                continue
            if state_only and not _wanted_for_state_only(rel):
                continue
            yield src, rel


def _copy_and_hash(src: Path, dst: Path, chunk: int = 65536) -> tuple[int, str]:
    """Stream src to dst, hashing as we go — one read, not two (NFR-2.2)."""
    digest = hashlib.sha256()
    total = 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        for block in iter(lambda: fin.read(chunk), b""):
            digest.update(block)
            fout.write(block)
            total += len(block)
    shutil.copystat(src, dst)      # preserve mtime: the incremental compare needs it
    return total, digest.hexdigest()


def _unique_snapshot_dir(parent: Path) -> Path:
    """A fresh timestamped dir that sorts strictly after every existing sibling.

    Two runs inside the same second collide, so the stamp gets a numeric
    suffix. The suffix is derived from the highest sibling sharing the stamp,
    NOT from the first free name: retention can delete the bare stamp, and
    reusing that freed name would produce a "newest" snapshot that sorts
    oldest — which rotation would then immediately prune.
    """
    parent.mkdir(parents=True, exist_ok=True)
    stamp = snapshot_timestamp()
    siblings = {p.name for p in parent.iterdir() if p.is_dir() and p.name.startswith(stamp)}
    if not siblings:
        return parent / stamp
    highest = 0
    for name in siblings:
        suffix = name[len(stamp):]
        if suffix.startswith("-") and suffix[1:].isdigit():
            highest = max(highest, int(suffix[1:]))
    return parent / f"{stamp}-{highest + 1}"


def _read_manifest(snapshot: Path) -> dict:
    return json.loads((Path(snapshot) / MANIFEST_NAME).read_text(encoding="utf-8"))


def _previous_index(link_dest: Path | None) -> dict[str, dict]:
    """Relpath -> manifest entry for the previous snapshot, for link-dest."""
    if link_dest is None:
        return {}
    try:
        manifest = _read_manifest(link_dest)
    except (OSError, ValueError):
        return {}
    return {entry["path"]: entry for entry in manifest.get("files", [])}


def cartridge_backup_name(root: Path) -> str:
    """Per-cartridge directory name under the backup destination."""
    label = describe_cartridge(root).get("label") or ""
    return label or Path(root).resolve().name or "cartridge"


def mirror_cartridge(root: Path, dest: Path, *, state_only: bool = False,
                     exclude_models: bool = False, link_dest: Path | None = None,
                     keep: int | None = None, force: bool = False,
                     progress: Callable[[int, int, Path], None] | None = None) -> Path:
    """Tier 2: verified whole-cartridge mirror into <dest>/<cartridge>/<timestamp>/.

    DBs go through VACUUM INTO; everything else is copied (or hardlinked from
    link_dest when the file is unchanged and the filesystem supports links).
    The mirror is verified before it is declared good, and retention only runs
    after a clean verify — an unverified copy that pruned the last known-good
    snapshot is worse than no backup at all.
    """
    root = Path(root)
    assert_cartridge_idle(root, force=force)
    started = utcnow()
    started_epoch = time.time()

    snap_parent = Path(dest) / cartridge_backup_name(root)
    snapshot = _unique_snapshot_dir(snap_parent)
    snapshot.mkdir(parents=True, exist_ok=True)

    # flatten=False: this mirror gets restored onto a real cartridge.
    db_entries = _vacuum_dbs(root, snapshot, flatten=False)
    skip = {Path(entry["source"]) for entry in db_entries.values()}

    # Probe regardless of whether we have a link source, so the manifest's
    # "hardlinks" field describes the destination filesystem rather than
    # whether this particular run happened to have a previous snapshot.
    fs_hardlinks = supports_hardlinks(Path(dest))
    can_link = bool(link_dest) and fs_hardlinks
    previous = _previous_index(link_dest) if can_link else {}

    payload = list(_iter_payload(root, state_only=state_only,
                                 exclude_models=exclude_models, skip=skip))
    files: list[dict] = []
    linked = copied = total_bytes = 0
    for index, (src, rel) in enumerate(payload, start=1):
        dst = snapshot / rel
        stat = src.stat()
        key = rel.as_posix()
        prior = previous.get(key)
        reuse = (
            prior is not None
            and prior.get("bytes") == stat.st_size
            and abs(float(prior.get("mtime", -1)) - stat.st_mtime) < 1e-6
            and link_dest is not None
            and (Path(link_dest) / rel).exists()
        )
        if reuse:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.link(Path(link_dest) / rel, dst)
            size, digest = stat.st_size, prior["sha256"]
            linked += 1
        else:
            size, digest = _copy_and_hash(src, dst)
            copied += 1
        total_bytes += size
        files.append({"path": key, "bytes": size, "mtime": stat.st_mtime, "sha256": digest})
        if progress is not None:
            progress(index, len(payload), rel)

    write_manifest(snapshot, {
        "kind": "mirror",
        "state_only": state_only,
        "exclude_models": exclude_models,
        "cartridge": describe_cartridge(root),
        "started_at": started,
        "finished_at": utcnow(),
        "finished_at_epoch": time.time(),
        "started_at_epoch": started_epoch,
        "hardlinks": fs_hardlinks,
        "link_dest": Path(link_dest).name if link_dest else None,
        "totals": {"files": len(files), "bytes": total_bytes,
                   "linked": linked, "copied": copied},
        "dbs": db_entries,
        "files": files,
    })

    problems = verify_snapshot(snapshot)
    if problems:
        raise RuntimeError(
            f"Mirror at {snapshot} failed verification:\n  " + "\n  ".join(problems[:10])
        )
    logger.info("Mirrored %d file(s) (%d linked) into %s", len(files), linked, snapshot)
    if keep:
        rotate_snapshots(snap_parent, keep, protect=snapshot)
    return snapshot


def verify_snapshot(snapshot: Path, *, against: Path | None = None) -> list[str]:
    """Re-hash every manifest entry. Returns discrepancies; empty means clean."""
    snapshot = Path(snapshot)
    problems: list[str] = []
    try:
        manifest = _read_manifest(snapshot)
    except FileNotFoundError:
        return [f"{MANIFEST_NAME} missing from {snapshot}"]
    except ValueError as exc:
        return [f"{MANIFEST_NAME} is unreadable: {exc}"]

    for key, entry in manifest.get("dbs", {}).items():
        path = snapshot / entry["snapshot"]
        if not path.exists():
            problems.append(f"{entry['snapshot']}: missing (db {key})")
        elif sha256_file(path) != entry["sha256"]:
            problems.append(f"{entry['snapshot']}: checksum mismatch (db {key})")

    for entry in manifest.get("files", []):
        path = snapshot / entry["path"]
        if not path.exists():
            problems.append(f"{entry['path']}: missing")
            continue
        if path.stat().st_size != entry["bytes"]:
            problems.append(f"{entry['path']}: size mismatch")
        elif sha256_file(path) != entry["sha256"]:
            problems.append(f"{entry['path']}: checksum mismatch")

    if against is not None:
        against = Path(against)
        for entry in manifest.get("files", []):
            live = against / entry["path"]
            if not live.exists():
                problems.append(f"{entry['path']}: gone from the live cartridge")
            elif live.stat().st_size != entry["bytes"]:
                problems.append(f"{entry['path']}: differs from the live cartridge")
    return problems


def latest_snapshot(dest: Path, label: str | None = None) -> Path | None:
    """Newest snapshot under dest, optionally restricted to one cartridge."""
    dest = Path(dest)
    if not dest.exists():
        return None
    roots = [dest / label] if label else [p for p in dest.iterdir() if p.is_dir()]
    candidates = [
        snap
        for cartridge_dir in roots if cartridge_dir.is_dir()
        for snap in cartridge_dir.iterdir()
        if snap.is_dir() and (snap / MANIFEST_NAME).exists()
    ]
    return max(candidates, key=lambda p: p.name) if candidates else None


def snapshot_is_fresh(snapshot: Path, root: Path) -> bool:
    """True when nothing on the cartridge has been written since the snapshot.

    This is the predicate migrate-fs gates on: reformatting is destructive, so
    the safety net must postdate the last write it is supposed to protect.
    """
    try:
        manifest = _read_manifest(snapshot)
    except (OSError, ValueError):
        return False
    finished = manifest.get("finished_at_epoch")
    if finished is None:
        return False
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in _EXCLUDE_DIRS and not d.startswith(".Trash-")
        ]
        here = Path(dirpath)
        for name in filenames:
            if _is_excluded_file(name):
                continue
            try:
                if (here / name).stat().st_mtime > finished:
                    return False
            except OSError:
                continue
    return True


def restore_snapshot(snapshot: Path, target: Path, *, force: bool = False) -> Path:
    """Copy a Tier-2 mirror back onto a cartridge (or a scratch dir).

    The manifest is metadata, not payload, so it is not restored.
    """
    snapshot, target = Path(snapshot), Path(target)
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(
            f"{target} is not empty; pass force=True to restore over it"
        )
    target.mkdir(parents=True, exist_ok=True)
    for src in sorted(snapshot.rglob("*")):
        rel = src.relative_to(snapshot)
        if rel.name == MANIFEST_NAME:
            continue
        dst = target / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            shutil.copystat(src, dst)
    logger.info("Restored %s into %s", snapshot, target)
    return target
