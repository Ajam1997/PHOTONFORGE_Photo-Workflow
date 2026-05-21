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
@click.option("--db", "db_path", required=True, type=click.Path(path_type=Path),
              help="Path to photonforge.db.")
@click.option("--json-progress", "json_progress", is_flag=True, default=False,
              help="Emit newline-delimited JSON progress lines.")
def scan(source: Path, db_path: Path, json_progress: bool) -> None:
    """Discover photos, read EXIF, and insert into photonforge.db."""
    import sqlite3

    from .grouping import read_exif_datetime
    from .photondb import ensure_table, insert_photo, update_stages

    folder_name = source.name
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_table(conn, folder_name)

    photos = sorted(
        p for p in source.rglob("*")
        if p.is_file()
        and p.suffix.lower() in PHOTO_EXTS
        and not any(part.startswith(".") for part in p.parts[len(source.parts):])
    )

    for p in photos:
        dt_val = read_exif_datetime(p)
        ts = dt_val.isoformat() if dt_val else None
        insert_photo(conn, folder_name, p.name, p.name, ts)
        update_stages(conn, folder_name, p.name, "scan")
        emit("scan", p.name, "ok", json_progress=json_progress)

    conn.close()

    if not json_progress:
        click.echo(f"Scanned {len(photos)} photos -> {db_path}")
    else:
        click.echo(json.dumps({"step": "_progress", "done": len(photos), "total": len(photos)}))


@cli.command()
@click.option("--db", "db_path", required=True, type=click.Path(exists=True, path_type=Path),
              help="Path to photonforge.db.")
@click.option("--folder", required=True, help="Folder/table name in the DB.")
@click.option("--source-dir", "source_dir", required=True, type=click.Path(exists=True, path_type=Path),
              help="Directory containing the photo files.")
@click.option("--json-progress", "json_progress", is_flag=True, default=False)
@click.option("--force", is_flag=True, default=False)
def dedup(db_path: Path, folder: str, source_dir: Path, json_progress: bool, force: bool) -> None:
    """Group photos into sessions and flag duplicates."""
    import sqlite3

    from .grouping import cluster_sessions
    from .dedup import deduplicate
    from .photondb import ensure_table, get_pending, update_stages, clear_stage

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_table(conn, folder)

    if force:
        clear_stage(conn, folder, "dedup")

    pending = get_pending(conn, folder, "dedup")
    if not pending:
        click.echo("All photos already deduped. Use --force to redo.")
        conn.close()
        return

    all_rows = conn.execute(f"SELECT * FROM [{folder}]").fetchall()

    records = []
    for row in all_rows:
        rec = PhotoRecord(path=source_dir / row["filename"])
        rec.session_id = row["session_id"] or ""
        records.append(rec)

    records = cluster_sessions(records)

    def _progress(done: int, total: int) -> None:
        if json_progress:
            click.echo(json.dumps({"step": "_progress", "done": done, "total": total}))

    _progress(0, len(records))
    records = deduplicate(records, progress_fn=_progress)

    for rec in records:
        fname = rec.path.name
        conn.execute(
            f"UPDATE [{folder}] SET session_id=?, is_duplicate=? WHERE filename=?",
            (rec.session_id, 1 if rec.is_duplicate else 0, fname),
        )
        update_stages(conn, folder, fname, "dedup")
        status = "duplicate" if rec.is_duplicate else "ok"
        emit("dedup", fname, status, json_progress=json_progress)

    conn.commit()
    conn.close()

    if not json_progress:
        sessions = len({r.session_id for r in records})
        dupes = sum(1 for r in records if r.is_duplicate)
        click.echo(f"Grouped into {sessions} sessions, flagged {dupes} duplicates")
    else:
        click.echo(json.dumps({"step": "_progress", "done": len(records), "total": len(records)}))


@cli.command()
@click.option("--db", "db_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--folder", required=True, help="Folder/table name in the DB.")
@click.option("--source-dir", "source_dir", required=True, type=click.Path(exists=True, path_type=Path),
              help="Directory containing the photo files.")
@click.option("--resume", is_flag=True, default=False)
@click.option("--force", is_flag=True, default=False)
@click.option("--json-progress", "json_progress", is_flag=True, default=False)
def score(db_path: Path, folder: str, source_dir: Path, resume: bool, force: bool, json_progress: bool) -> None:
    """Score photos for sharpness, composition, and exposure."""
    import sqlite3

    from .sharpness import score_sharpness
    from .composition import score_composition
    from .exposure import score_exposure
    from .darktable_bridge import compute_color_label
    from .photondb import ensure_table, get_pending, update_scores, update_stages, clear_stage

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_table(conn, folder)

    if force:
        clear_stage(conn, folder, "score")

    pending = get_pending(conn, folder, "score")
    to_score = [r for r in pending if not r["is_duplicate"]]

    if not to_score:
        click.echo("All non-duplicate photos already scored.")
        conn.close()
        return

    errors = 0
    for i, row in enumerate(to_score, 1):
        p = source_dir / row["filename"]
        try:
            sharp = score_sharpness(p)
            comp = score_composition(p)
            expo = score_exposure(p)
            update_scores(conn, folder, row["filename"], sharp, comp, expo)
            update_stages(conn, folder, row["filename"], "score")

            mean = (sharp + comp + expo) / 3.0
            stars = min(5, round(mean * 5))
            color_label = compute_color_label(sharp, comp, expo)

            if json_progress:
                emit("score", row["filename"], "ok", json_progress=True,
                     sharpness=round(sharp, 4), composition=round(comp, 4),
                     exposure=round(expo, 4), stars=stars, color_label=color_label)
        except Exception as exc:
            conn.execute(
                f"UPDATE [{folder}] SET error=? WHERE filename=?",
                (str(exc), row["filename"]),
            )
            conn.commit()
            errors += 1
            if json_progress:
                emit("score", row["filename"], "error", json_progress=True, message=str(exc))

        if json_progress and i % 10 == 0:
            click.echo(json.dumps({"step": "_progress", "done": i, "total": len(to_score)}))

    conn.close()

    if not json_progress:
        scored = len(to_score) - errors
        click.echo(f"Scored {scored}/{len(to_score)} photos. {errors} errors.")
    else:
        click.echo(json.dumps({"step": "_progress", "done": len(to_score), "total": len(to_score)}))


@cli.command()
@click.option("--db", "db_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--folder", required=True, help="Folder/table name in the DB.")
@click.option("--source-dir", "source_dir", required=True, type=click.Path(exists=True, path_type=Path),
              help="Directory containing the photo files.")
@click.option("--model-dir", default="models/florence2_int8", show_default=True,
              type=click.Path(path_type=Path))
@click.option("--resume", is_flag=True, default=False)
@click.option("--force", is_flag=True, default=False)
@click.option("--json-progress", "json_progress", is_flag=True, default=False)
def name(
    db_path: Path,
    folder: str,
    source_dir: Path,
    model_dir: Path,
    resume: bool,
    force: bool,
    json_progress: bool,
) -> None:
    """Generate semantic descriptions via Florence-2 (written to Darktable description, not filename)."""
    import sqlite3

    from .naming import generate_name
    from .photondb import ensure_table, get_pending, update_semantic, update_stages, clear_stage

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_table(conn, folder)

    if force:
        clear_stage(conn, folder, "name")

    pending = get_pending(conn, folder, "name")
    to_name = [r for r in pending if not r["is_duplicate"]]

    if not to_name:
        click.echo("All non-duplicate photos already named.")
        conn.close()
        return

    errors = 0
    for i, row in enumerate(to_name, 1):
        p = source_dir / row["filename"]
        try:
            slug = generate_name(p, model_dir=model_dir)
            update_semantic(conn, folder, row["filename"], slug)
            update_stages(conn, folder, row["filename"], "name")

            if json_progress:
                emit("name", row["filename"], "ok", json_progress=True, semantic_name=slug)
        except Exception as exc:
            conn.execute(
                f"UPDATE [{folder}] SET error=? WHERE filename=?",
                (str(exc), row["filename"]),
            )
            conn.commit()
            errors += 1
            if json_progress:
                emit("name", row["filename"], "error", json_progress=True, message=str(exc))

        if json_progress and i % 10 == 0:
            click.echo(json.dumps({"step": "_progress", "done": i, "total": len(to_name)}))

    conn.close()

    if not json_progress:
        named = len(to_name) - errors
        click.echo(f"Named {named}/{len(to_name)} photos. {errors} errors.")
    else:
        click.echo(json.dumps({"step": "_progress", "done": len(to_name), "total": len(to_name)}))


@cli.command()
@click.option("--db", "db_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--folder", required=True, help="Folder/table name in the DB.")
def status(db_path: Path, folder: str) -> None:
    """Show pipeline status for a folder."""
    import sqlite3

    from .photondb import sanitize_table_name

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    table = sanitize_table_name(folder)
    rows = conn.execute(f"SELECT * FROM [{table}]").fetchall()
    conn.close()

    total = len(rows)
    dupes = sum(1 for r in rows if r["is_duplicate"])

    stage_counts = {}
    for stage in ("scan", "dedup", "score", "name"):
        stage_counts[stage] = sum(1 for r in rows if stage in (r["stages"] or ""))

    error_count = sum(1 for r in rows if r["error"])

    click.echo(f"Database: {db_path} / table: {table}")
    click.echo(f"  Total photos:  {total}")
    click.echo(f"  Duplicates:    {dupes}")
    click.echo(f"  Scan:          {stage_counts['scan']}/{total}")
    click.echo(f"  Dedup:         {stage_counts['dedup']}/{total}")
    click.echo(f"  Score:         {stage_counts['score']}/{total - dupes} (non-duplicate)")
    click.echo(f"  Name:          {stage_counts['name']}/{total - dupes} (non-duplicate)")
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
    import sys
    # Force line-buffered stdout so Lua poller sees output in real time
    if not sys.stdout.line_buffering:
        sys.stdout.reconfigure(line_buffering=True)
    _write_sentinel()
    atexit.register(_cleanup_sentinel)
    cli()


if __name__ == "__main__":
    main()
