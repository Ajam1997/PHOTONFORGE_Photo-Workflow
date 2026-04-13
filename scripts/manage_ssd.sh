#!/bin/sh
# PHOTONForge: Mount and ingest a PHOTON-* ext4 cartridge.
# Triggered by udev when a partition with label matching PHOTON-* is added.
# Cartridge ID is extracted from the label (PHOTON-001 -> 001) and used as
# the mount subdirectory, so multiple cartridges can coexist under /mnt/photon_ssd/.
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

mkdir -p "$MOUNT_POINT"
mount "$DEVICE" "$MOUNT_POINT"
log "Mounted $DEVICE at $MOUNT_POINT"

log "Starting pipeline container"
docker compose -f "$COMPOSE_FILE" run --rm \
    -e PHOTON_SOURCE="$MOUNT_POINT" \
    --device "$DEVICE" \
    "$SERVICE"

log "Pipeline complete for $LABEL"
