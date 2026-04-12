#!/bin/sh
# PHOTONForge: rsync ingest triggered on SD card insertion (usb-0:3, VID 05e3).
# Runs the photo-workflow pipeline container against the SD mount point.
# Usage: ingest_sd.sh <device> <mount_point>
set -euo pipefail

DEVICE="${1:?Usage: ingest_sd.sh <device> <mount_point>}"
MOUNT_POINT="${2:?Usage: ingest_sd.sh <device> <mount_point>}"
OUTPUT_DIR="${PHOTON_OUTPUT:-/var/lib/photonforge/output}"
DARKTABLE_DB="${DARKTABLE_DB:-${HOME}/.config/darktable/library.db}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/photonforge/deploy/docker-compose.yml}"
SERVICE="${SERVICE:-photo-workflow}"

log() { printf '[%s] [ingest_sd] %s\n' "$(date -Iseconds)" "$*"; }

log "SD card detected: $DEVICE at $MOUNT_POINT"

# Skip if mount point is empty (partition table artifact, no filesystem yet)
if [ -z "$(ls -A "$MOUNT_POINT" 2>/dev/null)" ]; then
    log "Mount point $MOUNT_POINT is empty — skipping ingest"
    exit 0
fi

log "Starting ingest pipeline: source=$MOUNT_POINT output=$OUTPUT_DIR"
docker compose -f "$COMPOSE_FILE" run --rm \
    -e PHOTON_SOURCE="$MOUNT_POINT" \
    -e PHOTON_OUTPUT="$OUTPUT_DIR" \
    -e DARKTABLE_DB="$DARKTABLE_DB" \
    "$SERVICE"

log "Ingest complete for $DEVICE"
