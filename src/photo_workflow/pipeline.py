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

# Absolute corpus paths resolved from the package location so they work
# regardless of the working directory (e.g. when launched via Darktable .bat).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CORPUS = str(_REPO_ROOT / "corpus" / "genre_labels.jsonl")
_DEFAULT_SECONDARY_FEEDBACK = str(_REPO_ROOT / "corpus" / "secondary_feedback.jsonl")

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
        from .subject_context import ModelSessions, build_subject_context, _run_clip_aesthetic
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
                genre_result = route_genre(ctx, genre_prototypes=model_sessions.genre_prototypes,
                                          adapter=model_sessions.genre_adapter)

                # Score with detailed sub-scores
                sharpness_result = score_sharpness_detailed(ctx)
                composition_result = score_composition_detailed(ctx)
                exposure_result = score_exposure_detailed(ctx)

                # Aesthetic score from NIMA. None => unavailable, so fusion
                # renormalizes the profile instead of scoring a constant that
                # would silently distort every master score.
                aesthetic_score: float | None = None
                _clip_ok = ctx.clip_embedding is not None and not np.allclose(ctx.clip_embedding, 0.0)
                if model_sessions.aesthetic_head is not None and _clip_ok:
                    try:
                        aesthetic_score = _run_clip_aesthetic(ctx.clip_embedding, model_sessions.aesthetic_head)
                    except Exception as e:
                        logger.warning("Aesthetic scoring failed: %s", e)
                        aesthetic_score = None

                # Fuse all scores using genre weighting
                fusion = fuse_scores(
                    sharpness_result,
                    composition_result,
                    exposure_result,
                    genre_result,
                    aesthetic_score,
                    weight_profiles=model_sessions.aesthetic_weights,
                )

                # Populate old-style scores for backward compatibility
                record.sharpness_score = sharpness_result.overall
                record.composition_score = composition_result.overall
                record.exposure_score = exposure_result.overall

                # Populate genre fields
                record.genre = fusion.subject
                record.genre_confidence = fusion.subject_confidence
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
    all_rows = conn.execute(
        "SELECT filename, stages FROM photos WHERE folder=?", (table,)
    ).fetchall()
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
            total = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE folder=?", (table,)
            ).fetchone()[0]
            click.echo(json.dumps({"step": "_progress", "done": total, "total": total}))
        else:
            click.echo("All photos already deduped. Use --force to redo.")
        conn.close()
        return

    all_rows = conn.execute("SELECT * FROM photos WHERE folder=?", (table,)).fetchall()

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
            "UPDATE photos SET session_id=?, is_duplicate=? WHERE folder=? AND filename=?",
            (rec.session_id, 1 if rec.is_duplicate else 0, table, fname),
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
@click.option("--only-files", "only_files", default=None, type=click.Path(exists=True, path_type=Path),
              help="Text file with one filename per line; only re-score these images.")
@click.option("--skip-genre", "skip_genre", is_flag=True, default=False,
              help="Recalculate ratings only; preserve existing genres from the DB.")
@click.option("--json-progress", "json_progress", is_flag=True, default=False)
def score(db_path: Path, folder: str, source_dir: Path, model_dir: Path | None, training_db: Path | None, resume: bool, force: bool, only_files: Path | None, skip_genre: bool, json_progress: bool) -> None:
    """Score photos for sharpness, composition, exposure, and genre."""
    import sqlite3

    from .subject_context import ModelSessions, build_subject_context, _run_clip_aesthetic
    from .sharpness import score_sharpness, score_sharpness_detailed
    from .composition import score_composition, score_composition_detailed
    from .exposure import score_exposure, score_exposure_detailed
    from .genre_router import route_genre
    from .scoring_types import GenreResult
    from .score_fusion import fuse_scores
    from .darktable_bridge import compute_color_label
    from .score_fusion import absolute_star, hybrid_star, stars_to_color_label, _RATING_ABS_FLOOR
    from .photondb import sanitize_table_name, ensure_table, get_pending, update_scores, update_genre_scores, update_stages, clear_stage

    if model_dir is None:
        model_dir = Path(__file__).resolve().parent.parent.parent / "models"

    table = sanitize_table_name(folder)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_table(conn, table)

    if only_files:
        # Selective rescore: clear score stage only for listed filenames
        target_filenames = set(
            line.strip() for line in only_files.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        for fn in target_filenames:
            row = conn.execute(
                "SELECT filename, stages FROM photos WHERE folder=? AND filename=?", (table, fn)
            ).fetchone()
            if row:
                parts = [s for s in (row["stages"] or "").split(",") if s and s != "score"]
                conn.execute(
                    "UPDATE photos SET stages=? WHERE folder=? AND filename=?",
                    (",".join(parts), table, fn),
                )
        conn.commit()
    elif force:
        clear_stage(conn, table, "score")

    pending = get_pending(conn, table, "score")
    to_score = [r for r in pending if not r["is_duplicate"]]

    if not to_score:
        if json_progress:
            total = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE folder=?", (table,)
            ).fetchone()[0]
            click.echo(json.dumps({"step": "_progress", "done": total, "total": total}))
        else:
            click.echo("All non-duplicate photos already scored.")
        conn.close()
        return

    # Initialize model sessions for genre-aware scoring
    model_sessions = ModelSessions(model_dir, training_db_path=training_db)

    errors = 0
    rated: list[dict] = []  # keepers buffered for the final relative re-rating pass
    for i, row in enumerate(to_score, 1):
        p = source_dir / row["filename"]
        try:
            # Try genre-aware scoring first
            try:
                ctx = build_subject_context(p, model_sessions)
                if skip_genre:
                    # Preserve existing genres from DB; only recalculate ratings
                    db_genres_json = row["genres"] or "{}"
                    try:
                        db_genre_data = json.loads(db_genres_json)
                    except (json.JSONDecodeError, TypeError):
                        db_genre_data = {}
                    genre_result = GenreResult(
                        subject=db_genre_data.get("subject", row.get("primary_genre") or "general"),
                        subject_confidence=db_genre_data.get("subject_confidence", 1.0),
                        photo_type=db_genre_data.get("photo_type", "general"),
                        type_confidence=db_genre_data.get("type_confidence", 0.5),
                        subject_distribution={},
                        type_distribution={},
                        needs_review=bool(row["needs_review"]),
                    )
                else:
                    genre_result = route_genre(ctx, genre_prototypes=model_sessions.genre_prototypes,
                                          adapter=model_sessions.genre_adapter)
                sharpness_result = score_sharpness_detailed(ctx)
                composition_result = score_composition_detailed(ctx)
                exposure_result = score_exposure_detailed(ctx)

                # Aesthetic score from NIMA. None => unavailable (fusion renormalizes).
                aesthetic_score: float | None = None
                _clip_ok = ctx.clip_embedding is not None and not np.allclose(ctx.clip_embedding, 0.0)
                if model_sessions.aesthetic_head is not None and _clip_ok:
                    try:
                        aesthetic_score = _run_clip_aesthetic(ctx.clip_embedding, model_sessions.aesthetic_head)
                    except Exception as e:
                        logger.warning("Aesthetic scoring failed: %s", e)
                        aesthetic_score = None

                # Fuse scores
                fusion = fuse_scores(
                    sharpness_result,
                    composition_result,
                    exposure_result,
                    genre_result,
                    aesthetic_score,
                    weight_profiles=model_sessions.aesthetic_weights,
                )

                sharp = sharpness_result.overall
                comp = composition_result.overall
                expo = exposure_result.overall
                master = fusion.master_score

                update_scores(conn, table, row["filename"], sharp, comp, expo, auto_commit=False)
                clip_embedding_bytes = ctx.clip_embedding.tobytes() if ctx.clip_embedding is not None else None
                genres_data = {
                    "subject": fusion.subject,
                    "subject_confidence": round(fusion.subject_confidence, 4),
                    "photo_type": fusion.photo_type,
                    "type_confidence": round(fusion.type_confidence, 4),
                }
                update_genre_scores(
                    conn, table, row["filename"],
                    fusion.subject, fusion.subject_confidence, master, fusion.sub_scores,
                    genres=genres_data,
                    primary_genre=fusion.subject,
                    needs_review=fusion.needs_review,
                    clip_embedding=clip_embedding_bytes,
                    auto_commit=False,
                )
                update_stages(conn, table, row["filename"], "score", auto_commit=False)
                conn.commit()

                # Stream the rating per image (live feedback + interrupt-safe).
                # Absolute thresholds recalibrated for the min-gate's compressed range.
                stars = absolute_star(master, fusion.hard_reject)
                color_label = stars_to_color_label(stars, fusion.hard_reject)
                if json_progress:
                    emit("score", row["filename"], "ok", json_progress=True,
                         sharpness=round(sharp, 4), composition=round(comp, 4),
                         exposure=round(expo, 4), master=round(master, 4),
                         subject=fusion.subject,
                         subject_confidence=round(fusion.subject_confidence, 3),
                         photo_type=fusion.photo_type,
                         type_confidence=round(fusion.type_confidence, 3),
                         needs_review=fusion.needs_review,
                         stars=stars, color_label=color_label,
                         original_name=row["original_name"])
                # Buffer keepers for the final relative re-rating (provisional
                # absolute stars are shown live; the per-shoot percentile refines
                # the keepers once the whole folder's distribution is known).
                if not fusion.hard_reject and master >= _RATING_ABS_FLOOR:
                    rated.append({
                        "filename": row["filename"], "master": master, "prov": stars,
                        "sharpness": round(sharp, 4), "composition": round(comp, 4),
                        "exposure": round(expo, 4), "subject": fusion.subject,
                        "subject_confidence": round(fusion.subject_confidence, 3),
                        "photo_type": fusion.photo_type,
                        "type_confidence": round(fusion.type_confidence, 3),
                        "needs_review": fusion.needs_review,
                        "original_name": row["original_name"],
                    })
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
                stars = absolute_star(mean, False)
                color_label = stars_to_color_label(stars, False)
                if json_progress:
                    emit("score", row["filename"], "ok", json_progress=True,
                         sharpness=round(sharp, 4), composition=round(comp, 4),
                         exposure=round(expo, 4), stars=stars, color_label=color_label,
                         genre="general", genre_confidence=0.0,
                         original_name=row["original_name"])
        except Exception as exc:
            conn.execute(
                "UPDATE photos SET error=? WHERE folder=? AND filename=?",
                (str(exc), table, row["filename"]),
            )
            conn.commit()
            errors += 1
            if json_progress:
                emit("score", row["filename"], "error", json_progress=True, message=str(exc))

        if json_progress and i % 10 == 0:
            click.echo(json.dumps({"step": "_progress", "done": i, "total": len(to_score)}))

    # --- final relative re-rating (P6) ---------------------------------------
    # Live stars above are absolute/provisional. Now rank each keeper against the
    # WHOLE folder's master distribution and re-emit only those whose star changes
    # (so the applicator does minimal extra work). Floored/rejected frames already
    # got their correct 1 star live, so they are not re-rated.
    if json_progress and rated:
        all_masters = [
            r[0] for r in conn.execute(
                "SELECT master_score FROM photos WHERE folder=? AND master_score IS NOT NULL",
                (table,),
            )
        ]
        kept_sorted = sorted(m for m in all_masters if m >= _RATING_ABS_FLOOR)
        for item in rated:
            stars = hybrid_star(item["master"], False, kept_sorted)
            if stars == item["prov"]:
                continue
            emit("score", item["filename"], "ok", json_progress=True,
                 sharpness=item["sharpness"], composition=item["composition"],
                 exposure=item["exposure"], master=round(item["master"], 4),
                 subject=item["subject"], subject_confidence=item["subject_confidence"],
                 photo_type=item["photo_type"], type_confidence=item["type_confidence"],
                 needs_review=item["needs_review"],
                 stars=stars, color_label=stars_to_color_label(stars, False),
                 original_name=item["original_name"])

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
            total = conn.execute(
                "SELECT COUNT(*) FROM photos WHERE folder=?", (table,)
            ).fetchone()[0]
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
                "UPDATE photos SET error=? WHERE folder=? AND filename=?",
                (str(exc), table, row["filename"]),
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
    rows = conn.execute("SELECT * FROM photos WHERE folder=?", (table,)).fetchall()
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


@cli.command("suggest-training-set")
@click.option("--db", "photon_db", required=True,
              type=click.Path(exists=True, path_type=Path), help="photonforge.db path")
@click.option("--folder", required=True, help="Folder/table name in photonforge.db")
@click.option("--k", type=int, default=20, help="Number of frames to suggest for labeling.")
@click.option("--json-progress", "json_progress", is_flag=True, default=False)
def suggest_training_set(photon_db: Path, folder: str, k: int, json_progress: bool) -> None:
    """Pick the ~k most useful needs_review frames to label (active learning).

    Clusters the needs_review CLIP embeddings and selects one representative per
    cluster (diverse + each represents many similar uncertain frames). Emits
    'train-candidate' records so the Darktable applicator tags the picks
    photon|train_candidate — label just those, then Collect Corrections +
    Recalibrate. Labeling ~k frames improves the model across the whole folder.
    """
    import sqlite3 as _sqlite3

    import numpy as _np
    from .active_learning import select_representatives
    from .photondb import sanitize_table_name

    table = sanitize_table_name(folder)
    conn = _sqlite3.connect(str(photon_db))
    conn.row_factory = _sqlite3.Row
    rows = conn.execute(
        "SELECT filename, original_name, clip_embedding FROM photos "
        "WHERE folder=? AND needs_review=1 AND clip_embedding IS NOT NULL", (table,),
    ).fetchall()
    conn.close()

    if not rows:
        click.echo(json.dumps({"step": "suggest-training-set", "status": "error",
                               "message": f"no needs_review frames with embeddings in '{table}'"}))
        return

    X = _np.vstack([_np.frombuffer(r["clip_embedding"], dtype=_np.float32) for r in rows])
    reps = select_representatives(X, k)

    total = len(reps)
    if json_progress:
        click.echo(json.dumps({"step": "_progress", "done": 0, "total": total}))
    for i, (idx, csize) in enumerate(reps, 1):
        r = rows[idx]
        emit("train-candidate", r["filename"], "ok", json_progress=json_progress,
             cluster_size=csize, original_name=r["original_name"])
    if json_progress:
        click.echo(json.dumps({"step": "_progress", "done": total, "total": total}))
    else:
        click.echo(f"suggest-training-set: tagged {total} candidates from "
                   f"{len(rows)} needs_review frames in '{table}'.")


@cli.command("refresh-review")
@click.option("--db", "photon_db", required=True,
              type=click.Path(exists=True, path_type=Path), help="photonforge.db path")
@click.option("--folder", required=True, help="Folder/table name in photonforge.db")
@click.option("--model-dir", default=None, type=click.Path(path_type=Path),
              help="Scoring model directory (for the genre adapter).")
@click.option("--training-db", default=None, type=click.Path(exists=True, path_type=Path),
              help="Optional path to training_weights.db.")
@click.option("--json-progress", "json_progress", is_flag=True, default=False)
def refresh_review(photon_db: Path, folder: str, model_dir: Path | None,
                   training_db: Path | None, json_progress: bool) -> None:
    """Recompute needs_review from cached CLIP embeddings (no image re-decode).

    Re-runs only the (cheap) genre classifier on each scored frame's stored
    embedding to recompute the margin-based needs_review flag, updates the DB, and
    re-emits score records (preserving the existing genre + rating) so the
    Darktable applicator detaches stale photon|needs_review tags. Use this after a
    needs_review-logic change instead of a full re-score.
    """
    import sqlite3 as _sqlite3

    import numpy as _np
    from .subject_context import ModelSessions
    from .genre_adapter import predict_axis
    from .genre_router import SUBJECTS, PHOTO_TYPES, _top2_margin, _REVIEW_MARGIN
    from .photondb import sanitize_table_name

    if model_dir is None:
        model_dir = Path(__file__).resolve().parent.parent.parent / "models"
    table = sanitize_table_name(folder)
    adapter = ModelSessions(model_dir, training_db_path=training_db).genre_adapter
    if not adapter or not adapter.get("subject") or not adapter.get("type"):
        click.echo(json.dumps({"step": "refresh-review", "status": "error",
                               "message": "no genre adapter available"}))
        return

    conn = _sqlite3.connect(str(photon_db))
    conn.row_factory = _sqlite3.Row
    rows = conn.execute(
        "SELECT filename, original_name, genres, clip_embedding FROM photos "
        "WHERE folder=? AND is_duplicate=0 AND stages LIKE '%score%' "
        "AND clip_embedding IS NOT NULL", (table,),
    ).fetchall()

    total = len(rows)
    if json_progress:
        click.echo(json.dumps({"step": "_progress", "done": 0, "total": total}))
    changed = 0
    for i, row in enumerate(rows, 1):
        emb = _np.frombuffer(row["clip_embedding"], dtype=_np.float32)
        if emb.size == 0 or _np.allclose(emb, 0.0):
            continue
        subj_dist = predict_axis(emb, adapter["subject"], SUBJECTS)
        type_dist = predict_axis(emb, adapter["type"], PHOTO_TYPES)
        needs_review = (_top2_margin(subj_dist) < _REVIEW_MARGIN
                        or _top2_margin(type_dist) < _REVIEW_MARGIN)
        conn.execute("UPDATE photos SET needs_review=? WHERE folder=? AND filename=?",
                     (1 if needs_review else 0, table, row["filename"]))
        try:
            g = json.loads(row["genres"]) if row["genres"] else {}
        except (json.JSONDecodeError, TypeError):
            g = {}
        if json_progress:
            # No `stars` => applicator leaves the rating untouched; it detaches
            # stale needs_review and re-attaches subject/type + needs_review-if-true.
            emit("score", row["filename"], "ok", json_progress=True,
                 subject=g.get("subject", ""), photo_type=g.get("photo_type", ""),
                 needs_review=needs_review, original_name=row["original_name"])
        changed += 1
        if json_progress and i % 50 == 0:
            click.echo(json.dumps({"step": "_progress", "done": i, "total": total}))
    conn.commit()
    conn.close()
    if json_progress:
        click.echo(json.dumps({"step": "_progress", "done": total, "total": total}))
    else:
        click.echo(f"refresh-review: recomputed needs_review for {changed}/{total} frames.")


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
    applicator was not running).  Reads the genres JSON column and writes
    hierarchical tags: photon|subject|<name> and photon|type|<name>.
    """
    import sqlite3 as _sqlite3

    from .darktable_bridge import clear_photon_tags, write_darktable_keywords, purge_orphan_photon_tags
    from .photondb import sanitize_table_name

    table = sanitize_table_name(folder)
    conn = _sqlite3.connect(str(photon_db))
    conn.row_factory = _sqlite3.Row

    exists = conn.execute(
        "SELECT 1 FROM photos WHERE folder=? LIMIT 1", (table,)
    ).fetchone()
    if not exists:
        click.echo(json.dumps({"step": "sync-tags", "status": "error",
                               "message": f"Table '{table}' not found in {photon_db}"}))
        conn.close()
        return

    rows = conn.execute(
        "SELECT filename, genres FROM photos WHERE folder=? "
        "AND genres IS NOT NULL AND genres != '{}' AND genres != ''", (table,)
    ).fetchall()
    conn.close()

    total = len(rows)
    done = 0

    if json_progress:
        click.echo(json.dumps({"step": "_progress", "done": 0, "total": total}))

    for row in rows:
        filename: str = row["filename"]
        try:
            genre_data = json.loads(row["genres"])
            subject = genre_data.get("subject")
            photo_type = genre_data.get("photo_type")

            if json_progress:
                # Emit JSON for Lua applicator to apply via DT API
                click.echo(json.dumps({
                    "step": "sync-tags", "file": filename,
                    "status": "ok",
                    "subject": subject or "",
                    "photo_type": photo_type or "",
                }))
            else:
                # CLI mode: write directly to SQLite (DT must be closed)
                keywords = []
                if subject:
                    keywords.append("photon|subject|" + subject)
                if photo_type:
                    keywords.append("photon|type|" + photo_type)
                if keywords:
                    clear_photon_tags(dt_library, filename)
                    write_darktable_keywords(dt_library, filename, keywords)
            done += 1
        except Exception as exc:
            if json_progress:
                click.echo(json.dumps({
                    "step": "sync-tags", "file": filename,
                    "status": "error", "message": str(exc),
                }))

    if json_progress:
        click.echo(json.dumps({"step": "_progress", "done": done, "total": total}))
    else:
        # Garbage-collect deprecated/renamed photon tag definitions left empty by
        # re-scores (clear_photon_tags only drops associations, not the tags).
        purged = purge_orphan_photon_tags(dt_library)
        click.echo(f"Synced tags for {done}/{total} photos in '{folder}'."
                   + (f" Purged {purged} orphaned photon tags." if purged else ""))


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
    default=_DEFAULT_CORPUS,
    type=click.Path(path_type=Path),
    help="Path to genre_labels.jsonl",
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
    "--secondary-feedback",
    "secondary_feedback",
    default=_DEFAULT_SECONDARY_FEEDBACK,
    type=click.Path(path_type=Path),
    help="Path to secondary_feedback.jsonl (user-confirmed secondary genres "
    "used to augment prototype centroids)",
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
    secondary_feedback: Path,
    dry_run: bool,
) -> None:
    """Recalibrate genre prototypes by blending hardcoded + user corrections."""
    from .genre_trainer import recalibrate_prototypes
    from .training_weights_db import open_training_db, ensure_schema, next_version, upsert_prototype
    from .genre_router import SUBJECTS, PHOTO_TYPES, ALL_LABELS

    if model_dir is None:
        model_dir = Path(__file__).resolve().parent.parent.parent / "models"

    proto_path = model_dir / "genre_prototypes.npy"
    if not proto_path.exists():
        click.echo(
            f"ERROR: genre_prototypes.npy not found at {proto_path}\n"
            "Please rerun: python scripts/provision_scoring_models.py --only clip --force",
            err=True,
        )
        raise SystemExit(1)

    hardcoded_prototypes = np.load(str(proto_path))

    source_folders_list = list(source_folders) if source_folders else None
    sf_path = secondary_feedback if secondary_feedback.exists() else None

    result = recalibrate_prototypes(
        corpus,
        photon_db,
        hardcoded_prototypes,
        source_folders=source_folders_list,
        min_samples=min_samples,
        secondary_feedback_path=sf_path,
    )

    click.echo("\n=== Genre Calibration Report ===")
    click.echo(f"Hardcoded prototypes: {proto_path}")
    click.echo(f"Corpus: {corpus}")
    click.echo(f"Embeddings DB: {photon_db}")
    if sf_path:
        click.echo(f"Secondary feedback: {sf_path}")
    if source_folders_list:
        click.echo(f"Filtered to folders: {source_folders_list}")
    click.echo()

    click.echo("--- Subjects ---")
    for i, label in enumerate(SUBJECTS):
        if label not in result:
            click.echo(f"  {label}: SKIPPED")
            continue
        info = result[label]
        cosine_sim = float(np.dot(info["prototype"], hardcoded_prototypes[i]))
        click.echo(
            f"  {label:15} | n={info['n_corrections']:3} | alpha={info['alpha']:.3f} | "
            f"source={info['source']:10} | cosine_sim={cosine_sim:.4f}"
        )

    click.echo("\n--- Photo Types ---")
    n_subj = len(SUBJECTS)
    for i, label in enumerate(PHOTO_TYPES):
        if label not in result:
            click.echo(f"  {label}: SKIPPED")
            continue
        info = result[label]
        cosine_sim = float(np.dot(info["prototype"], hardcoded_prototypes[n_subj + i]))
        click.echo(
            f"  {label:15} | n={info['n_corrections']:3} | alpha={info['alpha']:.3f} | "
            f"source={info['source']:10} | cosine_sim={cosine_sim:.4f}"
        )

    if dry_run:
        click.echo("\n[DRY RUN] No changes written to database.")
        return

    click.echo(f"\nWriting to {training_db}...")
    conn = open_training_db(training_db)
    ensure_schema(conn)
    version = next_version(conn)

    for label in ALL_LABELS:
        if label not in result:
            continue
        info = result[label]
        upsert_prototype(
            conn,
            version,
            label,
            info["prototype"].astype(np.float32).tobytes(),
            info["n_corrections"],
            info["alpha"],
        )

    conn.close()
    click.echo(f"OK: Wrote {len(ALL_LABELS)} prototypes (version {version}) to {training_db}")


@training.command("train-adapter")
@click.option("--corpus", default=_DEFAULT_CORPUS, type=click.Path(path_type=Path),
              help="Path to genre_labels.jsonl")
@click.option("--photon-db", "photon_db", required=True,
              type=click.Path(exists=True, path_type=Path),
              help="Path to photonforge.db (to load CLIP embeddings)")
@click.option("--training-db", "training_db", required=True, type=click.Path(path_type=Path),
              help="Path to training_weights.db (output)")
@click.option("--cv-folds", default=5, type=int, help="Cross-validation folds for the accuracy report")
def train_adapter(corpus: Path, photon_db: Path, training_db: Path, cv_folds: int) -> None:
    """Train the learned linear genre classifier (subject + type) on the corpus."""
    import json as _json
    import sqlite3 as _sql

    from .genre_adapter import train_linear_adapter
    from .training_weights_db import (
        open_training_db, ensure_schema, next_version, upsert_linear_adapter,
    )

    labels: dict[str, tuple[str, str]] = {}
    for line in open(corpus, encoding="utf-8"):
        line = line.strip()
        if line:
            r = _json.loads(line)
            labels[r["filename"]] = (r["subject"], r["photo_type"])

    pc = _sql.connect(str(photon_db))
    emb: dict[str, np.ndarray] = {}
    # Embeddings live in photos.clip_embedding (analysis rows) and the embeddings
    # cache (training corpora: CURATED/WEB). Read both.
    for q in (
        "SELECT filename, clip_embedding FROM photos WHERE clip_embedding IS NOT NULL",
        "SELECT filename, clip_embedding FROM embeddings WHERE clip_embedding IS NOT NULL",
    ):
        try:
            cur = pc.execute(q)
        except _sql.OperationalError:
            continue
        for fn, blob in cur:
            if fn in labels and fn not in emb:
                emb[fn] = np.frombuffer(blob, dtype=np.float32)
    pc.close()

    names = [fn for fn in labels if fn in emb]
    if not names:
        click.echo("ERROR: no labeled images with CLIP embeddings found", err=True)
        raise SystemExit(1)
    X = np.vstack([emb[fn] for fn in names])
    ys = np.array([labels[fn][0] for fn in names])
    yt = np.array([labels[fn][1] for fn in names])

    click.echo(f"Training linear adapter on {len(names)} labeled embeddings...")
    heads = train_linear_adapter(X, ys, yt, cv_folds=cv_folds)

    conn = open_training_db(training_db)
    ensure_schema(conn)
    version = next_version(conn)
    for axis, h in heads.items():
        upsert_linear_adapter(conn, version, axis, h["classes"], h["weight"], h["bias"],
                              h["n_samples"], h["cv_accuracy"])
    conn.close()
    click.echo(f"OK: trained adapter (version {version}) -> {training_db}")
    for axis, h in heads.items():
        click.echo(f"  {axis:7}: {len(h['classes'])} classes, {h['n_samples']} samples, "
                   f"CV accuracy {h['cv_accuracy']:.3f}")


@training.command("bootstrap-aesthetic-weights")
@click.option("--training-db", "training_db", required=True, type=click.Path(path_type=Path),
              help="Path to training_weights.db (output)")
@click.option("--from-active", is_flag=True,
              help="Seed from the currently active DB profiles instead of the code defaults")
def bootstrap_aesthetic_weights(training_db: Path, from_active: bool) -> None:
    """Seed the aesthetic_weights table from the hardcoded score_fusion defaults.

    This is the one-time bootstrap that moves the per-genre weight profiles out of
    code and into the (tunable, versioned) DB. Re-running creates a new version.
    """
    from .score_fusion import bootstrap_weight_profiles
    from .training_weights_db import (
        open_training_db, ensure_schema, next_aesthetic_weights_version,
        upsert_aesthetic_weights, get_active_aesthetic_weights,
    )

    conn = open_training_db(training_db)
    ensure_schema(conn)
    if from_active:
        profiles = get_active_aesthetic_weights(conn)
        if not profiles:
            click.echo("ERROR: no active aesthetic weights to seed from", err=True)
            raise SystemExit(1)
    else:
        profiles = bootstrap_weight_profiles()

    version = next_aesthetic_weights_version(conn)
    n = 0
    for axis, by_label in profiles.items():
        for label, weights in by_label.items():
            upsert_aesthetic_weights(conn, version, axis, label, weights)
            n += 1
    conn.close()
    click.echo(f"OK: wrote {n} aesthetic weight profiles (version {version}) -> {training_db}")


@training.command("collect-corrections")
@click.option("--folder", required=True,
              help="Folder/table name in photonforge.db (e.g. TEST_1)")
@click.option("--photon-db", "photon_db", required=True,
              type=click.Path(exists=True, path_type=Path),
              help="Path to photonforge.db")
@click.option("--darktable-library", "dt_library", required=True,
              type=click.Path(path_type=Path),
              help="Path to Darktable library.db")
@click.option("--corpus", default=_DEFAULT_CORPUS,
              type=click.Path(path_type=Path), show_default=True,
              help="Corpus JSONL file — primary corrections appended here")
@click.option("--secondary-feedback", "secondary_feedback",
              default=_DEFAULT_SECONDARY_FEEDBACK,
              type=click.Path(path_type=Path), show_default=True,
              help="Secondary feedback JSONL — secondary tag add/remove events appended here")
@click.option("--dry-run", is_flag=True,
              help="Report corrections without writing to corpus")
@click.option("--json-progress", is_flag=True,
              help="Emit newline-delimited JSON progress lines")
def collect_corrections(
    folder: str,
    photon_db: Path,
    dt_library: Path,
    corpus: Path,
    secondary_feedback: Path,
    dry_run: bool,
    json_progress: bool,
) -> None:
    """Detect tag corrections made in Darktable and feed them to the training corpus.

    Reads photon|subject|<name> and photon|type|<name> tags from Darktable
    and compares them against what photonforge.db recorded.

    Subject corrections are appended to the corpus JSONL and improve CLIP
    prototypes on the next 'training recalibrate' run.
    Type feedback is logged to a separate JSONL for future calibration.
    """
    import getpass
    import sqlite3 as _sqlite3
    from datetime import datetime, timezone

    from .darktable_bridge import read_darktable_keywords
    from .genre_router import SUBJECTS, PHOTO_TYPES
    from .photondb import sanitize_table_name

    _SUBJECT_PREFIX = "photon|subject|"
    _TYPE_PREFIX = "photon|type|"

    subjects_set = set(SUBJECTS)
    types_set = set(PHOTO_TYPES)

    table = sanitize_table_name(folder)
    conn = _sqlite3.connect(str(photon_db))
    conn.row_factory = _sqlite3.Row

    exists = conn.execute(
        "SELECT 1 FROM photos WHERE folder=? LIMIT 1", (table,)
    ).fetchone()
    if not exists:
        click.echo(json.dumps({
            "step": "collect-corrections", "status": "error",
            "message": f"Table '{table}' not found in {photon_db}",
        }))
        conn.close()
        return

    rows = conn.execute(
        "SELECT filename, primary_genre, genres FROM photos WHERE folder=? "
        "AND primary_genre IS NOT NULL", (table,)
    ).fetchall()
    conn.close()

    total = len(rows)
    done = 0
    labeler = getpass.getuser() or "anon"
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    corpus_entries: list[dict] = []
    type_entries: list[dict] = []

    if json_progress:
        click.echo(json.dumps({"step": "_progress", "done": 0, "total": total}))

    for row in rows:
        filename: str = row["filename"]
        try:
            db_genre_data = json.loads(row["genres"] or "{}")
        except Exception:
            db_genre_data = {}

        db_subject = db_genre_data.get("subject", row["primary_genre"] or "general")
        db_type = db_genre_data.get("photo_type", "general")

        dt_tags = read_darktable_keywords(dt_library, filename)

        dt_subjects = [
            t[len(_SUBJECT_PREFIX):]
            for t in dt_tags if t.startswith(_SUBJECT_PREFIX)
        ]
        dt_types = [
            t[len(_TYPE_PREFIX):]
            for t in dt_tags if t.startswith(_TYPE_PREFIX)
        ]

        if not dt_subjects:
            done += 1
            if json_progress:
                click.echo(json.dumps({"step": "_progress", "done": done, "total": total}))
            continue

        dt_subject = dt_subjects[0] if dt_subjects[0] in subjects_set else None
        dt_type = dt_types[0] if dt_types and dt_types[0] in types_set else None

        # --- Subject correction -----------------------------------------------
        if dt_subject and dt_subject != db_subject:
            corpus_entries.append({
                "filename": filename,
                "subject": dt_subject,
                "source_folder": folder,
                "needs_review": False,
                "labeled_at": now_iso,
                "labeler": labeler,
                "correction_of": db_subject,
            })
            if json_progress:
                click.echo(json.dumps({
                    "step": "collect-corrections", "file": filename,
                    "status": "subject-correction",
                    "was": db_subject, "correction": dt_subject,
                }))

        # --- Type correction --------------------------------------------------
        if dt_type and dt_type != db_type:
            type_entries.append({
                "filename": filename,
                "photo_type": dt_type,
                "source_folder": folder,
                "db_type": db_type,
                "collected_at": now_iso,
                "labeler": labeler,
            })
            if json_progress:
                click.echo(json.dumps({
                    "step": "collect-corrections", "file": filename,
                    "status": "type-correction",
                    "was": db_type, "correction": dt_type,
                }))

        done += 1
        if json_progress:
            click.echo(json.dumps({"step": "_progress", "done": done, "total": total}))

    # --- Write results --------------------------------------------------------
    if not dry_run:
        if corpus_entries:
            corpus.parent.mkdir(parents=True, exist_ok=True)
            with corpus.open("a", encoding="utf-8") as f:
                for entry in corpus_entries:
                    f.write(json.dumps(entry) + "\n")

        if type_entries:
            secondary_feedback.parent.mkdir(parents=True, exist_ok=True)
            with secondary_feedback.open("a", encoding="utf-8") as f:
                for entry in type_entries:
                    f.write(json.dumps(entry) + "\n")

        # Update photonforge.db so genres reflect the user's corrections.
        update_conn = _sqlite3.connect(str(photon_db))
        corrected_filenames: list[str] = []
        for entry in corpus_entries:
            fn = entry["filename"]
            corrected_subject = entry["subject"]
            row = update_conn.execute(
                "SELECT genres FROM photos WHERE folder=? AND filename=?", (table, fn)
            ).fetchone()
            try:
                old_data = json.loads(row[0]) if row and row[0] else {}
            except Exception:
                old_data = {}
            old_data["subject"] = corrected_subject
            old_data["subject_confidence"] = 1.0
            # Check if we also have a type correction for this file
            for te in type_entries:
                if te["filename"] == fn:
                    old_data["photo_type"] = te["photo_type"]
                    old_data["type_confidence"] = 1.0
                    break
            update_conn.execute(
                "UPDATE photos SET primary_genre=?, genres=? WHERE folder=? AND filename=?",
                (corrected_subject, json.dumps(old_data), table, fn),
            )
            corrected_filenames.append(fn)
        # Type-only corrections (no subject change)
        for entry in type_entries:
            fn = entry["filename"]
            if fn in {e["filename"] for e in corpus_entries}:
                continue
            row = update_conn.execute(
                "SELECT genres FROM photos WHERE folder=? AND filename=?", (table, fn)
            ).fetchone()
            try:
                old_data = json.loads(row[0]) if row and row[0] else {}
            except Exception:
                old_data = {}
            old_data["photo_type"] = entry["photo_type"]
            old_data["type_confidence"] = 1.0
            update_conn.execute(
                "UPDATE photos SET genres=? WHERE folder=? AND filename=?",
                (json.dumps(old_data), table, fn),
            )
            corrected_filenames.append(fn)
        update_conn.commit()
        update_conn.close()

        manifest = _get_temp_dir() / "photonforge_corrected_files.txt"
        manifest.write_text("\n".join(corrected_filenames), encoding="utf-8")

    if not json_progress:
        dry_label = " [DRY RUN]" if dry_run else ""
        click.echo(f"Checked {total} images{dry_label}")
        click.echo(f"  Subject corrections:  {len(corpus_entries):3d}  -> {corpus}")
        click.echo(f"  Type corrections:     {len(type_entries):3d}  -> {secondary_feedback}")
        if corpus_entries:
            click.echo("\nSubject corrections:")
            for e in corpus_entries:
                click.echo(f"  {e['filename']:40s}  {e['correction_of']:12s} -> {e['subject']}")
    else:
        click.echo(json.dumps({
            "step": "collect-corrections",
            "status": "summary",
            "subject_corrections": len(corpus_entries),
            "type_corrections": len(type_entries),
            "dry_run": dry_run,
        }))


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
