"""FR-1.9: SSD volume detection and management."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import click

logger = logging.getLogger(__name__)


@dataclass
class Cartridge:
    device: str        # e.g. /dev/sdb
    mount_point: Path
    label: str
    size_bytes: int
    free_bytes: int


def detect_cartridges(label_prefix: str = "PHOTON") -> list[Cartridge]:
    """
    Detect mounted SSD volumes matching label_prefix via lsblk.
    Returns a list of Cartridge descriptors.
    """
    try:
        result = subprocess.run(
            ["lsblk", "--json", "--output", "NAME,LABEL,MOUNTPOINT,SIZE,FSAVAIL"],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError:
        logger.warning("lsblk not available — cannot detect cartridges")
        return []
    except subprocess.CalledProcessError as e:
        logger.error("lsblk failed: %s", e.stderr)
        return []

    import json
    data = json.loads(result.stdout)
    cartridges = []

    def _walk(devices: list) -> None:
        for dev in devices:
            label = dev.get("label") or ""
            mount = dev.get("mountpoint") or ""
            if label.startswith(label_prefix) and mount:
                try:
                    import shutil
                    usage = shutil.disk_usage(mount)
                    cartridges.append(Cartridge(
                        device=f"/dev/{dev['name']}",
                        mount_point=Path(mount),
                        label=label,
                        size_bytes=usage.total,
                        free_bytes=usage.free,
                    ))
                except Exception as e:
                    logger.warning("Could not stat %s: %s", mount, e)
            if dev.get("children"):
                _walk(dev["children"])

    _walk(data.get("blockdevices", []))
    logger.info("Detected %d PHOTON cartridge(s)", len(cartridges))
    return cartridges


def manage_cartridge(cartridge: Cartridge, pipeline_fn) -> None:
    """Run the pipeline against a detected cartridge's mount point."""
    logger.info("Processing cartridge: %s at %s", cartridge.label, cartridge.mount_point)
    pipeline_fn(cartridge.mount_point)


@click.group()
def main() -> None:
    """PHOTONForge cartridge management."""


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
    try:
        snapshot_databases(root, target)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    pruned = rotate_snapshots(snaproot, keep)
    if as_json:
        click.echo(_json.dumps({"step": "snapshot", "status": "ok",
                                "path": str(target), "pruned": len(pruned)}))
    else:
        click.echo(f"Snapshot written to {target} (pruned {len(pruned)} old).")


@main.command("backup")
@click.argument("root", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--dest", required=True, type=click.Path(path_type=Path),
              help="Backup destination directory (a second drive)")
@click.option("--state-only", is_flag=True, help="DBs, corpus, dt-config and XMP only")
@click.option("--exclude-models", is_flag=True, help="Skip models/ (regenerable)")
@click.option("--keep", default=None, type=int,
              help="Prune to N snapshots after a clean verify")
@click.option("--no-incremental", is_flag=True,
              help="Do not hardlink against the previous snapshot")
@click.option("--force", is_flag=True, help="Proceed even if the cartridge looks busy")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
def backup_cmd(root: Path, dest: Path, state_only: bool, exclude_models: bool,
               keep: int | None, no_incremental: bool, force: bool, as_json: bool) -> None:
    """Tier 2: verified whole-cartridge mirror to a second drive."""
    import json as _json

    from . import backup as backup_mod

    label = backup_mod.cartridge_backup_name(root)
    link_dest = None if no_incremental else backup_mod.latest_snapshot(dest, label)

    def _progress(index: int, total: int, rel: Path) -> None:
        if not as_json:
            click.echo(f"  [{index}/{total}] {rel}")

    try:
        snapshot = backup_mod.mirror_cartridge(
            root, dest, state_only=state_only, exclude_models=exclude_models,
            link_dest=link_dest, keep=keep, force=force, progress=_progress,
        )
    except backup_mod.CartridgeBusy as exc:
        raise click.ClickException(str(exc)) from exc
    except (FileNotFoundError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc

    manifest = _json.loads((snapshot / backup_mod.MANIFEST_NAME).read_text(encoding="utf-8"))
    totals = manifest["totals"]
    if as_json:
        click.echo(_json.dumps({
            "step": "backup", "status": "ok", "path": str(snapshot),
            "files": totals["files"], "bytes": totals["bytes"],
            "linked": totals["linked"], "hardlinks": manifest["hardlinks"],
        }))
    else:
        click.echo(
            f"Mirror written to {snapshot} — {totals['files']} files, "
            f"{totals['bytes']} bytes ({totals['linked']} linked)."
        )
        if link_dest is not None and not manifest["hardlinks"]:
            click.echo(
                "  Note: this filesystem has no hardlinks (exFAT/FAT32), so unchanged "
                "files were copied rather than linked."
            )


@main.command("verify-backup")
@click.argument("snapshot", required=False,
                type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--dest", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=None, help="Verify the newest snapshot under this destination")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=None, help="With --dest, scope 'newest' to this cartridge")
@click.option("--against", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=None, help="Also compare against this live cartridge")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
def verify_backup_cmd(snapshot: Path | None, dest: Path | None, root: Path | None,
                      against: Path | None, as_json: bool) -> None:
    """Re-checksum a Tier-2 mirror against its manifest.

    Give an explicit SNAPSHOT, or --dest to verify the newest one there
    (the panel has no snapshot picker, so it uses --dest).
    """
    import json as _json

    from .backup import cartridge_backup_name, latest_snapshot, verify_snapshot

    if snapshot is None:
        if dest is None:
            raise click.UsageError("Give a SNAPSHOT path or --dest to verify the newest.")
        label = cartridge_backup_name(root) if root else None
        snapshot = latest_snapshot(dest, label)
        if snapshot is None:
            raise click.ClickException(f"No snapshot found under {dest}")

    problems = verify_snapshot(snapshot, against=against)
    if as_json:
        click.echo(_json.dumps({"step": "verify-backup",
                                "status": "ok" if not problems else "failed",
                                "path": str(snapshot), "problems": problems}))
    else:
        for problem in problems:
            click.echo(f"  {problem}")
        click.echo(f"{snapshot}: {'clean' if not problems else f'{len(problems)} problem(s)'}")
    if problems:
        raise SystemExit(1)


@main.command("restore-backup")
@click.argument("snapshot", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--to", "target", required=True, type=click.Path(path_type=Path),
              help="Where to restore (a mounted cartridge, or a scratch dir)")
@click.option("--force", is_flag=True, help="Restore over a non-empty target")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
def restore_backup_cmd(snapshot: Path, target: Path, force: bool, as_json: bool) -> None:
    """Restore a Tier-2 mirror (DBs + photos) into --to."""
    import json as _json

    from .backup import restore_snapshot

    try:
        restore_snapshot(snapshot, target, force=force)
    except FileExistsError as exc:
        raise click.ClickException(str(exc)) from exc
    if as_json:
        click.echo(_json.dumps({"step": "restore-backup", "status": "ok",
                                "path": str(target)}))
    else:
        click.echo(f"Restored {snapshot} into {target}.")


@main.command("init")
@click.argument("mount_path", type=click.Path(path_type=Path))
def init_cartridge(mount_path: Path) -> None:
    """Provision a new PHOTON cartridge with the correct directory structure."""
    import sqlite3
    mount_path = mount_path.resolve()
    (mount_path / "darktable").mkdir(parents=True, exist_ok=True)
    (mount_path / "photos").mkdir(parents=True, exist_ok=True)
    db_path = mount_path / "darktable" / "library.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS images (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                folder   TEXT NOT NULL DEFAULT '',
                flags    INTEGER DEFAULT 0,
                caption  TEXT DEFAULT '',
                UNIQUE(filename, folder)
            );
            CREATE TABLE IF NOT EXISTS tags (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT UNIQUE,
                synonyms TEXT DEFAULT '',
                flags    INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS tagged_images (
                imgid  INTEGER,
                tagid  INTEGER,
                UNIQUE(imgid, tagid)
            );
        """)
    click.echo(f"Cartridge initialized at {mount_path}")
    click.echo(f"  {mount_path}/darktable/  (library.db created)")
    click.echo(f"  {mount_path}/photos/")


if __name__ == "__main__":
    main()
