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

# --- Genre prototypes: precompute 8×512 CLIP text embeddings ----------------
CLIP_TEXT_ENCODER="${REPO_ROOT}/models/mobileclip_s2_int8/text_encoder.onnx"
GENRE_PROTO="${REPO_ROOT}/models/genre_prototypes.npy"

if [ -f "$CLIP_TEXT_ENCODER" ]; then
    if [ -f "$GENRE_PROTO" ] && [ "$FORCE" = false ]; then
        log "Genre prototypes already present at $GENRE_PROTO. Use --force to regenerate."
    else
        log "Generating genre prototypes from CLIP text encoder..."
        python3 - <<'GENRE_EOF'
import sys
from pathlib import Path
import os
import numpy as np

repo_root = Path(os.environ.get("REPO_ROOT", "."))
text_encoder_path = repo_root / "models" / "mobileclip_s2_int8" / "text_encoder.onnx"
output_path = repo_root / "models" / "genre_prototypes.npy"

import onnxruntime as ort

try:
    from transformers import CLIPTokenizer
    tokenizer = CLIPTokenizer.from_pretrained("apple/MobileCLIP-S2-OpenCLIP", cache_dir=str(repo_root / "models" / ".cache" / "tokenizer"))
except Exception:
    from open_clip import get_tokenizer
    tokenizer = get_tokenizer("MobileCLIP-S2")

sess = ort.InferenceSession(str(text_encoder_path), providers=["CPUExecutionProvider"])
input_name = sess.get_inputs()[0].name

genre_prompts = [
    "a wildlife photograph of animals in their natural habitat",
    "a landscape photograph of natural scenery, mountains, or seascape",
    "a portrait photograph of a person, headshot or upper body",
    "a street photography scene of urban life and candid moments",
    "an architectural photograph of buildings, structures, or interiors",
    "a macro close-up photograph of small subjects with fine detail",
    "an event photograph of people at a gathering, ceremony, or celebration",
    "a general photograph",
]

prototypes = []
for prompt in genre_prompts:
    tokens = tokenizer(prompt, return_tensors="np", padding="max_length", max_length=77, truncation=True)
    input_ids = tokens["input_ids"].astype(np.int64) if hasattr(tokens, "__getitem__") else tokens.numpy().astype(np.int64)
    if input_ids.ndim == 1:
        input_ids = np.expand_dims(input_ids, 0)
    out = sess.run(None, {input_name: input_ids})
    emb = out[0].flatten().astype(np.float32)
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb = emb / norm
    prototypes.append(emb)
    print(f"[provision_models] Encoded: {prompt[:50]}... -> {emb.shape}", file=sys.stderr)

proto_matrix = np.stack(prototypes)  # (8, 512)
np.save(str(output_path), proto_matrix)
print(f"[provision_models] Saved genre prototypes: {output_path} shape={proto_matrix.shape}", file=sys.stderr)
GENRE_EOF
        log "Genre prototypes generated at $GENRE_PROTO"
    fi
else
    log "WARNING: CLIP text encoder not found at $CLIP_TEXT_ENCODER — skipping genre prototypes."
    log "Genre classification will fall back to EXIF+YOLO only."
fi
