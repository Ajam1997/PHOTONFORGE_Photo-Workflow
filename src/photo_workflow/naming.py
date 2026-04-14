"""FR-1.7: Semantic filename generation via Florence-2-base-ft multi-file ONNX."""

from __future__ import annotations

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
MAX_NEW_TOKENS = 32
EOS_TOKEN_ID = 2
_KPM_INFERENCE_LIMIT = 2.5  # seconds (KPM-1.2)

# Florence-2 image normalisation constants (ImageNet)
_IMG_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMG_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_IMG_SIZE = 768


@dataclass
class _Sessions:
    embed_tokens: object  # ort.InferenceSession
    encoder: object       # ort.InferenceSession
    decoder: object       # ort.InferenceSession
    tokenizer: object | None  # tokenizers.Tokenizer or None


_session_cache: dict[str, _Sessions] = {}


def _make_ort_session(path: Path) -> object:
    """Create an ONNX Runtime InferenceSession (CPU only)."""
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


def _resolve_onnx_path(onnx_dir: Path, stem: str) -> Path:
    """Try INT8 -> fp16 -> unquantized variants; return first that exists."""
    for suffix in (f"{stem}_int8.onnx", f"{stem}_fp16.onnx", f"{stem}.onnx"):
        p = onnx_dir / suffix
        if p.exists():
            return p
    raise FileNotFoundError(
        f"No ONNX variant found for '{stem}' in {onnx_dir}. "
        f"Tried: {stem}_int8.onnx, {stem}_fp16.onnx, {stem}.onnx"
    )


def _log_session_io(name: str, session: object) -> None:
    """Log input and output tensor names for a session (aids debugging)."""
    inputs = [f"{i.name}:{i.type}" for i in session.get_inputs()]  # type: ignore[union-attr]
    outputs = [f"{o.name}:{o.type}" for o in session.get_outputs()]  # type: ignore[union-attr]
    logger.info("[%s] inputs:  %s", name, inputs)
    logger.info("[%s] outputs: %s", name, outputs)


def _load_sessions(model_dir: Path) -> _Sessions:
    """Load all three Florence-2 ONNX sessions and the tokenizer."""
    onnx_dir = model_dir / ONNX_SUBDIR

    embed_path = _resolve_onnx_path(onnx_dir, "embed_tokens")
    encoder_path = _resolve_onnx_path(onnx_dir, "encoder_model")
    decoder_path = _resolve_onnx_path(onnx_dir, "decoder_model_merged")

    logger.info("Loading Florence-2 ONNX sessions from %s", onnx_dir)
    logger.info("  embed_tokens : %s", embed_path.name)
    logger.info("  encoder      : %s", encoder_path.name)
    logger.info("  decoder      : %s", decoder_path.name)

    embed_sess = _make_ort_session(embed_path)
    encoder_sess = _make_ort_session(encoder_path)
    decoder_sess = _make_ort_session(decoder_path)

    _log_session_io("embed_tokens", embed_sess)
    _log_session_io("encoder", encoder_sess)
    _log_session_io("decoder", decoder_sess)

    tokenizer = None
    tok_json = model_dir / "tokenizer.json"
    if tok_json.exists():
        try:
            from tokenizers import Tokenizer  # type: ignore[import]

            tokenizer = Tokenizer.from_file(str(tok_json))
        except Exception as e:
            logger.warning("Could not load tokenizer: %s — will use fallback prompt", e)

    return _Sessions(
        embed_tokens=embed_sess,
        encoder=encoder_sess,
        decoder=decoder_sess,
        tokenizer=tokenizer,
    )


def _preprocess_image(path: Path) -> np.ndarray:
    """Load image, resize to 768×768, normalise, return NCHW float32."""
    import cv2

    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"Could not read image: {path}")
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img_resized = cv2.resize(img_rgb, (_IMG_SIZE, _IMG_SIZE)).astype(np.float32) / 255.0
    img_norm = (img_resized - _IMG_MEAN) / _IMG_STD
    return np.transpose(img_norm, (2, 0, 1))[np.newaxis, :]  # (1, 3, 768, 768)


def _get_prompt_ids(sessions: _Sessions) -> np.ndarray:
    """Return token IDs for the <CAPTION> task prompt."""
    if sessions.tokenizer is not None:
        enc = sessions.tokenizer.encode("<CAPTION>")
        return np.array([enc.ids], dtype=np.int64)
    # Minimal fallback: BOS + known token ID for "<CAPTION>" in Florence-2 vocab
    return np.array([[0, 50265]], dtype=np.int64)


def _decode_ids(sessions: _Sessions, token_ids: list[int]) -> str:
    if sessions.tokenizer is not None:
        return sessions.tokenizer.decode(token_ids, skip_special_tokens=True)
    return ""


def _run_inference(sessions: _Sessions, pixel_values: np.ndarray) -> str:
    """Run the full encode→generate loop and return raw caption text."""
    # 1. Vision encoder
    encoder_out = sessions.encoder.run(None, {"pixel_values": pixel_values})  # type: ignore[union-attr]
    encoder_hidden_states = encoder_out[0]  # (1, seq, hidden)

    # 2. Prompt token embeddings
    prompt_ids = _get_prompt_ids(sessions)
    embed_out = sessions.embed_tokens.run(None, {"input_ids": prompt_ids})  # type: ignore[union-attr]
    inputs_embeds = embed_out[0]  # (1, prompt_len, hidden)

    prompt_len = inputs_embeds.shape[1]
    attention_mask = np.ones((1, prompt_len), dtype=np.int64)

    # 3. Autoregressive decode loop.
    # decoder_model_merged handles both prefill (use_cache_branch=False) and
    # incremental decode (use_cache_branch=True) in a single ONNX graph.
    generated: list[int] = []

    # Inspect decoder input names to build the feed dict correctly.
    decoder_input_names = {inp.name for inp in sessions.decoder.get_inputs()}  # type: ignore[union-attr]

    # Prefill step: pass inputs_embeds + encoder_hidden_states
    feed: dict[str, np.ndarray] = {
        "inputs_embeds": inputs_embeds,
        "encoder_hidden_states": encoder_hidden_states,
        "attention_mask": attention_mask,
    }
    if "use_cache_branch" in decoder_input_names:
        feed["use_cache_branch"] = np.array([False])

    past_key_values: dict[str, np.ndarray] = {}

    dec_out = sessions.decoder.run(None, feed)  # type: ignore[union-attr]
    dec_output_names = [o.name for o in sessions.decoder.get_outputs()]  # type: ignore[union-attr]

    # Extract logits (first output) and past_key_values (remaining outputs).
    logits = dec_out[0]  # (1, seq, vocab)
    next_token = int(np.argmax(logits[0, -1, :]))
    if next_token != EOS_TOKEN_ID:
        generated.append(next_token)

    for name, tensor in zip(dec_output_names[1:], dec_out[1:]):
        past_key_values[name] = tensor

    # Incremental decode
    for _ in range(MAX_NEW_TOKENS - 1):
        if next_token == EOS_TOKEN_ID:
            break

        token_id_arr = np.array([[next_token]], dtype=np.int64)
        step_embed_out = sessions.embed_tokens.run(None, {"input_ids": token_id_arr})  # type: ignore[union-attr]
        step_embeds = step_embed_out[0]  # (1, 1, hidden)

        total_len = prompt_len + len(generated)
        step_mask = np.ones((1, total_len), dtype=np.int64)

        step_feed: dict[str, np.ndarray] = {
            "inputs_embeds": step_embeds,
            "encoder_hidden_states": encoder_hidden_states,
            "attention_mask": step_mask,
        }
        if "use_cache_branch" in decoder_input_names:
            step_feed["use_cache_branch"] = np.array([True])

        # Re-map past_key_value output names → corresponding input names.
        # Florence-2 decoder uses "past_key_values.N.{encoder,decoder}.{key,value}" naming.
        for out_name, tensor in past_key_values.items():
            in_name = out_name.replace("present", "past_key_values")
            if in_name in decoder_input_names:
                step_feed[in_name] = tensor
            elif out_name in decoder_input_names:
                step_feed[out_name] = tensor

        step_out = sessions.decoder.run(None, step_feed)  # type: ignore[union-attr]
        logits = step_out[0]
        next_token = int(np.argmax(logits[0, -1, :]))
        if next_token != EOS_TOKEN_ID:
            generated.append(next_token)

        for name, tensor in zip(dec_output_names[1:], step_out[1:]):
            past_key_values[name] = tensor

    return _decode_ids(sessions, generated)


def _caption_to_slug(caption: str, stem_fallback: str) -> str:
    """Extract first MAX_WORDS words from caption and return a clean slug."""
    words = caption.split()[:MAX_WORDS]
    if not words:
        return stem_fallback
    phrase = " ".join(words)
    slug = re.sub(r"[^a-z0-9]+", "-", phrase.lower().strip()).strip("-")
    slug = slug[:64] if slug else stem_fallback
    return slug


def generate_name(path: Path, model_dir: Path = Path("models/florence2_int8")) -> str:
    """
    Run Florence-2 INT8 caption on the image and return a slug (first 5 words).
    Falls back to the original stem if the model is absent or inference fails.
    """
    cache_key = str(model_dir)
    if cache_key not in _session_cache:
        try:
            _session_cache[cache_key] = _load_sessions(model_dir)
        except Exception as e:
            logger.warning("Florence-2 model unavailable: %s — using original name", e)
            return path.stem

    sessions = _session_cache[cache_key]

    try:
        pixel_values = _preprocess_image(path)

        t0 = time.perf_counter()
        caption = _run_inference(sessions, pixel_values)
        elapsed = time.perf_counter() - t0

        if elapsed > _KPM_INFERENCE_LIMIT:
            logger.warning(
                "Florence-2 inference took %.2fs for %s (KPM-1.2 limit: 2.5s)",
                elapsed,
                path.name,
            )

        return _caption_to_slug(caption, path.stem)

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
