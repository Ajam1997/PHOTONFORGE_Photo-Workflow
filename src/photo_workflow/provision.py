# src/photo_workflow/provision.py
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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
        ["lsblk", "--json", "--bytes", "--output", "NAME,SIZE,LABEL,TYPE"],
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


def next_available_cartridge_id(label_prefix: str = "PHOTON") -> str:
    """Scan /mnt/photon_ssd/ and /dev/disk/by-label/ for next 3-digit ID."""
    existing_ids: set[int] = set()

    mount_base = Path("/mnt/photon_ssd")
    if mount_base.exists():
        for item in mount_base.iterdir():
            if item.is_dir() and item.name.isdigit():
                existing_ids.add(int(item.name))

    label_dir = Path("/dev/disk/by-label")
    if label_dir.exists():
        for item in label_dir.iterdir():
            match = re.match(rf"{label_prefix}-(\d{{3}})", item.name)
            if match:
                existing_ids.add(int(match.group(1)))

    for i in range(1, 1000):
        if i not in existing_ids:
            return f"{i:03d}"

    raise RuntimeError("No available cartridge IDs (001-999 all in use)")


@dataclass
class ProvisionResult:
    label: str
    device: str  # The partition device (e.g., /dev/sdb1)
    mount_point: str
    created_partition: bool
    wiped_signatures: bool


def provision_cartridge(
    device: str,
    label: str,
    force_repartition: bool = False,
    dry_run: bool = False,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> ProvisionResult:
    """
    Full provisioning workflow:
    1. Analyze device
    2. Wipefs -a on device and partition (if exists)
    3. Create GPT + single ext4 partition (if !has_partitions or force_repartition)
    4. mkfs.ext4 -L <label> on partition device
    5. udevadm trigger --action=add on partition device
    6. Initialize directory structure
    """
    import time

    def _emit(step: str, current: int, total: int) -> None:
        if progress_cb:
            progress_cb(step, current, total)
        logger.info("[%d/%d] %s", current, total, step)

    device_path = Path(device)
    if not device_path.exists():
        raise ValueError(f"Device {device} does not exist")

    _emit("analyzing", 0, 5)
    analysis = analyze_device(device)

    _emit("wiping", 1, 5)
    wiped = False
    if not dry_run:
        # Unmount device and all partitions before wiping
        real_device = str(Path(device).resolve())
        for line in Path("/proc/mounts").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                try:
                    resolved = str(Path(parts[0]).resolve())
                    if resolved == real_device or resolved.startswith(real_device):
                        subprocess.run(["sudo", "-n", "umount", "-l", parts[1]], check=False)
                except (OSError, ValueError):
                    pass

        subprocess.run(["sudo", "-n", "wipefs", "-a", device], check=False)
        if analysis.partition_device and Path(analysis.partition_device).exists():
            subprocess.run(["sudo", "-n", "wipefs", "-a", analysis.partition_device], check=False)
        wiped = True

    partition_device = analysis.partition_device
    created_partition = False

    if not analysis.has_partitions or force_repartition:
        _emit("partitioning", 2, 5)
        if not dry_run:
            subprocess.run(
                ["sudo", "-n", "parted", device, "--script",
                 "mklabel", "gpt", "mkpart", "primary", "ext4", "0%", "100%"],
                check=True,
            )
            partition_device = f"{device}1"
            created_partition = True
    else:
        _emit("partitioning", 2, 5)

    _emit("formatting", 3, 5)
    if not dry_run:
        subprocess.run(
            ["sudo", "-n", "mkfs.ext4", "-L", label, "-F", partition_device],
            check=True,
        )

    _emit("initializing", 4, 5)
    mount_point = f"/mnt/photon_ssd/{label.replace('PHOTON-', '')}"

    if not dry_run:
        subprocess.run(
            ["sudo", "-n", "udevadm", "trigger", "--action=add", partition_device],
            check=False,
        )
        time.sleep(1)

    return ProvisionResult(
        label=label,
        device=partition_device or device,
        mount_point=mount_point,
        created_partition=created_partition,
        wiped_signatures=wiped,
    )
