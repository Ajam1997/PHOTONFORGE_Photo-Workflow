"""Shared raw image loading: decode ARW/CR2/NEF/DNG via rawpy, fall back to cv2/Pillow."""

from __future__ import annotations

from pathlib import Path

# Single source of truth for supported extensions. Before consolidation,
# several modules kept their own disagreeing sets — e.g. pipeline scanning
# accepted .raf while is_raw() here didn't, so every Fuji RAF fell through
# to cv2.imread and errored in scoring.
RAW_EXTENSIONS = {
    ".arw", ".cr2", ".cr3", ".nef", ".dng", ".raw", ".orf", ".rw2",
    ".raf", ".pef", ".srw", ".3fr", ".mef",
}
JPG_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif"}
IMAGE_EXTENSIONS = RAW_EXTENSIONS | JPG_EXTENSIONS


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


def read_exif_datetime(path: Path):
    """Read EXIF DateTimeOriginal (falling back to Image DateTime) as datetime.

    The one implementation — grouping and ingest previously kept their own
    byte-identical copies differing only in return type.
    """
    from datetime import datetime

    try:
        import exifread

        with open(path, "rb") as f:
            tags = exifread.process_file(f, stop_tag="EXIF DateTimeOriginal", details=False)
        raw = tags.get("EXIF DateTimeOriginal") or tags.get("Image DateTime")
        if raw:
            return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None
