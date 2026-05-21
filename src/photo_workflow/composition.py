"""FR-1.5: Composition scoring via rule-of-thirds and saliency."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def _compute_saliency(img_bgr: np.ndarray) -> np.ndarray:
    """
    Compute a spectral residual saliency map from a BGR image.

    Implements the Hou & Zhang (2007) spectral residual method using NumPy FFT,
    avoiding the cv2.saliency contrib module (absent in opencv-headless).

    Returns a float32 map in [0.0, 1.0] of the same spatial dimensions as img_bgr.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # Resize to a fixed small size for efficiency
    small = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)

    # Spectral residual: SR = log(|FFT|) - avg_filtered(log(|FFT|))
    fft = np.fft.fft2(small)
    log_amplitude = np.log(np.abs(fft) + 1e-8)

    # Local average via a small uniform kernel (approximates smoothing in freq domain)
    kernel_size = 3
    kernel = np.ones((kernel_size, kernel_size), dtype=np.float32) / (kernel_size ** 2)
    avg_log_amplitude = cv2.filter2D(log_amplitude.astype(np.float32), -1, kernel)

    spectral_residual = log_amplitude - avg_log_amplitude

    # Reconstruct saliency from residual phase + original phase
    phase = np.angle(fft)
    sr_fft = np.exp(spectral_residual + 1j * phase)
    saliency_small = np.abs(np.fft.ifft2(sr_fft)) ** 2

    # Smooth and normalize
    saliency_small = cv2.GaussianBlur(
        saliency_small.astype(np.float32), (5, 5), sigmaX=2.5
    )
    s_min, s_max = saliency_small.min(), saliency_small.max()
    if s_max > s_min:
        saliency_small = (saliency_small - s_min) / (s_max - s_min)
    else:
        saliency_small = np.zeros_like(saliency_small)

    # Upsample back to original size
    h, w = img_bgr.shape[:2]
    saliency_map = cv2.resize(saliency_small, (w, h), interpolation=cv2.INTER_LINEAR)
    return saliency_map.astype(np.float32)


def _rule_of_thirds_score(saliency_map: np.ndarray) -> float:
    """Score how well salient regions align with rule-of-thirds intersections."""
    h, w = saliency_map.shape
    # Four RoT power points (normalized)
    power_points = [
        (h // 3, w // 3),
        (h // 3, 2 * w // 3),
        (2 * h // 3, w // 3),
        (2 * h // 3, 2 * w // 3),
    ]
    radius = min(h, w) // 10
    total_saliency = saliency_map.sum() + 1e-9

    score = 0.0
    for py, px in power_points:
        y0, y1 = max(0, py - radius), min(h, py + radius)
        x0, x1 = max(0, px - radius), min(w, px + radius)
        score += saliency_map[y0:y1, x0:x1].sum() / total_saliency

    return min(float(score), 1.0)


def score_composition(path: Path) -> float:
    """
    Score composition using spectral residual saliency + rule-of-thirds.
    Returns a score in [0.0, 1.0].
    """
    from .raw_loader import load_rgb
    try:
        img = load_rgb(path)
    except Exception:
        logger.warning("Could not load image for composition: %s", path)
        return 0.0

    try:
        saliency_map = _compute_saliency(img)
    except Exception as e:
        logger.warning("Saliency computation failed for %s: %s", path, e)
        return 0.0

    score = _rule_of_thirds_score(saliency_map)
    return round(score, 4)
