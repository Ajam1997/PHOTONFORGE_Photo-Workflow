"""Sidecar CLI: streams JSON-lines for Tauri shell plugin consumption."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import click

from photo_workflow.cartridge import detect_cartridges

PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".raw", ".cr2", ".cr3", ".nef", ".arw", ".dng"}


def emit(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.option("--source", required=True, help="Source mount path (SD card)")
@click.option("--output", required=True, help="Destination mount path (SSD)")
@click.option("--db", required=True, help="Path to library.db on SSD")
def ingest(source: str, output: str, db: str) -> None:
    """Ingest photos from SD to SSD, streaming progress events."""
    # NOTE: db is accepted for interface completeness but the darktable bridge
    # wiring is deferred to a later stage. db_upserted will be 0 until then.
    source_path = Path(source)
    output_path = Path(output)

    try:
        start = time.monotonic()

        # Scan source for photo files to know the total upfront.
        emit({"type": "progress", "step": "copying", "current": 0, "total": 0, "message": "Scanning…"})
        all_photos = [
            f for f in source_path.rglob("*")
            if f.is_file() and f.suffix.lower() in PHOTO_EXTS
        ]
        total = len(all_photos)
        emit({"type": "progress", "step": "copying", "current": 0, "total": total, "message": f"Found {total} photos"})

        output_path.mkdir(parents=True, exist_ok=True)

        # Build rsync command with --itemize-changes so each transferred file
        # prints one line of output we can count for live progress.
        cmd = [
            "rsync", "--archive", "--checksum", "--itemize-changes",
            "--include=*/",
        ]
        for ext in PHOTO_EXTS:
            cmd += [f"--include=*{ext}", f"--include=*{ext.upper()}"]
        cmd += ["--exclude=*", "--", str(source_path) + "/", str(output_path) + "/"]

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        current = 0
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            # itemize-changes lines start with status flags then filename, e.g. ">f+++++++++ DSC_0001.ARW"
            if line and not line.startswith("cd"):
                current += 1
                fname = line[10:].strip() if len(line) > 10 else line
                emit({"type": "progress", "step": "copying", "current": current, "total": total, "message": fname})

        proc.wait()
        if proc.returncode != 0:
            stderr = proc.stderr.read() if proc.stderr else ""  # type: ignore[union-attr]
            raise RuntimeError(stderr.strip() or f"rsync exited {proc.returncode}")

        elapsed = time.monotonic() - start
        emit({
            "type": "done",
            "summary": {
                "total": current if current > 0 else total,
                "duplicates_skipped": max(0, total - current),
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
