# src/photo_workflow/provision.py
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DeviceAnalysis:
    device: str  # e.g., /dev/sdb
    size_bytes: int
    has_partitions: bool
    existing_label: str | None
    partition_device: str | None  # e.g., /dev/sdb1 or None


def analyze_device(device: str) -> DeviceAnalysis:
    """Use lsblk to check partition status and existing label."""
    result = subprocess.run(
        ["lsblk", "--json", "--output", "NAME,SIZE,LABEL,TYPE"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)

    device_name = Path(device).name

    def _find_device(devices: list) -> dict | None:
        for dev in devices:
            if dev["name"] == device_name:
                return dev
            if dev.get("children"):
                found = _find_device(dev["children"])
                if found:
                    return found
        return None

    dev_info = _find_device(data.get("blockdevices", []))
    if not dev_info:
        raise ValueError(f"Device {device} not found in lsblk output")

    children = dev_info.get("children", [])
    has_partitions = bool(children)
    partition_device = f"{device}1" if has_partitions else None

    existing_label = None
    if has_partitions:
        existing_label = children[0].get("label")
    else:
        existing_label = dev_info.get("label")

    size_str = dev_info.get("size", 0)
    size_bytes = int(size_str) if isinstance(size_str, (int, str)) else 0

    return DeviceAnalysis(
        device=device,
        size_bytes=size_bytes,
        has_partitions=has_partitions,
        existing_label=existing_label,
        partition_device=partition_device,
    )
