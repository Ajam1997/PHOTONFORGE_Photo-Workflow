#!/bin/bash
# PHOTONForge: Mount and ingest a PHOTON-* ext4 cartridge.
# Usage: manage_ssd.sh <device> <label>
set -euo pipefail

DEVICE="${1:?Usage: manage_ssd.sh <device> <label>}"
LABEL="${2:?Usage: manage_ssd.sh <device> <label>}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/photonforge/deploy/docker-compose.yml}"
SERVICE="${SERVICE:-photo-workflow}"

# Strip PHOTON- prefix to get the cartridge ID (e.g. PHOTON-001 -> 001)
CARTRIDGE_ID="${LABEL#PHOTON-}"
MOUNT_POINT="/mnt/photon_ssd/${CARTRIDGE_ID}"

log() { printf '[%s] [manage_ssd] %s\n' "$(date -Iseconds)" "$*"; }

log "Cartridge $LABEL ($CARTRIDGE_ID) detected at $DEVICE"

# Guard: ensure this is actually a block device before proceeding
[ -b "$DEVICE" ] || { log "ERROR: $DEVICE is not a block device"; exit 1; }

mkdir -p "$MOUNT_POINT"
mount "$DEVICE" "$MOUNT_POINT" || { rmdir "$MOUNT_POINT" 2>/dev/null; exit 1; }
log "Mounted $DEVICE at $MOUNT_POINT"

# Unmount on any exit (success or failure) after this point
trap 'log "Cleanup: unmounting $MOUNT_POINT"; umount "$MOUNT_POINT" 2>/dev/null || true' EXIT

# Export so docker compose resolves the volume binding ${PHOTON_MOUNT}:/media/source
export PHOTON_MOUNT="$MOUNT_POINT"

log "Starting pipeline container"
docker compose -f "$COMPOSE_FILE" run --rm \
    -e PHOTON_SOURCE="$MOUNT_POINT" \
    "$SERVICE"

log "Pipeline complete for $LABEL"
