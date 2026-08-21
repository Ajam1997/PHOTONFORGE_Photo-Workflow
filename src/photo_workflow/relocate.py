"""Safe move/migrate of already-ingested photos between shoot folders.

Cartridge Manager plan, Task 1 (`dev-docs/superpowers/plans/2026-08-21-cartridge-manager-plan.md`).
Moves a photo (or a whole shoot folder) to a new location, renaming it to
the destination's naming convention, and keeps three things in lockstep:
the file on disk, its row in `photonforge.db`, and its row in Darktable's
`library.db`/`data.db` if one exists.

**Same-cartridge only in this version.** Moving between shoot folders on
one drive is an UPDATE-in-place on both DBs — real-Darktable-schema
research (see the plan doc) found that `history`, `history_hash`,
`masks_history`, `tagged_images`, `color_labels`, and `selected_images` all
key off the numeric `images.id`, never off filename or path, so a photo's
edits/tags/color-label survive automatically as long as the row is never
deleted and reinserted. Moving to a *different* cartridge means crossing
into a different `library.db` file entirely — a harder algorithm (copy the
row plus every related row, remap tag ids by name since data.db's tag ids
are independent per cartridge, then delete the source) that has not been
built or schema-verified yet; `move_photos`/`move_shoot_folder` raise
`CrossCartridgeNotSupportedError` rather than attempt it half-verified.

Never called from a pipeline stage (NFR-2.1) — this is a maintenance-time
operation, like `backup.py`, which it reuses for the pre-move snapshot.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .backup import (
    SNAPSHOT_DIRNAME,
    CartridgeBusy,
    cartridge_layout,
    sha256_file,
    snapshot_databases,
    snapshot_timestamp,
)
from .backup import assert_cartridge_idle as _assert_cartridge_idle
from .darktable_bridge import _open_dt, xmp_sidecar_path
from .photondb import ensure_schema, open_db
from .raw_loader import IMAGE_EXTENSIONS
from .volume import derive_trip_code, format_photo_name, get_next_sequence

logger = logging.getLogger(__name__)

INTENT_LOG_NAME = "move-in-progress.json"
MOVE_LOG_NAME = "move-log.jsonl"
INTENT_SCHEMA_VERSION = 1

# Target states, in order. A target only ever moves forward.
_STATE_ORDER = ("planned", "copied", "verified", "db_updated", "done")


class RelocateError(RuntimeError):
    """Base for every error this module raises on purpose."""


class GroupConflictError(RelocateError):
    """A requested photo is Darktable-grouped with a photo not in the move."""


class CrossCartridgeNotSupportedError(RelocateError):
    """Source and destination resolve to different cartridge roots.

    Not a missing feature stub in the sense of "will crash weirdly" — this
    is deliberately unimplemented (see module docstring) rather than
    attempted against an unverified algorithm.
    """


def assert_cartridge_idle(root: Path, *, force: bool = False) -> None:
    """backup.assert_cartridge_idle, re-raising CartridgeBusy as a RelocateError.

    Callers of this module should only ever need to catch RelocateError —
    not know that the busy-check happens to live in backup.py.
    """
    try:
        _assert_cartridge_idle(root, force=force)
    except CartridgeBusy as exc:
        raise RelocateError(str(exc)) from exc


class MoveInProgressError(RelocateError):
    """An intent log already exists and has not reached 'done'.

    Call resume_move() on it (or delete it by hand after confirming by eye
    that its 'done'-adjacent state is actually safe to discard) before
    starting a new move on this cartridge.
    """


@dataclass
class RelocateTarget:
    """One photo's move, fully resolved before any action starts."""

    src_path: Path
    dest_path: Path
    src_xmp: Path | None
    dest_xmp: Path | None
    state: str = "planned"

    def to_json(self) -> dict:
        return {
            "src_path": str(self.src_path),
            "dest_path": str(self.dest_path),
            "src_xmp": str(self.src_xmp) if self.src_xmp else None,
            "dest_xmp": str(self.dest_xmp) if self.dest_xmp else None,
            "state": self.state,
        }

    @classmethod
    def from_json(cls, data: dict) -> RelocateTarget:
        return cls(
            src_path=Path(data["src_path"]),
            dest_path=Path(data["dest_path"]),
            src_xmp=Path(data["src_xmp"]) if data.get("src_xmp") else None,
            dest_xmp=Path(data["dest_xmp"]) if data.get("dest_xmp") else None,
            state=data.get("state", "planned"),
        )


@dataclass
class RelocatePlan:
    """What preflight resolves before anything destructive happens."""

    targets: list[RelocateTarget]
    source_dir: Path
    dest_dir: Path
    cartridge_root: Path
    intent_log_path: Path


@dataclass
class RelocateResult:
    moved: list[tuple[Path, Path]] = field(default_factory=list)
    snapshot: Path | None = None
    dry_run: bool = False


def _cartridge_root_for(shoot_dir: Path) -> Path:
    """Layout B: a shoot folder's parent is the cartridge root."""
    return shoot_dir.parent


def _is_photo(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS and not path.name.endswith(".xmp")


def _write_intent_log(plan: RelocatePlan) -> None:
    plan.intent_log_path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema": INTENT_SCHEMA_VERSION,
        "source_dir": str(plan.source_dir),
        "dest_dir": str(plan.dest_dir),
        "cartridge_root": str(plan.cartridge_root),
        "targets": [t.to_json() for t in plan.targets],
    }
    plan.intent_log_path.write_text(json.dumps(body, indent=2), encoding="utf-8")


def _read_intent_log(path: Path) -> RelocatePlan:
    data = json.loads(path.read_text(encoding="utf-8"))
    return RelocatePlan(
        targets=[RelocateTarget.from_json(t) for t in data["targets"]],
        source_dir=Path(data["source_dir"]),
        dest_dir=Path(data["dest_dir"]),
        cartridge_root=Path(data["cartridge_root"]),
        intent_log_path=path,
    )


def _append_move_log(cartridge_root: Path, target: RelocateTarget, sha256: str) -> None:
    dot_dir = cartridge_root / ".photonforge"
    dot_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "src": str(target.src_path),
        "dest": str(target.dest_path),
        "sha256": sha256,
    }
    with open(dot_dir / MOVE_LOG_NAME, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# Darktable group resolution
# ---------------------------------------------------------------------------


def _group_members(conn: sqlite3.Connection, image_id: int) -> list[int]:
    """Every images.id sharing image_id's group, including itself."""
    row = conn.execute("SELECT group_id FROM images WHERE id=?", (image_id,)).fetchone()
    if row is None:
        return []
    gid = row["group_id"]
    if gid is None:
        return [image_id]
    rows = conn.execute("SELECT id FROM images WHERE group_id=?", (gid,)).fetchall()
    ids = [r["id"] for r in rows]
    return ids or [image_id]


def _ungroup_image(conn: sqlite3.Connection, image_id: int) -> None:
    """Split image_id out of its group; repoint remaining members to a valid leader."""
    members = _group_members(conn, image_id)
    conn.execute("UPDATE images SET group_id=? WHERE id=?", (image_id, image_id))
    remaining = [m for m in members if m != image_id]
    if remaining:
        new_leader = min(remaining)
        placeholders = ",".join("?" * len(remaining))
        conn.execute(
            f"UPDATE images SET group_id=? WHERE id IN ({placeholders})",
            (new_leader, *remaining),
        )


def _find_image_id(conn: sqlite3.Connection, film_id: int, filename: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM images WHERE film_id=? AND filename=?", (film_id, filename)
    ).fetchone()
    return row["id"] if row else None


def _find_film_id(conn: sqlite3.Connection, folder: str) -> int | None:
    row = conn.execute("SELECT id FROM film_rolls WHERE folder=?", (folder,)).fetchone()
    return row["id"] if row else None


def _ensure_film_roll(conn: sqlite3.Connection, folder: str) -> int:
    film_id = _find_film_id(conn, folder)
    if film_id is not None:
        return film_id
    cur = conn.execute(
        "INSERT INTO film_rolls (folder, access_timestamp) VALUES (?, strftime('%s','now'))",
        (folder,),
    )
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def plan_move(
    photo_paths: Sequence[Path],
    dest_dir: Path,
    dest_cart_id: str,
    dest_trip_code: str,
    *,
    ungroup: bool = False,
) -> RelocatePlan:
    """Resolve every path and every destination filename before anything runs.

    Raises CrossCartridgeNotSupportedError if source and destination are not
    on the same cartridge, GroupConflictError if a requested photo has
    Darktable group siblings not included in the move (pass ungroup=True to
    split instead), and RelocateError for anything else that makes the move
    unsafe to start (duplicate destination names, a missing source file).
    """
    photo_paths = [Path(p) for p in photo_paths]
    if not photo_paths:
        raise RelocateError("No photos given to move")
    for p in photo_paths:
        if not p.exists():
            raise RelocateError(f"Source photo does not exist: {p}")
    source_dirs = {p.parent.resolve() for p in photo_paths}
    if len(source_dirs) > 1:
        raise RelocateError(
            f"All photos in one move must share a source folder, got {len(source_dirs)}"
        )
    source_dir = next(iter(source_dirs))
    dest_dir = Path(dest_dir).resolve()

    cartridge_root = _cartridge_root_for(source_dir)
    dest_cartridge_root = _cartridge_root_for(dest_dir)
    if cartridge_root != dest_cartridge_root:
        raise CrossCartridgeNotSupportedError(
            f"{source_dir} and {dest_dir} are on different cartridges "
            f"({cartridge_root} vs {dest_cartridge_root}); cross-cartridge "
            "moves are not implemented yet — see the cartridge-manager plan."
        )

    layout = cartridge_layout(cartridge_root)
    library_db = layout.dbs.get("dt_library")
    group_extras: dict[Path, list[str]] = {}
    if library_db is not None:
        conn = _open_dt(library_db, check_lock=True)
        try:
            film_id = _find_film_id(conn, str(source_dir))
            if film_id is not None:
                requested_names = {p.name for p in photo_paths}
                for p in photo_paths:
                    image_id = _find_image_id(conn, film_id, p.name)
                    if image_id is None:
                        continue
                    members = _group_members(conn, image_id)
                    if len(members) <= 1 or ungroup:
                        continue
                    sibling_names = [
                        r["filename"]
                        for r in conn.execute(
                            "SELECT filename FROM images WHERE id IN "
                            f"({','.join('?' * len(members))}) AND id != ?",
                            (*members, image_id),
                        ).fetchall()
                    ]
                    missing = [n for n in sibling_names if n not in requested_names]
                    if missing:
                        group_extras[p] = missing
        finally:
            conn.close()
    if group_extras:
        detail = "; ".join(f"{p.name} -> {names}" for p, names in group_extras.items())
        raise GroupConflictError(
            f"Grouped photos not included in this move: {detail}. "
            "Include the sibling paths explicitly, or pass ungroup=True to split the group."
        )

    # No mkdir here: planning (including a dry_run call) must have zero side
    # effects. get_next_sequence() degrades gracefully when dest_dir does not
    # exist yet (treats it as empty); _copy_target() creates it for real.
    next_seq = get_next_sequence(dest_dir, dest_cart_id, dest_trip_code)
    targets: list[RelocateTarget] = []
    seen_dest_names: set[str] = set()
    for p in sorted(photo_paths, key=lambda x: x.name):
        dest_name = format_photo_name(dest_cart_id, dest_trip_code, next_seq, p.suffix)
        next_seq += 1
        if dest_name in seen_dest_names or (dest_dir / dest_name).exists():
            raise RelocateError(f"Destination filename collision: {dest_dir / dest_name}")
        seen_dest_names.add(dest_name)
        src_xmp = xmp_sidecar_path(p)
        targets.append(
            RelocateTarget(
                src_path=p,
                dest_path=dest_dir / dest_name,
                src_xmp=src_xmp if src_xmp.exists() else None,
                dest_xmp=(dest_dir / dest_name).with_name(dest_name + ".xmp")
                if src_xmp.exists()
                else None,
            )
        )

    return RelocatePlan(
        targets=targets,
        source_dir=source_dir,
        dest_dir=dest_dir,
        cartridge_root=cartridge_root,
        intent_log_path=cartridge_root / ".photonforge" / INTENT_LOG_NAME,
    )


# ---------------------------------------------------------------------------
# Per-target steps — shared by move_photos() and resume_move()
# ---------------------------------------------------------------------------


def _copy_target(target: RelocateTarget) -> None:
    target.dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target.src_path, target.dest_path)
    if target.src_xmp is not None and target.dest_xmp is not None:
        shutil.copy2(target.src_xmp, target.dest_xmp)
    target.state = "copied"


def _verify_target_copy(target: RelocateTarget) -> str:
    if not target.dest_path.exists():
        raise RelocateError(f"Copy did not produce {target.dest_path}")
    src_hash = sha256_file(target.src_path)
    dest_hash = sha256_file(target.dest_path)
    if src_hash != dest_hash:
        raise RelocateError(
            f"Checksum mismatch after copy: {target.src_path} -> {target.dest_path}"
        )
    if target.src_xmp is not None:
        if target.dest_xmp is None or not target.dest_xmp.exists():
            raise RelocateError(f"Sidecar copy did not produce {target.dest_xmp}")
        if sha256_file(target.src_xmp) != sha256_file(target.dest_xmp):
            raise RelocateError(f"Sidecar checksum mismatch: {target.src_xmp}")
    target.state = "verified"
    return dest_hash


def _update_photondb(target: RelocateTarget, plan: RelocatePlan) -> None:
    conn = open_db(plan.dest_dir)
    try:
        ensure_schema(conn)
        conn.execute(
            "UPDATE photos SET folder=?, filename=? WHERE folder=? AND filename=?",
            (
                plan.dest_dir.name,
                target.dest_path.name,
                plan.source_dir.name,
                target.src_path.name,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _update_darktable(
    target: RelocateTarget, plan: RelocatePlan, *, ungroup: bool
) -> None:
    layout = cartridge_layout(plan.cartridge_root)
    library_db = layout.dbs.get("dt_library")
    if library_db is None:
        return  # no Darktable sync on this cartridge yet — nothing to update
    conn = _open_dt(library_db, check_lock=True)
    try:
        film_id = _find_film_id(conn, str(plan.source_dir))
        if film_id is None:
            return  # source folder was never imported into Darktable
        image_id = _find_image_id(conn, film_id, target.src_path.name)
        if image_id is None:
            return  # this specific photo was never imported
        if ungroup:
            _ungroup_image(conn, image_id)
        dest_film_id = _ensure_film_roll(conn, str(plan.dest_dir))
        conn.execute(
            "UPDATE images SET filename=?, film_id=?, write_timestamp=strftime('%s','now') "
            "WHERE id=?",
            (target.dest_path.name, dest_film_id, image_id),
        )
        conn.commit()
    finally:
        conn.close()


def _verify_darktable(target: RelocateTarget, plan: RelocatePlan) -> None:
    layout = cartridge_layout(plan.cartridge_root)
    library_db = layout.dbs.get("dt_library")
    if library_db is None:
        return
    conn = _open_dt(library_db, check_lock=False)
    try:
        dest_film_id = _find_film_id(conn, str(plan.dest_dir))
        if dest_film_id is None:
            return
        row = conn.execute(
            "SELECT id FROM images WHERE film_id=? AND filename=?",
            (dest_film_id, target.dest_path.name),
        ).fetchone()
        if row is None:
            raise RelocateError(
                f"Darktable row for {target.dest_path.name} not found after move"
            )
    finally:
        conn.close()


def _verify_photondb(target: RelocateTarget, plan: RelocatePlan) -> None:
    conn = open_db(plan.dest_dir)
    try:
        row = conn.execute(
            "SELECT 1 FROM photos WHERE folder=? AND filename=?",
            (plan.dest_dir.name, target.dest_path.name),
        ).fetchone()
        if row is None:
            # A photo with no photonforge.db row (never scored) is legal —
            # nothing to verify. Only a *stale source row* is a real problem.
            stale = conn.execute(
                "SELECT 1 FROM photos WHERE folder=? AND filename=?",
                (plan.source_dir.name, target.src_path.name),
            ).fetchone()
            if stale is not None:
                raise RelocateError(
                    f"photonforge.db still has a stale row for {target.src_path.name} "
                    "under the source folder after the move"
                )
    finally:
        conn.close()


def _delete_source(target: RelocateTarget) -> None:
    target.src_path.unlink(missing_ok=True)
    if target.src_xmp is not None:
        target.src_xmp.unlink(missing_ok=True)
    target.state = "done"


def _run_target(target: RelocateTarget, plan: RelocatePlan, *, ungroup: bool) -> str:
    """Advance one target from wherever its state is to 'done'. Returns its sha256."""
    if _STATE_ORDER.index(target.state) < _STATE_ORDER.index("copied"):
        _copy_target(target)
        _write_intent_log(plan)
    digest = sha256_file(target.dest_path) if target.dest_path.exists() else ""
    if _STATE_ORDER.index(target.state) < _STATE_ORDER.index("verified"):
        digest = _verify_target_copy(target)
        _write_intent_log(plan)
    if _STATE_ORDER.index(target.state) < _STATE_ORDER.index("db_updated"):
        _update_photondb(target, plan)
        _update_darktable(target, plan, ungroup=ungroup)
        target.state = "db_updated"
        _write_intent_log(plan)
    if target.state != "done":
        _verify_photondb(target, plan)
        _verify_darktable(target, plan)
        _delete_source(target)
        _append_move_log(plan.cartridge_root, target, digest)
        _write_intent_log(plan)
    return digest


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def move_photos(
    photo_paths: Sequence[Path],
    dest_dir: Path,
    dest_cart_id: str,
    dest_trip_code: str,
    *,
    ungroup: bool = False,
    dry_run: bool = False,
    force: bool = False,
    progress: Callable[[int, int, Path], None] | None = None,
) -> RelocateResult:
    """Move `photo_paths` (all from one shoot folder) into dest_dir, renamed
    to dest_cart_id/dest_trip_code's convention.

    Snapshots the cartridge (Tier 1) before anything destructive, writes a
    resumable intent log, copies + hash-verifies before touching any DB,
    updates photonforge.db and Darktable's library.db in place (never
    delete+reinsert — see the module docstring for why that matters), and
    only deletes the source file after everything is verified.
    """
    plan = plan_move(
        photo_paths, dest_dir, dest_cart_id, dest_trip_code, ungroup=ungroup
    )
    if dry_run:
        return RelocateResult(
            moved=[(t.src_path, t.dest_path) for t in plan.targets], dry_run=True
        )

    if plan.intent_log_path.exists():
        existing = _read_intent_log(plan.intent_log_path)
        if any(t.state != "done" for t in existing.targets):
            raise MoveInProgressError(
                f"{plan.intent_log_path} shows an unfinished move — call "
                "resume_move() on it first."
            )

    assert_cartridge_idle(plan.cartridge_root, force=force)

    total_size = sum(t.src_path.stat().st_size for t in plan.targets)
    free = shutil.disk_usage(plan.cartridge_root).free
    if total_size > free:
        raise RelocateError(
            f"Not enough free space at {plan.cartridge_root}: need {total_size} "
            f"bytes, have {free}"
        )

    snapshot: Path | None = None
    try:
        snap_dest = plan.cartridge_root / SNAPSHOT_DIRNAME / snapshot_timestamp()
        snapshot = snapshot_databases(plan.cartridge_root, snap_dest)
    except FileNotFoundError:
        logger.info("No databases found at %s — skipping pre-move snapshot", plan.cartridge_root)

    _write_intent_log(plan)
    moved: list[tuple[Path, Path]] = []
    for index, target in enumerate(plan.targets, start=1):
        _run_target(target, plan, ungroup=ungroup)
        moved.append((target.src_path, target.dest_path))
        if progress is not None:
            progress(index, len(plan.targets), target.dest_path)

    plan.intent_log_path.unlink(missing_ok=True)
    return RelocateResult(moved=moved, snapshot=snapshot)


def move_shoot_folder(
    source_dir: Path,
    dest_root: Path,
    dest_cart_id: str,
    *,
    dest_folder_name: str | None = None,
    ungroup: bool = False,
    dry_run: bool = False,
    force: bool = False,
    progress: Callable[[int, int, Path], None] | None = None,
) -> RelocateResult:
    """Move every photo in source_dir into dest_root/<dest_folder_name>."""
    source_dir = Path(source_dir)
    dest_folder_name = dest_folder_name or source_dir.name
    dest_dir = Path(dest_root) / dest_folder_name
    trip_code = derive_trip_code(dest_folder_name)
    photo_paths = sorted(p for p in source_dir.iterdir() if _is_photo(p))
    if not photo_paths:
        raise RelocateError(f"No photos found in {source_dir}")
    return move_photos(
        photo_paths,
        dest_dir,
        dest_cart_id,
        trip_code,
        ungroup=ungroup,
        dry_run=dry_run,
        force=force,
        progress=progress,
    )


def resume_move(
    intent_log_path: Path,
    *,
    progress: Callable[[int, int, Path], None] | None = None,
) -> RelocateResult:
    """Complete (or safely no-op) a move interrupted mid-operation.

    A target still at 'planned' has had nothing destructive happen to it and
    is simply retried from the top. Anything past 'copied' resumes from
    exactly where its state says, never re-doing a step whose effect is
    already durable.
    """
    plan = _read_intent_log(Path(intent_log_path))
    moved: list[tuple[Path, Path]] = []
    for index, target in enumerate(plan.targets, start=1):
        if target.state != "done":
            _run_target(target, plan, ungroup=False)
        moved.append((target.src_path, target.dest_path))
        if progress is not None:
            progress(index, len(plan.targets), target.dest_path)
    plan.intent_log_path.unlink(missing_ok=True)
    return RelocateResult(moved=moved)
