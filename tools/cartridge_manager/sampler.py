"""Test dataset generator — random, stratified, and top/bottom sampling."""

from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import db_ops, file_ops


@dataclass
class SampleManifest:
    source_table: str
    strategy: str
    n_requested: int
    n_sampled: int
    seed: int
    criteria: dict
    timestamp: str
    filenames: list[str]


def random_sample(
    conn: sqlite3.Connection,
    table: str,
    n: int,
    *,
    seed: int | None = None,
    exclude_duplicates: bool = True,
) -> list[sqlite3.Row]:
    """Pick n random photos from a table."""
    rows = db_ops.get_all_rows(conn, table)
    if exclude_duplicates:
        rows = [r for r in rows if not r["is_duplicate"]]
    if seed is not None:
        random.seed(seed)
    n = min(n, len(rows))
    return random.sample(rows, n)


def stratified_sample(
    conn: sqlite3.Connection,
    table: str,
    n: int,
    *,
    by: str = "genre",
    seed: int | None = None,
    exclude_duplicates: bool = True,
) -> list[sqlite3.Row]:
    """Pick n photos proportionally across groups defined by column `by`."""
    rows = db_ops.get_all_rows(conn, table)
    if exclude_duplicates:
        rows = [r for r in rows if not r["is_duplicate"]]

    if seed is not None:
        random.seed(seed)

    buckets: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        try:
            key = row[by] or "unknown"
        except (IndexError, KeyError):
            key = "unknown"
        buckets.setdefault(key, []).append(row)

    total = len(rows)
    if total == 0:
        return []

    sampled: list[sqlite3.Row] = []
    remainder = n
    sorted_keys = sorted(buckets.keys())

    for key in sorted_keys:
        bucket = buckets[key]
        share = max(1, round(n * len(bucket) / total))
        share = min(share, len(bucket), remainder)
        sampled.extend(random.sample(bucket, share))
        remainder -= share
        if remainder <= 0:
            break

    return sampled


def top_bottom_sample(
    conn: sqlite3.Connection,
    table: str,
    n: int,
    *,
    by: str = "master_score",
    exclude_duplicates: bool = True,
) -> list[sqlite3.Row]:
    """Pick n/2 top-scoring and n/2 bottom-scoring photos."""
    rows = db_ops.get_all_rows(conn, table)
    if exclude_duplicates:
        rows = [r for r in rows if not r["is_duplicate"]]

    def _get_score(row):
        try:
            return row[by]
        except (IndexError, KeyError):
            return None

    rows_with_scores = [r for r in rows if _get_score(r) is not None]
    rows_with_scores.sort(key=lambda r: _get_score(r))

    half = n // 2
    bottom = rows_with_scores[:half]
    top = rows_with_scores[-half:] if half > 0 else []
    return bottom + top


def generate_test_dataset(
    conn: sqlite3.Connection,
    src_table: str,
    src_dir: Path,
    cartridge_root: Path,
    n: int,
    strategy: str = "random",
    *,
    seed: int | None = None,
    stratify_by: str = "genre",
    score_by: str = "master_score",
    progress_callback=None,
) -> SampleManifest:
    """Create a test dataset by sampling and copying photos.

    Args:
        conn: photonforge.db connection
        src_table: Source table to sample from
        src_dir: Directory containing the source photos
        cartridge_root: Cartridge root path
        n: Number of photos to sample
        strategy: "random", "stratified", or "top_bottom"
        seed: Random seed for reproducibility
        stratify_by: Column for stratified sampling
        score_by: Column for top/bottom sampling
        progress_callback: Optional callable(current, total) for UI updates

    Returns:
        SampleManifest with details of what was created.
    """
    if seed is None:
        seed = random.randint(0, 2**31)

    if strategy == "random":
        sampled = random_sample(conn, src_table, n, seed=seed)
    elif strategy == "stratified":
        sampled = stratified_sample(conn, src_table, n, by=stratify_by, seed=seed)
    elif strategy == "top_bottom":
        sampled = top_bottom_sample(conn, src_table, n, by=score_by)
    else:
        raise ValueError(f"Unknown sampling strategy: {strategy}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dataset_name = f"_testset_{ts}"
    dst_dir = file_ops.create_directory(cartridge_root, dataset_name)
    dst_table = db_ops.create_table(conn, dataset_name)

    journal = file_ops.OperationJournal(path=dst_dir / ".journal.json")
    filenames: list[str] = []

    for i, row in enumerate(sampled):
        filename = row["filename"]
        try:
            file_ops.copy_photo(src_dir, dst_dir, filename, journal=journal)
            db_ops.copy_row(conn, src_table, dst_table, filename)
            filenames.append(filename)
        except (FileNotFoundError, FileExistsError) as e:
            if progress_callback:
                progress_callback(i + 1, len(sampled), error=str(e))
            continue
        if progress_callback:
            progress_callback(i + 1, len(sampled))

    journal.clear()

    manifest = SampleManifest(
        source_table=src_table,
        strategy=strategy,
        n_requested=n,
        n_sampled=len(filenames),
        seed=seed,
        criteria={"stratify_by": stratify_by, "score_by": score_by},
        timestamp=ts,
        filenames=filenames,
    )

    manifest_path = dst_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_table": manifest.source_table,
                "strategy": manifest.strategy,
                "n_requested": manifest.n_requested,
                "n_sampled": manifest.n_sampled,
                "seed": manifest.seed,
                "criteria": manifest.criteria,
                "timestamp": manifest.timestamp,
                "filenames": manifest.filenames,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return manifest


# -- Merge datasets -----------------------------------------------------------


@dataclass
class MergeResult:
    dest_name: str
    sources: list[str]
    copied: int = 0
    skipped_dupes: int = 0
    errors: list[str] = field(default_factory=list)
    filenames: list[str] = field(default_factory=list)


def merge_datasets(
    conn: sqlite3.Connection,
    source_tables: list[str],
    source_dirs: list[Path],
    cartridge_root: Path,
    dest_name: str | None = None,
    *,
    progress_callback=None,
) -> MergeResult:
    """Merge multiple folders/datasets into a single combined dataset.

    Copies photos from all sources into one new folder. Deduplicates
    by filename — if a photo with the same name exists in multiple sources,
    only the first copy is kept.

    Args:
        conn: photonforge.db connection
        source_tables: List of source table names to merge from
        source_dirs: List of corresponding source directories
        cartridge_root: Cartridge root path
        dest_name: Name for the merged dataset (default: _merged_{timestamp})
        progress_callback: Optional callable(current, total)

    Returns:
        MergeResult with counts and details.
    """
    if len(source_tables) != len(source_dirs):
        raise ValueError("source_tables and source_dirs must have the same length")
    if len(source_tables) < 2:
        raise ValueError("Need at least 2 sources to merge")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if dest_name is None:
        dest_name = f"_merged_{ts}"

    dst_dir = file_ops.create_directory(cartridge_root, dest_name)
    dst_table = db_ops.create_table(conn, dest_name)

    result = MergeResult(dest_name=dest_name, sources=list(source_tables))
    seen_filenames: set[str] = set()

    # Collect all (table, dir, row) triples
    all_items: list[tuple[str, Path, str]] = []
    for table, src_dir in zip(source_tables, source_dirs):
        rows = db_ops.get_all_rows(conn, table)
        for row in rows:
            all_items.append((table, src_dir, row["filename"]))

    total = len(all_items)
    journal = file_ops.OperationJournal(path=dst_dir / ".journal.json")

    for i, (table, src_dir, filename) in enumerate(all_items):
        if filename in seen_filenames:
            result.skipped_dupes += 1
            if progress_callback:
                progress_callback(i + 1, total)
            continue

        try:
            file_ops.copy_photo(src_dir, dst_dir, filename, journal=journal)
            db_ops.copy_row(conn, table, dst_table, filename)
            seen_filenames.add(filename)
            result.copied += 1
            result.filenames.append(filename)
        except FileNotFoundError:
            # File in DB but not on disk — skip silently
            result.skipped_dupes += 1
        except FileExistsError:
            result.skipped_dupes += 1
        except Exception as e:
            result.errors.append(f"{filename}: {e}")

        if progress_callback:
            progress_callback(i + 1, total)

    journal.clear()

    # Write manifest
    manifest_path = dst_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "type": "merged",
                "sources": result.sources,
                "copied": result.copied,
                "skipped_dupes": result.skipped_dupes,
                "timestamp": ts,
                "filenames": result.filenames,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return result
