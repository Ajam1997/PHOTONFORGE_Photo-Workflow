#!/bin/sh
# SSD detection and Docker device remapping for PHOTONForge.
# Triggered by udev when a PHOTON-labeled SSD is inserted.
# Usage: manage_ssd.sh <device> <mount_point>
set -euo pipefail

DEVICE="${1:?Usage: manage_ssd.sh <device> <mount_point>}"
MOUNT_POINT="${2:?Usage: manage_ssd.sh <device> <mount_point>}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/photonforge/deploy/docker-compose.yml}"
SERVICE="${SERVICE:-photo-workflow}"

log() { printf '[manage_ssd] %s\n' "$*" >&2; }

log "SSD detected: $DEVICE at $MOUNT_POINT"

# Verify the volume has a PHOTON label
LABEL="$(lsblk -no LABEL "$DEVICE" 2>/dev/null || echo '')"
if ! echo "$LABEL" | grep -q '^PHOTON'; then
    log "Label '$LABEL' does not match PHOTON prefix — ignoring"
    exit 0
fi

# Export for docker-compose environment substitution
export PHOTON_DEVICE="$DEVICE"
export PHOTON_MOUNT="$MOUNT_POINT"

log "Starting pipeline container for $LABEL"
docker compose -f "$COMPOSE_FILE" run --rm \
    -e PHOTON_SOURCE="$MOUNT_POINT" \
    --device "$DEVICE" \
    "$SERVICE"

log "Pipeline complete for $LABEL"
