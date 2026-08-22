"""FR-1.9: SSD volume detection and management."""

from __future__ import annotations

import logging
import subprocess
import sys
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
        # One overwriting line, not one line per file: a real cartridge is
        # thousands of files and the scrollback is useless. The verify pass
        # reuses this and prefixes its entries with [verify].
        if as_json:
            return
        pct = (index * 100 // total) if total else 100
        sys.stdout.write(f"\r  {index}/{total} ({pct}%) {str(rel)[-48:]:<48}")
        sys.stdout.flush()

    try:
        snapshot = backup_mod.mirror_cartridge(
            root, dest, state_only=state_only, exclude_models=exclude_models,
            link_dest=link_dest, keep=keep, force=force, progress=_progress,
        )
    except backup_mod.CartridgeBusy as exc:
        raise click.ClickException(str(exc)) from exc
    except (FileNotFoundError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc

    if not as_json:
        sys.stdout.write("\r" + " " * 78 + "\r")
        sys.stdout.flush()

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

    def _progress(done: int, total: int, name: str) -> None:
        if as_json:
            return
        # Verification re-reads the whole mirror; on a real library that is
        # minutes. Overwrite one line so the window shows liveness without
        # scrolling thousands of filenames past.
        pct = (done * 100 // total) if total else 100
        sys.stdout.write(f"\r  verifying {done}/{total} ({pct}%) {name[-48:]:<48}")
        sys.stdout.flush()

    problems = verify_snapshot(snapshot, against=against, progress=_progress)
    if not as_json:
        sys.stdout.write("\r" + " " * 78 + "\r")
        sys.stdout.flush()
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


@main.command("make-portable")
@click.argument("drive", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--os", "oses", multiple=True, type=click.Choice(["win", "linux"]),
              default=("win", "linux"), show_default=True,
              help="Which Darktable app(s) to bundle")
@click.option("--manifest", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None,
              help="config/portable-manifest.yml (Darktable download pins); "
                   "omit to skip the Darktable-app step")
@click.option("--models-src", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=None, help="Local models/ dir to copy onto the drive")
@click.option("--cli-src", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=None, help="Local runtime/ dir (frozen CLI builds) to copy onto the drive")
@click.option("--cache", "cache_dir", type=click.Path(path_type=Path), default=None,
              help="Download cache for Darktable archives (required if --manifest is given)")
@click.option("--offline", is_flag=True, help="Cache-only: error instead of downloading")
@click.option("--templates-dir", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path("deploy/portable"), show_default=True)
@click.option("--lua-src", type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=Path("lua/photonforge"), show_default=True)
@click.option("--id", "cart_id", default=None,
              help="Expected PHOTON-XXX id; verified against the drive's volume label")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
def make_portable_cmd(drive: Path, oses: tuple, manifest: Path | None,
                      models_src: Path | None, cli_src: Path | None, cache_dir: Path | None,
                      offline: bool, templates_dir: Path, lua_src: Path,
                      cart_id: str | None, as_json: bool) -> None:
    """Assemble a self-contained portable drive (Darktable + CLI + models) onto DRIVE.

    DRIVE must already be a mounted, provisioned PHOTON-XXX cartridge (see
    `provision`). Runs unelevated; partitioning/formatting stays in
    provision.py.
    """
    from . import portable as portable_mod
    from .volume import extract_cartridge_id, get_volume_label

    label = get_volume_label(drive)
    if not label.startswith("PHOTON"):
        raise click.ClickException(
            f"{drive} does not look like a PHOTON cartridge (volume label: {label!r})."
        )
    if cart_id is not None and extract_cartridge_id(label) != cart_id.zfill(3)[:3]:
        raise click.ClickException(
            f"Volume label {label!r} (id {extract_cartridge_id(label)}) "
            f"does not match --id {cart_id}."
        )

    loaded_manifest = portable_mod.PortableManifest.load(manifest) if manifest else None

    def _progress(msg: str) -> None:
        if not as_json:
            click.echo(msg)

    try:
        result = portable_mod.build_portable_layout(
            drive, oses=list(oses), manifest=loaded_manifest,
            templates_dir=templates_dir, repo_lua_dir=lua_src,
            models_src=models_src, cli_src=cli_src, cache_dir=cache_dir,
            offline=offline, progress=_progress, volume_label=label,
        )
    except (portable_mod.DownloadError, FileNotFoundError, ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc

    if as_json:
        import json as _json
        click.echo(_json.dumps({
            "step": "make-portable", "status": "ok", "drive": str(drive),
            "apps": {k: str(v) for k, v in result.apps.items()},
            "runtimes": {k: str(v) for k, v in result.runtimes.items()},
            "models_copied": result.models_copied,
            "readme": str(result.readme),
            "autorun_inf": str(result.autorun_inf),
            "manifest_lock": str(result.manifest_lock),
        }))
    else:
        click.echo(f"Portable drive assembled at {drive}")
        click.echo(
            f"  plugin: {len(result.plugin['copied'])} copied, "
            f"{len(result.plugin['up_to_date'])} up to date"
        )
        for os_name, path in result.apps.items():
            click.echo(f"  apps/darktable-{os_name}: {path}")
        for os_name, path in result.runtimes.items():
            click.echo(f"  runtime/{os_name}: {path}")
        if result.models_copied:
            click.echo("  models/: copied")
        for launcher in result.launchers:
            click.echo(f"  launcher: {launcher.name}")
        click.echo(f"  readme: {result.readme.name}")
        click.echo(f"  drive icon/label: {result.autorun_inf.name}")
        click.echo(f"  manifest lock: {result.manifest_lock}")


def _resolve_cart_id(dest: Path, cart_id: str | None) -> str:
    from .volume import extract_cartridge_id, get_volume_label

    if cart_id is not None:
        return cart_id.zfill(3)[:3]
    label = get_volume_label(dest)
    if not label:
        raise click.ClickException(
            f"Could not read a volume label for {dest} — pass --cart-id explicitly."
        )
    return extract_cartridge_id(label)


def _report_relocate_result(result, *, as_json: bool, step: str) -> None:
    import json as _json

    if as_json:
        click.echo(_json.dumps({
            "step": step, "status": "ok",
            "moved": [[str(a), str(b)] for a, b in result.moved],
            "dry_run": result.dry_run,
            "snapshot": str(result.snapshot) if result.snapshot else None,
        }))
        return
    if result.dry_run:
        click.echo(f"Dry run — would move {len(result.moved)} photo(s):")
    else:
        click.echo(f"Moved {len(result.moved)} photo(s).")
    for src, dest in result.moved:
        click.echo(f"  {src.name} -> {dest}")
    if result.snapshot is not None:
        click.echo(f"  snapshot: {result.snapshot}")


@main.command("move-photos")
@click.argument("photos", nargs=-1, required=True,
                type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--dest", "dest_dir", required=True, type=click.Path(path_type=Path),
              help="Destination shoot folder (a subfolder of the cartridge root)")
@click.option("--cart-id", default=None,
              help="Destination cartridge id for renaming; auto-detected from the "
                   "destination's volume label if omitted")
@click.option("--trip-code", default=None,
              help="3-char trip code for renaming; derived from the destination "
                   "folder name if omitted")
@click.option("--ungroup", is_flag=True,
              help="Split a Darktable-grouped photo from its siblings instead of "
                   "refusing when they are not all included in the move")
@click.option("--dry-run", is_flag=True, help="Report the plan without moving anything")
@click.option("--force", is_flag=True, help="Proceed even if the cartridge looks busy")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
def move_photos_cmd(photos: tuple, dest_dir: Path, cart_id: str | None,
                    trip_code: str | None, ungroup: bool, dry_run: bool,
                    force: bool, as_json: bool) -> None:
    """Move PHOTOS (files, all from one shoot folder) to --dest, same cartridge only.

    Renames to the destination's naming convention and migrates the
    photonforge.db row and the Darktable library.db row (if either exists),
    keeping edits, tags, and color labels intact. Cross-cartridge moves are
    not supported yet — see the cartridge-manager plan.
    """
    from . import relocate
    from .volume import derive_trip_code

    resolved_cart_id = _resolve_cart_id(dest_dir, cart_id)
    resolved_trip_code = trip_code or derive_trip_code(dest_dir.name)

    def _progress(index: int, total: int, path: Path) -> None:
        if not as_json:
            click.echo(f"  [{index}/{total}] {path.name}")

    try:
        result = relocate.move_photos(
            list(photos), dest_dir, resolved_cart_id, resolved_trip_code,
            ungroup=ungroup, dry_run=dry_run, force=force,
            progress=None if dry_run else _progress,
        )
    except relocate.RelocateError as exc:
        raise click.ClickException(str(exc)) from exc

    _report_relocate_result(result, as_json=as_json, step="move-photos")


@main.command("move-shoot")
@click.argument("source_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("dest_root", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--dest-folder-name", default=None,
              help="Destination folder name; defaults to SOURCE_DIR's own name")
@click.option("--cart-id", default=None,
              help="Destination cartridge id for renaming; auto-detected from "
                   "DEST_ROOT's volume label if omitted")
@click.option("--ungroup", is_flag=True,
              help="Split Darktable-grouped photos from siblings left behind")
@click.option("--dry-run", is_flag=True, help="Report the plan without moving anything")
@click.option("--force", is_flag=True, help="Proceed even if the cartridge looks busy")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
def move_shoot_cmd(source_dir: Path, dest_root: Path, dest_folder_name: str | None,
                   cart_id: str | None, ungroup: bool, dry_run: bool,
                   force: bool, as_json: bool) -> None:
    """Move every photo in SOURCE_DIR into DEST_ROOT/<folder>, same cartridge only."""
    from . import relocate

    resolved_cart_id = _resolve_cart_id(dest_root, cart_id)

    def _progress(index: int, total: int, path: Path) -> None:
        if not as_json:
            click.echo(f"  [{index}/{total}] {path.name}")

    try:
        result = relocate.move_shoot_folder(
            source_dir, dest_root, resolved_cart_id,
            dest_folder_name=dest_folder_name, ungroup=ungroup, dry_run=dry_run,
            force=force, progress=None if dry_run else _progress,
        )
    except relocate.RelocateError as exc:
        raise click.ClickException(str(exc)) from exc

    _report_relocate_result(result, as_json=as_json, step="move-shoot")


@main.command("resume-move")
@click.argument("intent_log", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
def resume_move_cmd(intent_log: Path, as_json: bool) -> None:
    """Complete a move interrupted mid-operation (.photonforge/move-in-progress.json)."""
    from . import relocate

    def _progress(index: int, total: int, path: Path) -> None:
        if not as_json:
            click.echo(f"  [{index}/{total}] {path.name}")

    try:
        result = relocate.resume_move(intent_log, progress=_progress)
    except relocate.RelocateError as exc:
        raise click.ClickException(str(exc)) from exc

    _report_relocate_result(result, as_json=as_json, step="resume-move")


@main.command("init")
@click.argument("mount_path", type=click.Path(path_type=Path))
def init_cartridge(mount_path: Path) -> None:
    """[DEPRECATED] Legacy Layout A scaffold (<mount>/darktable/, <mount>/photos/).

    Superseded by Layout B (drive-root state) — see the portable-drive plan.
    New cartridges should use `provision` + `make-portable` instead. Kept
    only for compatibility with pre-migration cartridges.
    """
    import sqlite3
    click.echo(
        "Warning: 'init' creates the legacy Layout A scaffold "
        "(<mount>/darktable/, <mount>/photos/). New cartridges should use "
        "'provision' + 'make-portable' instead (Layout B — see "
        "dev-docs/superpowers/plans/2026-07-17-portable-drive-plan.md).",
        err=True,
    )
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
