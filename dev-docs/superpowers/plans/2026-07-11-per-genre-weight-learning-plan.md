# Per-Genre Weight Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the loop the tagging system was built for — learn per-genre scoring weight profiles from the user's star-rating corrections in Darktable, instead of shipping hardcoded weights forever.

**Architecture:** The plumbing already exists end-to-end: `score_fusion.py` applies per-genre profiles (`SUBJECT_WEIGHTS` × `TYPE_WEIGHTS`, 50/50 blend), the `aesthetic_weights` table in `training_weights.db` overrides them at scoring time via `ModelSessions.aesthetic_weights`, and `bootstrap_aesthetic_weights` seeds the table. What is missing is any *writer* that learns. This plan adds: (1) persisting the final emitted star per photo so corrections are diffable, (2) a `collect-star-feedback` command that harvests user rating changes from Darktable, (3) a pairwise (Bradley–Terry) weight fitter per subject label, blended toward the defaults with the same alpha-decay scheme `genre_trainer.py` uses, and (4) panel/CLI surfaces.

**Tech Stack:** Python 3.11, numpy (pure-numpy fitter — runtime venv has no sklearn), sqlite3, click, pytest; Darktable Lua panel button.

## Global Constraints

- NFR-2.1: 100% offline at runtime — the fitter must be pure numpy (no sklearn requirement at runtime; sklearn optional like `genre_adapter.py`).
- NFR-2.2: RSS ≤ 1.5 GB — fitting operates on sub-score dicts (~23 floats/photo), negligible.
- NFR-2.3: `training_weights.db` and feedback JSONL live on the external SSD cartridge root, next to `photonforge.db` (same convention as `genre_labels.jsonl`).
- Only the **subject-axis** profiles are learned initially. The 50/50 subject/type blend makes per-pair attribution ambiguous; type profiles stay at their defaults until subject learning is validated. (Type learning is a follow-up, not in this plan.)
- Learned weights must be non-negative and sum to 1 within a profile (matches the hand-tuned profile convention).
- Never move a profile fully away from defaults: blend `alpha*default + (1-alpha)*learned` with `alpha = max(0.3, 1.0 - 0.02*n_pairs)` (reuse `genre_trainer.compute_alpha`).

## Design Notes (read before Task 1)

**Why pairwise, not regression on stars:** the user's absolute stars are shoot-relative (P6 hybrid rating), so "user gave 4 stars" is not an absolute quality target. What *is* signal: within one shoot and one subject genre, the user ranked photo A above photo B while PHOTONForge ranked them the other way. Bradley–Terry on sub-score differences learns "which signals predict the user's preference" and is scale-free.

**Where corrections come from:** Darktable `images.flags` bits 0–2 store the 0–5 rating (bit 3 = reject). `read_darktable_rating` reads it the same way `darktable_bridge.read_darktable_keywords` reads tags. We compare against the star PHOTONForge last wrote (new `photos.stars` column) — a mismatch is a user correction.

**Bucket subtlety:** master = `min(technical, aesthetic)`. The fitter learns one flat profile over all sub-score keys present; `_compute_master_score` re-partitions into buckets at scoring time, so the learned profile plugs into the existing math unchanged.

---

### Task 1: Persist emitted stars in photonforge.db

**Files:**
- Modify: `src/photo_workflow/photondb.py` (add `_ensure_column` helper + `update_stars`)
- Modify: `src/photo_workflow/pipeline.py:588-696` (score command: write stars after live emit and after the hybrid re-rating pass)
- Test: `tests/test_photondb.py`

**Interfaces:**
- Produces: `photondb.update_stars(conn, table: str, filename: str, stars: int, *, auto_commit: bool = True) -> None`
- Produces: `photondb._ensure_column(conn, table: str, column: str, decl: str) -> None` (idempotent ALTER TABLE guard, reused by later plans)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_photondb.py (append)
def test_update_stars_roundtrip(tmp_path):
    from photo_workflow import photondb
    conn = photondb.open_db(tmp_path / "photos")
    photondb.ensure_schema(conn)
    photondb.insert_photo(conn, "SHOOT1", "a.jpg", "a.jpg", None)
    photondb.update_stars(conn, "SHOOT1", "a.jpg", 4)
    row = conn.execute(
        "SELECT stars FROM photos WHERE folder='SHOOT1' AND filename='a.jpg'"
    ).fetchone()
    assert row["stars"] == 4

def test_ensure_column_idempotent(tmp_path):
    from photo_workflow import photondb
    conn = photondb.open_db(tmp_path / "photos")
    photondb.ensure_schema(conn)
    photondb._ensure_column(conn, "photos", "stars", "INTEGER")
    photondb._ensure_column(conn, "photos", "stars", "INTEGER")  # second call: no error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_photondb.py::test_update_stars_roundtrip -v`
Expected: FAIL with `AttributeError: module 'photo_workflow.photondb' has no attribute 'update_stars'`

- [ ] **Step 3: Implement**

```python
# src/photo_workflow/photondb.py (append)
def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """Add a column if missing (SQLite has no IF NOT EXISTS for columns)."""
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        conn.commit()


def update_stars(
    conn: sqlite3.Connection, table: str, filename: str, stars: int,
    *, auto_commit: bool = True,
) -> None:
    """Record the star rating PHOTONForge emitted for this photo."""
    folder = sanitize_table_name(table)
    _ensure_column(conn, "photos", "stars", "INTEGER")
    conn.execute(
        "UPDATE photos SET stars=? WHERE folder=? AND filename=?",
        (int(stars), folder, filename),
    )
    if auto_commit:
        conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_photondb.py -v`
Expected: PASS

- [ ] **Step 5: Wire into the score command**

In `pipeline.py` score command:
- After the live emit block (both the hard-reject branch and the star branch around lines 607–616): call `update_stars(conn, table, row["filename"], 1 if fusion.hard_reject else stars, auto_commit=False)` then rely on the existing `conn.commit()`.
- In the final hybrid re-rating loop (around line 686), after computing `stars = hybrid_star(...)`: `update_stars(conn, table, item["filename"], stars, auto_commit=False)` and add one `conn.commit()` after the loop (the connection is still open; the existing `conn.close()` at line 698 comes after).

- [ ] **Step 6: Run the full suite and commit**

Run: `pytest -m "not slow" -q`
Expected: PASS

```bash
git add src/photo_workflow/photondb.py src/photo_workflow/pipeline.py tests/test_photondb.py
git commit -m "feat(scoring): persist emitted star rating in photos.stars"
```

---

### Task 2: Read user ratings from Darktable

**Files:**
- Modify: `src/photo_workflow/darktable_bridge.py` (add `read_darktable_rating`)
- Test: `tests/test_darktable_bridge.py`

**Interfaces:**
- Produces: `read_darktable_rating(library_db_path: Path, filename: str) -> int | None` — 0–5 stars, `-1` for rejected, `None` if the image is not in the library.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_darktable_bridge.py (append; follow the existing fixture style that
# builds a fake library.db/data.db pair — reuse the same helper the keyword tests use)
def test_read_darktable_rating(tmp_path):
    from photo_workflow.darktable_bridge import read_darktable_rating
    lib = tmp_path / "library.db"
    conn = sqlite3.connect(lib)
    # flags bits 0-2 = rating, bit 3 (0x8) = reject; 0x7 mask, like darktable
    conn.execute("CREATE TABLE images (id INTEGER PRIMARY KEY, filename TEXT, flags INTEGER)")
    conn.executemany(
        "INSERT INTO images (filename, flags) VALUES (?, ?)",
        [("four.jpg", 4), ("rejected.jpg", 8 | 2), ("zero.jpg", 0)],
    )
    conn.commit(); conn.close()
    (tmp_path / "data.db").touch()  # _open_dt ATTACHes it

    assert read_darktable_rating(lib, "four.jpg") == 4
    assert read_darktable_rating(lib, "rejected.jpg") == -1
    assert read_darktable_rating(lib, "zero.jpg") == 0
    assert read_darktable_rating(lib, "missing.jpg") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_darktable_bridge.py::test_read_darktable_rating -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement**

```python
# src/photo_workflow/darktable_bridge.py (append)
_DT_REJECT_BIT = 0x8
_DT_RATING_MASK = 0x7


def read_darktable_rating(library_db_path: Path, filename: str) -> int | None:
    """Read the user's star rating for one image from Darktable's library.

    Returns 0-5 stars, -1 when the image carries the reject flag, or None
    when the image is not in the library. Safe to run while DT is open
    (read-only, like read_darktable_keywords).
    """
    try:
        conn = _open_dt(library_db_path, check_lock=False)
        try:
            row = conn.execute(
                "SELECT flags FROM images WHERE filename=?", (filename,)
            ).fetchone()
        finally:
            conn.close()
    except Exception as e:
        logger.error("Failed to read Darktable rating for %s: %s", filename, e)
        return None
    if row is None:
        return None
    flags = row["flags"]
    if flags & _DT_REJECT_BIT:
        return -1
    return flags & _DT_RATING_MASK
```

- [ ] **Step 4: Run test, then commit**

Run: `pytest tests/test_darktable_bridge.py -v` — Expected: PASS

```bash
git add src/photo_workflow/darktable_bridge.py tests/test_darktable_bridge.py
git commit -m "feat(bridge): read user star ratings from Darktable library"
```

---

### Task 3: collect-star-feedback command

**Files:**
- Modify: `src/photo_workflow/pipeline.py` (new command in the existing `training` group, next to `collect_corrections` at line 1409)
- Test: `tests/test_star_feedback.py`

**Interfaces:**
- Consumes: `read_darktable_rating` (Task 2), `photos.stars` (Task 1)
- Produces: `star_feedback.jsonl` on the cartridge root, one line per disagreement:
  `{"filename", "source_folder", "subject", "photo_type", "photon_stars", "dt_stars", "sub_scores", "collected_at", "labeler"}`
- CLI: `photo-workflow training collect-star-feedback --folder F --photon-db P --darktable-library L [--feedback PATH] [--dry-run] [--json-progress]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_star_feedback.py
import json, sqlite3
from pathlib import Path
from click.testing import CliRunner
from photo_workflow.pipeline import cli
from photo_workflow import photondb


def _setup(tmp_path):
    # photonforge.db with one scored photo (photon said 2 stars)
    conn = photondb.open_db(tmp_path / "photos")
    photondb.ensure_schema(conn)
    photondb.insert_photo(conn, "SHOOT1", "a.jpg", "a.jpg", None)
    conn.execute(
        "UPDATE photos SET primary_genre='wildlife', "
        "genres='{\"subject\": \"wildlife\", \"photo_type\": \"scenic\"}', "
        "sub_scores='{\"eye_sharpness\": 0.9, \"subject_sharpness\": 0.8}' "
        "WHERE filename='a.jpg'")
    conn.commit()
    photondb.update_stars(conn, "SHOOT1", "a.jpg", 2)
    conn.close()
    # fake DT library: user bumped it to 5
    lib = tmp_path / "library.db"
    dtc = sqlite3.connect(lib)
    dtc.execute("CREATE TABLE images (id INTEGER PRIMARY KEY, filename TEXT, flags INTEGER)")
    dtc.execute("INSERT INTO images (filename, flags) VALUES ('a.jpg', 5)")
    dtc.commit(); dtc.close()
    (tmp_path / "data.db").touch()
    return tmp_path / "photonforge.db", lib


def test_collect_star_feedback_writes_disagreements(tmp_path):
    db, lib = _setup(tmp_path)
    fb = tmp_path / "star_feedback.jsonl"
    result = CliRunner().invoke(cli, [
        "training", "collect-star-feedback", "--folder", "SHOOT1",
        "--photon-db", str(db), "--darktable-library", str(lib),
        "--feedback", str(fb)])
    assert result.exit_code == 0, result.output
    lines = [json.loads(l) for l in fb.read_text().splitlines()]
    assert len(lines) == 1
    assert lines[0]["photon_stars"] == 2 and lines[0]["dt_stars"] == 5
    assert lines[0]["subject"] == "wildlife"
    assert lines[0]["sub_scores"]["eye_sharpness"] == 0.9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_star_feedback.py -v`
Expected: FAIL — `no such command 'collect-star-feedback'`

- [ ] **Step 3: Implement the command**

Add to `pipeline.py`, mirroring the `collect_corrections` structure (progress protocol, table check, labeler/timestamps):

```python
@training.command("collect-star-feedback")
@click.option("--folder", required=True)
@click.option("--photon-db", "photon_db", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--darktable-library", "dt_library", required=True,
              type=click.Path(path_type=Path))
@click.option("--feedback", default=None, type=click.Path(path_type=Path),
              help="star_feedback.jsonl path (default: next to photon-db)")
@click.option("--dry-run", is_flag=True)
@click.option("--json-progress", is_flag=True)
def collect_star_feedback(folder, photon_db, dt_library, feedback, dry_run, json_progress):
    """Harvest user star-rating corrections from Darktable.

    A photo whose Darktable rating differs from the star PHOTONForge emitted
    (photos.stars) is a preference signal; rows are appended to
    star_feedback.jsonl for `training learn-weights`.
    """
    import getpass
    import sqlite3 as _sqlite3
    from datetime import datetime, timezone
    from .darktable_bridge import read_darktable_rating
    from .photondb import sanitize_table_name

    if feedback is None:
        feedback = photon_db.parent / "star_feedback.jsonl"
    table = sanitize_table_name(folder)
    conn = _sqlite3.connect(str(photon_db)); conn.row_factory = _sqlite3.Row
    rows = conn.execute(
        "SELECT filename, stars, sub_scores, genres, primary_genre FROM photos "
        "WHERE folder=? AND stars IS NOT NULL AND is_duplicate=0", (table,)
    ).fetchall()
    conn.close()

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    labeler = getpass.getuser() or "anon"
    entries = []
    for i, row in enumerate(rows, 1):
        dt_stars = read_darktable_rating(dt_library, row["filename"])
        if dt_stars is None or dt_stars <= 0 or dt_stars == row["stars"]:
            # None: not in library; 0: unrated (DT default, not a correction);
            # -1: reject (hard-gate territory, not a weight signal); equal: agree.
            continue
        try:
            genres = json.loads(row["genres"] or "{}")
            sub_scores = json.loads(row["sub_scores"] or "{}")
        except json.JSONDecodeError:
            continue
        entries.append({
            "filename": row["filename"], "source_folder": folder,
            "subject": genres.get("subject", row["primary_genre"] or "general"),
            "photo_type": genres.get("photo_type", "general"),
            "photon_stars": row["stars"], "dt_stars": dt_stars,
            "sub_scores": sub_scores,
            "collected_at": now_iso, "labeler": labeler,
        })
        if json_progress:
            click.echo(json.dumps({"step": "collect-star-feedback",
                                   "file": row["filename"], "status": "correction",
                                   "was": row["stars"], "now": dt_stars}))
        if json_progress and i % 25 == 0:
            click.echo(json.dumps({"step": "_progress", "done": i, "total": len(rows)}))

    if not dry_run and entries:
        with open(feedback, "a", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
    summary = {"step": "collect-star-feedback", "status": "done",
               "corrections": len(entries), "checked": len(rows)}
    click.echo(json.dumps(summary) if json_progress
               else f"Collected {len(entries)} star corrections from {len(rows)} photos.")
```

- [ ] **Step 4: Run test, full suite, commit**

Run: `pytest tests/test_star_feedback.py -v && pytest -m "not slow" -q`
Expected: PASS

```bash
git add src/photo_workflow/pipeline.py tests/test_star_feedback.py
git commit -m "feat(training): collect-star-feedback harvests DT rating corrections"
```

---

### Task 4: Pairwise weight fitter (weight_trainer.py)

**Files:**
- Create: `src/photo_workflow/weight_trainer.py`
- Test: `tests/test_weight_trainer.py`

**Interfaces:**
- Consumes: `star_feedback.jsonl` entries (Task 3 schema), `genre_trainer.compute_alpha`, `score_fusion.SUBJECT_WEIGHTS`
- Produces:
  - `build_pairs(entries: list[dict]) -> dict[str, list[tuple[dict, dict]]]` — per subject label, (winner_sub_scores, loser_sub_scores) pairs from same-shoot disagreements
  - `fit_profile(pairs: list[tuple[dict, dict]], keys: list[str], l2: float = 0.05, iters: int = 800, lr: float = 0.2) -> dict[str, float]` — non-negative, sum-1 profile
  - `learn_subject_weights(feedback_path: Path, min_pairs: int = 20) -> dict[str, dict]` — `{label: {"weights": {...}, "n_pairs": int, "alpha": float, "source": "blended"|"default"}}`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_weight_trainer.py
import numpy as np
from photo_workflow.weight_trainer import build_pairs, fit_profile


def _entry(fn, folder, subject, photon, dt, **scores):
    return {"filename": fn, "source_folder": folder, "subject": subject,
            "photo_type": "scenic", "photon_stars": photon, "dt_stars": dt,
            "sub_scores": scores}


def test_build_pairs_same_shoot_same_subject_only():
    entries = [
        _entry("a.jpg", "S1", "wildlife", 2, 5, eye_sharpness=0.9),
        _entry("b.jpg", "S1", "wildlife", 4, 2, eye_sharpness=0.2),
        _entry("c.jpg", "S2", "wildlife", 1, 5, eye_sharpness=0.5),   # other shoot
        _entry("d.jpg", "S1", "landscape", 1, 5, eye_sharpness=0.5),  # other subject
    ]
    pairs = build_pairs(entries)
    # a (user: 5) beat b (user: 2); c and d pair with nothing in their group
    assert len(pairs["wildlife"]) == 1
    winner, loser = pairs["wildlife"][0]
    assert winner["eye_sharpness"] == 0.9 and loser["eye_sharpness"] == 0.2


def test_fit_profile_prefers_discriminating_signal():
    rng = np.random.RandomState(0)
    pairs = []
    for _ in range(60):
        # winner always higher eye_sharpness; balance is pure noise
        w = {"eye_sharpness": 0.6 + 0.4 * rng.rand(), "balance": rng.rand()}
        l = {"eye_sharpness": 0.4 * rng.rand(), "balance": rng.rand()}
        pairs.append((w, l))
    profile = fit_profile(pairs, ["eye_sharpness", "balance"])
    assert abs(sum(profile.values()) - 1.0) < 1e-6
    assert all(v >= 0 for v in profile.values())
    assert profile["eye_sharpness"] > profile["balance"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_weight_trainer.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement**

```python
# src/photo_workflow/weight_trainer.py
"""Learn per-genre aesthetic weight profiles from star-rating corrections.

Bradley-Terry pairwise model on sub-score differences: within one shoot and
one subject genre, a photo the user rated higher is a "win". Weights that
make w . (s_winner - s_loser) large explain the user's preference. Learned
profiles are projected to the non-negative simplex (same convention as the
hand-tuned profiles) and alpha-blended toward the defaults so small samples
cannot swing scoring wildly.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from .genre_trainer import compute_alpha
from .score_fusion import SUBJECT_WEIGHTS

logger = logging.getLogger(__name__)


def load_star_feedback(path: Path) -> list[dict]:
    """Last-write-wins per (source_folder, filename), like _load_corpus."""
    result: dict[tuple[str, str], dict] = {}
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("filename") and e.get("sub_scores"):
                result[(e.get("source_folder", ""), e["filename"])] = e
    return list(result.values())


def build_pairs(entries: list[dict]) -> dict[str, list[tuple[dict, dict]]]:
    """Group by (shoot, subject); pair photos the user ranked differently."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for e in entries:
        groups.setdefault((e.get("source_folder", ""), e.get("subject", "general")), []).append(e)

    pairs: dict[str, list[tuple[dict, dict]]] = {}
    for (_folder, subject), items in groups.items():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if a["dt_stars"] == b["dt_stars"]:
                    continue
                winner, loser = (a, b) if a["dt_stars"] > b["dt_stars"] else (b, a)
                pairs.setdefault(subject, []).append(
                    (winner["sub_scores"], loser["sub_scores"]))
    return pairs


def fit_profile(
    pairs: list[tuple[dict, dict]],
    keys: list[str],
    l2: float = 0.05,
    iters: int = 800,
    lr: float = 0.2,
) -> dict[str, float]:
    """Bradley-Terry logistic fit on sub-score diffs -> non-negative sum-1 profile."""
    D = np.array(
        [[float(w.get(k, 0.0)) - float(l.get(k, 0.0)) for k in keys] for w, l in pairs],
        dtype=np.float64,
    )
    n, d = D.shape
    wvec = np.full(d, 1.0 / d)
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-(D @ wvec)))          # P(winner beats loser)
        grad = D.T @ (p - 1.0) / n + l2 * wvec          # all targets are 1 (wins)
        wvec -= lr * grad
        wvec = np.maximum(wvec, 0.0)                    # project: non-negative
    total = wvec.sum()
    if total <= 0:
        wvec = np.full(d, 1.0 / d); total = 1.0
    wvec = wvec / total                                 # project: simplex
    return {k: float(v) for k, v in zip(keys, wvec)}


def learn_subject_weights(feedback_path: Path, min_pairs: int = 20) -> dict[str, dict]:
    """Fit + alpha-blend a profile per subject label with enough pairs.

    Returns {label: {"weights", "n_pairs", "alpha", "source"}} for every label
    in SUBJECT_WEIGHTS; labels below min_pairs keep the default profile.
    """
    entries = load_star_feedback(feedback_path)
    all_pairs = build_pairs(entries)
    out: dict[str, dict] = {}
    for label, default in SUBJECT_WEIGHTS.items():
        pairs = all_pairs.get(label, [])
        if len(pairs) < min_pairs:
            out[label] = {"weights": dict(default), "n_pairs": len(pairs),
                          "alpha": 1.0, "source": "default"}
            continue
        keys = sorted(default)  # learn over the keys the default profile uses
        learned = fit_profile(pairs, keys)
        alpha = compute_alpha(len(pairs))
        blended = {k: alpha * default.get(k, 0.0) + (1 - alpha) * learned.get(k, 0.0)
                   for k in keys}
        total = sum(blended.values()) or 1.0
        blended = {k: v / total for k, v in blended.items()}
        out[label] = {"weights": blended, "n_pairs": len(pairs),
                      "alpha": alpha, "source": "blended"}
        logger.info("'%s': %d pairs, alpha=%.3f", label, len(pairs), alpha)
    return out
```

- [ ] **Step 4: Run tests, commit**

Run: `pytest tests/test_weight_trainer.py -v` — Expected: PASS

```bash
git add src/photo_workflow/weight_trainer.py tests/test_weight_trainer.py
git commit -m "feat(training): pairwise per-genre weight fitter"
```

---

### Task 5: learn-weights command + inspection commands

**Files:**
- Modify: `src/photo_workflow/pipeline.py` (three commands in the `training` group; `bootstrap_aesthetic_weights` at line 1377 already shows the upsert pattern)
- Test: `tests/test_learn_weights_cli.py`

**Interfaces:**
- Consumes: `learn_subject_weights` (Task 4), `training_weights_db.upsert_aesthetic_weights` / `next_aesthetic_weights_version` / `get_active_aesthetic_weights`
- Produces CLI:
  - `training learn-weights --feedback F --training-db T [--min-pairs 20] [--dry-run] [--json-progress]`
  - `training show-weights --training-db T [--out weights.json]` — dump active profiles (both axes) as editable JSON
  - `training set-weights --training-db T --file weights.json` — manual import (validates labels/keys, renormalizes)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_learn_weights_cli.py
import json
from click.testing import CliRunner
from photo_workflow.pipeline import cli
from photo_workflow.training_weights_db import open_training_db, ensure_schema, get_active_aesthetic_weights


def _feedback_line(fn, dt, photon, eye):
    return json.dumps({"filename": fn, "source_folder": "S1", "subject": "wildlife",
                       "photo_type": "scenic", "photon_stars": photon, "dt_stars": dt,
                       "sub_scores": {"eye_sharpness": eye, "subject_sharpness": 0.5,
                                       "subject_isolation": 0.5, "exposure_overall": 0.5,
                                       "blur_type_penalty": 1.0, "aesthetic_clip": 0.5,
                                       "behavior_proxy": 0.5}})


def test_learn_weights_writes_blended_profile(tmp_path):
    fb = tmp_path / "star_feedback.jsonl"
    # 10 photos, alternating quality -> 5*5=25 cross pairs > min-pairs 20
    lines = []
    for i in range(5):
        lines.append(_feedback_line(f"hi{i}.jpg", 5, 2, 0.9))
        lines.append(_feedback_line(f"lo{i}.jpg", 1, 4, 0.1))
    fb.write_text("\n".join(lines))
    tdb = tmp_path / "training_weights.db"

    result = CliRunner().invoke(cli, [
        "training", "learn-weights", "--feedback", str(fb),
        "--training-db", str(tdb), "--min-pairs", "20"])
    assert result.exit_code == 0, result.output

    conn = open_training_db(tdb)
    active = get_active_aesthetic_weights(conn)
    conn.close()
    assert "wildlife" in active["subject"]
    # type axis must be seeded too (fusion requires both axes present to use the DB)
    assert active["type"]


def test_show_weights_round_trips(tmp_path):
    tdb = tmp_path / "training_weights.db"
    CliRunner().invoke(cli, ["training", "bootstrap-weights", "--training-db", str(tdb)])
    out = tmp_path / "w.json"
    r = CliRunner().invoke(cli, ["training", "show-weights",
                                 "--training-db", str(tdb), "--out", str(out)])
    assert r.exit_code == 0, r.output
    data = json.loads(out.read_text())
    assert "subject" in data and "wildlife" in data["subject"]
```

Note: if the bootstrap command's actual registered name differs (check `pipeline.py` around `bootstrap_aesthetic_weights` — line 1377 defines the function; find its `@training.command(...)` decorator name), use that name in the test.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_learn_weights_cli.py -v`
Expected: FAIL — no such command

- [ ] **Step 3: Implement the three commands**

```python
@training.command("learn-weights")
@click.option("--feedback", required=True, type=click.Path(path_type=Path))
@click.option("--training-db", "training_db", required=True, type=click.Path(path_type=Path))
@click.option("--min-pairs", default=20, show_default=True)
@click.option("--dry-run", is_flag=True)
@click.option("--json-progress", is_flag=True)
def learn_weights(feedback, training_db, min_pairs, dry_run, json_progress):
    """Learn subject-axis weight profiles from star_feedback.jsonl.

    Blended profiles are written to the aesthetic_weights table; the next
    score/rescore run picks them up automatically (--training-db). The type
    axis is seeded from defaults if absent — score fusion only uses the DB
    when BOTH axes are present (see ModelSessions.aesthetic_weights).
    """
    from .score_fusion import TYPE_WEIGHTS
    from .training_weights_db import (
        open_training_db, ensure_schema, next_aesthetic_weights_version,
        upsert_aesthetic_weights, get_active_aesthetic_weights,
    )
    from .weight_trainer import learn_subject_weights

    results = learn_subject_weights(feedback, min_pairs=min_pairs)
    learned = {k: v for k, v in results.items() if v["source"] == "blended"}
    for label, info in results.items():
        msg = {"step": "learn-weights", "label": label, "status": info["source"],
               "n_pairs": info["n_pairs"], "alpha": round(info["alpha"], 3)}
        click.echo(json.dumps(msg) if json_progress
                   else f"  {label}: {info['source']} ({info['n_pairs']} pairs)")
    if dry_run or not learned:
        click.echo(json.dumps({"step": "learn-weights", "status": "done",
                               "written": 0}) if json_progress
                   else "Nothing written (dry run or no label reached min-pairs).")
        return

    conn = open_training_db(training_db)
    ensure_schema(conn)
    version = next_aesthetic_weights_version(conn)
    for label, info in learned.items():
        upsert_aesthetic_weights(conn, version, "subject", label, info["weights"])
    # Ensure the type axis exists so the fusion override activates.
    active = get_active_aesthetic_weights(conn)
    if not active.get("type"):
        for label, weights in TYPE_WEIGHTS.items():
            upsert_aesthetic_weights(conn, version, "type", label, weights)
    conn.close()
    click.echo(json.dumps({"step": "learn-weights", "status": "done",
                           "written": len(learned), "version": version})
               if json_progress else f"Wrote {len(learned)} learned profiles (v{version}).")


@training.command("show-weights")
@click.option("--training-db", "training_db", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--out", default=None, type=click.Path(path_type=Path))
def show_weights(training_db, out):
    """Dump active aesthetic weight profiles as editable JSON."""
    from .training_weights_db import open_training_db, get_active_aesthetic_weights
    conn = open_training_db(training_db)
    active = get_active_aesthetic_weights(conn)
    conn.close()
    text = json.dumps(active, indent=2, sort_keys=True)
    if out:
        Path(out).write_text(text, encoding="utf-8")
        click.echo(f"Wrote {out}")
    else:
        click.echo(text)


@training.command("set-weights")
@click.option("--training-db", "training_db", required=True, type=click.Path(path_type=Path))
@click.option("--file", "weights_file", required=True,
              type=click.Path(exists=True, path_type=Path))
def set_weights(training_db, weights_file):
    """Import hand-edited weight profiles ({'subject': {label: {key: w}}, 'type': ...}).

    Unknown labels are rejected; each profile is renormalized to sum 1.
    """
    from .genre_router import SUBJECTS, PHOTO_TYPES
    from .training_weights_db import (
        open_training_db, ensure_schema, next_aesthetic_weights_version,
        upsert_aesthetic_weights,
    )
    data = json.loads(Path(weights_file).read_text(encoding="utf-8"))
    valid = {"subject": set(SUBJECTS), "type": set(PHOTO_TYPES)}
    conn = open_training_db(training_db)
    ensure_schema(conn)
    version = next_aesthetic_weights_version(conn)
    written = 0
    for axis, labels in data.items():
        if axis not in valid:
            raise click.ClickException(f"Unknown axis {axis!r}")
        for label, weights in labels.items():
            if label not in valid[axis]:
                raise click.ClickException(f"Unknown {axis} label {label!r}")
            total = sum(float(v) for v in weights.values())
            if total <= 0:
                raise click.ClickException(f"{axis}/{label}: weights sum to {total}")
            upsert_aesthetic_weights(conn, version, axis, label,
                                     {k: float(v) / total for k, v in weights.items()})
            written += 1
    conn.close()
    click.echo(f"Imported {written} profiles as version {version}.")
```

- [ ] **Step 4: Run tests, full suite, commit**

Run: `pytest tests/test_learn_weights_cli.py -v && pytest -m "not slow" -q`
Expected: PASS

```bash
git add src/photo_workflow/pipeline.py tests/test_learn_weights_cli.py
git commit -m "feat(training): learn-weights / show-weights / set-weights commands"
```

---

### Task 6: Panel + runner wiring

**Files:**
- Modify: `lua/photonforge/runner.lua` (add `collect-star-feedback` and `learn-weights` to `build_cmd`; both need `--photon-db`/`--darktable-library`/`--training-db` args following the existing `collect-corrections` / `recalibrate` patterns in the same function)
- Modify: `lua/photonforge/panel.lua` (Training tab: one new button after `recalibrate_btn`)

**Interfaces:**
- Consumes: CLI commands from Tasks 3 and 5.
- Produces: "3 ⚖ Learn Weights" button that dispatches `collect-star-feedback` then `learn-weights` (two steps via `runner.run_all`, like `correction_loop_btn` does with its `loop_steps` list).

- [ ] **Step 1: Extend `build_cmd` in runner.lua**

Read the existing `elseif step == "collect-corrections"` / `"recalibrate"` branches (below line 120 in runner.lua) and add matching branches:

```lua
elseif step == "collect-star-feedback" then
  return base .. " --folder " .. shell_quote(folder)
            .. " --photon-db " .. shell_quote(db)
            .. " --darktable-library " .. shell_quote(get_dt_library_path())
elseif step == "learn-weights" then
  local drive = get_drive_root(dest)
  return base .. " --feedback " .. shell_quote(drive .. "star_feedback.jsonl")
            .. " --training-db " .. shell_quote(drive .. "training_weights.db")
```

Note: the training commands live under the `training` subgroup — check how `build_cmd` composes `base` for `collect-corrections` (it may already prefix `training `); mirror exactly. `get_dt_library_path()` — reuse however `collect-corrections` resolves the DT library path in runner.lua (do not invent a new mechanism).

- [ ] **Step 2: Add the panel button**

In `panel.lua`, after `recalibrate_btn` (line ~549):

```lua
local learn_weights_btn = dt.new_widget("button") {
  label = "3 \u{2696} Learn Weights",
  tooltip = "Harvest your star-rating changes from Darktable and learn "
         .. "per-genre scoring weights from them. Re-score afterwards to apply.",
  clicked_callback = function()
    local ok, err = pcall(function()
      save_entries()
      if runner.is_busy() then
        append_log("[BUSY] A PHOTONForge run is already in progress.")
        return
      end
      append_log("[WEIGHTS] Collecting star feedback + learning weights...")
      set_running(true)
      dt.control.dispatch(function()
        local steps2 = {"collect-star-feedback", "learn-weights"}
        local ok2, err2 = pcall(runner.run_all, steps2, append_log, update_status, update_progress)
        if not ok2 then append_log("[ERROR] learn-weights: " .. tostring(err2)) end
        clear_progress()
      end)
    end)
    if not ok then append_log("[ERROR] " .. tostring(err)) end
  end,
}
```

Add `learn_weights_btn` to the `training_tab` box after `recalibrate_btn`, and add both step names to `dev_step_combo`.

- [ ] **Step 3: Manual verification (no Lua test harness exists)**

Use the dev panel: "Show resolved command" for `collect-star-feedback` and `learn-weights` and confirm paths. Then run the button against a scored test folder and check `star_feedback.jsonl` appears on the cartridge root and the log reports learned labels.

- [ ] **Step 4: Commit + docs**

Update `dev-docs/training-loop-guide.md` with the new star-feedback loop section (per the docs-impact matrix in `dev-docs/architecture/doc-maintenance-protocol.md`).

```bash
git add lua/photonforge/runner.lua lua/photonforge/panel.lua dev-docs/training-loop-guide.md
git commit -m "feat(panel): Learn Weights button wires star-feedback loop"
```

---

## Self-Review Notes

- Spec coverage: stars persisted (T1), DT rating read (T2), harvest (T3), fit+blend (T4), write/inspect/apply (T5), UI (T6). Type-axis learning explicitly deferred (Global Constraints).
- Known risk: `ModelSessions.aesthetic_weights` requires BOTH axes present (`active.get("subject") and active.get("type")`) — handled in Task 5 by seeding type defaults on first learn.
- Known risk: `flags` semantics differ across DT versions for reject (0x8 vs rating=6 historically); verified against DT 5.x behavior during Task 2 test setup — if the real library disagrees, fix the mask in `read_darktable_rating`, not the callers.
