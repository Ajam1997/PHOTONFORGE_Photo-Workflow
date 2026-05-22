"""FR-1.4: Focus scoring via Tenengrad + SML with subject-aware regions."""

from __future__ import annotations

import logging
from pathlib import Path

import click
import cv2
import numpy as np

from .scoring_types import SharpnessScores, SubjectContext

logger = logging.getLogger(__name__)

_SUPPORTED_EXTS = {
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".raw",
    ".cr2", ".cr3", ".nef", ".arw", ".dng",
}

# Thresholds for blur classification
_SHARP_THRESHOLD = 0.25  # Normalized score above this = "sharp"
_RATIO_BOKEH_THRESHOLD = 3.0  # subject/background ratio above this = bokeh


def _tenengrad(gray: np.ndarray) -> float:
    """Compute Tenengrad focus measure (Sobel gradient magnitude squared).

    Returns raw unnormalized score (higher = sharper).
    """
    if gray.size == 0:
        return 0.0
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    tenengrad = float(np.mean(gx**2 + gy**2))
    return tenengrad


def _sml(gray: np.ndarray) -> float:
    """Compute Sum of Modified Laplacian focus measure.

    Returns raw unnormalized score (higher = sharper).
    """
    if gray.size == 0:
        return 0.0
    img = gray.astype(np.float64)
    # Modified Laplacian: |d2f/dx2| + |d2f/dy2| (avoids sign cancellation)
    lxx = cv2.Sobel(img, cv2.CV_64F, 2, 0, ksize=3)
    lyy = cv2.Sobel(img, cv2.CV_64F, 0, 2, ksize=3)
    ml = np.abs(lxx) + np.abs(lyy)
    return float(np.mean(ml))


def _laplacian_variance(gray: np.ndarray) -> float:
    """Compute Laplacian variance (traditional focus measure).

    Returns raw unnormalized score (higher = sharper).
    Useful for pure checkerboard patterns where Sobel derivatives are zero.
    """
    if gray.size == 0:
        return 0.0
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return float(lap.var())


def _compute_region_sharpness(gray: np.ndarray, mask: np.ndarray) -> float:
    """Compute geometric mean of Tenengrad and SML for a masked region.

    Normalizes by mean luminance to make scores comparable across exposures.
    Returns normalized score in approximately [0, 1] range.
    """
    # Extract region pixels
    if mask.sum() == 0:
        return 0.0

    # Apply mask
    region = gray.copy()
    region[mask == 0] = 0

    # Compute focus measures on the masked region
    ten = _tenengrad(region)
    sml_val = _sml(region)

    if ten <= 0 or sml_val <= 0:
        return 0.0

    # Geometric mean
    raw = float(np.sqrt(ten * sml_val))

    # Normalize by mean luminance of the region to handle exposure differences
    mean_luma = float(gray[mask > 0].mean()) if mask.sum() > 0 else 128.0
    luma_factor = max(mean_luma, 1.0) / 128.0

    # Normalize to approximate [0, 1] range
    # Empirical normalization constant (tuned for typical photos)
    normalized = raw / (500.0 * luma_factor)
    return min(normalized, 1.0)


def _classify_blur(subject_sharp: bool, bg_sharp: bool, ratio: float) -> str:
    """Classify blur type based on region sharpness analysis.

    Args:
        subject_sharp: Whether subject region exceeds sharpness threshold.
        bg_sharp: Whether background region exceeds sharpness threshold.
        ratio: subject_sharpness / background_sharpness.

    Returns:
        One of: "sharp", "bokeh", "motion_subject", "motion_global", "misfocused"
    """
    if subject_sharp and bg_sharp:
        return "sharp"
    if subject_sharp and not bg_sharp:
        if ratio > _RATIO_BOKEH_THRESHOLD:
            return "bokeh"
        return "bokeh"  # Even moderate contrast with sharp subject = intentional DOF
    if not subject_sharp and bg_sharp:
        return "misfocused"
    # Neither sharp
    return "motion_global"


def score_sharpness_detailed(ctx: SubjectContext) -> SharpnessScores:
    """Compute subject-aware sharpness scores using Tenengrad + SML.

    Args:
        ctx: SubjectContext containing image_gray and subject_mask.

    Returns:
        SharpnessScores with per-region scores and blur classification.
    """
    gray = ctx.image_gray
    mask = ctx.subject_mask
    inv_mask = 1 - mask

    # Compute per-region sharpness
    subject_score = _compute_region_sharpness(gray, mask)
    background_score = _compute_region_sharpness(gray, inv_mask)

    # Eye region sharpness
    eye_score = subject_score  # Default: same as subject
    if ctx.faces:
        # Use first face's eye landmarks
        face = ctx.faces[0]
        if "left_eye" in face.landmarks and "right_eye" in face.landmarks:
            le = face.landmarks["left_eye"]
            re = face.landmarks["right_eye"]
            # Create eye region mask (rectangle around both eyes)
            eye_mask = np.zeros_like(gray, dtype=np.uint8)
            eye_w = abs(re[0] - le[0])
            eye_h = max(eye_w // 3, 10)
            y_center = (le[1] + re[1]) // 2
            x_min = min(le[0], re[0]) - eye_w // 4
            x_max = max(le[0], re[0]) + eye_w // 4
            y_min = y_center - eye_h
            y_max = y_center + eye_h
            # Clamp to image bounds
            y_min = max(0, y_min)
            y_max = min(gray.shape[0], y_max)
            x_min = max(0, x_min)
            x_max = min(gray.shape[1], x_max)
            if y_max > y_min and x_max > x_min:
                eye_mask[y_min:y_max, x_min:x_max] = 1
                eye_score = _compute_region_sharpness(gray, eye_mask)
    elif ctx.detections:
        # For animals: use upper third of primary detection bbox as eye region
        for det in ctx.detections:
            if det.class_name in ("cat", "dog", "bird", "horse", "bear"):
                x, y, w, h = det.bbox
                head_h = h // 3
                eye_mask = np.zeros_like(gray, dtype=np.uint8)
                y_min = max(0, y)
                y_max = min(gray.shape[0], y + head_h)
                x_min = max(0, x)
                x_max = min(gray.shape[1], x + w)
                if y_max > y_min and x_max > x_min:
                    eye_mask[y_min:y_max, x_min:x_max] = 1
                    eye_score = _compute_region_sharpness(gray, eye_mask)
                break

    # Sharpness contrast ratio
    sharpness_contrast = subject_score / max(background_score, 0.01)

    # Blur classification
    subject_sharp = subject_score >= _SHARP_THRESHOLD
    bg_sharp = background_score >= _SHARP_THRESHOLD
    blur_type = _classify_blur(subject_sharp, bg_sharp, sharpness_contrast)

    # Overall score (weighted combination favoring subject and eye)
    overall = 0.5 * subject_score + 0.35 * eye_score + 0.15 * min(sharpness_contrast / 5.0, 1.0)
    overall = min(overall, 1.0)

    return SharpnessScores(
        subject=round(subject_score, 4),
        eye_region=round(eye_score, 4),
        background=round(background_score, 4),
        sharpness_contrast=round(sharpness_contrast, 4),
        blur_type=blur_type,
        overall=round(overall, 4),
    )


# --- Backward compatibility ---

# Legacy threshold for the old API
BLUR_THRESHOLD = 100.0


def score_sharpness(path: Path) -> float:
    """Compute sharpness score for a single image file.

    Backward-compatible wrapper that returns a single float in [0.0, 1.0].
    Uses Tenengrad + SML geometric mean, with Laplacian variance as a fallback.
    """
    from .raw_loader import load_gray

    try:
        image_gray = load_gray(path)
    except Exception:
        logger.warning("Could not load image for sharpness: %s", path)
        return 0.0

    # Compute focus measures on full image (no masking to avoid edge artifacts)
    ten = _tenengrad(image_gray)
    sml_val = _sml(image_gray)

    if ten <= 0 and sml_val <= 0:
        # Fallback to Laplacian variance (e.g., for perfect checkerboards)
        lap_var = _laplacian_variance(image_gray)
        normalized = min(lap_var / (BLUR_THRESHOLD * 10.0), 1.0)
        return round(normalized, 4)

    if ten > 0 and sml_val > 0:
        # Geometric mean of both measures
        raw = float(np.sqrt(ten * sml_val))
    else:
        # Use whichever is non-zero
        raw = max(ten, sml_val)

    # Normalize by mean luminance
    mean_luma = float(image_gray.mean())
    luma_factor = max(mean_luma, 1.0) / 128.0

    # Normalize to [0, 1] range
    normalized = raw / (500.0 * luma_factor)
    normalized = min(normalized, 1.0)

    return round(normalized, 4)


@click.command("sharpness")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--threshold",
    default=BLUR_THRESHOLD,
    show_default=True,
    help="Blur threshold for normalization (variance units).",
)
def main(path: Path, threshold: float) -> None:
    """Score sharpness for PATH (file or directory of images)."""
    targets = sorted(path.iterdir()) if path.is_dir() else [path]
    for p in targets:
        if not (p.is_file() and p.suffix.lower() in _SUPPORTED_EXTS):
            continue
        score = score_sharpness(p)
        click.echo(f"{p}: {score:.4f}")
