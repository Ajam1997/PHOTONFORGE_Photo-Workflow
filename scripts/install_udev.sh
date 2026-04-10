#!/bin/sh
# Install PHOTONForge udev rules and reload udevd.
# Must be run as root.
set -euo pipefail

RULES_SRC="$(dirname "$0")/../deploy/udev"
RULES_DEST="/etc/udev/rules.d"

log() { printf '[install_udev] %s\n' "$*" >&2; }

if [ "$(id -u)" -ne 0 ]; then
    log "ERROR: Must run as root"
    exit 1
fi

log "Installing udev rules from $RULES_SRC → $RULES_DEST"
cp -v "$RULES_SRC"/99-photo-ssd.rules "$RULES_DEST/"
cp -v "$RULES_SRC"/99-photo-sd.rules  "$RULES_DEST/"

log "Reloading udev rules..."
udevadm control --reload-rules
udevadm trigger

log "udev rules installed successfully"
