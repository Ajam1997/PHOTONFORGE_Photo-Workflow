"""Sidecar CLI: streams JSON-lines for Tauri shell plugin consumption."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import click

from photo_workflow.cartridge import detect_cartridges
from photo_workflow.provision import (
    next_available_cartridge_id,
    provision_cartridge,
)

RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".rw2", ".orf", ".pef", ".srw", ".3fr", ".mef"}


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

        # Scan source for RAW files. Look inside DCIM/ first (camera card standard).
        emit({"type": "progress", "step": "copying", "current": 0, "total": 0, "message": "Scanning…"})
        dcim_path = source_path / "DCIM"
        scan_root = dcim_path if dcim_path.is_dir() else source_path
        all_raws = [
            f for f in scan_root.rglob("*")
            if f.is_file() and f.suffix.lower() in RAW_EXTS
        ]
        total = len(all_raws)
        emit({"type": "progress", "step": "copying", "current": 0, "total": total, "message": f"Found {total} RAW files"})

        if total == 0:
            elapsed = time.monotonic() - start
            emit({"type": "done", "summary": {"total": 0, "duplicates_skipped": 0, "scored": 0, "xmp_written": 0, "db_upserted": 0, "elapsed_seconds": round(elapsed, 2)}})
            return

        output_path.mkdir(parents=True, exist_ok=True)

        # rsync with --itemize-changes for per-file progress, RAW extensions only.
        cmd = [
            "rsync", "--archive", "--itemize-changes",
            "--include=*/",
        ]
        for ext in RAW_EXTS:
            cmd += [f"--include=*{ext}", f"--include=*{ext.upper()}"]
        cmd += ["--exclude=*", "--", str(scan_root) + "/", str(output_path) + "/"]

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
            # Resolve symlink (e.g. /dev/disk/by-label/PHOTON-001 → /dev/sdc1).
            real_device = str(Path(device).resolve())
            # Unmount every mount point that uses this device (requires root via sudo).
            for line in Path("/proc/mounts").read_text().splitlines():
                parts = line.split()
                if len(parts) >= 2 and str(Path(parts[0]).resolve()) == real_device:
                    subprocess.run(["sudo", "-n", "umount", parts[1]], check=False)

            result = subprocess.run(
                ["sudo", "-n", "mkfs.ext4", "-L", label, "-F", real_device],
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


@cli.command("list-drives")
def list_drives() -> None:
    """List USB block devices available for provisioning."""
    try:
        result = subprocess.run(
            ["lsblk", "--json", "--bytes", "--output", "NAME,SIZE,MODEL,TYPE,TRAN,LABEL,MOUNTPOINT"],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(result.stdout)
        drives = []
        for dev in data.get("blockdevices", []):
            if dev.get("type") == "disk" and dev.get("tran") == "usb":
                drives.append({
                    "device": f"/dev/{dev['name']}",
                    "size_bytes": int(dev.get("size") or 0),
                    "model": (dev.get("model") or "Unknown USB Drive").strip(),
                    "label": dev.get("label"),
                })
        emit({"type": "drives", "items": drives})
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "message": str(exc)})
        sys.exit(1)


@cli.command("cartridge-provision")
@click.option("--device", required=True, help="Block device path, e.g. /dev/sdb")
@click.option("--label", required=True, help="New label, e.g. PHOTON-002")
@click.option("--force-repartition", is_flag=True, default=False, help="Force repartition even if partitions exist")
@click.option("--dry-run", is_flag=True, default=False, help="Simulate without touching disk")
def cartridge_provision(device: str, label: str, force_repartition: bool, dry_run: bool) -> None:
    """Provision a new PHOTON cartridge with partition, format, and init."""
    try:
        def progress_cb(step: str, current: int, total: int) -> None:
            emit({"type": "progress", "step": step, "current": current, "total": total, "message": step})

        result = provision_cartridge(
            device=device,
            label=label,
            force_repartition=force_repartition,
            dry_run=dry_run,
            progress_cb=progress_cb,
        )

        emit({
            "type": "provision_done",
            "label": result.label,
            "device": result.device,
            "mount_point": result.mount_point,
            "created_partition": result.created_partition,
            "wiped_signatures": result.wiped_signatures,
        })
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "message": str(exc)})
        sys.exit(1)


if __name__ == "__main__":
    cli()
