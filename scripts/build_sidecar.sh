#!/usr/bin/env bash
set -euo pipefail

# Build the photo-workflow sidecar binary using PyInstaller.
# Must be run on the Yoga 910 (Linux x86_64).
# Output: photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$REPO_ROOT/photonforge-gui/src-tauri/binaries"
BINARY_NAME="photo-workflow-sidecar-x86_64-unknown-linux-gnu"

cd "$REPO_ROOT"

# Activate venv if present; otherwise rely on PATH having the right pip/pyinstaller
if [ -f ".venv/bin/activate" ]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi

echo "Installing build dependencies..."
pip install pyinstaller --quiet

echo "Building sidecar binary..."
pyinstaller \
  --onefile \
  --name "photo-workflow-sidecar" \
  --distpath "$OUTPUT_DIR" \
  --workpath /tmp/pyinstaller-build \
  --specpath /tmp/pyinstaller-build \
  src/photo_workflow/sidecar_cli.py

# Rename to Tauri's required target-triple format
mv "$OUTPUT_DIR/photo-workflow-sidecar" "$OUTPUT_DIR/$BINARY_NAME"
chmod +x "$OUTPUT_DIR/$BINARY_NAME"

echo "Binary written to: $OUTPUT_DIR/$BINARY_NAME"
echo "File size: $(du -h "$OUTPUT_DIR/$BINARY_NAME" | cut -f1)"
