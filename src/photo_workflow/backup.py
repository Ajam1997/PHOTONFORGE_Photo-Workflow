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

import hashlib
import json
import logging
import shutil
import sqlite3
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


def _vacuum_dbs(root: Path, dest_dir: Path) -> dict[str, dict]:
    """VACUUM INTO every present DB under dest_dir; return the manifest entries.

    VACUUM INTO writes a defragmented, self-contained copy while readers stay live;
    a plain file copy of a DB mid-write can be torn. Snapshot filenames are
    basenames, so library.db/data.db land flat next to photonforge.db.
    """
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


def rotate_snapshots(snapshots_root: Path, keep: int) -> list[Path]:
    """Keep the newest `keep` timestamped snapshot dirs; delete the rest.

    Sorting is lexicographic, which is chronological for snapshot_timestamp()
    names. Loose files are ignored — only directories are candidates.
    """
    snapshots_root = Path(snapshots_root)
    if not snapshots_root.exists() or keep <= 0:
        return []
    dirs = sorted((p for p in snapshots_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    to_delete = dirs[:-keep]
    for path in to_delete:
        shutil.rmtree(path, ignore_errors=True)
        logger.info("Pruned old snapshot %s", path.name)
    return to_delete
