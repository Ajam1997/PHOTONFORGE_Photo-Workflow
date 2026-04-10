"""FR-1.6: Exposure scoring via luminance zone entropy."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

NUM_ZONES = 11  # FR-1.6: 11-zone luminance segmentation per spec


def score_exposure(path: Path) -> float:
    """
    Score exposure quality using Shannon entropy of luminance zone histogram.
    Higher entropy = more evenly distributed tones = better exposure.
    Returns a score in [0.0, 1.0].
    """
    img = cv2.imread(str(path))
    if img is None:
        logger.warning("Could not load image for exposure: %s", path)
        return 0.0

    # Convert to YCrCb and extract luminance channel
    ycrcb = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
    luma = ycrcb[:, :, 0]

    hist, _ = np.histogram(luma, bins=NUM_ZONES, range=(0, 256))
    hist = hist.astype(np.float32)

    # Remove empty zones, normalize to probability distribution
    hist = hist[hist > 0]
    if len(hist) == 0:
        return 0.0
    prob = hist / hist.sum()

    entropy = -float(np.sum(prob * np.log2(prob)))
    max_entropy = np.log2(NUM_ZONES)
    score = entropy / max_entropy if max_entropy > 0 else 0.0

    return round(min(score, 1.0), 4)
