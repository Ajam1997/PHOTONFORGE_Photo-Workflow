#!/usr/bin/env bash
# One-time install: grant the sidecar passwordless sudo for disk operations.
# Must be run as root (or via sudo) on the Yoga 910.
set -euo pipefail

SUDOERS_FILE="/etc/sudoers.d/photonforge"
SUDOERS_USER="${SUDO_USER:-alex}"

if [[ $EUID -ne 0 ]]; then
  echo "Run this script as root: sudo bash scripts/install_polkit.sh" >&2
  exit 1
fi

# Write all commands on a single line — multi-line sudoers entries require \
# continuation and are easy to get wrong.
echo "${SUDOERS_USER} ALL=(ALL) NOPASSWD: /usr/sbin/parted *, /usr/sbin/wipefs *, /usr/sbin/mkfs.ext4 *, /usr/bin/udevadm *, /usr/bin/umount *" \
  > "$SUDOERS_FILE"
chmod 440 "$SUDOERS_FILE"

# Validate before leaving — visudo -c exits non-zero if syntax is bad.
if ! visudo -c -f "$SUDOERS_FILE"; then
  echo "ERROR: sudoers syntax check failed — removing bad file" >&2
  rm -f "$SUDOERS_FILE"
  exit 1
fi

echo "Sudoers rule installed at $SUDOERS_FILE"
echo "Test with: sudo -n mkfs.ext4 --help"
