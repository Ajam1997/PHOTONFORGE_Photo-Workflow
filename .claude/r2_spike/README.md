# R2 model-stack spike

Long-pole scaffold for the one-shot R2 spike. Spec:
`dev-docs/architecture/r2-model-stack-investigation.md` (§ Spike Specification).

**Runs on the dev-box venv**, not this repo's host system Python. Prereqs:
`torch`, `transformers`, `onnxruntime`, `opencv-python`, plus the
`photo_workflow` package importable (`pip install -e .`).

## Run order

1. **Export the dual-output SegFormer** (the long pole — adds the pooled-feature
   tap stock ONNX lacks):

   ```
   python .claude/r2_spike/export_segformer_dual.py --out-dir models/segformer_b0_ade_int8
   ```

   Then **review** `models/segformer_b0_ade_int8/region_lut.json` and correct any
   class→region-type assignment before step 2 (the script prints the table).

2. **Extract features once** into the shared cache:

   ```
   python .claude/r2_spike/extract_features.py \
       --segformer models/segformer_b0_ade_int8/model.onnx \
       --corpus corpus/genre_labels.jsonl --image-root <corpus image root> \
       --eval-dirs <ICELAND dir> <MISC2026 dir> \
       --photon-db <photonforge.db> --cache-dir .claude/r2_spike/cache
   ```

   Reuses cached CLIP-S2 embeddings from `photonforge.db` when present; recomputes
   otherwise. Needs MobileCLIP-S0 provisioned at
   `models/mobileclip_s0_int8/vision_encoder.onnx` for the S0 candidate.

## Still to write (next)

- `track_a_probe.py` — read cache → logistic-regression genre probes (subject
  15-way, type 11-way, 5-fold CV) + aesthetic heads per backbone → decision table.
- `track_b_caption_bench.py` — SmolVLM2 / LFM2.5-VL / Florence-2 ONNX harness ×
  {bare, instruction, grounded} prompts over the eval frames → caption + latency
  + RSS table.

## Notes / assumptions to verify on first run

- `pooled_feat` is the MiT-b0 last-stage GAP (256-d for b0). The export prints a
  warning if the dim isn't 256.
- SegFormer uses ImageNet normalization (handled in `extract_features.py`);
  MobileCLIP uses identity norm at 256px (handled in `_run_clip`). Confirm the
  S0 export matches that preprocessing.
- Corpus path resolution assumes `<image-root>/<source_folder>/<filename>`, with
  an `rglob` fallback by filename.
