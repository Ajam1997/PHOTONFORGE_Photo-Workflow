# ADR-003 — udisks2 Auto-Mount + Polling Instead of udev Rules

**Status:** Accepted (recorded retroactively, 2026-07)

## Context

The original host-integration design used custom udev rules (an
`install_udev.sh` script and a `deploy/udev/` rules directory, both since
deleted) to trigger ingest when a PHOTON cartridge or SD card was inserted.
Custom udev rules require root installation, fight the desktop's own
auto-mounter, and are hard to debug on a stock Ubuntu desktop session.

## Decision

Rely on the desktop's **udisks2 auto-mount** and detect volumes by
**polling** instead of event hooks:

- Volume/label detection via `lsblk` (`src/photo_workflow/volume.py`);
  mount appearance observed in `/proc/mounts`
  (state machine: [system-state-machine.md](../system-state-machine.md)).
- Safe eject via `udisksctl unmount` with a plain `umount` fallback
  (`scripts/safe_eject.sh`, soak-tested by `scripts/soak_cycle.py`).
- Privileged provisioning operations (parted/wipefs/mkfs.ext4/udevadm/umount)
  are granted through a scoped sudoers rule installed once by
  `scripts/install_polkit.sh`; the DT plugin launches elevated commands via
  `pkexec` in a visible terminal.

## Consequences

- No root daemon and no custom udev rules to install; stock udisks2 behavior
  is preserved.
- Fully automatic ingest-on-insert (UN-030) and auto-eject (UN-041) are
  deferred to v2; Release 1 is plugin-driven with manual eject.
- Docs citing udev scopes/scripts were corrected in the 2026-07 docs overhaul.
