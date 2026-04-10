"""FR-1.9: SSD volume detection and management."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

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
                    stat = Path(mount).stat()
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
