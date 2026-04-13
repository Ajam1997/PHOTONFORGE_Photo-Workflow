#!/bin/sh
# PHOTONForge: Mount and rsync-ingest an SD card insertion (usb-0:3, VID 05e3).
# Usage: ingest_sd.sh <device>
set -euo pipefail

DEVICE="${1:?Usage: ingest_sd.sh <device>}"
MOUNT_POINT="/mnt/photon_sd"
OUTPUT_DIR="${PHOTON_OUTPUT:-/var/lib/photonforge/output}"
DARKTABLE_DB="${DARKTABLE_DB:-${HOME}/.config/darktable/library.db}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/photonforge/deploy/docker-compose.yml}"
SERVICE="${SERVICE:-photo-workflow}"

log() { printf '[%s] [ingest_sd] %s\n' "$(date -Iseconds)" "$*"; }

log "SD card detected: $DEVICE"

# Guard: ensure this is actually a block device before proceeding
[ -b "$DEVICE" ] || { log "ERROR: $DEVICE is not a block device"; exit 1; }

mkdir -p "$MOUNT_POINT"
mount "$DEVICE" "$MOUNT_POINT" || { rmdir "$MOUNT_POINT" 2>/dev/null; exit 1; }
log "Mounted $DEVICE at $MOUNT_POINT"

# Unmount on any exit (success or failure) after this point
trap 'log "Cleanup: unmounting $MOUNT_POINT"; umount "$MOUNT_POINT" 2>/dev/null || true' EXIT

# Skip if card is empty (e.g. freshly formatted with no photos yet)
if [ -z "$(ls -A "$MOUNT_POINT" 2>/dev/null)" ]; then
    log "SD card is empty — skipping ingest"
    exit 0
fi

log "Starting ingest pipeline: source=$MOUNT_POINT output=$OUTPUT_DIR"
docker compose -f "$COMPOSE_FILE" run --rm \
    -e PHOTON_SOURCE="$MOUNT_POINT" \
    -e PHOTON_OUTPUT="$OUTPUT_DIR" \
    -e DARKTABLE_DB="$DARKTABLE_DB" \
    "$SERVICE"

log "Ingest complete for $DEVICE"
