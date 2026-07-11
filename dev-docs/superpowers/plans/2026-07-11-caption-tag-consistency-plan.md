# Caption/Tag Consistency Checking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cross-check each photo's Florence-2 caption (the "description") against its assigned genre tags; when they disagree, flag the photo for tag training — turning the naming system into a free consistency oracle for the genre system.

**Architecture:** The genre router classifies from the CLIP image embedding; Florence-2 captions the same image independently. Two independent models agreeing is strong evidence the tag is right; disagreement is exactly the frame worth a human label. Phase 1 (this plan) is a deterministic lexicon matcher: caption text → candidate subject via per-subject keyword lists, compared against the tagged subject through a compatibility table (so "seascape" vs "landscape" never false-alarms). Inconsistent frames get `photon|train_candidate` (the active-learning tag the panel workflow already uses), `needs_review=1` in photonforge.db, and a JSONL audit trail. Phase 2 (optional follow-up, sketched in the final section, not tasked) upgrades the matcher to MobileCLIP text-tower similarity.

**Tech Stack:** Python 3.11, sqlite3, click, pytest. Reuses: `photon|train_candidate` handling in `applicator.lua` (rec.step == "train-candidate"), the `training` CLI group, the panel dispatch pattern.

## Global Constraints

- NFR-2.1: fully offline — Phase 1 uses only string matching; no new models at runtime.
- The check must never *change* a tag. It only flags. Corrections flow through the existing loop: user fixes the tag in DT → Collect Corrections → Recalibrate.
- Subjects only. Photo-type (how it was shot) is rarely inferable from a content caption — do not generate false alarms from the type axis.
- Captions are stored in `photos.semantic_name` (first line = caption, second line = EXIF summary — split on `\n` before matching; see `naming.generate_name`).
- A photo with no caption (name step not run, model unavailable → EXIF-only semantic_name) must be skipped silently, not flagged.

## Design: lexicon + compatibility table

Two data structures, both in the new module:

1. `SUBJECT_LEXICON: dict[str, list[str]]` — lowercase keyword/phrase lists per subject. Match against the caption with word-boundary regex. Multi-word phrases allowed ("city skyline").
2. `COMPATIBLE: dict[str, set[str]]` — subjects that must never be flagged against each other even when the lexicon says otherwise (landscape/seascape/sky/waterfall all describe overlapping scenes; people/pet appear together; building/monument/cityscape overlap).

Flag rule: flag only when the caption yields a **unique, unambiguous** subject vote (exactly one subject's lexicon matches) AND that subject is neither the tagged subject nor in its compatibility set. Bias hard toward precision — a false "inconsistent" flag erodes trust in the whole training loop.

---

### Task 1: consistency module (lexicon matcher)

**Files:**
- Create: `src/photo_workflow/consistency.py`
- Test: `tests/test_consistency.py`

**Interfaces:**
- Produces:
  - `predict_subject_from_caption(caption: str) -> tuple[str | None, list[str]]` — (unique subject or None, matched terms)
  - `check_consistency(caption: str, subject: str) -> ConsistencyResult`
  - `@dataclass ConsistencyResult: consistent: bool; caption_subject: str | None; tagged_subject: str; evidence: list[str]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_consistency.py
from photo_workflow.consistency import (
    ConsistencyResult, check_consistency, predict_subject_from_caption,
)


def test_unique_subject_match():
    subj, terms = predict_subject_from_caption("A brown bear catching a salmon in a river")
    assert subj == "wildlife"
    assert "bear" in terms


def test_ambiguous_caption_gives_none():
    # dog (pet) + mountains (landscape) -> two subjects vote -> no unique call
    subj, _ = predict_subject_from_caption("A dog running in front of snowy mountains")
    assert subj is None


def test_no_keywords_gives_none():
    subj, _ = predict_subject_from_caption("An interesting scene")
    assert subj is None


def test_inconsistent_when_unique_and_incompatible():
    r = check_consistency("A plate of pasta with basil on a wooden table", "landscape")
    assert not r.consistent
    assert r.caption_subject == "food"


def test_compatible_subjects_never_flag():
    # seascape caption vs landscape tag: overlapping scene classes
    r = check_consistency("Waves crashing on a rocky beach at sunset", "landscape")
    assert r.consistent


def test_matching_subject_is_consistent():
    r = check_consistency("A brown bear in a forest", "wildlife")
    assert r.consistent


def test_empty_or_exif_only_caption_is_consistent():
    assert check_consistency("", "wildlife").consistent
    assert check_consistency("50mm | f/2.8 | 1/500s | ISO 200", "wildlife").consistent
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_consistency.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement**

```python
# src/photo_workflow/consistency.py
"""Caption <-> genre-tag consistency check (Phase 1: lexicon matcher).

The genre router classifies from the CLIP image embedding; Florence-2
captions the image independently. When both agree, the tag is almost
certainly right; when a caption unambiguously names a different subject,
that frame is the highest-value candidate for tag training.

Precision-first: flag only a UNIQUE lexicon vote that is INCOMPATIBLE with
the tagged subject. Everything ambiguous passes as consistent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .genre_router import SUBJECTS

SUBJECT_LEXICON: dict[str, list[str]] = {
    "people": ["man", "woman", "person", "people", "boy", "girl", "child",
               "children", "couple", "crowd", "bride", "groom", "portrait of"],
    "pet": ["dog", "puppy", "cat", "kitten"],
    "wildlife": ["bear", "bird", "eagle", "deer", "elephant", "giraffe", "zebra",
                 "lion", "fox", "wolf", "seal", "whale", "owl", "squirrel",
                 "reindeer", "moose", "puffin", "wild animal"],
    "plant": ["flower", "flowers", "blossom", "leaf", "leaves", "tree bark",
              "mushroom", "plant", "rose", "tulip", "cactus", "fern"],
    "landscape": ["mountain", "mountains", "valley", "hills", "meadow", "forest",
                  "desert", "glacier", "canyon", "field of", "countryside"],
    "seascape": ["ocean", "sea", "waves", "beach", "coast", "coastline",
                 "cliffs above the sea", "lighthouse"],
    "sky": ["sunset sky", "clouds", "night sky", "stars", "milky way", "aurora",
            "northern lights", "moon", "rainbow"],
    "cityscape": ["city skyline", "skyline", "cityscape", "downtown",
                  "city at night", "aerial view of a city"],
    "building": ["building", "house", "cathedral", "church", "castle", "skyscraper",
                 "barn", "cabin", "bridge", "facade"],
    "vehicle": ["car", "truck", "motorcycle", "bus", "train", "airplane", "boat",
                "ship", "bicycle", "tractor"],
    "food": ["plate of", "food", "meal", "pasta", "pizza", "cake", "dessert",
             "sandwich", "salad", "coffee", "breakfast", "dinner"],
    "object": ["watch", "camera", "bottle", "book", "tool", "statue of a"],
    "abstract": ["abstract", "pattern", "texture", "light trails", "bokeh balls"],
    "monument": ["monument", "memorial", "statue", "ruins", "temple", "pyramid"],
    "waterfall": ["waterfall", "cascade", "falls"],
}

# Subjects that describe overlapping scenes: never flag within a set.
COMPATIBLE: dict[str, set[str]] = {
    "landscape": {"seascape", "sky", "waterfall", "plant"},
    "seascape": {"landscape", "sky", "vehicle"},          # boats in seascapes
    "sky": {"landscape", "seascape"},
    "waterfall": {"landscape"},
    "people": {"pet"},
    "pet": {"people", "wildlife"},
    "wildlife": {"pet"},
    "building": {"monument", "cityscape"},
    "monument": {"building", "cityscape"},
    "cityscape": {"building", "monument", "vehicle"},
    "vehicle": {"cityscape"},
    "plant": {"landscape"},
    "food": {"object"},
    "object": {"food", "abstract"},
    "abstract": {"object"},
}

_WORD_RE_CACHE: dict[str, re.Pattern] = {}


def _term_matches(term: str, caption_lc: str) -> bool:
    pat = _WORD_RE_CACHE.get(term)
    if pat is None:
        pat = re.compile(r"\b" + re.escape(term) + r"\b")
        _WORD_RE_CACHE[term] = pat
    return bool(pat.search(caption_lc))


def predict_subject_from_caption(caption: str) -> tuple[str | None, list[str]]:
    """Unique subject the caption names, or (None, []) when 0 or 2+ subjects vote."""
    caption_lc = (caption or "").lower()
    votes: dict[str, list[str]] = {}
    for subject in SUBJECTS:
        hits = [t for t in SUBJECT_LEXICON.get(subject, []) if _term_matches(t, caption_lc)]
        if hits:
            votes[subject] = hits
    if len(votes) != 1:
        return None, []
    subject, hits = next(iter(votes.items()))
    return subject, hits


@dataclass
class ConsistencyResult:
    consistent: bool
    caption_subject: str | None
    tagged_subject: str
    evidence: list[str] = field(default_factory=list)


def check_consistency(caption: str, subject: str) -> ConsistencyResult:
    """Flag only a unique caption subject that is incompatible with the tag."""
    caption_subject, evidence = predict_subject_from_caption(caption)
    if caption_subject is None or caption_subject == subject:
        return ConsistencyResult(True, caption_subject, subject, evidence)
    if caption_subject in COMPATIBLE.get(subject, set()):
        return ConsistencyResult(True, caption_subject, subject, evidence)
    return ConsistencyResult(False, caption_subject, subject, evidence)
```

- [ ] **Step 4: Run tests, commit**

Run: `pytest tests/test_consistency.py -v` — Expected: PASS

```bash
git add src/photo_workflow/consistency.py tests/test_consistency.py
git commit -m "feat(training): caption/tag consistency lexicon matcher"
```

---

### Task 2: check-consistency command

**Files:**
- Modify: `src/photo_workflow/pipeline.py` (new command in the `training` group)
- Test: `tests/test_check_consistency_cli.py`

**Interfaces:**
- Consumes: `check_consistency` (Task 1); `photos.semantic_name`, `photos.genres` columns.
- Produces:
  - JSON records `{"step": "train-candidate", "file": <filename>, "reason": "caption-mismatch", "caption_subject": ..., "tagged_subject": ...}` — **the applicator already attaches `photon|train_candidate` for `step == "train-candidate"`** (`applicator.lua:80-89`), so the Lua side needs zero changes.
  - `needs_review=1` written back to photonforge.db for flagged rows (so a subsequent re-score/refresh keeps them YELLOW under the 2026-07-11 color-label plan).
  - Audit trail appended to `consistency_flags.jsonl` next to the DB.
- CLI: `photo-workflow training check-consistency --folder F --db P [--flags PATH] [--dry-run] [--json-progress]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_check_consistency_cli.py
import json
from click.testing import CliRunner
from photo_workflow.pipeline import cli
from photo_workflow import photondb


def _seed(tmp_path, filename, caption, subject):
    conn = photondb.open_db(tmp_path / "photos")
    photondb.ensure_schema(conn)
    photondb.insert_photo(conn, "SHOOT1", filename, filename, None)
    conn.execute(
        "UPDATE photos SET semantic_name=?, genres=? WHERE filename=?",
        (caption, json.dumps({"subject": subject, "photo_type": "scenic"}), filename))
    conn.commit(); conn.close()
    return tmp_path / "photonforge.db"


def test_flags_mismatch_and_sets_needs_review(tmp_path):
    db = _seed(tmp_path, "a.jpg", "A plate of pasta on a table\n50mm | f/2.8", "landscape")
    result = CliRunner().invoke(cli, [
        "training", "check-consistency", "--folder", "SHOOT1",
        "--db", str(db), "--json-progress"])
    assert result.exit_code == 0, result.output
    recs = [json.loads(l) for l in result.output.splitlines() if l.strip()]
    tc = [r for r in recs if r.get("step") == "train-candidate"]
    assert len(tc) == 1 and tc[0]["file"] == "a.jpg"
    assert tc[0]["caption_subject"] == "food"

    import sqlite3
    conn = sqlite3.connect(db)
    assert conn.execute(
        "SELECT needs_review FROM photos WHERE filename='a.jpg'").fetchone()[0] == 1
    assert (tmp_path / "consistency_flags.jsonl").exists()


def test_consistent_photo_untouched(tmp_path):
    db = _seed(tmp_path, "b.jpg", "A brown bear in a forest", "wildlife")
    result = CliRunner().invoke(cli, [
        "training", "check-consistency", "--folder", "SHOOT1",
        "--db", str(db), "--json-progress"])
    recs = [json.loads(l) for l in result.output.splitlines() if l.strip()]
    assert not [r for r in recs if r.get("step") == "train-candidate"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_check_consistency_cli.py -v`
Expected: FAIL — no such command

- [ ] **Step 3: Implement**

```python
@training.command("check-consistency")
@click.option("--folder", required=True)
@click.option("--db", "db_path", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--flags", "flags_path", default=None, type=click.Path(path_type=Path),
              help="consistency_flags.jsonl (default: next to the DB)")
@click.option("--dry-run", is_flag=True)
@click.option("--json-progress", is_flag=True)
def check_consistency_cmd(folder, db_path, flags_path, dry_run, json_progress):
    """Cross-check Florence-2 captions against genre tags; flag mismatches.

    Flagged photos get needs_review=1 in the DB, a train-candidate record
    (the Darktable applicator attaches photon|train_candidate), and a line in
    consistency_flags.jsonl. Tags are never changed here — fix them in DT,
    then Collect Corrections + Recalibrate.
    """
    import sqlite3 as _sqlite3
    from datetime import datetime, timezone
    from .consistency import check_consistency
    from .photondb import sanitize_table_name

    if flags_path is None:
        flags_path = db_path.parent / "consistency_flags.jsonl"
    table = sanitize_table_name(folder)
    conn = _sqlite3.connect(str(db_path)); conn.row_factory = _sqlite3.Row
    rows = conn.execute(
        "SELECT filename, semantic_name, genres, primary_genre FROM photos "
        "WHERE folder=? AND is_duplicate=0 AND semantic_name != ''", (table,)
    ).fetchall()

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    flagged = 0
    flag_lines: list[dict] = []
    for i, row in enumerate(rows, 1):
        caption = (row["semantic_name"] or "").split("\n", 1)[0]
        try:
            subject = json.loads(row["genres"] or "{}").get(
                "subject", row["primary_genre"] or "general")
        except json.JSONDecodeError:
            subject = row["primary_genre"] or "general"
        if subject not in SUBJECT_LEXICON_SUBJECTS:  # see note below
            continue
        result = check_consistency(caption, subject)
        if result.consistent:
            continue
        flagged += 1
        rec = {"step": "train-candidate", "file": row["filename"],
               "reason": "caption-mismatch",
               "caption_subject": result.caption_subject,
               "tagged_subject": subject, "evidence": result.evidence}
        if json_progress:
            click.echo(json.dumps(rec))
        flag_lines.append({**rec, "folder": folder, "flagged_at": now_iso})
        if not dry_run:
            conn.execute(
                "UPDATE photos SET needs_review=1 WHERE folder=? AND filename=?",
                (table, row["filename"]))
        if json_progress and i % 25 == 0:
            click.echo(json.dumps({"step": "_progress", "done": i, "total": len(rows)}))

    if not dry_run:
        conn.commit()
        if flag_lines:
            with open(flags_path, "a", encoding="utf-8") as f:
                for line in flag_lines:
                    f.write(json.dumps(line) + "\n")
    conn.close()
    done = {"step": "check-consistency", "status": "done",
            "flagged": flagged, "checked": len(rows)}
    click.echo(json.dumps(done) if json_progress
               else f"Flagged {flagged}/{len(rows)} photos for tag training.")
```

Note on `SUBJECT_LEXICON_SUBJECTS`: import `from .consistency import SUBJECT_LEXICON` and use `subject not in SUBJECT_LEXICON` — skips rows whose stored subject predates the current taxonomy instead of flagging them.

- [ ] **Step 4: Run tests, full suite, commit**

Run: `pytest tests/test_check_consistency_cli.py -v && pytest -m "not slow" -q`
Expected: PASS

```bash
git add src/photo_workflow/pipeline.py tests/test_check_consistency_cli.py
git commit -m "feat(training): check-consistency flags caption/tag mismatches"
```

---

### Task 3: Panel + runner wiring

**Files:**
- Modify: `lua/photonforge/runner.lua` (`build_cmd` branch for `check-consistency`: `--db <photonforge.db> --folder <folder>` — same args as the `dedup` branch at runner.lua:96-98)
- Modify: `lua/photonforge/panel.lua` (Training tab: "Check Consistency" button next to `refresh_review_btn`, line ~761; add to `dev_step_combo`)

**Interfaces:**
- Consumes: the CLI from Task 2. Progress + `train-candidate` records flow through the existing `runner.run_step → applicator.apply` path unchanged.

- [ ] **Step 1: runner.lua branch**

```lua
elseif step == "check-consistency" then
  return base .. " --db " .. shell_quote(db) .. " --folder " .. shell_quote(folder)
```

(Verify how the training-group commands compose `base` — mirror the `collect-corrections` branch's prefixing exactly.)

- [ ] **Step 2: panel.lua button**

```lua
local consistency_btn = dt.new_widget("button") {
  label = "\u{2194} Check Consistency",
  tooltip = "Cross-check Florence-2 captions against genre tags. Mismatches "
         .. "get photon|train_candidate — filter, fix the tag, then "
         .. "Collect Corrections + Recalibrate.",
  clicked_callback = function()
    dispatch_step("check-consistency",
      "[CONSIST] Checking captions against genre tags...",
      "[CONSIST] Done. Filter by 'photon|train_candidate' to review flags.")
  end,
}
```

Place it in the row with `sync_tags_btn` / `refresh_review_btn` in `training_tab`.

- [ ] **Step 3: Manual verification**

Dev panel → "Show resolved command" for `check-consistency`; then run against a scored+named test folder; confirm flagged images show `photon|train_candidate` in DT and `consistency_flags.jsonl` lands on the cartridge root.

- [ ] **Step 4: Docs + commit**

Add the consistency step to `dev-docs/training-loop-guide.md` (it becomes step 0 of the correction loop: Check Consistency → review flags → fix tags → Collect Corrections → Recalibrate).

```bash
git add lua/photonforge/runner.lua lua/photonforge/panel.lua dev-docs/training-loop-guide.md
git commit -m "feat(panel): Check Consistency button"
```

---

## Phase 2 sketch (not tasked — future work)

Replace/augment the lexicon with MobileCLIP text-tower similarity:
- Provisioning: export the MobileCLIP **text encoder** to ONNX INT8 alongside the image tower (`scripts/provision_models.sh`), ship tokenizer.
- Runtime: embed the caption text, cosine-compare against the same subject prototypes the router uses; flag when `argmax(text_sim)` disagrees with the tagged subject by a margin AND the image-side router also had low margin.
- Benefit: catches mismatches the lexicon can't ("a person paragliding over cliffs" → people vs landscape), and the margin is tunable. Cost: one more ONNX session under the KPM-1.3 RSS budget — measure before enabling by default.
- The `check-consistency` CLI surface, DB writes, and Lua flow are unchanged; only `check_consistency()`'s internals grow a second expert.
