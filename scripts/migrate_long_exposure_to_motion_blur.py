#!/usr/bin/env python3
"""Idempotent migration: rename Photo-Type label 'long-exposure' -> 'motion-blur'.

Renames the label everywhere it is stored, across the local weights DB and the
on-cartridge runtime DBs (NFR-2.3: library/runtime DBs live on the external SSD,
so the path is a required argument — nothing is hardcoded).

Handles, skipping any table/column that is absent:
  - aesthetic_weights.label          (exact-string column)
  - genre_prototypes.genre           (exact-string column)
  - photos.photo_type                (exact-string column, legacy schema)
  - photos.genres                    (JSON: object {"photo_type": ...} or list)
  - embeddings.genres                (JSON, same handling)
  - genre_adapter_linear.classes     (JSON list of class names, order-preserving)

JSON handling replaces the whole-string value "long-exposure" wherever it appears
inside the parsed structure, preserving list order and dict keys, so positionally
weight-aligned columns (classes, prototypes) stay aligned. Re-running is a no-op.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

OLD = "long-exposure"
NEW = "motion-blur"

# Exact-string columns: (table, column)
_EXACT_COLUMNS = [
    ("aesthetic_weights", "label"),
    ("genre_prototypes", "genre"),
    ("photos", "photo_type"),
]

# JSON columns: (table, column)
_JSON_COLUMNS = [
    ("photos", "genres"),
    ("embeddings", "genres"),
    ("genre_adapter_linear", "classes"),
]


def _table_columns(cur: sqlite3.Cursor, table: str) -> set[str]:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (table,))
    if not cur.fetchone():
        return set()
    cur.execute(f"PRAGMA table_info('{table}');")
    return {row[1] for row in cur.fetchall()}


def _replace_in_json(value: Any) -> tuple[Any, bool]:
    """Recursively replace the exact string OLD with NEW. Returns (new_value, changed)."""
    if isinstance(value, str):
        return (NEW, True) if value == OLD else (value, False)
    if isinstance(value, list):
        changed = False
        out = []
        for item in value:
            new_item, c = _replace_in_json(item)
            out.append(new_item)
            changed = changed or c
        return out, changed
    if isinstance(value, dict):
        changed = False
        out = {}
        for k, v in value.items():
            new_v, c = _replace_in_json(v)
            out[k] = new_v
            changed = changed or c
        return out, changed
    return value, False


def migrate_db(db_path: str) -> dict[str, int]:
    """Migrate a single database. Returns {table.column: rows_affected}."""
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")

    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    affected: dict[str, int] = {}

    try:
        for table, column in _EXACT_COLUMNS:
            if column in _table_columns(cur, table):
                cur.execute(
                    f"UPDATE {table} SET {column} = ? WHERE {column} = ?;", (NEW, OLD)
                )
                if cur.rowcount:
                    affected[f"{table}.{column}"] = cur.rowcount

        for table, column in _JSON_COLUMNS:
            if column not in _table_columns(cur, table):
                continue
            cur.execute(
                f"SELECT rowid, {column} FROM {table} WHERE {column} LIKE ?;",
                (f"%{OLD}%",),
            )
            rows = cur.fetchall()
            count = 0
            for rowid, raw in rows:
                if raw is None:
                    continue
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                except (json.JSONDecodeError, TypeError):
                    continue
                new_parsed, changed = _replace_in_json(parsed)
                if changed:
                    cur.execute(
                        f"UPDATE {table} SET {column} = ? WHERE rowid = ?;",
                        (json.dumps(new_parsed), rowid),
                    )
                    count += 1
            if count:
                affected[f"{table}.{column}"] = count

        conn.commit()
    except Exception as e:  # noqa: BLE001 - re-raised with context
        conn.rollback()
        raise RuntimeError(f"Migration failed on {path}: {e}") from e
    finally:
        conn.close()

    return affected


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Idempotent rename 'long-exposure' -> 'motion-blur' in photo-workflow DBs."
    )
    parser.add_argument(
        "--db-path",
        required=True,
        help="Path to the database file (e.g. the cartridge photonforge.db / training_weights.db).",
    )
    args = parser.parse_args()

    print(f"Migrating database: {args.db_path}")
    affected = migrate_db(args.db_path)
    if affected:
        print("Migration complete. Rows affected:")
        for key, count in affected.items():
            print(f"  {key}: {count}")
    else:
        print("No rows to migrate (already migrated or tables absent).")


if __name__ == "__main__":
    main()
