"""AnalysisPipeline — orchestrates all photo workflow stages."""

from __future__ import annotations

import json
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


def emit(
    step: str,
    file: str,
    status: str,
    json_progress: bool = False,
    **fields: object,
) -> None:
    """Print a progress line — JSON when json_progress=True, human text otherwise."""
    if json_progress:
        click.echo(json.dumps({"step": step, "file": file, "status": status, **fields}))
    else:
        extras = "  ".join(f"{k}={v}" for k, v in fields.items())
        click.echo(f"  {step} {file} [{status}]  {extras}")


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
            xmp_written = sync_to_darktable(records)
            db_upserted = 0
        else:
            xmp_written = 0
            db_upserted = 0

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


def _rename_photo_by_slug(path: Path, slug: str) -> Path:
    """Rename a photo on disk using a semantic slug. Returns the new path."""
    if not slug:
        return path
    directory = path.parent
    suffix = path.suffix
    candidate = directory / f"{slug}{suffix}"
    counter = 2
    while candidate.exists() and candidate != path:
        candidate = directory / f"{slug}_{counter}{suffix}"
        counter += 1
    if candidate == path:
        return path
    try:
        os.rename(path, candidate)
        logger.info("Renamed %s -> %s", path.name, candidate.name)
        return candidate
    except OSError as exc:
        logger.warning("Could not rename %s: %s", path, exc)
        return path


# --- Staged CLI -----------------------------------------------------------

# Supported image extensions for scanning (union of RAW + common formats)
PHOTO_EXTS = {
    ".jpg", ".jpeg", ".png", ".tiff", ".tif",
    ".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf",
    ".rw2", ".orf", ".pef", ".srw", ".3fr", ".mef",
}


def _next_sequence_counter(directory: Path, ext: str) -> int:
    """Return highest existing 5-digit sequence number + 1, or 1 if none exist."""
    max_seq = 0
    for p in directory.iterdir():
        if p.suffix.lower() == ext.lower() and p.stem.isdigit() and len(p.stem) == 5:
            max_seq = max(max_seq, int(p.stem))
    return max_seq + 1


@click.group()
def cli() -> None:
    """PHOTONForge staged photo analysis pipeline."""
    pass


@cli.command()
@click.option("--source", required=True, type=click.Path(exists=True, path_type=Path),
              help="SD card or source directory to ingest from.")
@click.option("--dest", required=True, type=click.Path(path_type=Path),
              help="Destination directory (e.g. H:\\ICELAND).")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show what would be copied without copying.")
@click.option("--json-progress", "json_progress", is_flag=True, default=False,
              help="Emit newline-delimited JSON progress lines.")
def ingest(source: Path, dest: Path, dry_run: bool, json_progress: bool) -> None:
    """Copy photos from SD card to destination with YYYYMMDD_ prefix."""
    from .ingest import ingest_volume

    copied = ingest_volume(source, dest, dry_run=dry_run)
    for p in copied:
        emit("ingest", p.name, "ok", json_progress=json_progress, dest=str(p))
    if not json_progress:
        verb = "Would copy" if dry_run else "Copied"
        click.echo(f"{verb} {len(copied)} photos to {dest}")
    else:
        click.echo(json.dumps({"step": "_progress", "done": len(copied), "total": len(copied)}))


@cli.command()
@click.option("--source", required=True, type=click.Path(exists=True, path_type=Path),
              help="Directory containing photos to process.")
@click.option("--manifest", "manifest_path", default="manifest.jsonl",
              type=click.Path(path_type=Path), show_default=True,
              help="Path to the JSONL manifest file.")
@click.option("--recursive", is_flag=True, default=False,
              help="Recurse into subdirectories.")
@click.option("--json-progress", "json_progress", is_flag=True, default=False,
              help="Emit newline-delimited JSON progress lines.")
def scan(source: Path, manifest_path: Path, recursive: bool, json_progress: bool) -> None:
    """Discover photos and create the manifest."""
    from .grouping import read_exif_datetime
    from .manifest import ManifestEntry, save_manifest

    glob_fn = source.rglob if recursive else source.glob
    photos = sorted(
        p for p in glob_fn("*")
        if p.is_file() and p.suffix.lower() in PHOTO_EXTS
    )

    entries: list[ManifestEntry] = []
    for p in photos:
        dt = read_exif_datetime(p)
        entries.append(ManifestEntry(
            path=str(p),
            exif_timestamp=dt.isoformat() if dt else None,
            stages_completed=["scan"],
        ))
        emit("scan", p.name, "ok", json_progress=json_progress)

    save_manifest(entries, manifest_path)
    if not json_progress:
        click.echo(f"Scanned {len(entries)} photos -> {manifest_path}")
    else:
        click.echo(json.dumps({"step": "_progress", "done": len(entries), "total": len(entries)}))


@cli.command()
@click.option("--manifest", "manifest_path", required=True,
              type=click.Path(exists=True, path_type=Path),
              help="Path to the JSONL manifest file.")
@click.option("--json-progress", "json_progress", is_flag=True, default=False,
              help="Emit newline-delimited JSON progress lines.")
def dedup(manifest_path: Path, json_progress: bool) -> None:
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
        status = "duplicate" if record.is_duplicate else "ok"
        emit("dedup", Path(entry.path).name, status, json_progress=json_progress)

    save_manifest(entries, manifest_path)

    if not json_progress:
        sessions = len({e.session_id for e in entries})
        dupes = sum(1 for e in entries if e.is_duplicate)
        click.echo(f"Grouped into {sessions} sessions, flagged {dupes} duplicates")
    else:
        click.echo(json.dumps({"step": "_progress", "done": len(entries), "total": len(entries)}))


@cli.command()
@click.option("--manifest", "manifest_path", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--resume", is_flag=True, default=False,
              help="Skip photos already scored.")
@click.option("--force", is_flag=True, default=False,
              help="Re-score all photos regardless of prior completion.")
@click.option("--verbose", is_flag=True, default=False)
@click.option("--quiet", is_flag=True, default=False)
@click.option("--json-progress", "json_progress", is_flag=True, default=False,
              help="Emit newline-delimited JSON progress lines.")
def score(manifest_path: Path, resume: bool, force: bool, verbose: bool, quiet: bool, json_progress: bool) -> None:
    """Score photos for sharpness, composition, and exposure."""
    from .manifest import load_manifest, save_manifest, checkpoint
    from .progress import ProgressTracker
    from .sharpness import score_sharpness
    from .composition import score_composition
    from .exposure import score_exposure
    from .darktable_bridge import compute_color_label

    entries = load_manifest(manifest_path)

    not_deduped = [e for e in entries if "dedup" not in e.stages_completed]
    if not_deduped:
        raise click.ClickException(
            f"{len(not_deduped)} photos have not been through 'dedup'. "
            f"Run 'photo-workflow dedup' first."
        )

    to_score = [
        e for e in entries
        if not e.is_duplicate and (force or "score" not in e.stages_completed)
    ]

    if not to_score and not force:
        if resume:
            click.echo("All non-duplicate photos already scored.")
        else:
            click.echo("All non-duplicate photos already scored. Use --resume or --force.")
        return

    if resume and not force:
        already = sum(1 for e in entries if not e.is_duplicate and "score" in e.stages_completed)
        if already > 0:
            click.echo(f"Resuming: {already} already scored, {len(to_score)} remaining")

    tracker = ProgressTracker(stage="score", total=len(to_score))
    errors = 0

    for i, entry in enumerate(to_score, 1):
        p = Path(entry.path)
        try:
            entry.sharpness = score_sharpness(p)
            entry.composition = score_composition(p)
            entry.exposure = score_exposure(p)
            entry.error = None
            if "score" not in entry.stages_completed:
                entry.stages_completed.append("score")

            mean = (entry.sharpness + entry.composition + entry.exposure) / 3.0
            stars = min(5, round(mean * 5))
            color_label = compute_color_label(entry.sharpness, entry.composition, entry.exposure)

            if json_progress:
                emit("score", p.name, "ok", json_progress=True,
                     sharpness=round(entry.sharpness, 4),
                     composition=round(entry.composition, 4),
                     exposure=round(entry.exposure, 4),
                     stars=stars,
                     color_label=color_label)
            elif verbose:
                click.echo(
                    f"  {p.name}: sharp={entry.sharpness:.4f} "
                    f"comp={entry.composition:.4f} exp={entry.exposure:.4f}"
                )
        except Exception as exc:
            entry.error = str(exc)
            errors += 1
            logger.warning("Score failed for %s: %s", p, exc)
            if json_progress:
                emit("score", p.name, "error", json_progress=True, message=str(exc))

        if not (quiet or json_progress):
            tracker.update(i)

        if i % 50 == 0:
            checkpoint(entries, manifest_path)

    if not (quiet or json_progress):
        tracker.finish()

    save_manifest(entries, manifest_path)

    if not json_progress:
        scored = len(to_score) - errors
        click.echo(f"Scored {scored}/{len(to_score)} photos. {errors} errors.")
    else:
        click.echo(json.dumps({"step": "_progress", "done": len(to_score), "total": len(to_score)}))


@cli.command()
@click.option("--manifest", "manifest_path", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--model-dir", default="models/florence2_int8", show_default=True,
              type=click.Path(path_type=Path),
              help="Path to the Florence-2 INT8 ONNX model directory.")
@click.option("--resume", is_flag=True, default=False,
              help="Skip photos already named.")
@click.option("--force", is_flag=True, default=False,
              help="Re-name all photos regardless of prior completion.")
@click.option("--verbose", is_flag=True, default=False)
@click.option("--quiet", is_flag=True, default=False)
@click.option("--json-progress", "json_progress", is_flag=True, default=False,
              help="Emit newline-delimited JSON progress lines.")
def name(
    manifest_path: Path,
    model_dir: Path,
    resume: bool,
    force: bool,
    verbose: bool,
    quiet: bool,
    json_progress: bool,
) -> None:
    """Generate semantic filenames via Florence-2 and rename files on disk."""
    from .manifest import load_manifest, save_manifest, checkpoint
    from .progress import ProgressTracker
    from .naming import generate_name

    entries = load_manifest(manifest_path)

    not_scored = [
        e for e in entries
        if not e.is_duplicate and "score" not in e.stages_completed
    ]
    if not_scored:
        raise click.ClickException(
            f"{len(not_scored)} photos have not been through 'score'. "
            f"Run 'photo-workflow score' first."
        )

    to_name = [
        e for e in entries
        if not e.is_duplicate and (force or "name" not in e.stages_completed)
    ]

    if not to_name and not force:
        if resume:
            click.echo("All non-duplicate photos already named.")
        else:
            click.echo("All non-duplicate photos already named. Use --resume or --force.")
        return

    if resume and not force:
        already = sum(
            1 for e in entries
            if not e.is_duplicate and "name" in e.stages_completed
        )
        if already > 0:
            click.echo(f"Resuming: {already} already named, {len(to_name)} remaining")

    tracker = ProgressTracker(stage="name", total=len(to_name))
    errors = 0

    # Determine starting sequence counter (scan before any renames)
    if to_name:
        dest_dir = Path(to_name[0].path).parent
        dest_ext = Path(to_name[0].path).suffix
        counter = _next_sequence_counter(dest_dir, dest_ext)
    else:
        counter = 1

    for i, entry in enumerate(to_name, 1):
        p = Path(entry.path)
        try:
            slug = generate_name(p, model_dir=model_dir)
            entry.semantic_name = slug

            # Store original filename before rename
            entry.metadata = entry.metadata or {}
            entry.metadata["original_filename"] = p.name

            # Rename to sequence number
            seq_name = f"{counter:05d}{p.suffix}"
            new_path = p.parent / seq_name
            if not new_path.exists() or new_path == p:
                try:
                    os.rename(p, new_path)
                    entry.path = str(new_path)
                except OSError as exc:
                    logger.warning("Could not rename %s to %s: %s", p, new_path, exc)
            counter += 1

            entry.error = None
            if "name" not in entry.stages_completed:
                entry.stages_completed.append("name")

            if json_progress:
                emit("name", seq_name, "ok", json_progress=True, semantic_name=slug, original=p.name)
            elif verbose:
                click.echo(f"  {p.name} -> {seq_name}")
        except Exception as exc:
            entry.error = str(exc)
            errors += 1
            logger.warning("Name failed for %s: %s", p, exc)
            if json_progress:
                emit("name", p.name, "error", json_progress=True, message=str(exc))

        if not (quiet or json_progress):
            tracker.update(i)

        if i % 50 == 0:
            checkpoint(entries, manifest_path)

    if not (quiet or json_progress):
        tracker.finish()

    save_manifest(entries, manifest_path)

    if not json_progress:
        named = len(to_name) - errors
        click.echo(f"Named {named}/{len(to_name)} photos. {errors} errors.")
    else:
        click.echo(json.dumps({"step": "_progress", "done": len(to_name), "total": len(to_name)}))


@cli.command()
@click.option("--manifest", "manifest_path", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True, default=False,
              help="Print what would happen without writing.")
@click.option("--verbose", is_flag=True, default=False)
@click.option("--json-progress", "json_progress", is_flag=True, default=False,
              help="Emit newline-delimited JSON progress lines.")
def sync(manifest_path: Path, dry_run: bool, verbose: bool, json_progress: bool) -> None:
    """Write XMP sidecars for all named photos."""
    from .manifest import load_manifest, save_manifest
    from .darktable_bridge import sync_to_darktable

    entries = load_manifest(manifest_path)

    not_named = [
        e for e in entries
        if not e.is_duplicate and "name" not in e.stages_completed
    ]
    if not_named:
        raise click.ClickException(
            f"{len(not_named)} photos have not been through 'name'. "
            f"Run 'photo-workflow name' first."
        )

    records = []
    for e in entries:
        rec = PhotoRecord(
            path=Path(e.path),
            session_id=e.session_id,
            is_duplicate=e.is_duplicate,
            sharpness_score=e.sharpness or 0.0,
            composition_score=e.composition or 0.0,
            exposure_score=e.exposure or 0.0,
            semantic_name=e.semantic_name or "",
            metadata={"original_filename": Path(e.path).name},
        )
        records.append(rec)

    if dry_run:
        non_dupes = sum(1 for r in records if not r.is_duplicate)
        click.echo(f"Dry run: would write {non_dupes} XMP sidecars")
        return

    xmp_written = sync_to_darktable(records, verbose=verbose)

    for record in records:
        xmp_path = record.path.with_suffix(".xmp")
        emit("sync", record.path.name, "ok", json_progress=json_progress,
             xmp=str(xmp_path))

    for entry in entries:
        if not entry.is_duplicate and "sync" not in entry.stages_completed:
            entry.stages_completed.append("sync")
    save_manifest(entries, manifest_path)

    if not json_progress:
        click.echo(f"Wrote {xmp_written} XMP sidecars")
    else:
        click.echo(json.dumps({"step": "_progress", "done": xmp_written, "total": xmp_written}))


@cli.command()
@click.option("--manifest", "manifest_path", required=True,
              type=click.Path(exists=True, path_type=Path))
def status(manifest_path: Path) -> None:
    """Show manifest summary: per-stage completion and error count."""
    from .manifest import load_manifest

    entries = load_manifest(manifest_path)
    total = len(entries)
    dupes = sum(1 for e in entries if e.is_duplicate)

    stage_counts = {}
    for stage in ("scan", "dedup", "score", "name", "sync"):
        stage_counts[stage] = sum(1 for e in entries if stage in e.stages_completed)

    error_count = sum(1 for e in entries if e.error)

    click.echo(f"Manifest: {manifest_path}")
    click.echo(f"  Total photos:  {total}")
    click.echo(f"  Duplicates:    {dupes}")
    click.echo(f"  Scan:          {stage_counts['scan']}/{total}")
    click.echo(f"  Dedup:         {stage_counts['dedup']}/{total}")
    click.echo(f"  Score:         {stage_counts['score']}/{total - dupes} (non-duplicate)")
    click.echo(f"  Name:          {stage_counts['name']}/{total - dupes} (non-duplicate)")
    click.echo(f"  Sync:          {stage_counts['sync']}/{total - dupes} (non-duplicate)")
    click.echo(f"  Errors:        {error_count}")


@cli.command()
@click.option("--source", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--output", required=True, type=click.Path(path_type=Path))
@click.option("--db", required=True, type=click.Path(path_type=Path), help="Darktable library.db path")
@click.option("--dry-run", is_flag=True)
@click.option("--model-dir", default="models/florence2_int8", show_default=True,
              type=click.Path(path_type=Path))
def run(source: Path, output: Path, db: Path, dry_run: bool, model_dir: Path) -> None:
    """Run the full pipeline in one shot (legacy mode)."""
    config = PipelineConfig(
        source_dir=source,
        output_dir=output,
        darktable_db=db,
        model_dir=model_dir,
        dry_run=dry_run,
    )
    pipeline = AnalysisPipeline(config)
    records, summary = pipeline.run()
    click.echo(
        f"Done: {summary.total} total, {summary.duplicates_skipped} dupes, "
        f"{summary.scored} scored, {summary.xmp_written} XMP, "
        f"{summary.db_upserted} DB rows, {summary.elapsed_seconds:.1f}s"
    )


def _get_temp_dir() -> Path:
    """Return the platform temp directory."""
    import tempfile
    return Path(tempfile.gettempdir())


def _write_sentinel(temp_dir: Path | None = None) -> None:
    """Write PID file and sentinel for Lua plugin process detection."""
    if temp_dir is None:
        temp_dir = _get_temp_dir()
    pid_file = temp_dir / "photonforge.pid"
    sentinel = temp_dir / "photonforge.running"
    pid_file.write_text(str(os.getpid()))
    sentinel.write_text("")


def _cleanup_sentinel(temp_dir: Path | None = None) -> None:
    """Remove sentinel file on clean exit. PID file is left for kill reference."""
    if temp_dir is None:
        temp_dir = _get_temp_dir()
    sentinel = temp_dir / "photonforge.running"
    try:
        sentinel.unlink()
    except FileNotFoundError:
        pass


def main() -> None:
    import atexit
    _write_sentinel()
    atexit.register(_cleanup_sentinel)
    cli()


if __name__ == "__main__":
    main()
