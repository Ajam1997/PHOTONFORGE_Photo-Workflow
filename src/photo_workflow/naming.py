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
MAX_NEW_TOKENS = 20
EOS_TOKEN_ID = 2
DECODER_START_TOKEN_ID = 2   # decoder_start_token_id from generation_config.json
FORCED_BOS_TOKEN_ID = 0      # forced_bos_token_id: first generated token is always 0
_KPM_INFERENCE_LIMIT = 2.5  # seconds (KPM-1.2)


@dataclass
class _Sessions:
    vision_encoder: object
    embed_tokens: object
    encoder: object
    decoder: object          # decoder_model_int8.onnx — used for all decode steps
    tokenizer: object | None
    img_size: tuple[int, int]   # (height, width)
    img_mean: np.ndarray        # shape (3,) float32
    img_std: np.ndarray         # shape (3,) float32


_session_cache: dict[str, _Sessions] = {}


def _resolve_onnx_path(onnx_dir: Path, stem: str) -> Path:
    for suffix in (f"{stem}_int8.onnx", f"{stem}_fp16.onnx", f"{stem}.onnx"):
        p = onnx_dir / suffix
        if p.exists():
            return p
    raise FileNotFoundError(
        f"No ONNX variant found for '{stem}' in {onnx_dir}. "
        f"Tried: {stem}_int8.onnx, {stem}_fp16.onnx, {stem}.onnx"
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

    size_val = preproc["size"]
    if isinstance(size_val, dict):
        img_h = int(size_val["height"])
        img_w = int(size_val["width"])
    else:
        img_h = int(size_val)
        img_w = int(size_val)

    img_mean = np.array(preproc["image_mean"], dtype=np.float32)
    img_std = np.array(preproc["image_std"], dtype=np.float32)

    tokenizer = None
    tok_json = model_dir / "tokenizer.json"
    if tok_json.exists():
        try:
            from tokenizers import Tokenizer  # type: ignore[import]

            tokenizer = Tokenizer.from_file(str(tok_json))
        except Exception as e:
            logger.warning("Could not load tokenizer: %s — will use fallback prompt", e)

    return _Sessions(
        vision_encoder=vision_encoder_sess,
        embed_tokens=embed_sess,
        encoder=encoder_sess,
        decoder=decoder_sess,
        tokenizer=tokenizer,
        img_size=(img_h, img_w),
        img_mean=img_mean,
        img_std=img_std,
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


def _run_inference(sessions: _Sessions, pixel_values: np.ndarray) -> str:
    # Step 3: vision encoder
    vision_out = sessions.vision_encoder.run(None, {"pixel_values": pixel_values})  # type: ignore[union-attr]
    image_features = vision_out[0]  # (1, img_seq, 768)

    # Step 4: tokenize "<CAPTION>"
    if sessions.tokenizer is not None:
        enc = sessions.tokenizer.encode("<CAPTION>")
        prompt_ids = np.array([enc.ids], dtype=np.int64)
    else:
        prompt_ids = np.array([[0, 50265]], dtype=np.int64)

    # Step 5: embed prompt tokens
    embed_out = sessions.embed_tokens.run(None, {"input_ids": prompt_ids})  # type: ignore[union-attr]
    text_embeds = embed_out[0]  # (1, txt_seq, 768)

    # Step 6: concatenate image_features + text_embeds
    combined_embeds = np.concatenate([image_features, text_embeds], axis=1)  # (1, img_seq+txt_seq, 768)

    # Step 7: attention mask over combined sequence
    attention_mask = np.ones((1, combined_embeds.shape[1]), dtype=np.int64)

    # Step 8: encoder
    encoder_out = sessions.encoder.run(  # type: ignore[union-attr]
        None,
        {
            "attention_mask": attention_mask,
            "inputs_embeds": combined_embeds,
        },
    )
    encoder_hidden_states = encoder_out[0]  # (1, combined_seq, 768)

    # Step 9: greedy decode — no KV cache; decoder_model accepts any sequence length
    decoder_input_names = {inp.name for inp in sessions.decoder.get_inputs()}  # type: ignore[union-attr]

    generated: list[int] = []

    # Seed decoder with [decoder_start_token_id, forced_bos_token_id] = [2, 0]
    # This mirrors Florence-2's generation_config: decoder starts at token 2,
    # then token 0 (forced_bos) is prepended before content tokens are generated.
    start_ids = np.array([[DECODER_START_TOKEN_ID, FORCED_BOS_TOKEN_ID]], dtype=np.int64)
    start_embeds = sessions.embed_tokens.run(None, {"input_ids": start_ids})[0]  # [1, 2, 768]
    decoder_embeds = start_embeds  # growing buffer

    for step in range(MAX_NEW_TOKENS):
        feed = {
            "inputs_embeds": decoder_embeds,
            "encoder_hidden_states": encoder_hidden_states,
            "encoder_attention_mask": attention_mask,
        }
        feed = {k: v for k, v in feed.items() if k in decoder_input_names}

        dec_out = sessions.decoder.run(None, feed)  # type: ignore[union-attr]
        logits = dec_out[0]                              # [1, seq, 51289]
        next_token = int(np.argmax(logits[0, -1, :]))    # greedy from last position

        if next_token == EOS_TOKEN_ID:
            break

        generated.append(next_token)

        # Embed next token and append to sequence
        next_ids = np.array([[next_token]], dtype=np.int64)
        next_embeds = sessions.embed_tokens.run(None, {"input_ids": next_ids})[0]  # type: ignore[union-attr]  # [1, 1, 768]
        decoder_embeds = np.concatenate([decoder_embeds, next_embeds], axis=1)       # [1, seq+1, 768]

    # Step 10: decode token ids
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
