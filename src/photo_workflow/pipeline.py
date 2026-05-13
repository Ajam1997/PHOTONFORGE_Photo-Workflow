"""AnalysisPipeline — orchestrates all photo workflow stages."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import click

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass


@dataclass
class PipelineConfig:
    source_dir: Path
    output_dir: Path
    darktable_db: Path
    model_dir: Path = Path("models/florence2_int8")
    dry_run: bool = False


@dataclass
class PhotoRecord:
    """Shared state passed through each pipeline stage."""
    path: Path
    session_id: str = ""
    is_duplicate: bool = False
    sharpness_score: float = 0.0
    composition_score: float = 0.0
    exposure_score: float = 0.0
    semantic_name: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class PipelineSummary:
    total: int
    duplicates_skipped: int
    scored: int
    xmp_written: int
    db_upserted: int
    elapsed_seconds: float


def _rename_photo(record: PhotoRecord) -> None:
    """Rename *record.path* on disk to use the semantic slug as the filename.

    The new name is ``{semantic_name}{original_suffix}`` (e.g.
    ``golden-sunset-beach-afternoon-light.jpg``).  If a file with that name
    already exists in the same directory, ``_2``, ``_3``, … are appended
    before the suffix to avoid collisions.  ``record.path`` is updated in
    place after a successful rename.
    """
    if not record.semantic_name:
        return

    directory = record.path.parent
    suffix = record.path.suffix
    base_name = record.semantic_name

    candidate = directory / f"{base_name}{suffix}"
    counter = 2
    while candidate.exists() and candidate != record.path:
        candidate = directory / f"{base_name}_{counter}{suffix}"
        counter += 1

    if candidate == record.path:
        # Already named correctly — nothing to do
        return

    try:
        os.rename(record.path, candidate)
        logger.info("Renamed %s -> %s", record.path.name, candidate.name)
        record.path = candidate
    except OSError as exc:
        logger.warning("Could not rename %s: %s", record.path, exc)


class AnalysisPipeline:
    """Orchestrates ingest → group → dedup → score → name → catalog."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self._setup_logging()

    def _setup_logging(self) -> None:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    def run(self) -> tuple[list[PhotoRecord], PipelineSummary]:
        """Execute the full pipeline and return processed records and summary."""
        from .ingest import ingest_volume
        from .grouping import cluster_sessions
        from .dedup import deduplicate
        from .sharpness import score_sharpness
        from .composition import score_composition
        from .exposure import score_exposure
        from .naming import generate_name
        from .darktable_bridge import sync_to_darktable

        t0 = time.perf_counter()

        logger.info("Pipeline start: source=%s", self.config.source_dir)

        paths = ingest_volume(self.config.source_dir, self.config.output_dir, dry_run=self.config.dry_run)

        # Store original filename before any rename so it can be preserved in XMP
        records = [
            PhotoRecord(path=p, metadata={"original_filename": p.name})
            for p in paths
        ]

        records = cluster_sessions(records)
        records = deduplicate(records)

        for record in records:
            if record.is_duplicate:
                continue
            record.sharpness_score = score_sharpness(record.path)
            record.composition_score = score_composition(record.path)
            record.exposure_score = score_exposure(record.path)
            record.semantic_name = generate_name(record.path, model_dir=self.config.model_dir)

        scored = sum(1 for r in records if not r.is_duplicate)

        # Rename files on disk to the semantic slug (skipped in dry-run mode)
        if not self.config.dry_run:
            for record in records:
                if record.is_duplicate or not record.semantic_name:
                    continue
                _rename_photo(record)

        if not self.config.dry_run:
            xmp_written, db_upserted = sync_to_darktable(records, db_path=self.config.darktable_db)
        else:
            xmp_written, db_upserted = 0, 0

        logger.info("Pipeline complete: %d records processed", len(records))

        summary = PipelineSummary(
            total=len(records),
            duplicates_skipped=sum(1 for r in records if r.is_duplicate),
            scored=scored,
            xmp_written=xmp_written,
            db_upserted=db_upserted,
            elapsed_seconds=time.perf_counter() - t0,
        )
        return records, summary


# --- Staged CLI -----------------------------------------------------------

# Supported image extensions for scanning (union of RAW + common formats)
PHOTO_EXTS = {
    ".jpg", ".jpeg", ".png", ".tiff", ".tif",
    ".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf",
    ".rw2", ".orf", ".pef", ".srw", ".3fr", ".mef",
}


@click.group()
def cli() -> None:
    """PHOTONForge staged photo analysis pipeline."""
    pass


@cli.command()
@click.option("--source", required=True, type=click.Path(exists=True, path_type=Path),
              help="Directory containing photos to process.")
@click.option("--manifest", "manifest_path", default="manifest.jsonl",
              type=click.Path(path_type=Path), show_default=True,
              help="Path to the JSONL manifest file.")
@click.option("--recursive", is_flag=True, default=False,
              help="Recurse into subdirectories.")
def scan(source: Path, manifest_path: Path, recursive: bool) -> None:
    """Discover photos and create the manifest."""
    from .grouping import _read_exif_datetime
    from .manifest import ManifestEntry, save_manifest

    glob_fn = source.rglob if recursive else source.glob
    photos = sorted(
        p for p in glob_fn("*")
        if p.is_file() and p.suffix.lower() in PHOTO_EXTS
    )

    entries: list[ManifestEntry] = []
    for p in photos:
        dt = _read_exif_datetime(p)
        entries.append(ManifestEntry(
            path=str(p),
            exif_timestamp=dt.isoformat() if dt else None,
            stages_completed=["scan"],
        ))

    save_manifest(entries, manifest_path)
    click.echo(f"Scanned {len(entries)} photos -> {manifest_path}")


@cli.command()
@click.option("--manifest", "manifest_path", required=True,
              type=click.Path(exists=True, path_type=Path),
              help="Path to the JSONL manifest file.")
def dedup(manifest_path: Path) -> None:
    """Group photos into sessions and flag duplicates."""
    from .manifest import load_manifest, save_manifest

    entries = load_manifest(manifest_path)

    not_scanned = [e for e in entries if "scan" not in e.stages_completed]
    if not_scanned:
        raise click.ClickException(
            f"{len(not_scanned)} photos have not been through 'scan'. "
            f"Run 'photo-workflow scan' first."
        )

    to_process = [e for e in entries if "dedup" not in e.stages_completed]
    if not to_process:
        click.echo("All photos already deduped. Use --force to redo.")
        return

    from .grouping import cluster_sessions
    from .dedup import deduplicate

    records = [
        PhotoRecord(path=Path(e.path), session_id=e.session_id)
        for e in entries
    ]

    records = cluster_sessions(records)
    records = deduplicate(records)

    for entry, record in zip(entries, records):
        entry.session_id = record.session_id
        entry.is_duplicate = record.is_duplicate
        if "dedup" not in entry.stages_completed:
            entry.stages_completed.append("dedup")

    save_manifest(entries, manifest_path)

    sessions = len({e.session_id for e in entries})
    dupes = sum(1 for e in entries if e.is_duplicate)
    click.echo(f"Grouped into {sessions} sessions, flagged {dupes} duplicates")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
