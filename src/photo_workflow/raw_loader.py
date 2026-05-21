"""Shared raw image loading: decode ARW/CR2/NEF/DNG via rawpy, fall back to cv2/Pillow."""

from __future__ import annotations

from pathlib import Path

RAW_EXTENSIONS = {".arw", ".cr2", ".cr3", ".nef", ".dng", ".raw", ".orf", ".rw2"}


def is_raw(path: Path) -> bool:
    return path.suffix.lower() in RAW_EXTENSIONS


def load_rgb(path: Path):
    """Return a numpy BGR array (OpenCV convention). Uses rawpy for raw files, cv2 otherwise."""
    import cv2

    if is_raw(path):
        import rawpy
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=True)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    img = cv2.imread(str(path))
    if img is None:
        raise ValueError(f"cv2.imread failed for {path}")
    return img


def load_gray(path: Path):
    """Return a numpy grayscale array. Uses rawpy for raw files, cv2 otherwise."""
    import cv2

    if is_raw(path):
        import rawpy
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=True)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"cv2.imread failed for {path}")
    return img


def load_pil(path: Path):
    """Return a PIL Image. Uses rawpy for raw files, Pillow otherwise."""
    from PIL import Image

    if is_raw(path):
        import rawpy
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(use_camera_wb=True, half_size=True, no_auto_bright=True)
        return Image.fromarray(rgb)
    return Image.open(path)


def load_thumbnail(path: Path):
    """Extract the embedded JPEG preview from a raw file (fast). Falls back to load_pil."""
    import io
    from PIL import Image

    if is_raw(path):
        import rawpy
        try:
            with rawpy.imread(str(path)) as raw:
                thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                return Image.open(io.BytesIO(thumb.data))
            else:
                return Image.fromarray(thumb.data)
        except Exception:
            pass
    return load_pil(path)
