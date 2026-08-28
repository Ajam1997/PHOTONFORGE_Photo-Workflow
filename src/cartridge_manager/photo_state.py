"""Backend photo viewer state — no PySide6 import at all."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from photo_workflow import backup, photondb
from photo_workflow.darktable_bridge import read_darktable_color_label, read_darktable_keywords
from photo_workflow.raw_loader import IMAGE_EXTENSIONS, load_thumbnail

logger = logging.getLogger(__name__)


@dataclass
class PhotoInfo:
    """Displayable summary of a photo's state from photonforge.db and Darktable."""

    path: Path
    master_score: float | None
    primary_genre: str
    stages: list[str]
    needs_review: bool
    darktable_tags: list[str]
    darktable_color_label: int | None
    thumbnail_path: Path | None  # None if thumbnail generation failed for this photo


def list_photos(folder: Path) -> list[Path]:
    """Recursively find every image file under folder, sorted by name.

    Filters out .xmp sidecar files. Returns a list suitable for deterministic
    ordering (used in tests and gallery building).
    """
    folder = Path(folder)
    photos: list[Path] = []

    for file_path in folder.rglob("*"):
        if file_path.is_file():
            suffix = file_path.suffix.lower()
            # Skip sidecar files and non-images
            if suffix == ".xmp" or suffix not in IMAGE_EXTENSIONS:
                continue
            photos.append(file_path)

    # Sort for deterministic ordering
    return sorted(photos)


def describe_photo(photo_path: Path) -> PhotoInfo:
    """Gather everything the viewer needs about one photo.

    Degrades gracefully — never raises — matching the pattern in cartridges.describe().
    Each independent piece of state (photonforge.db row, Darktable tags, color label)
    is wrapped in try/except so one missing/broken piece doesn't prevent showing the rest.
    """
    photo_path = Path(photo_path)
    shoot_folder = photo_path.parent
    cartridge_root = shoot_folder.parent

    # Query photonforge.db
    master_score = None
    primary_genre = ""
    stages: list[str] = []
    needs_review = False

    try:
        conn = photondb.open_db(shoot_folder)
        try:
            photondb.ensure_schema(conn)
            row = conn.execute(
                "SELECT master_score, primary_genre, stages, needs_review FROM photos "
                "WHERE folder=? AND filename=?",
                (shoot_folder.name, photo_path.name)
            ).fetchone()

            if row:
                master_score = row["master_score"]
                primary_genre = row["primary_genre"] or ""
                stages_str = row["stages"] or ""
                stages = [s for s in stages_str.split(",") if s]
                needs_review = bool(row["needs_review"])
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001 - degrade gracefully on any DB error
        logger.warning("Failed to read photonforge.db for %s: %s", photo_path.name, e)

    # Query Darktable state
    darktable_tags: list[str] = []
    darktable_color_label: int | None = None

    try:
        layout = backup.cartridge_layout(cartridge_root)
        if "dt_library" in layout.dbs:
            darktable_tags = read_darktable_keywords(layout.dbs["dt_library"], photo_path.name)
            darktable_color_label = read_darktable_color_label(layout.dbs["dt_library"], photo_path.name)
    except Exception as e:  # noqa: BLE001 - degrade gracefully on any Darktable error
        logger.warning("Failed to read Darktable state for %s: %s", photo_path.name, e)

    return PhotoInfo(
        path=photo_path,
        master_score=master_score,
        primary_genre=primary_genre,
        stages=stages,
        needs_review=needs_review,
        darktable_tags=darktable_tags,
        darktable_color_label=darktable_color_label,
        thumbnail_path=None,  # Filled in by caller via get_cached_thumbnail
    )


def get_cached_thumbnail(photo_path: Path, cache_dir: Path, *, max_size: int = 256) -> Path | None:
    """Return a cached JPEG thumbnail for photo_path, generating it if missing or stale.

    Cache key includes source file's mtime so an edited/replaced source photo
    invalidates its old cache entry. Degrades gracefully — returns None on any error
    rather than raising, so one bad photo doesn't abort loading a folder.
    """
    photo_path = Path(photo_path)
    cache_dir = Path(cache_dir)

    try:
        # Cache key includes mtime for invalidation on source updates
        mtime = int(photo_path.stat().st_mtime)
        cache_file = cache_dir / f"{photo_path.name}.{mtime}.jpg"

        # Cache hit: return immediately without regenerating
        if cache_file.exists():
            return cache_file

        # Cache miss: generate the thumbnail
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Load the image and extract/decode thumbnail
        pil_image = load_thumbnail(photo_path)

        # Convert to RGB (embedded previews may be non-RGB modes that JPEG can't save)
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")

        # Thumbnail in-place, preserving aspect ratio
        pil_image.thumbnail((max_size, max_size))

        # Save as JPEG to cache
        pil_image.save(cache_file, "JPEG", quality=85)

        return cache_file

    except Exception as e:  # noqa: BLE001 - degrade gracefully on corrupt/unsupported files
        logger.warning("Failed to generate thumbnail for %s: %s", photo_path.name, e)
        return None


def build_gallery(
    folder: Path,
    cache_dir: Path,
    *,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[PhotoInfo]:
    """Build the full gallery of photos for a folder, with cached thumbnails.

    This is the function the Worker wraps. For each photo (in order):
    - Gather metadata via describe_photo
    - Generate/retrieve cached thumbnail via get_cached_thumbnail
    - Call progress callback if given (1-based index, matching relocate.py's convention)
    - Append to result list

    Returns the full list of PhotoInfo objects.
    """
    photos = list_photos(folder)
    gallery: list[PhotoInfo] = []

    for index, photo_path in enumerate(photos):
        info = describe_photo(photo_path)
        info.thumbnail_path = get_cached_thumbnail(photo_path, cache_dir)
        gallery.append(info)

        # Call progress callback (1-based index, matching relocate.py convention)
        if progress is not None:
            progress(index + 1, len(photos), photo_path.name)

    return gallery
