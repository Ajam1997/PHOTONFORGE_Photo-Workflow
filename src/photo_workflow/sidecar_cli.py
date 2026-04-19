"""Sidecar CLI: streams JSON-lines for Tauri shell plugin consumption."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import click

from photo_workflow.ingest import ingest_volume
from photo_workflow.cartridge import detect_cartridges


def emit(obj: dict) -> None:
    """Emit a JSON-line event to stdout."""
    print(json.dumps(obj), flush=True)


@click.group()
def cli() -> None:
    """PHOTONForge sidecar CLI for Tauri integration."""
    pass


@cli.command()
@click.option("--source", required=True, help="Source mount path (SD card)")
@click.option("--output", required=True, help="Destination mount path (SSD)")
@click.option("--db", required=True, help="Path to library.db on SSD")
def ingest(source: str, output: str, db: str) -> None:
    """Ingest photos from SD to SSD, streaming progress events."""
    source_path = Path(source)
    output_path = Path(output)

    try:
        start = time.monotonic()
        emit({"type": "progress", "step": "copying", "current": 0, "total": 0, "message": ""})
        files = ingest_volume(source_path, output_path)
        total = len(files)
        emit({"type": "progress", "step": "copying", "current": total, "total": total, "message": ""})
        elapsed = time.monotonic() - start
        emit({
            "type": "done",
            "summary": {
                "total": total,
                "duplicates_skipped": 0,
                "scored": 0,
                "xmp_written": 0,
                "db_upserted": 0,
                "elapsed_seconds": round(elapsed, 2),
            },
        })
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "message": str(exc)})
        sys.exit(1)


@cli.command("cartridge-list")
def cartridge_list() -> None:
    """List all mounted PHOTON cartridges."""
    try:
        cartridges = detect_cartridges()
        emit({
            "type": "cartridges",
            "items": [
                {
                    "label": c.label,
                    "mount_point": str(c.mount_point),
                    "free_bytes": c.free_bytes,
                    "size_bytes": c.size_bytes,
                }
                for c in cartridges
            ],
        })
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "message": str(exc)})
        sys.exit(1)


@cli.command("cartridge-reformat")
@click.option("--device", required=True, help="Block device path, e.g. /dev/sdb")
@click.option("--label", required=True, help="New filesystem label, e.g. PHOTON-002")
@click.option("--dry-run", is_flag=True, default=False, help="Simulate without touching disk")
def cartridge_reformat(device: str, label: str, dry_run: bool) -> None:
    """Reformat a cartridge as ext4 with the given label."""
    try:
        emit({"type": "progress", "step": "formatting", "current": 0, "total": 1, "message": device})
        if not dry_run:
            result = subprocess.run(
                ["mkfs.ext4", "-L", label, "-F", device],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "mkfs.ext4 failed")
        suffix = label.replace("PHOTON-", "").zfill(3)
        mount_point = f"/mnt/photon_ssd/{suffix}"
        emit({"type": "progress", "step": "formatting", "current": 1, "total": 1, "message": ""})
        emit({"type": "reformat_done", "label": label, "mount_point": mount_point})
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "message": str(exc)})
        sys.exit(1)


if __name__ == "__main__":
    cli()
