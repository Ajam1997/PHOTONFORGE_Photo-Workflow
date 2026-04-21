#!/usr/bin/env bash
# One-time install: grant the sidecar binary passwordless permission to run mkfs.ext4.
# Must be run as root (or via sudo) on the Yoga 910.
set -euo pipefail

POLKIT_RULE="/etc/polkit-1/rules.d/50-photonforge-reformat.rules"

if [[ $EUID -ne 0 ]]; then
  echo "Run this script as root: sudo bash scripts/install_polkit.sh" >&2
  exit 1
fi

cat > "$POLKIT_RULE" << 'EOF'
// Allow photo-workflow-sidecar to reformat cartridges without a password.
// Covers: unmount (to clear existing mounts) and mkfs.ext4 (to reformat).
polkit.addRule(function(action, subject) {
    if (action.id === "org.freedesktop.policykit.exec" &&
        (action.lookup("program") === "/sbin/mkfs.ext4" ||
         action.lookup("program") === "/bin/umount" ||
         action.lookup("program") === "/usr/bin/umount") &&
        subject.user === "alex") {
        return polkit.Result.YES;
    }
});
EOF

chmod 644 "$POLKIT_RULE"
echo "Polkit rule installed at $POLKIT_RULE"
echo "Restart polkit to apply: systemctl restart polkit"
