#!/bin/bash
# PHOTONForge: Mount a PHOTON-* ext4 SSD cartridge and launch the pipeline.
# Called by udev rule 99-photo-ssd.rules on ACTION==add.
# Usage: on_ssd_add.sh <device> <label>
#
# Constraints (DO NOT REGRESS):
#   - Uses systemd-mount so the mount survives udev worker timeout.
#   - Chowns mount point to alex:alex so the pipeline runs unprivileged.
#   - No inline shell here; all logic in this script, not in the udev RUN value.
set -euo pipefail

DEVICE="${1:?Usage: on_ssd_add.sh <device> <label>}"
LABEL="${2:?Usage: on_ssd_add.sh <device> <label>}"
PIPELINE_USER="${PIPELINE_USER:-alex}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/photonforge/deploy/docker-compose.yml}"
SERVICE="${SERVICE:-photo-workflow}"
LOG="/var/log/photonforge.log"

log() { printf '[%s] [on_ssd_add] %s\n' "$(date -Iseconds)" "$*" | tee -a "$LOG"; }

log "SSD add: $DEVICE label=$LABEL"

[ -b "$DEVICE" ] || { log "ERROR: $DEVICE is not a block device"; exit 1; }

# Strip PHOTON- prefix for mount point name (e.g. PHOTON-001 -> 001)
CARTRIDGE_ID="${LABEL#PHOTON-}"
MOUNT_POINT="/mnt/photon_ssd/${CARTRIDGE_ID}"

mkdir -p "$MOUNT_POINT"

# Use systemd-mount so the mount outlives the udev worker cgroup
systemd-mount --no-block --automount=no \
    --options "rw,noatime" \
    "$DEVICE" "$MOUNT_POINT"

# Wait for mount to appear (systemd-mount --no-block returns before mount is ready)
for i in $(seq 1 10); do
    findmnt --noheadings "$MOUNT_POINT" >/dev/null 2>&1 && break
    sleep 1
done
findmnt --noheadings "$MOUNT_POINT" >/dev/null 2>&1 || {
    log "ERROR: $MOUNT_POINT not mounted after 10s"
    exit 1
}

# Chown so the pipeline runs as the non-root user
chown "${PIPELINE_USER}:${PIPELINE_USER}" "$MOUNT_POINT"
log "Mounted $DEVICE at $MOUNT_POINT (owner: $PIPELINE_USER)"

export PHOTON_MOUNT="$MOUNT_POINT"
log "Starting pipeline container for $LABEL"
docker compose -f "$COMPOSE_FILE" run --rm \
    -e PHOTON_SOURCE="$MOUNT_POINT" \
    "$SERVICE" >> "$LOG" 2>&1

log "Pipeline complete for $LABEL"
