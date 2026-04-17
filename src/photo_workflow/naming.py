"""FR-1.7: Semantic filename generation via Florence-2-base-ft multi-file ONNX."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import click
import numpy as np

logger = logging.getLogger(__name__)

ONNX_SUBDIR = "onnx"
MAX_WORDS = 5
MAX_NEW_TOKENS = 30
EOS_TOKEN_ID = 2
DECODER_START_TOKEN_ID = 2   # decoder_start_token_id from generation_config.json
FORCED_BOS_TOKEN_ID = 0      # forced_bos_token_id: first generated token is always 0
# Florence-2 caption task prompt — "What does the image describe?" is the canonical
# text prompt that activates captioning in the fine-tuned Florence-2-base-ft model.
# Internal task token <cap> (id=51269) does NOT work as an encoder input — it produces
# VQA-style non-answers ("answering does not require reading...") instead of captions.
CAPTION_PROMPT_TEXT = "What does the image describe?"
_KPM_INFERENCE_LIMIT = 2.5  # seconds (KPM-1.2)
# Resize to 512×512 before vision encoding. Florence-2's ViT accepts dynamic spatial
# inputs; 512 reduces patch count by 55% vs 768 (257 vs 577 tokens), cutting vision
# encoder latency below the KPM-1.2 budget without meaningful caption quality loss.
INFER_IMG_SIZE = 512


@dataclass
class _Sessions:
    vision_encoder: object
    embed_tokens: object
    encoder: object
    decoder: object          # decoder_model_merged_int8.onnx — KV-cache enabled
    tokenizer: object | None
    img_size: tuple[int, int]   # (height, width)
    img_mean: np.ndarray        # shape (3,) float32
    img_std: np.ndarray         # shape (3,) float32
    prompt_ids: np.ndarray      # tokenized CAPTION_PROMPT_TEXT, shape (1, seq)
    decoder_out_names: list[str]  # output names for the decoder session


_session_cache: dict[str, _Sessions] = {}


def _resolve_onnx_path(onnx_dir: Path, stem: str) -> Path:
    """Resolve an ONNX model file by trying common quantization suffixes.

    For the decoder, prefer ``decoder_model_merged_int8.onnx`` (KV-cache enabled)
    before falling back to the non-merged variants.
    """
    # Merged decoder preferred for KV-cache (one token per step vs full sequence).
    if stem == "decoder_model":
        for suffix in (
            "decoder_model_merged_int8.onnx",
            "decoder_model_merged_fp16.onnx",
            "decoder_model_merged.onnx",
            "decoder_model_int8.onnx",
            "decoder_model_fp16.onnx",
            "decoder_model.onnx",
        ):
            p = onnx_dir / suffix
            if p.exists():
                return p
    elif stem == "vision_encoder":
        # uint8 is ~30% faster than int8 on i7-7500U AVX2 at 512×512 input.
        for suffix in (
            "vision_encoder_uint8.onnx",
            "vision_encoder_int8.onnx",
            "vision_encoder_fp16.onnx",
            "vision_encoder.onnx",
        ):
            p = onnx_dir / suffix
            if p.exists():
                return p
    else:
        for suffix in (f"{stem}_int8.onnx", f"{stem}_fp16.onnx", f"{stem}.onnx"):
            p = onnx_dir / suffix
            if p.exists():
                return p
    raise FileNotFoundError(
        f"No ONNX variant found for '{stem}' in {onnx_dir}."
    )


def _make_ort_session(path: Path) -> object:
    import onnxruntime as ort

    opts = ort.SessionOptions()
    opts.inter_op_num_threads = 2
    opts.intra_op_num_threads = 2
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(
        str(path),
        sess_options=opts,
        providers=["CPUExecutionProvider"],
    )


def _log_session_io(name: str, session: object) -> None:
    inputs = [f"{i.name}:{i.type}" for i in session.get_inputs()]  # type: ignore[union-attr]
    outputs = [f"{o.name}:{o.type}" for o in session.get_outputs()]  # type: ignore[union-attr]
    logger.info("[%s] inputs:  %s", name, inputs)
    logger.info("[%s] outputs: %s", name, outputs)


def _is_merged_decoder(session: object) -> bool:
    """Return True if *session* is the merged (KV-cache) decoder variant."""
    input_names = {i.name for i in session.get_inputs()}  # type: ignore[union-attr]
    return "use_cache_branch" in input_names


def _load_sessions(model_dir: Path) -> _Sessions:
    onnx_dir = model_dir / ONNX_SUBDIR

    vision_encoder_path = _resolve_onnx_path(onnx_dir, "vision_encoder")
    embed_path = _resolve_onnx_path(onnx_dir, "embed_tokens")
    encoder_path = _resolve_onnx_path(onnx_dir, "encoder_model")
    decoder_path = _resolve_onnx_path(onnx_dir, "decoder_model")

    logger.info("Loading Florence-2 ONNX sessions from %s", onnx_dir)
    logger.info("  vision_encoder : %s", vision_encoder_path.name)
    logger.info("  embed_tokens   : %s", embed_path.name)
    logger.info("  encoder        : %s", encoder_path.name)
    logger.info("  decoder        : %s", decoder_path.name)

    vision_encoder_sess = _make_ort_session(vision_encoder_path)
    embed_sess = _make_ort_session(embed_path)
    encoder_sess = _make_ort_session(encoder_path)
    decoder_sess = _make_ort_session(decoder_path)

    _log_session_io("vision_encoder", vision_encoder_sess)
    _log_session_io("embed_tokens", embed_sess)
    _log_session_io("encoder", encoder_sess)
    _log_session_io("decoder", decoder_sess)

    # Load preprocessor_config.json
    preproc_path = model_dir / "preprocessor_config.json"
    with open(preproc_path) as f:
        preproc = json.load(f)

    img_h = INFER_IMG_SIZE
    img_w = INFER_IMG_SIZE

    img_mean = np.array(preproc["image_mean"], dtype=np.float32)
    img_std = np.array(preproc["image_std"], dtype=np.float32)

    tokenizer = None
    tok_json = model_dir / "tokenizer.json"
    prompt_ids: np.ndarray = np.array([[0]], dtype=np.int64)  # fallback single BOS
    if tok_json.exists():
        try:
            from tokenizers import Tokenizer  # type: ignore[import]

            tokenizer = Tokenizer.from_file(str(tok_json))
            ids = tokenizer.encode(CAPTION_PROMPT_TEXT).ids
            prompt_ids = np.array([ids], dtype=np.int64)
            logger.info(
                "Caption prompt %r tokenized to %d tokens: %s",
                CAPTION_PROMPT_TEXT,
                len(ids),
                ids,
            )
        except Exception as e:
            logger.warning("Could not load tokenizer: %s — will use fallback prompt", e)

    decoder_out_names: list[str] = [o.name for o in decoder_sess.get_outputs()]  # type: ignore[union-attr]

    return _Sessions(
        vision_encoder=vision_encoder_sess,
        embed_tokens=embed_sess,
        encoder=encoder_sess,
        decoder=decoder_sess,
        tokenizer=tokenizer,
        img_size=(img_h, img_w),
        img_mean=img_mean,
        img_std=img_std,
        prompt_ids=prompt_ids,
        decoder_out_names=decoder_out_names,
    )


def _preprocess_image(path: Path, sessions: _Sessions) -> np.ndarray:
    import cv2

    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"Could not read image: {path}")
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = sessions.img_size
    img_resized = cv2.resize(img_rgb, (w, h)).astype(np.float32) / 255.0
    img_norm = (img_resized - sessions.img_mean) / sessions.img_std
    return np.transpose(img_norm, (2, 0, 1))[np.newaxis, :]  # (1, 3, H, W)


def _build_empty_past_kv(session: object) -> dict[str, np.ndarray]:
    """Build zero-filled past_key_values tensors for the first decoder step.

    The merged decoder requires explicit past_key_values inputs.  On step 0
    (``use_cache_branch=False``) the model recomputes both decoder and encoder
    attention from scratch, so an empty (seq_len=0) tensor is acceptable for
    all KV slots.

    Returns a dict mapping each ``past_key_values.*`` input name to a
    ``np.float32`` zero tensor of shape ``(1, 12, 0, 64)``.
    """
    return {
        inp.name: np.zeros((1, 12, 0, 64), dtype=np.float32)
        for inp in session.get_inputs()  # type: ignore[union-attr]
        if inp.name.startswith("past_key_values")
    }


def _run_inference(sessions: _Sessions, pixel_values: np.ndarray) -> str:
    # Step 1: vision encoder
    vision_out = sessions.vision_encoder.run(None, {"pixel_values": pixel_values})  # type: ignore[union-attr]
    image_features = vision_out[0]  # (1, img_seq, 768)

    # Step 2: embed caption task prompt tokens
    # CAPTION_PROMPT_TEXT ("What does the image describe?") is pre-tokenized at load time.
    text_embeds = sessions.embed_tokens.run(None, {"input_ids": sessions.prompt_ids})[0]  # type: ignore[union-attr]

    # Step 3: concatenate image_features + text_embeds and run encoder
    combined_embeds = np.concatenate([image_features, text_embeds], axis=1)
    attention_mask = np.ones((1, combined_embeds.shape[1]), dtype=np.int64)
    encoder_out = sessions.encoder.run(  # type: ignore[union-attr]
        None,
        {
            "attention_mask": attention_mask,
            "inputs_embeds": combined_embeds,
        },
    )[0]  # (1, combined_seq, 768)

    # Step 4: greedy decode
    use_kv_cache = _is_merged_decoder(sessions.decoder)

    if use_kv_cache:
        return _decode_with_kv_cache(sessions, encoder_out, attention_mask)
    else:
        return _decode_no_cache(sessions, encoder_out, attention_mask)


def _decode_with_kv_cache(
    sessions: _Sessions,
    encoder_hidden_states: np.ndarray,
    encoder_attention_mask: np.ndarray,
) -> str:
    """Greedy decode using the merged KV-cache decoder (decoder_model_merged_*).

    Step 0 processes the seed tokens [decoder_start=2, forced_bos=0] with
    ``use_cache_branch=False`` which computes and caches both the decoder and
    encoder attention states.  Steps 1+ process one token at a time with
    ``use_cache_branch=True``, reusing the cached encoder KV (which is fixed
    throughout generation) and accumulating the decoder KV.
    """
    out_names = sessions.decoder_out_names

    # --- Step 0: prime the cache ---
    seed_ids = np.array([[DECODER_START_TOKEN_ID, FORCED_BOS_TOKEN_ID]], dtype=np.int64)
    seed_embeds = sessions.embed_tokens.run(None, {"input_ids": seed_ids})[0]  # type: ignore[union-attr]

    kv_zero = _build_empty_past_kv(sessions.decoder)
    feed0: dict[str, np.ndarray] = {
        "inputs_embeds": seed_embeds,
        "encoder_hidden_states": encoder_hidden_states,
        "encoder_attention_mask": encoder_attention_mask,
        "use_cache_branch": np.array([False]),
        **kv_zero,
    }
    dec_out0 = sessions.decoder.run(None, feed0)  # type: ignore[union-attr]
    logits = dec_out0[0]
    present0 = {out_names[i]: dec_out0[i] for i in range(1, len(dec_out0))}

    # Encoder KV is fixed after step 0 (cross-attention cache does not change).
    # Decoder KV grows by 1 position per step.
    encoder_kv: dict[str, np.ndarray] = {k: v for k, v in present0.items() if "encoder" in k}
    decoder_kv: dict[str, np.ndarray] = {k: v for k, v in present0.items() if "decoder" in k}

    next_token = int(np.argmax(logits[0, -1, :]))
    generated: list[int] = []

    # --- Steps 1+: one token at a time with KV cache ---
    for _ in range(MAX_NEW_TOKENS):
        if next_token == EOS_TOKEN_ID:
            break
        generated.append(next_token)

        next_ids = np.array([[next_token]], dtype=np.int64)
        next_emb = sessions.embed_tokens.run(None, {"input_ids": next_ids})[0]  # type: ignore[union-attr]

        # Map present.X.Y.Z -> past_key_values.X.Y.Z; encoder KV is held constant
        kv_feed: dict[str, np.ndarray] = {}
        for inp in sessions.decoder.get_inputs():  # type: ignore[union-attr]
            if not inp.name.startswith("past_key_values"):
                continue
            present_name = inp.name.replace("past_key_values", "present")
            if "encoder" in inp.name:
                kv_feed[inp.name] = encoder_kv[present_name]
            else:
                kv_feed[inp.name] = decoder_kv[present_name]

        feed_n: dict[str, np.ndarray] = {
            "inputs_embeds": next_emb,
            "encoder_hidden_states": encoder_hidden_states,
            "encoder_attention_mask": encoder_attention_mask,
            "use_cache_branch": np.array([True]),
            **kv_feed,
        }
        dec_out_n = sessions.decoder.run(None, feed_n)  # type: ignore[union-attr]
        logits = dec_out_n[0]
        present_n = {out_names[i]: dec_out_n[i] for i in range(1, len(dec_out_n))}

        # Only the decoder KV is updated; encoder KV stays from step 0
        decoder_kv = {k: v for k, v in present_n.items() if "decoder" in k}
        next_token = int(np.argmax(logits[0, -1, :]))

    if sessions.tokenizer is not None:
        return sessions.tokenizer.decode(generated, skip_special_tokens=True)
    return ""


def _decode_no_cache(
    sessions: _Sessions,
    encoder_hidden_states: np.ndarray,
    encoder_attention_mask: np.ndarray,
) -> str:
    """Greedy decode using the non-merged decoder (no KV cache).

    Falls back to growing-sequence decode when only ``decoder_model_int8.onnx``
    is available (no ``use_cache_branch`` input).  Slower than KV-cache but
    functionally correct.
    """
    decoder_input_names = {inp.name for inp in sessions.decoder.get_inputs()}  # type: ignore[union-attr]

    seed_ids = np.array([[DECODER_START_TOKEN_ID, FORCED_BOS_TOKEN_ID]], dtype=np.int64)
    seed_embeds = sessions.embed_tokens.run(None, {"input_ids": seed_ids})[0]  # type: ignore[union-attr]
    decoder_embeds = seed_embeds

    generated: list[int] = []

    for _ in range(MAX_NEW_TOKENS):
        feed: dict[str, np.ndarray] = {
            "inputs_embeds": decoder_embeds,
            "encoder_hidden_states": encoder_hidden_states,
            "encoder_attention_mask": encoder_attention_mask,
        }
        feed = {k: v for k, v in feed.items() if k in decoder_input_names}

        dec_out = sessions.decoder.run(None, feed)  # type: ignore[union-attr]
        logits = dec_out[0]
        next_token = int(np.argmax(logits[0, -1, :]))

        if next_token == EOS_TOKEN_ID:
            break

        generated.append(next_token)

        next_ids = np.array([[next_token]], dtype=np.int64)
        next_emb = sessions.embed_tokens.run(None, {"input_ids": next_ids})[0]  # type: ignore[union-attr]
        decoder_embeds = np.concatenate([decoder_embeds, next_emb], axis=1)

    if sessions.tokenizer is not None:
        return sessions.tokenizer.decode(generated, skip_special_tokens=True)
    return ""


def _caption_to_slug(caption: str) -> str:
    words = caption.split()[:MAX_WORDS]
    slug = re.sub(r"[^a-z0-9]+", "-", " ".join(words).lower()).strip("-")
    return slug[:64]


def generate_name(path: Path, model_dir: Path = Path("models/florence2_int8")) -> str:
    cache_key = str(model_dir)
    if cache_key not in _session_cache:
        try:
            _session_cache[cache_key] = _load_sessions(model_dir)
        except Exception as e:
            logger.warning("Florence-2 model unavailable: %s — using original name", e)
            return path.stem

    sessions = _session_cache[cache_key]

    try:
        pixel_values = _preprocess_image(path, sessions)

        t0 = time.perf_counter()
        caption = _run_inference(sessions, pixel_values)
        elapsed = time.perf_counter() - t0

        if elapsed > _KPM_INFERENCE_LIMIT:
            logger.warning(
                "Florence-2 inference took %.2fs for %s (KPM-1.2 limit: 2.5s)",
                elapsed,
                path.name,
            )

        slug = _caption_to_slug(caption)
        return slug if slug else path.stem

    except Exception as e:
        logger.warning("Naming inference failed for %s: %s", path.name, e)
        return path.stem


@click.command("name")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--model-dir",
    default="models/florence2_int8",
    show_default=True,
    type=click.Path(path_type=Path),
    help="Path to the florence2_int8 model directory (contains onnx/ subdir).",
)
def main(path: Path, model_dir: Path) -> None:
    """Generate a 5-word semantic filename slug for PATH using Florence-2 INT8."""
    result = generate_name(path, model_dir=model_dir)
    click.echo(result)
