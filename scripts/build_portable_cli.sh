#!/usr/bin/env bash
# Freeze photo-workflow + photo-cartridge into a self-contained onedir build
# for a portable cartridge's runtime/linux/ (portable-drive plan, Task 6).
#
# Builds in a FRESH, throwaway venv and installs the package NON-EDITABLE, so
# the frozen build reflects exactly what `pip install .` would ship -- never
# an editable install pointing back at this checkout's src/ tree, which would
# make the frozen exe silently depend on files that will not travel with it.
#
# Usage:
#   scripts/build_portable_cli.sh [OUTPUT_DIR]
#   OUTPUT_DIR defaults to <repo>/runtime/linux. Point it at a mounted
#   cartridge's runtime/linux/ to build straight onto the drive.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$REPO_ROOT/runtime/linux}"

log() { printf '[build] %s\n' "$*" >&2; }

BUILD_TMP="$(mktemp -d)"
trap 'rm -rf "$BUILD_TMP"' EXIT
BUILD_VENV="$BUILD_TMP/venv"

log "repo:   $REPO_ROOT"
log "output: $OUT_DIR"

python3 -m venv "$BUILD_VENV"
"$BUILD_VENV/bin/pip" install --quiet --upgrade pip
log "installing photo-workflow[build] (non-editable)..."
"$BUILD_VENV/bin/pip" install --quiet "${REPO_ROOT}[build]"

log "running pyinstaller..."
"$BUILD_VENV/bin/pyinstaller" --noconfirm --clean \
  --distpath "$BUILD_TMP/dist" --workpath "$BUILD_TMP/work" \
  "$REPO_ROOT/scripts/photonforge.spec"

# The spec's single COLLECT() call already produces a flat directory with
# both executables and one shared _internal/ -- exactly the shape
# runner.lua's portable_exe() probes for. Nothing to flatten; just place it.
rm -rf "$OUT_DIR"
mkdir -p "$(dirname "$OUT_DIR")"
mv "$BUILD_TMP/dist/photonforge-runtime" "$OUT_DIR"

log "smoke-testing the frozen executables..."
if ! "$OUT_DIR/photo-workflow" --help >/dev/null; then
  log "FAILED: $OUT_DIR/photo-workflow --help"
  exit 1
fi
if ! "$OUT_DIR/photo-cartridge" --help >/dev/null; then
  log "FAILED: $OUT_DIR/photo-cartridge --help"
  exit 1
fi

SIZE="$(du -sh "$OUT_DIR" | cut -f1)"
log "OK: $OUT_DIR ($SIZE) -- photo-workflow, photo-cartridge, _internal/"
