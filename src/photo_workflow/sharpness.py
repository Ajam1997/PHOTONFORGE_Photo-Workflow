"""FR-1.4: Focus scoring via Laplacian variance."""

from __future__ import annotations

import logging
from pathlib import Path

import click
import cv2
import numpy as np
from scipy.ndimage import laplace

logger = logging.getLogger(__name__)

_SUPPORTED_EXTS = {
    ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".raw",
    ".cr2", ".cr3", ".nef", ".arw", ".dng",
}

# Variance below this is considered blurry (tune per sensor/resolution)
BLUR_THRESHOLD = 100.0


def score_sharpness(path: Path) -> float:
    """
    Compute Laplacian variance as a sharpness proxy.
    Returns a score in [0.0, 1.0] normalized against a practical max.
    """
    from .raw_loader import load_gray
    try:
        img = load_gray(path)
    except Exception:
        logger.warning("Could not load image for sharpness: %s", path)
        return 0.0

    lap = laplace(img.astype(np.float64))
    variance = float(lap.var())
    # Soft-normalize: score saturates near 1.0 at ~10× the blur threshold
    score = min(variance / (BLUR_THRESHOLD * 10.0), 1.0)
    return round(score, 4)


@click.command("sharpness")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--threshold",
    default=BLUR_THRESHOLD,
    show_default=True,
    help="Blur threshold for normalization (variance units).",
)
def main(path: Path, threshold: float) -> None:
    """Score sharpness for PATH (file or directory of images).

    Prints one line per image: '<path>: <score>'
    Score is in [0.0, 1.0]; values below 0.1 typically indicate blur.
    """
    targets = sorted(path.iterdir()) if path.is_dir() else [path]
    for p in targets:
        if not (p.is_file() and p.suffix.lower() in _SUPPORTED_EXTS):
            continue
        from .raw_loader import load_gray
        try:
            img = load_gray(p)
        except Exception:
            click.echo(f"{p}: unreadable")
            continue
        variance = float(laplace(img.astype(np.float64)).var())
        score = round(min(variance / (threshold * 10.0), 1.0), 4)
        click.echo(f"{p}: {score:.4f}")
