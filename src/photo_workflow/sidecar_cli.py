"""Sidecar CLI: streams JSON-lines for Tauri shell plugin consumption."""
from __future__ import annotations

import json
import re
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
from photo_workflow.grouping import cluster_sessions
from photo_workflow.dedup import deduplicate
from photo_workflow.sharpness import score_sharpness
from photo_workflow.composition import score_composition
from photo_workflow.exposure import score_exposure
from photo_workflow.naming import generate_name
from photo_workflow.darktable_bridge import sync_to_darktable
from photo_workflow.pipeline import PhotoRecord

RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".rw2", ".orf", ".pef", ".srw", ".3fr", ".mef"}


def emit(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


def _read_proc_mounts() -> str:
    """Return the contents of /proc/mounts as a string."""
    return Path("/proc/mounts").read_text()


def _eject_sd(mount_point: str) -> None:
    """Resolve SD card block device from mount point and power it off. Non-fatal."""
    try:
        device = None
        for line in _read_proc_mounts().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == mount_point:
                device = parts[0]
                break
        if not device:
            return
        disk = re.sub(r"p?\d+$", "", device)
        subprocess.run(["udisksctl", "power-off", "-b", disk], check=False)
    except Exception:  # noqa: BLE001
        pass


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.option("--source", required=True, help="Source mount path (SD card)")
@click.option("--output", required=True, help="Destination mount path (SSD)")
@click.option("--db", required=True, help="Path to library.db on SSD")
@click.option("--model-dir", default="models/florence2_int8", show_default=True, help="Florence-2 model directory")
@click.option("--skip-dedup", is_flag=True, default=False)
@click.option("--skip-scoring", is_flag=True, default=False)
@click.option("--skip-naming", is_flag=True, default=False)
@click.option("--skip-darktable", is_flag=True, default=False)
def ingest(
    source: str,
    output: str,
    db: str,
    model_dir: str,
    skip_dedup: bool,
    skip_scoring: bool,
    skip_naming: bool,
    skip_darktable: bool,
) -> None:
    """Ingest photos from SD to SSD and run the full analysis pipeline."""
    source_path = Path(source)
    output_path = Path(output)

    try:
        start = time.monotonic()

        # ── Copy ──────────────────────────────────────────────────────────────
        emit({"type": "progress", "step": "copy", "current": 0, "total": 0, "message": "Scanning…"})
        dcim_path = source_path / "DCIM"
        scan_root = dcim_path if dcim_path.is_dir() else source_path
        all_raws = [f for f in scan_root.rglob("*") if f.is_file() and f.suffix.lower() in RAW_EXTS]
        total = len(all_raws)
        emit({"type": "progress", "step": "copy", "current": 0, "total": total, "message": f"Found {total} RAW files"})

        copied_paths: list[Path] = []

        if total > 0:
            output_path.mkdir(parents=True, exist_ok=True)
            cmd = ["rsync", "--archive", "--itemize-changes", "--include=*/"]
            for ext in RAW_EXTS:
                cmd += [f"--include=*{ext}", f"--include=*{ext.upper()}"]
            cmd += ["--exclude=*", "--", str(scan_root) + "/", str(output_path) + "/"]

            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip("\r\n")
                if line and not line.startswith("cd"):
                    # Itemize field width differs across rsync versions (9 in
                    # 2.x, 11 in 3.x); split on the first space instead of a
                    # fixed offset — the old line[10:] left a stray "+ " prefix
                    # on rsync 3.x, producing nonexistent paths downstream.
                    _, _, fname = line.partition(" ")
                    if not fname:
                        continue
                    dest = output_path / fname
                    if dest.suffix.lower() in RAW_EXTS:
                        copied_paths.append(dest)
                    emit({"type": "progress", "step": "copy", "current": len(copied_paths), "total": total, "message": fname})
            proc.wait()
            if proc.returncode != 0:
                stderr = proc.stderr.read() if proc.stderr else ""  # type: ignore[union-attr]
                raise RuntimeError(stderr.strip() or f"rsync exited {proc.returncode}")

        emit({"type": "stage_done", "stage": "copy", "copied": len(copied_paths)})

        # Eject SD immediately — non-blocking, non-fatal
        _eject_sd(source)
        emit({"type": "sd_ejected"})

        if not copied_paths:
            elapsed = time.monotonic() - start
            emit({"type": "done", "summary": {"total": 0, "duplicates_skipped": 0, "scored": 0, "named": 0, "xmp_written": 0, "db_upserted": 0, "elapsed_seconds": round(elapsed, 2)}})
            return

        records = [PhotoRecord(path=p, metadata={"original_filename": p.name}) for p in copied_paths]

        # Session grouping always runs (prereq for dedup, fast)
        records = cluster_sessions(records)

        # ── Dedup ─────────────────────────────────────────────────────────────
        dupes_found = 0
        if not skip_dedup:
            emit({"type": "progress", "step": "dedup", "current": 0, "total": len(records), "message": f"Analysing {len(records)} files…"})
            records, _new_hashes = deduplicate(records)
            dupes_found = sum(1 for r in records if r.is_duplicate)
            emit({"type": "stage_done", "stage": "dedup", "dupes_found": dupes_found})

        active = [r for r in records if not r.is_duplicate]

        # ── Scoring ───────────────────────────────────────────────────────────
        scored = 0
        if not skip_scoring:
            for i, record in enumerate(active):
                record.sharpness_score = score_sharpness(record.path)
                record.composition_score = score_composition(record.path)
                record.exposure_score = score_exposure(record.path)
                scored += 1
                emit({"type": "progress", "step": "scoring", "current": i + 1, "total": len(active), "message": record.path.name})
            emit({"type": "stage_done", "stage": "scoring", "scored": scored})

        # ── Naming ────────────────────────────────────────────────────────────
        named = 0
        if not skip_naming:
            model_path = Path(model_dir)
            for i, record in enumerate(active):
                record.semantic_name = generate_name(record.path, model_dir=model_path)
                named += 1
                emit({"type": "progress", "step": "naming", "current": i + 1, "total": len(active), "message": record.path.name})
            emit({"type": "stage_done", "stage": "naming", "named": named})

        # ── Darktable sync ────────────────────────────────────────────────────
        xmp_written = 0
        db_upserted = 0
        if not skip_darktable:
            # sync_to_darktable(records) -> int; the old db_path= kwarg call
            # raised TypeError on every non-skip run (masked by test mocks).
            xmp_written = sync_to_darktable(records)
            emit({"type": "stage_done", "stage": "darktable", "xmp_written": xmp_written, "db_upserted": db_upserted})

        elapsed = time.monotonic() - start
        emit({
            "type": "done",
            "summary": {
                "total": len(records),
                "duplicates_skipped": dupes_found,
                "scored": scored,
                "named": named,
                "xmp_written": xmp_written,
                "db_upserted": db_upserted,
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
