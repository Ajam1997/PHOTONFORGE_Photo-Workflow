"""Volume label detection and PHOTONForge file naming helpers."""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def get_volume_label(drive_path: Path) -> str:
    """Read the volume label for the drive containing drive_path.

    Windows: uses ctypes Win32 API (no subprocess, no terminal flash).
    Linux: uses lsblk.
    """
    if sys.platform == "win32":
        return _get_label_windows(drive_path)
    return _get_label_linux(drive_path)


def _get_label_windows(drive_path: Path) -> str:
    import ctypes

    root = drive_path.anchor
    if not root:
        return ""
    volume_name = ctypes.create_unicode_buffer(256)
    result = ctypes.windll.kernel32.GetVolumeInformationW(
        root,
        volume_name,
        256,
        None,
        None,
        None,
        None,
        0,
    )
    if result:
        return volume_name.value
    return ""


def _find_mount_point(path: Path) -> Path:
    """Walk up from path to the filesystem it is mounted on."""
    import os

    p = path.resolve()
    while not os.path.ismount(p) and p != p.parent:
        p = p.parent
    return p


def _get_label_linux(drive_path: Path) -> str:
    import json
    import subprocess

    # drive_path is usually a folder *inside* the cartridge; compare against
    # its mount point. Both columns must be requested explicitly — the old
    # "-no LABEL" call emitted only the label key, so the mountpoint match
    # never hit and every cartridge fell back to ID 000.
    mount_point = str(_find_mount_point(drive_path))
    try:
        result = subprocess.run(
            ["lsblk", "-J", "-o", "LABEL,MOUNTPOINT"],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)

        def _walk(devices: list) -> str:
            for dev in devices:
                if dev.get("mountpoint") == mount_point and dev.get("label"):
                    return dev["label"]
                found = _walk(dev.get("children") or [])
                if found:
                    return found
            return ""

        return _walk(data.get("blockdevices", []))
    except Exception as e:
        logger.warning("Could not read volume label: %s", e)
    return ""


def extract_cartridge_id(label: str) -> str:
    """Parse volume label to extract 3-digit cartridge ID.

    'PHOTONFORGE-003' -> '003'. Falls back to '000'.
    """
    m = re.search(r"-(\d+)$", label)
    if m:
        return m.group(1).zfill(3)[:3]
    return "000"


def derive_trip_code(folder_name: str) -> str:
    """Derive 3-char trip code from folder name.

    'ICELAND' -> 'ICE', 'My Trip' -> 'MYT', 'AB' -> 'ABX'.
    """
    alpha = re.sub(r"[^A-Za-z]", "", folder_name).upper()
    if len(alpha) < 3:
        alpha = alpha.ljust(3, "X")
    return alpha[:3]


def format_photo_name(cart_id: str, trip_code: str, seq: int, ext: str) -> str:
    """Format a PHOTONForge filename: P003ICE0000001.ARW"""
    return f"P{cart_id}{trip_code}{seq:07d}{ext}"


def get_next_sequence(dest_dir: Path, cart_id: str, trip_code: str) -> int:
    """Find the highest existing sequence number + 1 for this cart+trip prefix."""
    prefix = f"P{cart_id}{trip_code}"
    max_seq = 0
    if dest_dir.exists():
        for p in dest_dir.iterdir():
            name = p.stem
            if name.startswith(prefix) and len(name) == 14:
                try:
                    seq = int(name[7:14])
                    max_seq = max(max_seq, seq)
                except ValueError:
                    pass
    return max_seq + 1
