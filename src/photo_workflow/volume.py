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


def _get_label_linux(drive_path: Path) -> str:
    import subprocess

    mount_point = str(drive_path)
    try:
        result = subprocess.run(
            ["lsblk", "-no", "LABEL", "-J"],
            capture_output=True,
            text=True,
            check=True,
        )
        import json

        data = json.loads(result.stdout)
        for dev in data.get("blockdevices", []):
            if dev.get("mountpoint") == mount_point and dev.get("label"):
                return dev["label"]
            for child in dev.get("children", []):
                if child.get("mountpoint") == mount_point and child.get("label"):
                    return child["label"]
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
