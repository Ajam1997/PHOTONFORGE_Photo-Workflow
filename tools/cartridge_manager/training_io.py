"""Training weights DB import/export/merge for 2-axis genre detection."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Import current genre labels for cross-referencing calibration health
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
try:
    from photo_workflow.genre_router import SUBJECTS, PHOTO_TYPES, ALL_LABELS
except ImportError:
    SUBJECTS = []
    PHOTO_TYPES = []
    ALL_LABELS = []


_TRAINING_TABLES = [
    "genre_prototypes",
    "genre_corrections",
    "genre_adapter",
    "custom_genres",
]


@dataclass
class TrainingDBStats:
    n_prototypes: int = 0
    n_active_prototypes: int = 0
    max_version: int = 0
    n_corrections: int = 0
    n_adapters: int = 0
    n_custom_genres: int = 0
    custom_genre_names: list[str] = field(default_factory=list)
    source_cartridge: str = ""


@dataclass
class ImportPreview:
    new_corrections: int = 0
    conflicting_prototypes: int = 0
    new_custom_genres: list[str] = field(default_factory=list)
    bundle_stats: TrainingDBStats | None = None
    local_stats: TrainingDBStats | None = None


def _get_stats(conn: sqlite3.Connection) -> TrainingDBStats:
    stats = TrainingDBStats()
    _db_errors = (sqlite3.OperationalError, sqlite3.DatabaseError)
    try:
        stats.n_prototypes = conn.execute(
            "SELECT COUNT(*) as c FROM genre_prototypes"
        ).fetchone()[0]
        stats.n_active_prototypes = conn.execute(
            "SELECT COUNT(*) as c FROM genre_prototypes WHERE is_active=1"
        ).fetchone()[0]
        row = conn.execute(
            "SELECT MAX(version) as v FROM genre_prototypes"
        ).fetchone()
        stats.max_version = row[0] if row[0] is not None else 0
    except _db_errors:
        pass

    try:
        stats.n_corrections = conn.execute(
            "SELECT COUNT(*) as c FROM genre_corrections"
        ).fetchone()[0]
    except _db_errors:
        pass

    try:
        stats.n_adapters = conn.execute(
            "SELECT COUNT(*) as c FROM genre_adapter"
        ).fetchone()[0]
    except _db_errors:
        pass

    try:
        rows = conn.execute("SELECT name FROM custom_genres ORDER BY name").fetchall()
        stats.custom_genre_names = [r[0] for r in rows]
        stats.n_custom_genres = len(stats.custom_genre_names)
    except _db_errors:
        pass

    return stats


def get_local_stats(db_path: Path) -> TrainingDBStats:
    if not db_path.exists():
        return TrainingDBStats()
    conn = sqlite3.connect(str(db_path))
    try:
        return _get_stats(conn)
    finally:
        conn.close()


# -- Export --


def export_training_bundle(
    db_path: Path,
    out_path: Path,
    source_cartridge: str = "",
) -> Path:
    """Export a full training bundle as a .photon-training ZIP.

    Contains the full SQLite DB, a manifest, and checksums.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Training DB not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    stats = _get_stats(conn)
    stats.source_cartridge = source_cartridge
    conn.close()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_copy = tmp_path / "training_weights.db"
        shutil.copy2(str(db_path), str(db_copy))

        sha = hashlib.sha256(db_copy.read_bytes()).hexdigest()
        (tmp_path / "checksums.sha256").write_text(
            f"{sha}  training_weights.db\n", encoding="utf-8"
        )

        manifest = {
            "format_version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source_cartridge": source_cartridge,
            "prototype_version": stats.max_version,
            "n_active_prototypes": stats.n_active_prototypes,
            "n_corrections": stats.n_corrections,
            "n_adapters": stats.n_adapters,
            "custom_genres": stats.custom_genre_names,
        }
        (tmp_path / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        if not out_path.suffix:
            out_path = out_path.with_suffix(".photon-training")

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_copy, "training_weights.db")
            zf.write(tmp_path / "manifest.json", "manifest.json")
            zf.write(tmp_path / "checksums.sha256", "checksums.sha256")

    return out_path


def export_corrections_only(
    db_path: Path,
    out_path: Path,
    source_cartridge: str = "",
) -> Path:
    """Export only corrections and custom genres (no ONNX blobs)."""
    if not db_path.exists():
        raise FileNotFoundError(f"Training DB not found: {db_path}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        lite_db = tmp_path / "training_weights.db"

        src_conn = sqlite3.connect(str(db_path))
        dst_conn = sqlite3.connect(str(lite_db))

        dst_conn.executescript("""
            CREATE TABLE IF NOT EXISTS genre_corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_path TEXT NOT NULL,
                clip_embedding BLOB NOT NULL,
                aux_features BLOB,
                original_genres TEXT NOT NULL,
                corrected_genres TEXT NOT NULL,
                correction_source TEXT DEFAULT 'darktable',
                corrected_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS custom_genres (
                name TEXT PRIMARY KEY,
                first_seen_at TEXT DEFAULT (datetime('now')),
                n_examples INTEGER DEFAULT 0,
                promoted INTEGER DEFAULT 0
            );
        """)

        for row in src_conn.execute("SELECT * FROM genre_corrections").fetchall():
            dst_conn.execute(
                "INSERT INTO genre_corrections "
                "(image_path, clip_embedding, aux_features, original_genres, "
                "corrected_genres, correction_source, corrected_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    row[1], row[2], row[3], row[4],
                    row[5], row[6], row[7],
                ),
            )

        for row in src_conn.execute("SELECT * FROM custom_genres").fetchall():
            dst_conn.execute(
                "INSERT OR IGNORE INTO custom_genres "
                "(name, first_seen_at, n_examples, promoted) "
                "VALUES (?, ?, ?, ?)",
                (row[0], row[1], row[2], row[3]),
            )

        dst_conn.commit()

        stats = _get_stats(src_conn)
        src_conn.close()
        dst_conn.close()

        sha = hashlib.sha256(lite_db.read_bytes()).hexdigest()
        (tmp_path / "checksums.sha256").write_text(
            f"{sha}  training_weights.db\n", encoding="utf-8"
        )

        manifest = {
            "format_version": 1,
            "type": "corrections_only",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source_cartridge": source_cartridge,
            "n_corrections": stats.n_corrections,
            "custom_genres": stats.custom_genre_names,
        }
        (tmp_path / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        if not out_path.suffix:
            out_path = out_path.with_suffix(".photon-training")

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(lite_db, "training_weights.db")
            zf.write(tmp_path / "manifest.json", "manifest.json")
            zf.write(tmp_path / "checksums.sha256", "checksums.sha256")

    return out_path


# -- Import --


def _extract_bundle(bundle_path: Path) -> tuple[Path, dict, Path]:
    """Extract a bundle to a temp dir. Returns (tmp_dir, manifest, db_path).

    Caller must clean up the temp dir.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="photon_import_"))
    with zipfile.ZipFile(bundle_path, "r") as zf:
        zf.extractall(tmp_dir)

    manifest_path = tmp_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    db_path = tmp_dir / "training_weights.db"
    checksum_path = tmp_dir / "checksums.sha256"
    if checksum_path.exists():
        expected = checksum_path.read_text(encoding="utf-8").split()[0]
        actual = hashlib.sha256(db_path.read_bytes()).hexdigest()
        if expected != actual:
            raise ValueError("Bundle checksum mismatch — file may be corrupted")

    return tmp_dir, manifest, db_path


def preview_import(bundle_path: Path, local_db_path: Path) -> ImportPreview:
    """Dry-run import: return a diff summary without modifying anything."""
    tmp_dir, manifest, bundle_db_path = _extract_bundle(bundle_path)

    try:
        bundle_conn = sqlite3.connect(str(bundle_db_path))
        bundle_stats = _get_stats(bundle_conn)

        local_stats = TrainingDBStats()
        if local_db_path.exists():
            local_conn = sqlite3.connect(str(local_db_path))
            local_stats = _get_stats(local_conn)

            local_paths = {
                r[0]
                for r in local_conn.execute(
                    "SELECT image_path FROM genre_corrections"
                ).fetchall()
            }
            bundle_paths = {
                r[0]
                for r in bundle_conn.execute(
                    "SELECT image_path FROM genre_corrections"
                ).fetchall()
            }
            new_corrections = len(bundle_paths - local_paths)

            local_genres = set(local_stats.custom_genre_names)
            new_genres = [
                g for g in bundle_stats.custom_genre_names if g not in local_genres
            ]

            conflicting = 0
            try:
                local_active = {
                    r[0]
                    for r in local_conn.execute(
                        "SELECT genre FROM genre_prototypes WHERE is_active=1"
                    ).fetchall()
                }
                bundle_active = {
                    r[0]
                    for r in bundle_conn.execute(
                        "SELECT genre FROM genre_prototypes WHERE is_active=1"
                    ).fetchall()
                }
                conflicting = len(local_active & bundle_active)
            except sqlite3.OperationalError:
                pass

            local_conn.close()
        else:
            new_corrections = bundle_stats.n_corrections
            new_genres = bundle_stats.custom_genre_names
            conflicting = 0

        bundle_conn.close()

        return ImportPreview(
            new_corrections=new_corrections,
            conflicting_prototypes=conflicting,
            new_custom_genres=new_genres,
            bundle_stats=bundle_stats,
            local_stats=local_stats,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def import_training_bundle(
    bundle_path: Path,
    local_db_path: Path,
    strategy: str = "merge_corrections",
) -> TrainingDBStats:
    """Import a training bundle into the local DB.

    Strategies:
        replace          — wipe local tables, load bundle wholesale
        merge_corrections — append new corrections, keep local prototypes
        merge_all         — merge corrections + higher-version prototypes + union custom genres
    """
    tmp_dir, manifest, bundle_db_path = _extract_bundle(bundle_path)

    try:
        if strategy == "replace":
            return _import_replace(bundle_db_path, local_db_path)
        elif strategy == "merge_corrections":
            return _import_merge_corrections(bundle_db_path, local_db_path)
        elif strategy == "merge_all":
            return _import_merge_all(bundle_db_path, local_db_path)
        else:
            raise ValueError(f"Unknown import strategy: {strategy}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# -- Corpus JSONL merge --


@dataclass
class CorpusMergeResult:
    base_count: int = 0
    new_count: int = 0
    merged_count: int = 0
    added: int = 0
    updated: int = 0
    output_path: str = ""


def merge_corpora(
    base_path: Path,
    new_path: Path,
    output_path: Path | None = None,
) -> CorpusMergeResult:
    """Merge two corpus JSONL files with last-write-wins per filename.

    Records from new_path override base_path when filenames collide.
    If output_path is None, the base file is overwritten in place.
    """
    if not base_path.exists():
        raise FileNotFoundError(f"Base corpus not found: {base_path}")
    if not new_path.exists():
        raise FileNotFoundError(f"New corpus not found: {new_path}")

    if output_path is None:
        output_path = base_path

    base_records: dict[str, str] = {}
    for line in base_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        base_records[rec["filename"]] = line

    result = CorpusMergeResult(base_count=len(base_records))

    new_count = 0
    for line in new_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        fn = rec["filename"]
        new_count += 1
        if fn in base_records:
            result.updated += 1
        else:
            result.added += 1
        base_records[fn] = line

    result.new_count = new_count
    result.merged_count = len(base_records)
    result.output_path = str(output_path)

    sorted_lines = sorted(base_records.values(), key=lambda l: json.loads(l)["filename"])
    output_path.write_text(
        "\n".join(sorted_lines) + "\n",
        encoding="utf-8",
    )

    return result


@dataclass
class CorpusStats:
    """Summary statistics for a corpus JSONL file."""
    total_labels: int = 0
    unique_filenames: int = 0
    subject_counts: dict[str, int] = field(default_factory=dict)
    type_counts: dict[str, int] = field(default_factory=dict)
    labeler_counts: dict[str, int] = field(default_factory=dict)
    source_folder_counts: dict[str, int] = field(default_factory=dict)
    needs_review_count: int = 0
    unlabeled_count: int = 0  # subject == "" or missing
    date_range: tuple[str, str] = ("", "")
    # Calibration health (populated when training DB available)
    calibration: list[dict] = field(default_factory=list)
    stale_corpus_labels: list[str] = field(default_factory=list)


def analyze_corpus(
    corpus_path: Path,
    training_db_path: Path | None = None,
) -> CorpusStats:
    """Analyze a corpus JSONL file and optionally cross-reference with training DB.

    Returns per-axis label distributions, labeler stats, date range,
    and calibration health per genre if a training_weights.db is provided.
    """
    if not corpus_path.exists():
        raise FileNotFoundError(f"Corpus not found: {corpus_path}")

    stats = CorpusStats()
    records: dict[str, dict] = {}  # last-write-wins
    all_dates: list[str] = []

    for line in corpus_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        fn = rec.get("filename", "")
        if fn:
            records[fn] = rec
            stats.total_labels += 1

    stats.unique_filenames = len(records)

    for rec in records.values():
        subj = rec.get("subject", "")
        ptype = rec.get("photo_type", "")
        labeler = rec.get("labeler", "unknown")
        folder = rec.get("source_folder", "")
        date = rec.get("labeled_at", "")

        if subj:
            stats.subject_counts[subj] = stats.subject_counts.get(subj, 0) + 1
        else:
            stats.unlabeled_count += 1

        if ptype and ptype != "general":
            stats.type_counts[ptype] = stats.type_counts.get(ptype, 0) + 1

        stats.labeler_counts[labeler] = stats.labeler_counts.get(labeler, 0) + 1
        if folder:
            stats.source_folder_counts[folder] = stats.source_folder_counts.get(folder, 0) + 1

        if rec.get("needs_review"):
            stats.needs_review_count += 1

        if date:
            all_dates.append(date)

    if all_dates:
        all_dates.sort()
        stats.date_range = (all_dates[0], all_dates[-1])

    # Cross-reference with training DB for calibration health
    current_labels = set(ALL_LABELS) if ALL_LABELS else set()

    if training_db_path and training_db_path.exists():
        try:
            conn = sqlite3.connect(str(training_db_path))
            rows = conn.execute(
                "SELECT genre, n_corrections, alpha, is_active, version "
                "FROM genre_prototypes WHERE is_active=1 ORDER BY genre"
            ).fetchall()
            seen_genres: set[str] = set()
            for row in rows:
                genre, n_corr, alpha, _, version = row
                seen_genres.add(genre)
                corpus_count = stats.subject_counts.get(genre, 0) + stats.type_counts.get(genre, 0)
                # Mark whether this prototype matches a current genre label
                if current_labels:
                    status = "current" if genre in current_labels else "STALE"
                else:
                    status = "?"
                stats.calibration.append({
                    "genre": genre,
                    "n_corrections": n_corr,
                    "alpha": alpha,
                    "version": version,
                    "corpus_labels": corpus_count,
                    "source": "blended" if alpha < 1.0 else "hardcoded",
                    "status": status,
                })
            # Add entries for current genres that have NO prototype at all
            if current_labels:
                for label in sorted(current_labels - seen_genres):
                    corpus_count = stats.subject_counts.get(label, 0) + stats.type_counts.get(label, 0)
                    stats.calibration.append({
                        "genre": label,
                        "n_corrections": 0,
                        "alpha": 1.0,
                        "version": 0,
                        "corpus_labels": corpus_count,
                        "source": "none",
                        "status": "MISSING",
                    })
            conn.close()
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            pass

    # Flag corpus labels that don't match current genre lists
    if current_labels:
        all_corpus_labels = set(stats.subject_counts.keys()) | set(stats.type_counts.keys())
        stats.stale_corpus_labels = sorted(all_corpus_labels - current_labels)
    else:
        stats.stale_corpus_labels = []

    return stats


def format_corpus_report(stats: CorpusStats) -> str:
    """Format CorpusStats as a human-readable text report."""
    lines: list[str] = []
    lines.append(f"{'═' * 50}")
    lines.append(f"  CORPUS SUMMARY")
    lines.append(f"{'═' * 50}")
    lines.append(f"  Unique photos:   {stats.unique_filenames}")
    lines.append(f"  Total records:   {stats.total_labels}  (last-write-wins deduped)")
    lines.append(f"  Needs review:    {stats.needs_review_count}")
    lines.append(f"  Unlabeled:       {stats.unlabeled_count}")
    if stats.date_range[0]:
        lines.append(f"  Date range:      {stats.date_range[0][:10]}  →  {stats.date_range[1][:10]}")
    lines.append("")

    subjects_set = set(SUBJECTS) if SUBJECTS else set()
    types_set = set(PHOTO_TYPES) if PHOTO_TYPES else set()

    # Subject distribution
    lines.append(f"  SUBJECTS (what)  [{len(SUBJECTS)} current labels]")
    lines.append(f"  {'─' * 45}")
    if stats.subject_counts:
        max_count = max(stats.subject_counts.values())
        bar_width = 20
        for subj, count in sorted(stats.subject_counts.items(), key=lambda x: -x[1]):
            bar_len = round(count / max_count * bar_width) if max_count else 0
            bar = "█" * bar_len
            pct = count / stats.unique_filenames * 100 if stats.unique_filenames else 0
            flag = "" if (not subjects_set or subj in subjects_set) else "  ⚠ NOT IN CURRENT LABELS"
            lines.append(f"  {subj:<16} {count:>4}  {pct:5.1f}%  {bar}{flag}")
    else:
        lines.append("  (none)")
    lines.append("")

    # Photo type distribution
    lines.append(f"  PHOTO TYPES (how)  [{len(PHOTO_TYPES)} current labels]")
    lines.append(f"  {'─' * 45}")
    if stats.type_counts:
        max_count = max(stats.type_counts.values())
        bar_width = 20
        for ptype, count in sorted(stats.type_counts.items(), key=lambda x: -x[1]):
            bar_len = round(count / max_count * bar_width) if max_count else 0
            bar = "█" * bar_len
            pct = count / stats.unique_filenames * 100 if stats.unique_filenames else 0
            flag = "" if (not types_set or ptype in types_set) else "  ⚠ NOT IN CURRENT LABELS"
            lines.append(f"  {ptype:<16} {count:>4}  {pct:5.1f}%  {bar}{flag}")
    else:
        lines.append("  (none)")
    lines.append("")

    # Warn about stale corpus labels
    if stats.stale_corpus_labels:
        lines.append(f"  ⚠ STALE CORPUS LABELS (not in current genre_router)")
        lines.append(f"  {'─' * 45}")
        for label in stats.stale_corpus_labels:
            count = stats.subject_counts.get(label, 0) + stats.type_counts.get(label, 0)
            lines.append(f"  {label:<20} {count:>4} labels")
        lines.append("")

    # Source folders
    lines.append(f"  SOURCE FOLDERS")
    lines.append(f"  {'─' * 40}")
    for folder, count in sorted(stats.source_folder_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {folder:<24} {count:>4}")
    lines.append("")

    # Labelers
    lines.append(f"  LABELERS")
    lines.append(f"  {'─' * 40}")
    for labeler, count in sorted(stats.labeler_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {labeler:<24} {count:>4}")
    lines.append("")

    # Calibration health
    if stats.calibration:
        current_cal = [c for c in stats.calibration if c.get("status") == "current"]
        stale_cal = [c for c in stats.calibration if c.get("status") == "STALE"]
        missing_cal = [c for c in stats.calibration if c.get("status") == "MISSING"]

        if current_cal:
            lines.append(f"  CALIBRATION — CURRENT PROTOTYPES ({len(current_cal)})")
            lines.append(f"  {'─' * 58}")
            lines.append(f"  {'Genre':<16} {'Samples':>7} {'Alpha':>6} {'Source':<10} {'Corpus':>6}")
            lines.append(f"  {'─' * 58}")
            for cal in sorted(current_cal, key=lambda c: -c["n_corrections"]):
                lines.append(
                    f"  {cal['genre']:<16} {cal['n_corrections']:>7} "
                    f"{cal['alpha']:>6.2f} {cal['source']:<10} {cal['corpus_labels']:>6}"
                )
            lines.append("")

        if missing_cal:
            lines.append(f"  ⚠ MISSING PROTOTYPES ({len(missing_cal)} current genres with no prototype)")
            lines.append(f"  {'─' * 58}")
            for cal in missing_cal:
                corpus_note = f"  ({cal['corpus_labels']} in corpus)" if cal['corpus_labels'] else ""
                lines.append(f"  {cal['genre']:<16} — no active prototype{corpus_note}")
            lines.append("")

        if stale_cal:
            lines.append(f"  ⚠ STALE PROTOTYPES ({len(stale_cal)} not in current genre_router)")
            lines.append(f"  {'─' * 58}")
            lines.append(f"  {'Genre':<16} {'Samples':>7} {'Alpha':>6} {'Source':<10} {'Corpus':>6}")
            lines.append(f"  {'─' * 58}")
            for cal in sorted(stale_cal, key=lambda c: -c["n_corrections"]):
                lines.append(
                    f"  {cal['genre']:<16} {cal['n_corrections']:>7} "
                    f"{cal['alpha']:>6.2f} {cal['source']:<10} {cal['corpus_labels']:>6}"
                )
            lines.append(f"  These prototypes trained on old labels — consider recalibrating.")
            lines.append("")

        lines.append(f"  Alpha: 1.00 = fully hardcoded, 0.30 = mostly learned")
        lines.append(f"  Corpus: labels in this corpus for this genre")

    return "\n".join(lines)


@dataclass
class CleanCorpusResult:
    input_records: int = 0
    output_records: int = 0
    dropped_empty: int = 0
    dropped_dupes: int = 0
    output_path: str = ""


def export_clean_corpus(
    source_path: Path,
    output_path: Path,
    *,
    drop_empty: bool = True,
    drop_needs_review: bool = False,
) -> CleanCorpusResult:
    """Export a deduplicated, cleaned corpus JSONL.

    Reads the source corpus, applies last-write-wins per filename,
    optionally strips unlabeled (empty subject) and needs_review entries,
    sorts by filename, and writes a clean output.

    Args:
        source_path: Input corpus JSONL
        output_path: Where to save the clean corpus
        drop_empty: Remove records with empty subject (default True)
        drop_needs_review: Remove records flagged needs_review (default False)

    Returns:
        CleanCorpusResult with counts.
    """
    if not source_path.exists():
        raise FileNotFoundError(f"Corpus not found: {source_path}")

    result = CleanCorpusResult()

    # Read all records, last-write-wins
    all_records: dict[str, dict] = {}
    for line in source_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        fn = rec.get("filename", "")
        if fn:
            result.input_records += 1
            if fn in all_records:
                result.dropped_dupes += 1
            all_records[fn] = rec

    # Filter
    clean: list[dict] = []
    for rec in all_records.values():
        if drop_empty and not rec.get("subject"):
            result.dropped_empty += 1
            continue
        if drop_needs_review and rec.get("needs_review"):
            result.dropped_empty += 1
            continue
        clean.append(rec)

    clean.sort(key=lambda r: r["filename"])
    result.output_records = len(clean)
    result.output_path = str(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(r) for r in clean) + "\n",
        encoding="utf-8",
    )

    return result


def _ensure_local_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS genre_prototypes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version INTEGER NOT NULL,
            genre TEXT NOT NULL,
            prototype BLOB NOT NULL,
            n_corrections INTEGER DEFAULT 0,
            alpha REAL DEFAULT 1.0,
            created_at TEXT DEFAULT (datetime('now')),
            is_active INTEGER DEFAULT 1,
            UNIQUE(version, genre)
        );
        CREATE TABLE IF NOT EXISTS genre_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_path TEXT NOT NULL,
            clip_embedding BLOB NOT NULL,
            aux_features BLOB,
            original_genres TEXT NOT NULL,
            corrected_genres TEXT NOT NULL,
            correction_source TEXT DEFAULT 'darktable',
            corrected_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS genre_adapter (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version INTEGER NOT NULL,
            model_onnx BLOB NOT NULL,
            n_training_samples INTEGER,
            f1_score REAL,
            created_at TEXT DEFAULT (datetime('now')),
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS custom_genres (
            name TEXT PRIMARY KEY,
            first_seen_at TEXT DEFAULT (datetime('now')),
            n_examples INTEGER DEFAULT 0,
            promoted INTEGER DEFAULT 0
        );
    """)
    conn.commit()


def _import_replace(bundle_db: Path, local_db: Path) -> TrainingDBStats:
    shutil.copy2(str(bundle_db), str(local_db))
    conn = sqlite3.connect(str(local_db))
    stats = _get_stats(conn)
    conn.close()
    return stats


def _import_merge_corrections(bundle_db: Path, local_db: Path) -> TrainingDBStats:
    local = sqlite3.connect(str(local_db))
    _ensure_local_schema(local)
    local.execute("ATTACH DATABASE ? AS bundle", (str(bundle_db),))

    local_paths = {
        r[0]
        for r in local.execute("SELECT image_path FROM genre_corrections").fetchall()
    }

    for row in local.execute("SELECT * FROM bundle.genre_corrections").fetchall():
        if row[1] not in local_paths:
            local.execute(
                "INSERT INTO genre_corrections "
                "(image_path, clip_embedding, aux_features, original_genres, "
                "corrected_genres, correction_source, corrected_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row[1], row[2], row[3], row[4], row[5], row[6], row[7]),
            )

    for row in local.execute("SELECT * FROM bundle.custom_genres").fetchall():
        local.execute(
            "INSERT OR IGNORE INTO custom_genres "
            "(name, first_seen_at, n_examples, promoted) "
            "VALUES (?, ?, ?, ?)",
            (row[0], row[1], row[2], row[3]),
        )

    local.commit()
    local.execute("DETACH DATABASE bundle")
    stats = _get_stats(local)
    local.close()
    return stats


def _import_merge_all(bundle_db: Path, local_db: Path) -> TrainingDBStats:
    local = sqlite3.connect(str(local_db))
    _ensure_local_schema(local)
    local.execute("ATTACH DATABASE ? AS bundle", (str(bundle_db),))

    # Merge corrections
    local_paths = {
        r[0]
        for r in local.execute("SELECT image_path FROM genre_corrections").fetchall()
    }
    for row in local.execute("SELECT * FROM bundle.genre_corrections").fetchall():
        if row[1] not in local_paths:
            local.execute(
                "INSERT INTO genre_corrections "
                "(image_path, clip_embedding, aux_features, original_genres, "
                "corrected_genres, correction_source, corrected_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row[1], row[2], row[3], row[4], row[5], row[6], row[7]),
            )

    # Merge prototypes: take bundle versions that are newer
    local_max = local.execute(
        "SELECT MAX(version) FROM genre_prototypes"
    ).fetchone()[0] or 0
    bundle_max = local.execute(
        "SELECT MAX(version) FROM bundle.genre_prototypes"
    ).fetchone()[0] or 0

    if bundle_max > local_max:
        for row in local.execute(
            "SELECT * FROM bundle.genre_prototypes WHERE version > ?",
            (local_max,),
        ).fetchall():
            local.execute(
                "UPDATE genre_prototypes SET is_active=0 WHERE genre=? AND is_active=1",
                (row[2],),
            )
            local.execute(
                "INSERT OR IGNORE INTO genre_prototypes "
                "(version, genre, prototype, n_corrections, alpha, created_at, is_active) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row[1], row[2], row[3], row[4], row[5], row[6], row[7]),
            )

    # Merge adapters: take bundle if higher version
    try:
        local_adapter_v = local.execute(
            "SELECT MAX(version) FROM genre_adapter"
        ).fetchone()[0] or 0
        bundle_adapter_v = local.execute(
            "SELECT MAX(version) FROM bundle.genre_adapter"
        ).fetchone()[0] or 0
        if bundle_adapter_v > local_adapter_v:
            for row in local.execute(
                "SELECT * FROM bundle.genre_adapter WHERE version > ?",
                (local_adapter_v,),
            ).fetchall():
                local.execute(
                    "INSERT OR IGNORE INTO genre_adapter "
                    "(version, model_onnx, n_training_samples, f1_score, created_at, is_active) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (row[1], row[2], row[3], row[4], row[5], row[6]),
                )
    except sqlite3.OperationalError:
        pass

    # Merge custom genres
    for row in local.execute("SELECT * FROM bundle.custom_genres").fetchall():
        existing = local.execute(
            "SELECT n_examples FROM custom_genres WHERE name=?", (row[0],)
        ).fetchone()
        if existing is None:
            local.execute(
                "INSERT INTO custom_genres (name, first_seen_at, n_examples, promoted) "
                "VALUES (?, ?, ?, ?)",
                (row[0], row[1], row[2], row[3]),
            )
        else:
            local.execute(
                "UPDATE custom_genres SET n_examples = MAX(n_examples, ?) WHERE name=?",
                (row[2], row[0]),
            )

    local.commit()
    local.execute("DETACH DATABASE bundle")
    stats = _get_stats(local)
    local.close()
    return stats
