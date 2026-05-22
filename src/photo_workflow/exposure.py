"""FR-1.6: Exposure scoring — zone system, clipping, DR, style detection, face exposure."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from .scoring_types import ExposureScores, FaceDetection, SubjectContext

logger = logging.getLogger(__name__)

NUM_ZONES = 11  # FR-1.6: 11-zone luminance segmentation


def _detect_style(zone_probs: np.ndarray) -> tuple[str, float]:
    """Detect intentional exposure style from zone distribution.

    Args:
        zone_probs: Normalized histogram over 11 zones (sums to ~1.0).

    Returns:
        Tuple of (style_name, confidence).
    """
    high_zones = float(zone_probs[7:].sum())  # Zones VII-X
    low_zones = float(zone_probs[:5].sum())  # Zones 0-IV

    if high_zones > 0.70 and low_zones < 0.10:
        return "high_key", high_zones

    if low_zones > 0.70 and high_zones < 0.10:
        # Check for bright accent (distinguishes low-key from just underexposed)
        if zone_probs[8:].sum() > 0.02:
            return "low_key", low_zones
        return "low_key", low_zones * 0.7  # Lower confidence without accent

    # Silhouette: bimodal with peaks at 0-I and VIII-X
    shadow_peak = float(zone_probs[:2].sum())
    highlight_peak = float(zone_probs[8:].sum())
    if shadow_peak > 0.25 and highlight_peak > 0.25:
        return "silhouette", min(shadow_peak, highlight_peak)

    return "normal", 0.0


def _compute_face_exposure(
    image_bgr: np.ndarray,
    faces: list[FaceDetection],
) -> float:
    """Compute face region exposure quality.

    Returns score in [0, 1] if face present, -1.0 if no face.
    """
    if not faces:
        return -1.0

    # Use first (highest confidence) face
    face = max(faces, key=lambda f: f.confidence)
    x, y, w, h = face.bbox

    # Extract face region
    img_h, img_w = image_bgr.shape[:2]
    x = max(0, x)
    y = max(0, y)
    x2 = min(img_w, x + w)
    y2 = min(img_h, y + h)

    if x2 <= x or y2 <= y:
        return -1.0

    face_region = image_bgr[y:y2, x:x2]
    if face_region.size == 0:
        return -1.0

    # Convert to YCrCb and get luma
    ycrcb = cv2.cvtColor(face_region, cv2.COLOR_BGR2YCrCb)
    median_luma = float(np.median(ycrcb[:, :, 0]))

    # Score against ideal band [110, 220]
    ideal_low, ideal_high = 110.0, 220.0
    if ideal_low <= median_luma <= ideal_high:
        return 1.0
    elif median_luma < ideal_low:
        return max(0.0, median_luma / ideal_low)
    else:
        return max(0.0, 1.0 - (median_luma - ideal_high) / (255.0 - ideal_high))


def score_exposure_detailed(ctx: SubjectContext) -> ExposureScores:
    """Compute comprehensive exposure sub-scores.

    Args:
        ctx: SubjectContext with image and face detections.

    Returns:
        ExposureScores with zone analysis, clipping, DR, style, and face exposure.
    """
    img_bgr = ctx.image_bgr

    # Convert to YCrCb and extract luma
    ycrcb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2YCrCb)
    luma = ycrcb[:, :, 0].astype(np.float32)

    # Zone histogram
    hist, _ = np.histogram(luma, bins=NUM_ZONES, range=(0, 256))
    hist_float = hist.astype(np.float32)
    total_pixels = float(hist_float.sum())

    # Zone entropy
    nonzero = hist_float[hist_float > 0]
    if len(nonzero) == 0:
        zone_entropy = 0.0
    else:
        prob = nonzero / nonzero.sum()
        entropy = -float(np.sum(prob * np.log2(prob)))
        max_entropy = np.log2(NUM_ZONES)
        zone_entropy = entropy / max_entropy if max_entropy > 0 else 0.0

    # Zone diversity
    zone_diversity = int(np.sum(hist_float > (total_pixels * 0.01)))

    # Clipping detection
    clipping_shadows = float(np.mean(luma < 4.0))
    clipping_highlights = float(np.mean(luma > 251.0))

    # Dynamic range
    p005 = float(np.percentile(luma, 0.5))
    p995 = float(np.percentile(luma, 99.5))
    dynamic_range = (p995 - p005) / 255.0

    # Midtone density (zones III-VII, approximately luma 90-160)
    midtone_pixels = float(np.sum((luma >= 90) & (luma <= 160)))
    midtone_density = midtone_pixels / max(total_pixels, 1)

    # Style detection
    zone_probs = hist_float / max(total_pixels, 1)
    style, style_confidence = _detect_style(zone_probs)

    # Face exposure
    face_exposure = _compute_face_exposure(img_bgr, ctx.faces)

    # Overall score computation
    score = zone_entropy

    # Penalize clipping (unless style justifies it)
    if style != "silhouette":
        score -= clipping_shadows * 2.0
    if style != "high_key":
        score -= clipping_highlights * 2.0

    # Reward good dynamic range (unless intentional style)
    if style == "normal":
        score += (dynamic_range - 0.5) * 0.3

    # Face exposure penalty (hard to fix in post)
    if face_exposure >= 0 and face_exposure < 0.5:
        score -= (0.5 - face_exposure) * 0.4

    # Clamp
    overall = max(0.0, min(1.0, score))

    return ExposureScores(
        zone_entropy=round(zone_entropy, 4),
        zone_diversity=zone_diversity,
        clipping_shadows=round(clipping_shadows, 4),
        clipping_highlights=round(clipping_highlights, 4),
        dynamic_range=round(dynamic_range, 4),
        midtone_density=round(midtone_density, 4),
        face_exposure=round(face_exposure, 4),
        style=style,
        style_confidence=round(style_confidence, 4),
        overall=round(overall, 4),
    )


# --- Backward compatibility ---

def score_exposure(path: Path) -> float:
    """Score exposure for a single image. Backward-compatible wrapper."""
    from .raw_loader import load_rgb
    try:
        img = load_rgb(path)
    except Exception:
        logger.warning("Could not load image for exposure: %s", path)
        return 0.0

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ctx = SubjectContext(
        image_bgr=img,
        image_gray=gray,
        thumbnail_rgb=np.zeros((100, 100, 3), dtype=np.uint8),
        subject_mask=np.ones((h, w), dtype=np.uint8),
        subject_area_ratio=1.0,
        faces=[],
        detections=[],
        primary_subject_bbox=None,
        clip_embedding=np.zeros(512, dtype=np.float32),
        exif={},
    )

    scores = score_exposure_detailed(ctx)
    return scores.overall
