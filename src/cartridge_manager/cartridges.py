"""Backend cartridge introspection — no PySide6 import."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from photo_workflow import backup


@dataclass
class CartridgeInfo:
    """Displayable summary of a cartridge's contents and state."""

    root: Path
    label: str
    cart_id: str
    free_bytes: int
    total_bytes: int
    busy_reason: str | None
    has_photonforge_db: bool
    has_darktable: bool


def describe(root: Path) -> CartridgeInfo:
    """Gather everything the cartridge list view needs about one cartridge root.

    Degrades gracefully — never raises — the same way backup.describe_cartridge
    already does, since this is read-only status display, not a destructive
    operation that should refuse on uncertainty.
    """
    root = Path(root)

    # Basic info: label, id, root path
    desc = backup.describe_cartridge(root)
    label = desc.get("label", "")
    cart_id = desc.get("id", "")

    # Busy status
    busy_reason = backup.cartridge_busy_reason(root)

    # Database presence
    layout = backup.cartridge_layout(root)
    has_photonforge_db = "photonforge" in layout.dbs
    has_darktable = "dt_library" in layout.dbs

    # Free/total space; gracefully degrade to 0 if the path doesn't exist
    # or is unmounted (drive may have been ejected between list and refresh)
    free_bytes = 0
    total_bytes = 0
    try:
        usage = shutil.disk_usage(root)
        free_bytes = usage.free
        total_bytes = usage.total
    except OSError:
        pass  # path missing or unmounted; leave both at 0

    return CartridgeInfo(
        root=root,
        label=label,
        cart_id=cart_id,
        free_bytes=free_bytes,
        total_bytes=total_bytes,
        busy_reason=busy_reason,
        has_photonforge_db=has_photonforge_db,
        has_darktable=has_darktable,
    )
