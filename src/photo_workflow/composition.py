"""FR-1.5: Composition scoring via rule-of-thirds and saliency."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


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
    Score composition using OpenCV's spectral residual saliency + rule-of-thirds.
    Returns a score in [0.0, 1.0].
    """
    img = cv2.imread(str(path))
    if img is None:
        logger.warning("Could not load image for composition: %s", path)
        return 0.0

    saliency = cv2.saliency.StaticSaliencySpectralResidual_create()
    ok, saliency_map = saliency.computeSaliency(img)
    if not ok:
        logger.warning("Saliency computation failed: %s", path)
        return 0.0

    saliency_map = (saliency_map * 255).astype(np.uint8)
    score = _rule_of_thirds_score(saliency_map.astype(np.float32))
    return round(score, 4)
