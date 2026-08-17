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
