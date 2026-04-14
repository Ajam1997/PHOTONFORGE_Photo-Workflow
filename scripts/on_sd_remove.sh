#!/bin/bash
# PHOTONForge: Safely eject an SD card.
# Called by udev rule 99-photo-sd.rules on ACTION==remove.
# Usage: on_sd_remove.sh <device>
#
# Constraints (DO NOT REGRESS):
#   - Handles both systemd-mount case and automount symlink case.
#   - No inline shell; all logic here, not in the udev RUN value.
set -euo pipefail

DEVICE="${1:?Usage: on_sd_remove.sh <device>}"
MOUNT_POINT="/mnt/photon_sd"
SCRIPT_DIR="$(dirname "$0")"
LOG="/var/log/photonforge.log"

log() { printf '[%s] [on_sd_remove] %s\n' "$(date -Iseconds)" "$*" | tee -a "$LOG"; }

log "SD remove: $DEVICE"

if [ -L "$MOUNT_POINT" ]; then
    log "Removing automount symlink: $MOUNT_POINT"
    rm -f "$MOUNT_POINT"
elif [ -d "$MOUNT_POINT" ]; then
    "$SCRIPT_DIR/safe_eject.sh" "$MOUNT_POINT" >> "$LOG" 2>&1 || true
fi

log "SD eject complete: $DEVICE"
