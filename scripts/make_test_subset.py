"""Sample N random photos + their DB rows from an existing cartridge into K test subsets.

Use this to build small reproducible test sets for evaluating pipeline changes
(e.g. multi-genre output, KPM measurement) without re-running the full library.
Generating multiple subsets with different seeds lets you measure variance across
independent random samples.

Example:
    python scripts/make_test_subset.py \
        --cartridge /mnt/photon_ssd/001 \
        --source-folder ICELAND \
        --source-dir /mnt/photon_ssd/001/ICELAND \
        --count 100 \
        --subsets 3 \
        --base-seed 42

This will, for each of subsets 1..K:
    1. Create /mnt/photon_ssd/001/TEST_<N>/ on the cartridge
    2. Copy <count> random files from /mnt/photon_ssd/001/ICELAND/ into it
       (including any sidecar .xmp files alongside each photo)
    3. Create a TEST_<N> table in /mnt/photon_ssd/001/photonforge.db
       with the current pipeline schema
    4. Copy the matching rows from [ICELAND] into [TEST_<N>],
       resetting stages='' so the subset can be re-processed cleanly

Each subset uses an independent seed derived from --base-seed (default 42),
so subsets may overlap — this is the typical pattern for variance measurement.
Pass --base-seed for reproducibility; omit to get nondeterministic sampling.
"""

from __future__ import annotations

import argparse
import random
import shutil
import sqlite3
import sys
from pathlib import Path

# Allow running as a standalone script from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from photo_workflow.photondb import ensure_table, sanitize_table_name


SIDECAR_SUFFIXES = (".xmp", ".XMP")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cartridge", required=True, type=Path,
                   help="Cartridge root containing photonforge.db (e.g. /mnt/photon_ssd/001 or H:\\)")
    p.add_argument("--source-folder", required=True,
                   help="Source folder name; also used as the DB table name (e.g. ICELAND)")
    p.add_argument("--source-dir", required=True, type=Path,
                   help="Directory containing the actual source photo files")
    p.add_argument("--count", type=int, default=100,
                   help="Number of random photos to sample per subset (default: 100)")
    p.add_argument("--subsets", type=int, default=3,
                   help="Number of independent subsets to create (default: 3)")
    p.add_argument("--base-seed", type=int, default=42,
                   help="Base random seed. Subset N uses base_seed + N - 1. "
                        "Pass --base-seed 0 along with --nondeterministic for unseeded runs. (default: 42)")
    p.add_argument("--nondeterministic", action="store_true",
                   help="Use unseeded RNG for every subset (default: derive seeds from --base-seed)")
    p.add_argument("--test-folder-prefix", default="TEST",
                   help="Destination folder/table prefix. Subset N becomes <prefix>_<N> (default: TEST)")
    p.add_argument("--reset-stages", action="store_true", default=True,
                   help="Clear the stages column on copied rows so they re-process from scratch (default: True)")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    db_path = args.cartridge / "photonforge.db"
    if not db_path.exists():
        print(f"ERROR: photonforge.db not found at {db_path}", file=sys.stderr)
        return 1
    if not args.source_dir.is_dir():
        print(f"ERROR: source-dir does not exist or is not a directory: {args.source_dir}", file=sys.stderr)
        return 1

    if args.subsets < 1:
        print(f"ERROR: --subsets must be >= 1, got {args.subsets}", file=sys.stderr)
        return 1

    src_table = sanitize_table_name(args.source_folder)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        # Verify source table exists
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (src_table,),
        ).fetchone()
        if not existing:
            print(f"ERROR: source table [{src_table}] does not exist in {db_path}", file=sys.stderr)
            return 1

        # Read all rows from source table once
        all_rows = conn.execute(f"SELECT * FROM [{src_table}]").fetchall()
        if not all_rows:
            print(f"ERROR: source table [{src_table}] is empty", file=sys.stderr)
            return 1

        candidates = [r for r in all_rows if (args.source_dir / r["filename"]).is_file()]
        print(f"Source: {len(all_rows)} rows in [{src_table}], "
              f"{len(candidates)} with files present in {args.source_dir}")

        if not candidates:
            print("ERROR: no candidate files found on disk", file=sys.stderr)
            return 1

        src_cols = [c[1] for c in conn.execute(f"PRAGMA table_info([{src_table}])").fetchall()]

        for n in range(1, args.subsets + 1):
            dst_folder = f"{args.test_folder_prefix}_{n}"
            dst_table = sanitize_table_name(dst_folder)

            if dst_table == src_table:
                print(f"ERROR: subset {n} table [{dst_table}] collides with source table; "
                      f"pick a different --test-folder-prefix", file=sys.stderr)
                return 1

            seed = None if args.nondeterministic else args.base_seed + n - 1
            rng = random.Random(seed)

            if len(candidates) < args.count:
                print(f"\n[Subset {n}] WARNING: only {len(candidates)} candidates available; "
                      f"sampling all of them", file=sys.stderr)
                sample = list(candidates)
            else:
                sample = rng.sample(candidates, args.count)

            dest_dir = args.cartridge / dst_folder
            dest_dir.mkdir(parents=True, exist_ok=True)

            ensure_table(conn, dst_table)
            dst_cols = [c[1] for c in conn.execute(f"PRAGMA table_info([{dst_table}])").fetchall()]
            common_cols = [c for c in src_cols if c in dst_cols]
            col_list_sql = ",".join(f"[{c}]" for c in common_cols)
            placeholder_sql = ",".join("?" * len(common_cols))

            copied_files = 0
            copied_sidecars = 0
            copied_rows = 0
            skipped_existing = 0

            for row in sample:
                src_file = args.source_dir / row["filename"]
                dst_file = dest_dir / row["filename"]

                if dst_file.exists():
                    skipped_existing += 1
                else:
                    shutil.copy2(src_file, dst_file)
                    copied_files += 1

                for suffix in SIDECAR_SUFFIXES:
                    sidecar = src_file.with_suffix(src_file.suffix + suffix)
                    if sidecar.is_file():
                        dst_sidecar = dst_file.with_suffix(dst_file.suffix + suffix)
                        if not dst_sidecar.exists():
                            shutil.copy2(sidecar, dst_sidecar)
                            copied_sidecars += 1

                values = []
                for c in common_cols:
                    v = row[c]
                    if args.reset_stages and c == "stages":
                        v = ""
                    values.append(v)

                conn.execute(
                    f"INSERT OR REPLACE INTO [{dst_table}] ({col_list_sql}) VALUES ({placeholder_sql})",
                    values,
                )
                copied_rows += 1

            conn.commit()

            seed_label = "nondeterministic" if seed is None else f"seed={seed}"
            print(f"\n[Subset {n}] {seed_label}")
            print(f"  Destination:                {dest_dir}")
            print(f"  Files copied:               {copied_files} (+ {skipped_existing} already present)")
            print(f"  Sidecars copied:            {copied_sidecars}")
            print(f"  Rows inserted into [{dst_table}]: {copied_rows}")

        if args.reset_stages:
            print("\nAll subset rows have stages='' so they re-process from scratch.")
        return 0

    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
