---
name: Florence-2 caption prompt root cause and fix
description: The correct caption task prompt for Florence-2-base-ft is text "What does the image describe?" not the internal <cap> token (51269)
type: project
---

The internal `<cap>` token (id=51269) used as an encoder input produces VQA non-answers ("answering does not require reading text in the image", "yes", "no") instead of captions. Confirmed via live diagnostic on Yoga 910 with real images.

The correct fix (verified on DSC04937–DSC04939.JPG): tokenize the string `"What does the image describe?"` as the encoder text prompt (produces IDs `[0, 2264, 473, 5, 2274, 6190, 116, 2]` with the Florence-2 tokenizer) and pass those embeddings concatenated after image features into the encoder.

**Why:** Florence-2-base-ft was fine-tuned with natural-language task prompts. The internal `<cap>` token is a vocabulary artifact from training data but the encoder was not trained to route it to captioning behavior.

**How to apply:** The fix is in `naming.py` (`CAPTION_PROMPT_TEXT = "What does the image describe?"`). If caption quality degrades after a model update, re-run the SSH diagnostic script to verify the prompt still produces descriptive output. Do not revert to token-based prompting.

Also: `decoder_model_merged_int8.onnx` exists and requires `past_key_values` inputs + `use_cache_branch` bool. Step 0 uses `use_cache_branch=False` with all-zero KV (shape `[1,12,0,64]`); steps 1+ use `use_cache_branch=True` with encoder KV held fixed from step 0 present outputs (encoder KV shape becomes `[1,12,585,64]` after step 0 — do NOT update it from subsequent present outputs which return `[0,12,1,64]`).
