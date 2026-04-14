#!/bin/bash
# PHOTONForge: Safely eject a PHOTON-* SSD cartridge.
# Called by udev rule 99-photo-ssd.rules on ACTION==remove.
# Usage: on_ssd_remove.sh <device> <label>
#
# Constraints (DO NOT REGRESS):
#   - Delegates to safe_eject.sh for WAL flush + unmount.
#   - No inline shell; all logic here, not in the udev RUN value.
set -euo pipefail

DEVICE="${1:?Usage: on_ssd_remove.sh <device> <label>}"
LABEL="${2:?Usage: on_ssd_remove.sh <device> <label>}"
SCRIPT_DIR="$(dirname "$0")"
LOG="/var/log/photonforge.log"

log() { printf '[%s] [on_ssd_remove] %s\n' "$(date -Iseconds)" "$*" | tee -a "$LOG"; }

log "SSD remove: $DEVICE label=$LABEL"

CARTRIDGE_ID="${LABEL#PHOTON-}"
MOUNT_POINT="/mnt/photon_ssd/${CARTRIDGE_ID}"
DB_PATH="${MOUNT_POINT}/darktable/library.db"

"$SCRIPT_DIR/safe_eject.sh" "$MOUNT_POINT" "$DB_PATH" >> "$LOG" 2>&1 || true
log "SSD eject complete: $LABEL"
