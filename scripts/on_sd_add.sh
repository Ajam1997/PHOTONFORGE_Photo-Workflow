#!/bin/bash
# PHOTONForge: Mount an SD card and trigger ingest pipeline.
# Called by udev rule 99-photo-sd.rules on ACTION==add.
# Usage: on_sd_add.sh <device>
#
# Constraints (DO NOT REGRESS):
#   - Uses systemd-mount (not plain mount) so mount survives udev worker timeout.
#   - Detects automount: if desktop already mounted the card, symlinks /mnt/photon_sd
#     to the existing mount point instead of double-mounting.
#   - No inline shell; all logic here, not in the udev RUN value.
set -euo pipefail

DEVICE="${1:?Usage: on_sd_add.sh <device>}"
MOUNT_POINT="/mnt/photon_sd"
OUTPUT_DIR="${PHOTON_OUTPUT:-/var/lib/photonforge/output}"
DARKTABLE_DB="${DARKTABLE_DB:-/mnt/photon_ssd/001/darktable/library.db}"
COMPOSE_FILE="${COMPOSE_FILE:-/opt/photonforge/deploy/docker-compose.yml}"
SERVICE="${SERVICE:-photo-workflow}"
LOG="/var/log/photonforge.log"

log() { printf '[%s] [on_sd_add] %s\n' "$(date -Iseconds)" "$*" | tee -a "$LOG"; }

log "SD add: $DEVICE"

[ -b "$DEVICE" ] || { log "ERROR: $DEVICE is not a block device"; exit 1; }

# Detect if Ubuntu desktop automounter already mounted this device
EXISTING_MOUNT="$(findmnt --noheadings --output TARGET --source "$DEVICE" 2>/dev/null || true)"

if [ -n "$EXISTING_MOUNT" ]; then
    log "Device already mounted at $EXISTING_MOUNT by automounter — symlinking"
    # Remove stale symlink or empty dir if present
    [ -L "$MOUNT_POINT" ] && rm -f "$MOUNT_POINT"
    [ -d "$MOUNT_POINT" ] && rmdir "$MOUNT_POINT" 2>/dev/null || true
    ln -sf "$EXISTING_MOUNT" "$MOUNT_POINT"
    log "Symlinked $MOUNT_POINT -> $EXISTING_MOUNT"
    MOUNTED_BY_US=false
else
    mkdir -p "$MOUNT_POINT"
    systemd-mount --no-block --automount=no \
        --options "ro,noatime" \
        "$DEVICE" "$MOUNT_POINT"

    # Wait for mount to appear
    for i in $(seq 1 10); do
        findmnt --noheadings "$MOUNT_POINT" >/dev/null 2>&1 && break
        sleep 1
    done
    findmnt --noheadings "$MOUNT_POINT" >/dev/null 2>&1 || {
        log "ERROR: $MOUNT_POINT not mounted after 10s"
        exit 1
    }
    log "Mounted $DEVICE at $MOUNT_POINT"
    MOUNTED_BY_US=true
fi

# Skip if card is empty
if [ -z "$(ls -A "$MOUNT_POINT" 2>/dev/null)" ]; then
    log "SD card is empty — skipping ingest"
    "$MOUNTED_BY_US" && systemd-mount --umount "$MOUNT_POINT" || true
    exit 0
fi

log "Starting ingest pipeline: source=$MOUNT_POINT output=$OUTPUT_DIR"
docker compose -f "$COMPOSE_FILE" run --rm \
    -e PHOTON_SOURCE="$MOUNT_POINT" \
    -e PHOTON_OUTPUT="$OUTPUT_DIR" \
    -e DARKTABLE_DB="$DARKTABLE_DB" \
    "$SERVICE" >> "$LOG" 2>&1

log "Ingest complete for $DEVICE"
