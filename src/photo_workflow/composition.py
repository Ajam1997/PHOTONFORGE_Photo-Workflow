"""FR-1.5: Composition scoring — RoT, symmetry, leading lines, negative space, isolation, balance."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from .scoring_types import CompositionScores, SubjectContext

logger = logging.getLogger(__name__)


def _compute_saliency(img_bgr: np.ndarray) -> np.ndarray:
    """Compute spectral residual saliency map (Hou & Zhang 2007).

    Returns float32 map in [0.0, 1.0] at original resolution.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    small = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)

    fft = np.fft.fft2(small)
    log_amplitude = np.log(np.abs(fft) + 1e-8)

    kernel = np.ones((3, 3), dtype=np.float32) / 9.0
    avg_log_amplitude = cv2.filter2D(log_amplitude.astype(np.float32), -1, kernel)
    spectral_residual = log_amplitude - avg_log_amplitude

    phase = np.angle(fft)
    sr_fft = np.exp(spectral_residual + 1j * phase)
    saliency_small = np.abs(np.fft.ifft2(sr_fft)) ** 2

    saliency_small = cv2.GaussianBlur(saliency_small.astype(np.float32), (5, 5), sigmaX=2.5)
    s_min, s_max = saliency_small.min(), saliency_small.max()
    if s_max > s_min:
        saliency_small = (saliency_small - s_min) / (s_max - s_min)
    else:
        saliency_small = np.zeros_like(saliency_small)

    h, w = img_bgr.shape[:2]
    saliency_map = cv2.resize(saliency_small, (w, h), interpolation=cv2.INTER_LINEAR)
    return saliency_map.astype(np.float32)


def _improved_rot_score(saliency_map: np.ndarray) -> float:
    """Score Rule of Thirds using Gaussian falloff from power points.

    Uses exp(-d^2 / 2*sigma^2) where d is normalized by diagonal.
    """
    h, w = saliency_map.shape
    diagonal = np.sqrt(h**2 + w**2)
    sigma = 0.1  # Gaussian width relative to diagonal

    power_points = [
        (h / 3, w / 3),
        (h / 3, 2 * w / 3),
        (2 * h / 3, w / 3),
        (2 * h / 3, 2 * w / 3),
    ]

    # Find salient region centroids via thresholding
    threshold = saliency_map.mean() + saliency_map.std()
    salient_mask = saliency_map > threshold

    if not salient_mask.any():
        return 0.0

    # Find centroid of salient region
    ys, xs = np.where(salient_mask)
    if len(ys) == 0:
        return 0.0

    # Weighted centroid
    weights = saliency_map[salient_mask]
    cy = float(np.average(ys, weights=weights))
    cx = float(np.average(xs, weights=weights))

    # Score: max Gaussian proximity to any power point
    best_score = 0.0
    for py, px in power_points:
        d = np.sqrt((cy - py)**2 + (cx - px)**2) / diagonal
        score = float(np.exp(-d**2 / (2 * sigma**2)))
        best_score = max(best_score, score)

    return min(best_score, 1.0)


def _symmetry_score(img_bgr: np.ndarray) -> float:
    """Bilateral (left-right) symmetry via correlation of the image with its mirror.

    The previous version mirrored ORB keypoint *coordinates* but read descriptors
    off the un-mirrored image, so it almost never matched (scored ~0 for nearly
    every photo). This compares the actual image to its horizontal flip with a
    normalized cross-correlation on a blurred, downscaled luminance map — high for
    bilaterally symmetric scenes, low for asymmetric ones. Returns [0, 1].
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    scale = min(1.0, 256 / max(h, w))
    if scale < 1.0:
        gray = cv2.resize(gray, (max(int(w * scale), 1), max(int(h * scale), 1)))
    gray = cv2.GaussianBlur(gray, (5, 5), 0).astype(np.float32)

    flipped = gray[:, ::-1]
    a = gray - gray.mean()
    b = flipped - flipped.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    if denom < 1e-6:
        return 0.0
    ncc = float((a * b).sum() / denom)  # [-1, 1]
    return max(0.0, ncc)


def _colorfulness_score(img_bgr: np.ndarray) -> float:
    """Hasler-Süsstrunk colorfulness, normalized to [0, 1].

    A real measure of color richness/saturation spread (the `color_contrast`
    sub-score used to be a misnamed alias of subject_isolation). ~0 for
    grayscale/muted, ~1 for vivid scenes.
    """
    b = img_bgr[..., 0].astype(np.float32)
    g = img_bgr[..., 1].astype(np.float32)
    r = img_bgr[..., 2].astype(np.float32)
    rg = r - g
    yb = 0.5 * (r + g) - b
    std_root = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2))
    mean_root = float(np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    colorfulness = std_root + 0.3 * mean_root  # Hasler-Süsstrunk metric (~0..150)
    return float(min(colorfulness / 100.0, 1.0))


def _leading_lines_score(img_bgr: np.ndarray, subject_centroid: tuple[float, float]) -> float:
    """Detect leading lines converging toward the subject.

    Uses probabilistic Hough transform on Canny edges.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    diagonal = np.sqrt(h**2 + w**2)

    # Resize for speed
    scale = min(1.0, 1024 / max(h, w))
    if scale < 1.0:
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)))
        h_s, w_s = gray.shape
        cx = subject_centroid[0] * scale
        cy = subject_centroid[1] * scale
        diag_s = np.sqrt(h_s**2 + w_s**2)
    else:
        cx, cy = subject_centroid
        diag_s = diagonal

    edges = cv2.Canny(gray, 50, 150)
    min_length = int(0.15 * diag_s)

    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=50,
                            minLineLength=min_length, maxLineGap=10)

    if lines is None or len(lines) == 0:
        return 0.0

    convergence_score = 0.0
    total_weight = 0.0

    for line in lines:
        x1, y1, x2, y2 = line[0]
        length = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)

        # Check if line extension converges toward subject centroid
        dx, dy = x2 - x1, y2 - y1
        norm = np.sqrt(dx**2 + dy**2)
        if norm == 0:
            continue

        # Distance from subject centroid to the line
        dist = abs(dy * cx - dx * cy + x2 * y1 - y2 * x1) / norm
        proximity = 0.15 * diag_s  # 15% of diagonal threshold

        if dist < proximity:
            convergence_score += length
        total_weight += length

    if total_weight == 0:
        return 0.0

    score = convergence_score / total_weight
    return min(score, 1.0)


def _negative_space_score(subject_mask: np.ndarray, gray: np.ndarray) -> float:
    """Score negative space quality — ratio and background smoothness.

    High score = good amount of clean negative space surrounding subject.
    """
    total_pixels = subject_mask.size
    subject_pixels = int(subject_mask.sum())
    negative_ratio = 1.0 - (subject_pixels / max(total_pixels, 1))

    # Score peaks around 0.65-0.75 (Gaussian centered at 0.7)
    ratio_score = float(np.exp(-((negative_ratio - 0.7) ** 2) / (2 * 0.15**2)))

    # Background smoothness: low gradient = clean background
    bg_mask = (subject_mask == 0)
    if bg_mask.any():
        bg_region = gray.copy()
        bg_region[~bg_mask] = 0
        grad_x = cv2.Sobel(bg_region, cv2.CV_64F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(bg_region, cv2.CV_64F, 0, 1, ksize=3)
        grad_mag = np.sqrt(grad_x**2 + grad_y**2)
        mean_grad = float(grad_mag[bg_mask].mean()) if bg_mask.any() else 0.0
        # Lower gradient = smoother = better. Normalize inversely.
        smoothness = max(0.0, 1.0 - mean_grad / 100.0)
    else:
        smoothness = 0.0

    # Combined score
    return ratio_score * 0.6 + smoothness * 0.4


def _subject_isolation_score(
    img_bgr: np.ndarray,
    subject_mask: np.ndarray,
    sharpness_contrast: float,
) -> float:
    """Score how well the subject separates from background.

    Combines sharpness contrast, color contrast (DeltaE), and luminance contrast.
    """
    # Color contrast in Lab
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2Lab).astype(np.float32)
    subject_pixels = lab[subject_mask > 0]
    bg_pixels = lab[subject_mask == 0]

    if len(subject_pixels) == 0 or len(bg_pixels) == 0:
        return 0.0

    mean_subject = subject_pixels.mean(axis=0)
    mean_bg = bg_pixels.mean(axis=0)

    # CIE76 DeltaE
    delta_e = float(np.sqrt(np.sum((mean_subject - mean_bg) ** 2)))
    color_contrast = min(delta_e / 50.0, 1.0)

    # Luminance contrast
    luma_subject = float(mean_subject[0])  # L channel
    luma_bg = float(mean_bg[0])
    luma_contrast = min(abs(luma_subject - luma_bg) / 100.0, 1.0)

    # Sharpness contrast (normalize ratio to [0,1])
    sharp_contrast_norm = min(sharpness_contrast / 5.0, 1.0)

    # Weighted combination
    isolation = 0.4 * sharp_contrast_norm + 0.35 * color_contrast + 0.25 * luma_contrast
    return min(isolation, 1.0)


def _balance_score(saliency_map: np.ndarray) -> float:
    """Score visual balance — how centered the visual weight is.

    Returns 1.0 for perfectly centered, 0.0 for extreme corner.
    """
    h, w = saliency_map.shape
    total = saliency_map.sum()
    if total == 0:
        return 0.5  # Neutral

    # Weighted centroid
    ys, xs = np.mgrid[0:h, 0:w]
    cy = float(np.sum(ys * saliency_map) / total)
    cx = float(np.sum(xs * saliency_map) / total)

    # Distance from center normalized by half-diagonal
    center_y, center_x = h / 2, w / 2
    dist = np.sqrt((cy - center_y)**2 + (cx - center_x)**2)
    half_diag = np.sqrt(h**2 + w**2) / 2

    score = 1.0 - (dist / half_diag)
    return max(0.0, min(score, 1.0))


def score_composition_detailed(ctx: SubjectContext) -> CompositionScores:
    """Compute comprehensive composition sub-scores.

    Args:
        ctx: SubjectContext with image, mask, and detection info.

    Returns:
        CompositionScores with six sub-scores and an overall.
    """
    img_bgr = ctx.image_bgr
    gray = ctx.image_gray
    mask = ctx.subject_mask

    # Compute saliency map
    try:
        saliency = _compute_saliency(img_bgr)
    except Exception:
        saliency = np.zeros(gray.shape, dtype=np.float32)

    # Find subject centroid for leading lines
    ys, xs = np.where(mask > 0)
    if len(ys) > 0:
        subject_centroid = (float(xs.mean()), float(ys.mean()))
    else:
        h, w = gray.shape
        subject_centroid = (w / 2, h / 2)

    # Compute sub-scores
    rot = _improved_rot_score(saliency)
    symmetry = _symmetry_score(img_bgr)
    lines = _leading_lines_score(img_bgr, subject_centroid)
    neg_space = _negative_space_score(mask, gray)

    # For isolation, we need sharpness contrast — compute a quick ratio
    from .sharpness import _compute_region_sharpness
    subj_sharp = _compute_region_sharpness(gray, mask)
    bg_sharp = _compute_region_sharpness(gray, 1 - mask)
    sharp_contrast = subj_sharp / max(bg_sharp, 0.01)

    isolation = _subject_isolation_score(img_bgr, mask, sharp_contrast)
    balance = _balance_score(saliency)
    colorfulness = _colorfulness_score(img_bgr)

    # Overall: equal-weighted (genre weighting happens in fusion)
    overall = (rot + symmetry + lines + neg_space + isolation + balance) / 6.0

    return CompositionScores(
        rule_of_thirds=round(rot, 4),
        symmetry=round(symmetry, 4),
        leading_lines=round(lines, 4),
        negative_space=round(neg_space, 4),
        subject_isolation=round(isolation, 4),
        balance=round(balance, 4),
        overall=round(overall, 4),
        colorfulness=round(colorfulness, 4),
    )


# --- Backward compatibility ---

def score_composition(path: Path) -> float:
    """Score composition for a single image. Backward-compatible wrapper."""
    from .raw_loader import load_rgb
    try:
        img = load_rgb(path)
    except Exception:
        logger.warning("Could not load image for composition: %s", path)
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

    scores = score_composition_detailed(ctx)
    return scores.overall
