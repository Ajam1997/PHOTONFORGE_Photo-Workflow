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
import numpy as np

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass


@dataclass
class PipelineConfig:
    source_dir: Path
    output_dir: Path
    darktable_db: Path
    model_dir: Path = Path("models/florence2_int8")
    scoring_model_dir: Path = Path("models")
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
    genre: str = ""
    genre_confidence: float = 0.0
    master_score: float = 0.0
    sub_scores: dict = field(default_factory=dict)
    hard_reject: bool = False
    hard_reject_reason: str = ""
    genres: list[tuple[str, float]] = field(default_factory=list)  # Multi-genre output
    needs_review: bool = False  # True when low-confidence fallback
    clip_embedding: bytes | None = None  # Raw CLIP embedding bytes


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
        from .subject_context import ModelSessions, build_subject_context
        from .sharpness import score_sharpness_detailed
        from .composition import score_composition_detailed
        from .exposure import score_exposure_detailed
        from .genre_router import route_genre
        from .score_fusion import fuse_scores

        t0 = time.perf_counter()

        logger.info("Pipeline start: source=%s", self.config.source_dir)

        paths = ingest_volume(self.config.source_dir, self.config.output_dir, dry_run=self.config.dry_run)

        # Store original filename before any rename so it can be preserved in XMP
        records = [
            PhotoRecord(path=p, metadata={"original_filename": p.name})
            for p in paths
        ]

        records = cluster_sessions(records)
        records, _new_hashes = deduplicate(records)

        # Initialize model sessions for genre-aware scoring
        model_sessions = ModelSessions(self.config.scoring_model_dir)

        for record in records:
            if record.is_duplicate:
                continue

            try:
                # Build subject context (runs all models once)
                ctx = build_subject_context(record.path, model_sessions)

                # Route genre using CLIP + EXIF + YOLO
                genre_result = route_genre(ctx, genre_prototypes=model_sessions.genre_prototypes)

                # Score with detailed sub-scores
                sharpness_result = score_sharpness_detailed(ctx)
                composition_result = score_composition_detailed(ctx)
                exposure_result = score_exposure_detailed(ctx)

                # Get aesthetic score (fallback to 0.5 if not available)
                aesthetic_score = 0.5
                if model_sessions.clip_aesthetic_head is not None:
                    try:
                        input_name = model_sessions.clip_aesthetic_head.get_inputs()[0].name
                        # Use CLIP embedding as input to aesthetic head
                        aesthetic_output = model_sessions.clip_aesthetic_head.run(
                            None, {input_name: np.expand_dims(ctx.clip_embedding, axis=0)}
                        )
                        aesthetic_score = float(aesthetic_output[0][0])
                        aesthetic_score = max(0.0, min(1.0, aesthetic_score))
                    except Exception as e:
                        logger.warning("Aesthetic scoring failed: %s", e)
                        aesthetic_score = 0.5

                # Fuse all scores using genre weighting
                fusion = fuse_scores(
                    sharpness_result,
                    composition_result,
                    exposure_result,
                    genre_result,
                    aesthetic_score,
                )

                # Populate old-style scores for backward compatibility
                record.sharpness_score = sharpness_result.overall
                record.composition_score = composition_result.overall
                record.exposure_score = exposure_result.overall

                # Populate new genre-aware fields
                record.genre = fusion.genre
                record.genre_confidence = fusion.genre_confidence
                record.master_score = fusion.master_score
                record.sub_scores = fusion.sub_scores
                record.hard_reject = fusion.hard_reject
                record.hard_reject_reason = fusion.hard_reject_reason
                record.genres = fusion.genres
                record.needs_review = fusion.needs_review
                record.clip_embedding = ctx.clip_embedding.tobytes() if ctx.clip_embedding is not None else None

                # Semantic name (old path still works)
                record.semantic_name = generate_name(record.path, model_dir=self.config.model_dir)
            except Exception as e:
                logger.error("Scoring failed for %s: %s", record.path, e)
                # Fallback to legacy scoring if genre-aware fails
                record.sharpness_score = score_sharpness(record.path)
                record.composition_score = score_composition(record.path)
                record.exposure_score = score_exposure(record.path)
                record.semantic_name = generate_name(record.path, model_dir=self.config.model_dir)
                record.genre = "general"
                record.genre_confidence = 0.0
                record.master_score = (record.sharpness_score + record.composition_score + record.exposure_score) / 3.0

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
@click.option("--file-type", "file_type", type=click.Choice(["both", "raw", "jpg"]),
              default="both", help="File types to ingest: raw, jpg, or both.")
def ingest(source: Path, dest: Path, dry_run: bool, json_progress: bool, file_type: str) -> None:
    """Copy photos from SD card to destination with cartridge-prefix renaming."""
    from .ingest import ingest_volume
    from .volume import extract_cartridge_id, get_volume_label

    label = get_volume_label(dest)
    cart_id = extract_cartridge_id(label)
    if json_progress:
        click.echo(json.dumps({"step": "ingest", "file": f"label='{label}' cart={cart_id}",
                                "status": "info"}))
    else:
        click.echo(f"Volume label: '{label}', cartridge ID: {cart_id}")

    def _progress(new_name: str, original: str, done: int, total: int) -> None:
        emit("ingest", new_name, "ok", json_progress=json_progress, dest=original)
        if json_progress:
            click.echo(json.dumps({"step": "_progress", "done": done, "total": total}))

    def _scan_progress(done: int, total: int) -> None:
        if json_progress and done % 10 == 0:
            emit("ingest", f"scanning EXIF {done}/{total}", "info", json_progress=True)

    copied = ingest_volume(
        source, dest, dry_run=dry_run, progress_fn=_progress,
        scan_progress_fn=_scan_progress, file_type=file_type,
    )
    if not json_progress:
        verb = "Would copy" if dry_run else "Copied"
        click.echo(f"{verb} {len(copied)} photos to {dest}")


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

    from .photondb import sanitize_table_name

    BATCH_SIZE = 50

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

    table = sanitize_table_name(folder_name)
    all_rows = conn.execute(f"SELECT filename, stages FROM [{table}]").fetchall()
    already_scanned = {row["filename"] for row in all_rows if "scan" in (row["stages"] or "")}
    to_scan = [p for p in photos if p.name not in already_scanned]

    if not to_scan:
        if json_progress:
            click.echo(json.dumps({"step": "_progress", "done": len(photos), "total": len(photos)}))
        else:
            click.echo(f"All {len(photos)} photos already scanned.")
        conn.close()
        return

    if json_progress:
        click.echo(json.dumps({"step": "_progress", "done": 0, "total": len(to_scan)}))

    for i, p in enumerate(to_scan, 1):
        dt_val = read_exif_datetime(p)
        ts = dt_val.isoformat() if dt_val else None
        insert_photo(conn, folder_name, p.name, p.name, ts, auto_commit=False)
        update_stages(conn, folder_name, p.name, "scan", auto_commit=False)
        if i % BATCH_SIZE == 0:
            conn.commit()
        emit("scan", p.name, "ok", json_progress=json_progress)
        if json_progress and i % 10 == 0:
            click.echo(json.dumps({"step": "_progress", "done": i, "total": len(to_scan)}))

    conn.commit()
    conn.close()

    if not json_progress:
        click.echo(f"Scanned {len(to_scan)} new photos ({len(already_scanned)} already scanned) -> {db_path}")
    else:
        click.echo(json.dumps({"step": "_progress", "done": len(to_scan), "total": len(to_scan)}))


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

    from datetime import datetime
    from .grouping import cluster_sessions
    from .dedup import deduplicate
    from .photondb import sanitize_table_name, ensure_table, get_pending, get_dhashes, update_dhash, update_stages, clear_stage

    table = sanitize_table_name(folder)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_table(conn, table)

    if force:
        clear_stage(conn, table, "dedup")

    pending = get_pending(conn, table, "dedup")
    if not pending:
        if json_progress:
            total = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            click.echo(json.dumps({"step": "_progress", "done": total, "total": total}))
        else:
            click.echo("All photos already deduped. Use --force to redo.")
        conn.close()
        return

    all_rows = conn.execute(f"SELECT * FROM [{table}]").fetchall()

    # Build timestamp map from DB to avoid re-reading EXIF from disk
    timestamps: dict[str, datetime] = {}
    for row in all_rows:
        ts = row["exif_timestamp"]
        if ts:
            try:
                timestamps[row["filename"]] = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                pass

    records = []
    for row in all_rows:
        rec = PhotoRecord(path=source_dir / row["filename"])
        rec.session_id = row["session_id"] or ""
        records.append(rec)

    records = cluster_sessions(records, timestamps=timestamps)

    dhash_cache = get_dhashes(conn, table)

    def _progress(done: int, total: int) -> None:
        if json_progress:
            click.echo(json.dumps({"step": "_progress", "done": done, "total": total}))

    _progress(0, len(records))
    records, new_hashes = deduplicate(records, progress_fn=_progress, dhash_cache=dhash_cache)

    for fname, h in new_hashes.items():
        update_dhash(conn, table, fname, h, auto_commit=False)

    for rec in records:
        fname = rec.path.name
        conn.execute(
            f"UPDATE [{table}] SET session_id=?, is_duplicate=? WHERE filename=?",
            (rec.session_id, 1 if rec.is_duplicate else 0, fname),
        )
        update_stages(conn, table, fname, "dedup", auto_commit=False)
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
@click.option("--model-dir", default=None, type=click.Path(path_type=Path),
              help="Scoring model directory (for genre-aware scoring).")
@click.option("--training-db", default=None, type=click.Path(exists=True, path_type=Path),
              help="Optional path to training_weights.db (to use calibrated prototypes).")
@click.option("--resume", is_flag=True, default=False)
@click.option("--force", is_flag=True, default=False)
@click.option("--json-progress", "json_progress", is_flag=True, default=False)
def score(db_path: Path, folder: str, source_dir: Path, model_dir: Path | None, training_db: Path | None, resume: bool, force: bool, json_progress: bool) -> None:
    """Score photos for sharpness, composition, exposure, and genre."""
    import sqlite3

    from .subject_context import ModelSessions, build_subject_context
    from .sharpness import score_sharpness, score_sharpness_detailed
    from .composition import score_composition, score_composition_detailed
    from .exposure import score_exposure, score_exposure_detailed
    from .genre_router import route_genre
    from .score_fusion import fuse_scores
    from .darktable_bridge import compute_color_label
    from .photondb import sanitize_table_name, ensure_table, get_pending, update_scores, update_genre_scores, update_stages, clear_stage

    if model_dir is None:
        model_dir = Path(__file__).resolve().parent.parent.parent / "models"

    table = sanitize_table_name(folder)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_table(conn, table)

    if force:
        clear_stage(conn, table, "score")

    pending = get_pending(conn, table, "score")
    to_score = [r for r in pending if not r["is_duplicate"]]

    if not to_score:
        if json_progress:
            total = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            click.echo(json.dumps({"step": "_progress", "done": total, "total": total}))
        else:
            click.echo("All non-duplicate photos already scored.")
        conn.close()
        return

    # Initialize model sessions for genre-aware scoring
    model_sessions = ModelSessions(model_dir, training_db_path=training_db)

    errors = 0
    for i, row in enumerate(to_score, 1):
        p = source_dir / row["filename"]
        try:
            # Try genre-aware scoring first
            try:
                ctx = build_subject_context(p, model_sessions)
                genre_result = route_genre(ctx, genre_prototypes=model_sessions.genre_prototypes)
                sharpness_result = score_sharpness_detailed(ctx)
                composition_result = score_composition_detailed(ctx)
                exposure_result = score_exposure_detailed(ctx)

                # Aesthetic score
                aesthetic_score = 0.5
                if model_sessions.clip_aesthetic_head is not None:
                    try:
                        input_name = model_sessions.clip_aesthetic_head.get_inputs()[0].name
                        aesthetic_output = model_sessions.clip_aesthetic_head.run(
                            None, {input_name: np.expand_dims(ctx.clip_embedding, axis=0)}
                        )
                        aesthetic_score = float(aesthetic_output[0][0])
                        aesthetic_score = max(0.0, min(1.0, aesthetic_score))
                    except Exception:
                        aesthetic_score = 0.5

                # Fuse scores
                fusion = fuse_scores(
                    sharpness_result,
                    composition_result,
                    exposure_result,
                    genre_result,
                    aesthetic_score,
                )

                sharp = sharpness_result.overall
                comp = composition_result.overall
                expo = exposure_result.overall
                master = fusion.master_score

                update_scores(conn, table, row["filename"], sharp, comp, expo, auto_commit=False)
                clip_embedding_bytes = ctx.clip_embedding.tobytes() if ctx.clip_embedding is not None else None
                update_genre_scores(
                    conn, table, row["filename"],
                    fusion.genre, fusion.genre_confidence, master, fusion.sub_scores,
                    genres=fusion.genres,
                    primary_genre=fusion.genre,
                    needs_review=fusion.needs_review,
                    clip_embedding=clip_embedding_bytes,
                    auto_commit=False,
                )
                update_stages(conn, table, row["filename"], "score", auto_commit=False)
                conn.commit()

                stars = fusion.star_rating
                color_label = fusion.color_label

                if json_progress:
                    # Emit multi-genre data so the Lua applicator can write all tags.
                    # genres = list of {"g": <name>, "c": <confidence>}, top-3 above 0.15 floor.
                    genres_payload = [
                        {"g": g, "c": round(c, 3)} for g, c in fusion.genres
                    ]
                    emit("score", row["filename"], "ok", json_progress=True,
                         sharpness=round(sharp, 4), composition=round(comp, 4),
                         exposure=round(expo, 4), master=round(master, 4),
                         genre=fusion.genre, genre_confidence=round(fusion.genre_confidence, 3),
                         genres=genres_payload, needs_review=fusion.needs_review,
                         stars=stars, color_label=color_label,
                         original_name=row["original_name"])
            except Exception as genre_error:
                # Fallback to legacy scoring
                logger.warning("Genre-aware scoring failed, falling back to legacy: %s", genre_error)
                sharp = score_sharpness(p)
                comp = score_composition(p)
                expo = score_exposure(p)
                update_scores(conn, table, row["filename"], sharp, comp, expo, auto_commit=False)
                update_stages(conn, table, row["filename"], "score", auto_commit=False)
                conn.commit()

                mean = (sharp + comp + expo) / 3.0
                stars = min(5, round(mean * 5))
                color_label = compute_color_label(sharp, comp, expo)

                if json_progress:
                    emit("score", row["filename"], "ok", json_progress=True,
                         sharpness=round(sharp, 4), composition=round(comp, 4),
                         exposure=round(expo, 4), stars=stars, color_label=color_label,
                         genre="general", genre_confidence=0.0,
                         original_name=row["original_name"])
        except Exception as exc:
            conn.execute(
                f"UPDATE [{table}] SET error=? WHERE filename=?",
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
@click.option("--model-dir", default=None, type=click.Path(path_type=Path),
              help="Florence-2 model directory.")
@click.option("--resume", is_flag=True, default=False)
@click.option("--force", is_flag=True, default=False)
@click.option("--json-progress", "json_progress", is_flag=True, default=False)
def name(
    db_path: Path,
    folder: str,
    source_dir: Path,
    model_dir: Path | None,
    resume: bool,
    force: bool,
    json_progress: bool,
) -> None:
    """Generate semantic descriptions via Florence-2 (written to Darktable description, not filename)."""
    if model_dir is None:
        model_dir = Path(__file__).resolve().parent.parent.parent / "models" / "florence2_int8"
    import sqlite3

    from .naming import generate_name
    from .photondb import sanitize_table_name, ensure_table, get_pending, update_semantic, update_stages, clear_stage

    table = sanitize_table_name(folder)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_table(conn, table)

    if force:
        clear_stage(conn, table, "name")

    pending = get_pending(conn, table, "name")
    to_name = [r for r in pending if not r["is_duplicate"]]

    if not to_name:
        if json_progress:
            total = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
            click.echo(json.dumps({"step": "_progress", "done": total, "total": total}))
        else:
            click.echo("All non-duplicate photos already named.")
        conn.close()
        return

    # Pre-warm Florence-2 sessions once before the batch so the first image
    # is not penalised by ONNX JIT compilation (KPM-1.2).
    from .naming import warm_sessions
    warm_sessions(model_dir)

    errors = 0
    for i, row in enumerate(to_name, 1):
        p = source_dir / row["filename"]
        try:
            slug = generate_name(p, model_dir=model_dir)
            update_semantic(conn, table, row["filename"], slug, auto_commit=False)
            update_stages(conn, table, row["filename"], "name", auto_commit=False)
            conn.commit()

            if json_progress:
                emit("name", row["filename"], "ok", json_progress=True, semantic_name=slug)
        except Exception as exc:
            conn.execute(
                f"UPDATE [{table}] SET error=? WHERE filename=?",
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


@cli.command("sync-tags")
@click.option("--db", "photon_db", required=True,
              type=click.Path(exists=True, path_type=Path),
              help="photonforge.db path")
@click.option("--folder", required=True,
              help="Folder/table name in photonforge.db (e.g. TEST_1)")
@click.option("--darktable-library", "dt_library", required=True,
              type=click.Path(path_type=Path),
              help="Darktable library.db path")
@click.option("--json-progress", is_flag=True,
              help="Emit newline-delimited JSON progress lines.")
def sync_tags(photon_db: Path, folder: str, dt_library: Path,
              json_progress: bool) -> None:
    """Push PHOTONForge genre tags from photonforge.db into Darktable's library.db.

    Use this after running the score step from the command line (when the Lua
    applicator was not running).  Reads the genres JSON column and attaches each
    genre as a flat tag in Darktable.
    """
    import sqlite3 as _sqlite3

    from .darktable_bridge import write_darktable_keywords
    from .photondb import sanitize_table_name

    table = sanitize_table_name(folder)
    conn = _sqlite3.connect(str(photon_db))
    conn.row_factory = _sqlite3.Row

    # Verify table exists
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        click.echo(json.dumps({"step": "sync-tags", "status": "error",
                               "message": f"Table '{table}' not found in {photon_db}"}))
        conn.close()
        return

    rows = conn.execute(
        f"SELECT filename, genres FROM [{table}] "
        "WHERE genres IS NOT NULL AND genres != '[]'"
    ).fetchall()
    conn.close()

    total = len(rows)
    done = 0

    if json_progress:
        click.echo(json.dumps({"step": "_progress", "done": 0, "total": total}))

    for row in rows:
        filename: str = row["filename"]
        try:
            genres_list = json.loads(row["genres"])
            keywords = [entry["g"] for entry in genres_list if entry.get("g")]
            if keywords:
                write_darktable_keywords(dt_library, filename, keywords)
            done += 1
            if json_progress:
                click.echo(json.dumps({
                    "step": "sync-tags", "file": filename,
                    "status": "ok", "tags": keywords,
                }))
        except Exception as exc:
            if json_progress:
                click.echo(json.dumps({
                    "step": "sync-tags", "file": filename,
                    "status": "error", "message": str(exc),
                }))

    if json_progress:
        click.echo(json.dumps({"step": "_progress", "done": done, "total": total}))
    else:
        click.echo(f"Synced tags for {done}/{total} photos in '{folder}'.")


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


# --- Training subcommand group -----------------------------------------------

@cli.group()
def training() -> None:
    """Genre prototype calibration and model management."""
    pass


@training.command("recalibrate")
@click.option(
    "--corpus",
    default="corpus/genre_labels.jsonl",
    type=click.Path(path_type=Path),
    help="Path to genre_labels.jsonl (default: corpus/genre_labels.jsonl)",
)
@click.option(
    "--photon-db",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to photonforge.db (to load CLIP embeddings)",
)
@click.option(
    "--training-db",
    required=True,
    type=click.Path(path_type=Path),
    help="Path to training_weights.db (output: where to store recalibrated prototypes)",
)
@click.option(
    "--model-dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Scoring model directory (for hardcoded genre_prototypes.npy). "
    "Defaults to <repo>/models",
)
@click.option(
    "--source-folders",
    multiple=True,
    help="Limit corpus to these source_folder values; default: all",
)
@click.option(
    "--min-samples",
    default=10,
    type=int,
    help="Minimum samples per genre to re-estimate (default: 10)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print per-genre report without writing to database",
)
def recalibrate(
    corpus: Path,
    photon_db: Path,
    training_db: Path,
    model_dir: Path | None,
    source_folders: tuple[str, ...],
    min_samples: int,
    dry_run: bool,
) -> None:
    """Recalibrate genre prototypes by blending hardcoded + user corrections."""
    from .genre_trainer import recalibrate_prototypes
    from .training_weights_db import open_training_db, ensure_schema, next_version, upsert_prototype
    from .genre_router import GENRES

    if model_dir is None:
        model_dir = Path(__file__).resolve().parent.parent.parent / "models"

    # Load hardcoded prototypes
    proto_path = model_dir / "genre_prototypes.npy"
    if not proto_path.exists():
        click.echo(
            f"ERROR: genre_prototypes.npy not found at {proto_path}\n"
            "Please rerun: python -m photo_workflow.provision provision_scoring_models "
            "--only clip --force",
            err=True,
        )
        raise SystemExit(1)

    hardcoded_prototypes = np.load(str(proto_path))

    # Recalibrate
    source_folders_list = list(source_folders) if source_folders else None
    result = recalibrate_prototypes(
        corpus,
        photon_db,
        hardcoded_prototypes,
        source_folders=source_folders_list,
        min_samples=min_samples,
    )

    # Print report
    click.echo("\n=== Genre Calibration Report ===")
    click.echo(f"Hardcoded prototypes: {proto_path}")
    click.echo(f"Corpus: {corpus}")
    click.echo(f"Embeddings DB: {photon_db}")
    if source_folders_list:
        click.echo(f"Filtered to folders: {source_folders_list}")
    click.echo()

    for genre in GENRES:
        if genre not in result:
            click.echo(f"{genre}: SKIPPED (not in result)")
            continue

        info = result[genre]
        source = info["source"]
        n_corrections = info["n_corrections"]
        alpha = info["alpha"]
        proto = info["prototype"]

        # Cosine similarity to hardcoded
        hardcoded_idx = GENRES.index(genre)
        hardcoded = hardcoded_prototypes[hardcoded_idx]
        cosine_sim = float(np.dot(proto, hardcoded))

        click.echo(
            f"{genre:15} | n={n_corrections:3} | alpha={alpha:.3f} | "
            f"source={source:10} | cosine_sim={cosine_sim:.4f}"
        )

    if dry_run:
        click.echo("\n[DRY RUN] No changes written to database.")
        return

    # Write to database
    click.echo(f"\nWriting to {training_db}...")
    conn = open_training_db(training_db)
    ensure_schema(conn)
    version = next_version(conn)

    for genre in GENRES:
        if genre not in result:
            continue
        info = result[genre]
        upsert_prototype(
            conn,
            version,
            genre,
            info["prototype"].astype(np.float32).tobytes(),
            info["n_corrections"],
            info["alpha"],
        )

    conn.close()
    click.echo(f"✓ Wrote {len(GENRES)} prototypes (version {version}) to {training_db}")


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
