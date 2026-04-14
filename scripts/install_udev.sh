#!/bin/bash
# Install PHOTONForge udev rules, wrapper scripts, and log file.
# Must be run as root.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RULES_SRC="${SCRIPT_DIR}/../deploy/udev"
RULES_DEST="/etc/udev/rules.d"
OPT_SCRIPTS="/opt/photonforge/scripts"
LOG_FILE="/var/log/photonforge.log"

log() { printf '[install_udev] %s\n' "$*" >&2; }

if [ "$(id -u)" -ne 0 ]; then
    log "ERROR: Must run as root"
    exit 1
fi

# Install udev rules
log "Installing udev rules from $RULES_SRC -> $RULES_DEST"
cp -v "$RULES_SRC/99-photo-ssd.rules" "$RULES_DEST/"
cp -v "$RULES_SRC/99-photo-sd.rules"  "$RULES_DEST/"

# Install wrapper scripts
log "Installing wrapper scripts to $OPT_SCRIPTS"
mkdir -p "$OPT_SCRIPTS"
for script in on_ssd_add.sh on_ssd_remove.sh on_sd_add.sh on_sd_remove.sh safe_eject.sh; do
    cp -v "${SCRIPT_DIR}/${script}" "${OPT_SCRIPTS}/"
    chmod 755 "${OPT_SCRIPTS}/${script}"
done

# Create log file with world-writable permissions so udev (root) and pipeline (alex) can both write
if [ ! -f "$LOG_FILE" ]; then
    touch "$LOG_FILE"
    chmod 666 "$LOG_FILE"
    log "Created $LOG_FILE"
else
    log "$LOG_FILE already exists — skipping"
fi

# Reload udev
log "Reloading udev rules..."
udevadm control --reload-rules
udevadm trigger

log "Installation complete"
