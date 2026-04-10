"""FR-1.4: Focus scoring via Laplacian variance."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Variance below this is considered blurry (tune per sensor/resolution)
BLUR_THRESHOLD = 100.0


def score_sharpness(path: Path) -> float:
    """
    Compute Laplacian variance as a sharpness proxy.
    Returns a score in [0.0, 1.0] normalized against a practical max.
    """
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        logger.warning("Could not load image for sharpness: %s", path)
        return 0.0

    variance = float(cv2.Laplacian(img, cv2.CV_64F).var())
    # Soft-normalize: score saturates near 1.0 at ~10× the blur threshold
    score = min(variance / (BLUR_THRESHOLD * 10.0), 1.0)
    return round(score, 4)
