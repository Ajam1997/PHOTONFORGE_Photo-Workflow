#!/bin/bash
# Provision Florence-2-base-ft INT8 ONNX weights for PHOTONForge.
# Run ONCE during initial machine setup — NOT during pipeline operation.
# Requires: Python 3.11+, huggingface_hub, onnxruntime
#
# Usage:
#   bash scripts/provision_models.sh [--force]
#
# Output:
#   models/florence2_int8/   — INT8-quantized encoder + decoder ONNX files
#
# NFR-2.1: This script intentionally uses the internet. After it completes,
# the pipeline runs 100% offline. Do not call this script from pipeline code.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS_DIR="${REPO_ROOT}/models/florence2_int8"
CACHE_DIR="${REPO_ROOT}/models/.cache/florence2_fp32"
FORCE=false

log() { printf '[%s] [provision_models] %s\n' "$(date -Iseconds)" "$*" >&2; }

for arg in "$@"; do
    case "$arg" in
        --force) FORCE=true ;;
        *) log "Unknown argument: $arg"; exit 1 ;;
    esac
done

# Check for required Python packages
python3 -c "import huggingface_hub, onnxruntime" 2>/dev/null || {
    log "ERROR: Missing Python dependencies. Install with:"
    log "  pip install huggingface_hub onnxruntime"
    exit 1
}

if [ -d "$MODELS_DIR" ] && [ "$FORCE" = false ]; then
    COUNT="$(find "$MODELS_DIR" -name '*.onnx' | wc -l)"
    if [ "$COUNT" -gt 0 ]; then
        log "INT8 weights already present at $MODELS_DIR ($COUNT .onnx files). Use --force to re-download."
        exit 0
    fi
fi

log "Downloading Florence-2-base-ft ONNX from onnx-community/Florence-2-base-ft..."
mkdir -p "$CACHE_DIR" "$MODELS_DIR"

python3 - <<'PYEOF'
import sys
from pathlib import Path
import os

repo_root = Path(os.environ.get("REPO_ROOT", "."))
cache_dir = repo_root / "models" / ".cache" / "florence2_fp32"
models_dir = repo_root / "models" / "florence2_int8"

from huggingface_hub import snapshot_download

local_dir = snapshot_download(
    repo_id="onnx-community/Florence-2-base-ft",
    local_dir=str(cache_dir),
    ignore_patterns=["*.msgpack", "*.h5", "flax_model*", "tf_model*", "rust_model*"],
)
print(f"[provision_models] Downloaded to {local_dir}", file=sys.stderr)

from onnxruntime.quantization import quantize_dynamic, QuantType

fp32_dir = Path(local_dir) / "onnx"
if not fp32_dir.exists():
    fp32_dir = Path(local_dir)

onnx_files = list(fp32_dir.glob("*.onnx"))
if not onnx_files:
    print(f"[provision_models] ERROR: No .onnx files found in {fp32_dir}", file=sys.stderr)
    sys.exit(1)

for src in onnx_files:
    dst = models_dir / src.name
    print(f"[provision_models] Quantizing {src.name} -> INT8...", file=sys.stderr)
    quantize_dynamic(
        str(src),
        str(dst),
        weight_type=QuantType.QUInt8,
        optimize_model=True,
    )
    print(f"[provision_models] Written: {dst}", file=sys.stderr)

print(f"[provision_models] Done. {len(onnx_files)} model(s) quantized.", file=sys.stderr)
PYEOF

export REPO_ROOT
log "Quantization complete. Weights at $MODELS_DIR"
log "Listing:"
find "$MODELS_DIR" -name '*.onnx' -exec ls -lh {} \;
