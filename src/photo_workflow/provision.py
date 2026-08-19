# src/photo_workflow/provision.py
from __future__ import annotations

import json
import logging
import os
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
    # Use the kernel's own name for the first partition (handles nvme0n1p1,
    # mmcblk0p1, sdb1 alike) instead of guessing "{device}1".
    partition_device = f"/dev/{children[0]['name']}" if has_partitions else None

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


def _partition_node(device: str) -> str:
    """First-partition node: /dev/sdb -> /dev/sdb1, /dev/nvme0n1 -> /dev/nvme0n1p1."""
    return f"{device}p1" if device[-1].isdigit() else f"{device}1"


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


# Supported cartridge filesystems.
#
# exFAT is the default because a cartridge has to be readable by Windows, macOS
# and Android as well as Linux, and ext4 is Linux-only (see the portable-drive
# plan's "Dominant constraint"). ext4 stays available for a Linux-only drive.
#
# parted_type is parted's fs-type argument, which on GPT only selects the
# PARTITION TYPE GUID -- mkfs decides the actual filesystem. "ntfs" looks wrong
# next to exFAT but is deliberate: it yields Microsoft Basic Data, the GUID
# Windows expects before it will assign a drive letter. Naming ext4 there would
# stamp "Linux filesystem data" onto a drive whose whole point is cross-OS use.
#
# mkfs_label_flag differs by tool: exfatprogs' mkfs.exfat takes -L. The older
# exfat-utils build takes -n, so exfatprogs specifically is required.
_FILESYSTEMS = {
    "exfat": {
        "mkfs": "mkfs.exfat",
        "parted_type": "ntfs",
        "label_flag": "-L",
        "extra_args": [],
        "max_label": 11,      # exFAT volume labels are capped at 11 characters
    },
    "ext4": {
        "mkfs": "mkfs.ext4",
        "parted_type": "ext4",
        "label_flag": "-L",
        "extra_args": ["-F"],
        "max_label": 16,
    },
}

DEFAULT_FS = "exfat"


def _fs_spec(fs: str) -> dict:
    spec = _FILESYSTEMS.get(fs)
    if spec is None:
        raise ValueError(
            f"Unsupported filesystem {fs!r}; expected one of {sorted(_FILESYSTEMS)}"
        )
    return spec


def _resolve_mount_point(partition_device: str | None, label: str) -> str:
    """Where the cartridge actually ended up, once udisks2 has auto-mounted it.

    The old hardcoded /mnt/photon_ssd/<id> never matched reality -- udisks2
    mounts under /media/$USER/<LABEL> -- so callers were handed a path with
    nothing on it. Ask the kernel, and fall back to the udisks2 convention only
    when the answer is not available yet.
    """
    if partition_device:
        try:
            result = subprocess.run(
                ["lsblk", "--json", "--output", "NAME,MOUNTPOINT", partition_device],
                capture_output=True, text=True, check=True,
            )
            for dev in json.loads(result.stdout).get("blockdevices", []):
                mount = dev.get("mountpoint")
                if mount:
                    return mount
        except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as exc:
            logger.debug("Could not read mount point for %s: %s", partition_device, exc)
    user = os.environ.get("SUDO_USER") or os.environ.get("USER") or "root"
    return f"/media/{user}/{label}"


@dataclass
class ProvisionResult:
    label: str
    device: str  # The partition device (e.g., /dev/sdb1)
    mount_point: str
    created_partition: bool
    wiped_signatures: bool
    filesystem: str = DEFAULT_FS


def provision_cartridge(
    device: str,
    label: str,
    force_repartition: bool = False,
    dry_run: bool = False,
    progress_cb: Callable[[str, int, int], None] | None = None,
    fs: str = DEFAULT_FS,
) -> ProvisionResult:
    """
    Full provisioning workflow:
    1. Analyze device
    2. Wipefs -a on device and partition (if exists)
    3. Create GPT + single partition (if !has_partitions or force_repartition)
    4. mkfs.<fs> -L <label> on partition device
    5. udevadm trigger --action=add on partition device
    6. Resolve the resulting mount point

    `fs` defaults to exFAT so the cartridge is readable on Windows, macOS and
    Android as well as Linux; pass "ext4" for a Linux-only drive.
    """
    import time

    def _emit(step: str, current: int, total: int) -> None:
        if progress_cb:
            progress_cb(step, current, total)
        logger.info("[%d/%d] %s", current, total, step)

    spec = _fs_spec(fs)
    if len(label) > spec["max_label"]:
        raise ValueError(
            f"Label {label!r} is {len(label)} characters; {fs} allows at most "
            f"{spec['max_label']}"
        )

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

        # Wipe the whole device (erasing the partition table) ONLY when we are
        # about to create a new one. When reusing an existing partition, wipe
        # just that partition's filesystem signature — wiping the device here
        # used to erase the GPT and then format through a stale kernel node,
        # bricking the cartridge on replug.
        if not analysis.has_partitions or force_repartition:
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
                 "mklabel", "gpt", "mkpart", "primary", spec["parted_type"],
                 "0%", "100%"],
                check=True,
            )
            partition_device = _partition_node(device)
            created_partition = True
            # The new partition node may not exist yet; wait for udev.
            subprocess.run(["sudo", "-n", "udevadm", "settle"], check=False)
            for _ in range(20):
                if Path(partition_device).exists():
                    break
                time.sleep(0.25)
    else:
        _emit("partitioning", 2, 5)

    _emit("formatting", 3, 5)
    if not dry_run:
        subprocess.run(
            ["sudo", "-n", spec["mkfs"], spec["label_flag"], label,
             *spec["extra_args"], partition_device],
            check=True,
        )

    _emit("initializing", 4, 5)

    if not dry_run:
        subprocess.run(
            ["sudo", "-n", "udevadm", "trigger", "--action=add", partition_device],
            check=False,
        )
        time.sleep(1)

    mount_point = _resolve_mount_point(partition_device, label)

    return ProvisionResult(
        label=label,
        device=partition_device or device,
        mount_point=mount_point,
        created_partition=created_partition,
        wiped_signatures=wiped,
        filesystem=fs,
    )
