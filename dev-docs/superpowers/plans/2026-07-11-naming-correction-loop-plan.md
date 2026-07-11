# Naming Correction Loop (EARS-style) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user correct Florence-2 naming mistakes through a structured semantic-formula form (EARS-style: fixed slots, controlled phrasing); accumulate the corrections as a training corpus that (a) fixes the photo immediately, (b) fine-tunes the captioner offline, and (c) eventually enables a smaller specialized model.

**Architecture:** A caption formula with four slots — `[qualifier] SUBJECT ACTION [SETTING]` — renders deterministic, trainable captions the way EARS templates render requirements. Corrections are captured via CLI (and a panel form) into `naming_corrections.jsonl` on the cartridge; the corrected caption is applied to photonforge.db + the DT description immediately. A corpus exporter materializes (image, caption) pairs; a provisioning-time LoRA fine-tune script (dev machine, NOT the Yoga — NFR-2.1 allows internet/heavy compute at provisioning) produces a new Florence-2 checkpoint that re-exports through the existing ONNX INT8 path. A keyword-recall eval harness gates deployment: the new model must beat the old one on held-out corrections before `models/florence2_int8` is replaced.

**Tech Stack:** Python 3.11, click, pytest (runtime side). Fine-tune side (dev machine only): PyTorch + transformers + peft (LoRA), optimum for ONNX export — mirrors how `scripts/provision_models.sh` sources models today.

## Global Constraints

- NFR-2.1: runtime stays offline. Fine-tuning and re-export happen at provisioning time on the dev machine; the Yoga only ever receives a vendored `models/florence2_int8/` directory.
- KPM-1.2: any replacement model must still infer ≤ 2.5 s/image on i7-7500U. The INT8 export + benchmark step is mandatory before swap-in.
- The semantic formula must render captions in the same register Florence-2 was trained on (lowercase-ish natural sentences, "A bear catching a fish in a river"), NOT tag-speak — otherwise fine-tuning teaches the model a new dialect from ~50 samples, which degrades it.
- Corrections JSONL lives on the cartridge root next to `genre_labels.jsonl` (same last-write-wins convention).
- Do not rename files on disk from a caption correction. The caption is metadata (`semantic_name`, DT description). File naming policy is out of scope here.

## The semantic formula (the contract)

```
caption := "A" [qualifier] subject action [setting]
qualifier := adjective phrase        e.g. "close-up of a", "silhouetted"   (optional)
subject   := noun phrase             e.g. "brown bear", "old fisherman"    (required)
action    := verb phrase or state    e.g. "catching a salmon", "at rest"   (required; "standing"/"sitting" allowed)
setting   := prepositional phrase    e.g. "in a rushing river at dusk"     (optional)
```

Rendered examples:
- subject="brown bear", action="catching a salmon", setting="in a rushing river" → `"A brown bear catching a salmon in a rushing river"`
- qualifier="close-up of a", subject="dew-covered rose", action="blooming" → `"A close-up of a dew-covered rose blooming"`

Why slots instead of free text: consistent syntax → the fine-tune corpus teaches *content* corrections, not style drift; slot values are reusable for future keyword/tag extraction; and the form is faster to fill than composing a sentence.

---

### Task 1: formula renderer + corrections store

**Files:**
- Create: `src/photo_workflow/naming_corrections.py`
- Test: `tests/test_naming_corrections.py`

**Interfaces:**
- Produces:
  - `render_caption(subject: str, action: str, setting: str = "", qualifier: str = "") -> str`
  - `@dataclass CaptionCorrection: filename, source_folder, old_caption, subject, action, setting, qualifier, caption, labeled_at, labeler`
  - `append_correction(path: Path, corr: CaptionCorrection) -> None`
  - `load_corrections(path: Path) -> list[CaptionCorrection]` (last-write-wins per (source_folder, filename))

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_naming_corrections.py
from pathlib import Path
from photo_workflow.naming_corrections import (
    CaptionCorrection, append_correction, load_corrections, render_caption,
)


def test_render_full_formula():
    assert render_caption("brown bear", "catching a salmon",
                          setting="in a rushing river") \
        == "A brown bear catching a salmon in a rushing river"


def test_render_with_qualifier_and_article_folding():
    # qualifier already carries its own article: don't produce "A a close-up..."
    assert render_caption("dew-covered rose", "blooming",
                          qualifier="close-up of a") \
        == "A close-up of a dew-covered rose blooming"


def test_render_minimal_and_whitespace_hygiene():
    assert render_caption("  lighthouse ", " standing ") == "A lighthouse standing"


def test_render_requires_subject_and_action():
    import pytest
    with pytest.raises(ValueError):
        render_caption("", "running")
    with pytest.raises(ValueError):
        render_caption("dog", "")


def test_corrections_roundtrip_last_write_wins(tmp_path):
    p = tmp_path / "naming_corrections.jsonl"
    c1 = CaptionCorrection("a.jpg", "S1", "old", "dog", "running", "", "",
                           render_caption("dog", "running"), "2026-07-11T00:00:00", "alex")
    c2 = CaptionCorrection("a.jpg", "S1", "old", "red fox", "running", "", "",
                           render_caption("red fox", "running"), "2026-07-11T00:01:00", "alex")
    append_correction(p, c1)
    append_correction(p, c2)
    loaded = load_corrections(p)
    assert len(loaded) == 1
    assert loaded[0].subject == "red fox"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_naming_corrections.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement**

```python
# src/photo_workflow/naming_corrections.py
"""EARS-style caption corrections: semantic formula -> training captions.

caption := "A" [qualifier] subject action [setting]

Slot phrasing stays in Florence-2's native register (natural lowercase
sentences) so fine-tuning corrects CONTENT without teaching a new style.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


def render_caption(subject: str, action: str, setting: str = "",
                   qualifier: str = "") -> str:
    subject = " ".join(subject.split())
    action = " ".join(action.split())
    setting = " ".join(setting.split())
    qualifier = " ".join(qualifier.split())
    if not subject or not action:
        raise ValueError("subject and action are required")
    parts = [p for p in (qualifier, subject, action, setting) if p]
    body = " ".join(parts)
    return "A " + body[0].lower() + body[1:] if not body[0].isdigit() else "A " + body


@dataclass
class CaptionCorrection:
    filename: str
    source_folder: str
    old_caption: str
    subject: str
    action: str
    setting: str
    qualifier: str
    caption: str
    labeled_at: str
    labeler: str


def append_correction(path: Path, corr: CaptionCorrection) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(corr)) + "\n")


def load_corrections(path: Path) -> list[CaptionCorrection]:
    """Last-write-wins per (source_folder, filename)."""
    result: dict[tuple[str, str], CaptionCorrection] = {}
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                corr = CaptionCorrection(**d)
            except (json.JSONDecodeError, TypeError):
                continue
            result[(corr.source_folder, corr.filename)] = corr
    return list(result.values())
```

(Adjust `render_caption`'s article logic during implementation if a test shows an edge — the tests above are the contract.)

- [ ] **Step 4: Run tests, commit**

Run: `pytest tests/test_naming_corrections.py -v` — Expected: PASS

```bash
git add src/photo_workflow/naming_corrections.py tests/test_naming_corrections.py
git commit -m "feat(naming): EARS-style caption formula + corrections store"
```

---

### Task 2: correct-name command (capture + immediate apply)

**Files:**
- Modify: `src/photo_workflow/pipeline.py` (new command in the `training` group)
- Test: `tests/test_correct_name_cli.py`

**Interfaces:**
- Consumes: Task 1 module; `photondb.update_semantic`; `darktable_bridge.xmp_sidecar_path`/`_write_xmp` conventions.
- Produces CLI:
  `photo-workflow training correct-name --folder F --db P --file IMG_1234.ARW --subject "brown bear" --action "catching a salmon" [--setting ...] [--qualifier ...] [--corrections PATH] [--json-progress]`
  - Appends to `naming_corrections.jsonl`
  - Updates `photos.semantic_name` (caption line replaced, EXIF line preserved)
  - Emits `{"step": "name", "file": ..., "semantic_name": ...}` so the applicator sets the DT description via the existing `rec.step == "name"` branch (`applicator.lua:171-174`) — zero Lua changes for apply.
  - Interactive mode: with no `--subject/--action` flags, prompt for each slot (`click.prompt`) showing the current caption first.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_correct_name_cli.py
import json
from click.testing import CliRunner
from photo_workflow.pipeline import cli
from photo_workflow import photondb


def test_correct_name_updates_db_and_corpus(tmp_path):
    conn = photondb.open_db(tmp_path / "photos")
    photondb.ensure_schema(conn)
    photondb.insert_photo(conn, "SHOOT1", "a.jpg", "a.jpg", None)
    conn.execute("UPDATE photos SET semantic_name=? WHERE filename='a.jpg'",
                 ("A dog running\n50mm | f/2.8",))
    conn.commit(); conn.close()
    db = tmp_path / "photonforge.db"
    corr = tmp_path / "naming_corrections.jsonl"

    result = CliRunner().invoke(cli, [
        "training", "correct-name", "--folder", "SHOOT1", "--db", str(db),
        "--file", "a.jpg", "--subject", "red fox", "--action", "running",
        "--setting", "across a snowy field",
        "--corrections", str(corr), "--json-progress"])
    assert result.exit_code == 0, result.output

    import sqlite3
    c = sqlite3.connect(db)
    name = c.execute("SELECT semantic_name FROM photos WHERE filename='a.jpg'").fetchone()[0]
    assert name.splitlines()[0] == "A red fox running across a snowy field"
    assert name.splitlines()[1] == "50mm | f/2.8"        # EXIF line preserved

    entry = json.loads(corr.read_text().splitlines()[0])
    assert entry["old_caption"] == "A dog running"
    assert entry["caption"] == "A red fox running across a snowy field"

    recs = [json.loads(l) for l in result.output.splitlines() if l.strip()]
    assert any(r.get("step") == "name" and
               r["semantic_name"].startswith("A red fox") for r in recs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_correct_name_cli.py -v`
Expected: FAIL — no such command

- [ ] **Step 3: Implement**

```python
@training.command("correct-name")
@click.option("--folder", required=True)
@click.option("--db", "db_path", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--file", "filename", required=True)
@click.option("--subject", default=None)
@click.option("--action", default=None)
@click.option("--setting", default="")
@click.option("--qualifier", default="")
@click.option("--corrections", "corrections_path", default=None,
              type=click.Path(path_type=Path))
@click.option("--json-progress", is_flag=True)
def correct_name(folder, db_path, filename, subject, action, setting,
                 qualifier, corrections_path, json_progress):
    """Correct a photo's caption via the semantic formula.

    caption := "A" [qualifier] subject action [setting]

    Applies immediately (DB + DT description via the applicator) and appends
    the correction to naming_corrections.jsonl for offline fine-tuning.
    """
    import getpass
    import sqlite3 as _sqlite3
    from datetime import datetime, timezone
    from .naming_corrections import (
        CaptionCorrection, append_correction, render_caption,
    )
    from .photondb import sanitize_table_name, update_semantic

    if corrections_path is None:
        corrections_path = db_path.parent / "naming_corrections.jsonl"
    table = sanitize_table_name(folder)
    conn = _sqlite3.connect(str(db_path)); conn.row_factory = _sqlite3.Row
    row = conn.execute(
        "SELECT semantic_name FROM photos WHERE folder=? AND filename=?",
        (table, filename)).fetchone()
    if row is None:
        raise click.ClickException(f"{filename} not found in folder {folder}")
    lines = (row["semantic_name"] or "").split("\n")
    old_caption, exif_tail = lines[0], lines[1:]

    if subject is None:
        click.echo(f"Current caption: {old_caption or '(none)'}")
        subject = click.prompt("Subject (noun phrase)")
        action = click.prompt("Action/state (verb phrase)")
        setting = click.prompt("Setting (prepositional phrase)", default="")
        qualifier = click.prompt("Qualifier", default="")
    if action is None:
        raise click.ClickException("--action is required with --subject")

    caption = render_caption(subject, action, setting=setting, qualifier=qualifier)
    new_semantic = "\n".join([caption] + exif_tail)
    update_semantic(conn, table, filename, new_semantic)
    conn.close()

    append_correction(corrections_path, CaptionCorrection(
        filename=filename, source_folder=folder, old_caption=old_caption,
        subject=subject, action=action, setting=setting, qualifier=qualifier,
        caption=caption,
        labeled_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        labeler=getpass.getuser() or "anon"))

    if json_progress:
        click.echo(json.dumps({"step": "name", "file": filename,
                               "status": "ok", "semantic_name": new_semantic}))
    else:
        click.echo(f"Corrected: {caption}")
```

Also regenerate the XMP sidecar if one exists for the photo (call the same write path the name step uses — check how the staged `name` command writes XMP after `update_semantic` and mirror it; if it doesn't, skip XMP here too and note it).

- [ ] **Step 4: Run tests, full suite, commit**

Run: `pytest tests/test_correct_name_cli.py -v && pytest -m "not slow" -q`
Expected: PASS

```bash
git add src/photo_workflow/pipeline.py tests/test_correct_name_cli.py
git commit -m "feat(training): correct-name captures formula-based caption corrections"
```

---

### Task 3: Panel form (Correct Name section)

**Files:**
- Modify: `lua/photonforge/panel.lua` (Training tab: "CORRECT NAME" section — 4 entry widgets + Apply button acting on the current DT selection)
- Modify: `lua/photonforge/runner.lua` (a `run_correct_name(args, append_log)` helper that shells the CLI with explicit flags; the generic `build_cmd(step)` shape doesn't fit per-image args)

**Interfaces:**
- Consumes: `training correct-name` CLI (Task 2); `dt.gui.selection()`; `runner` busy/kill machinery.
- Behavior: exactly one selected image required; on Apply, runs the CLI with `--file <selection.filename>` and the four slot values; the emitted `step:"name"` record flows through `applicator.apply` to set `img.description`.

- [ ] **Step 1: Add `run_correct_name` to runner.lua**

```lua
function M.run_correct_name(opts, append_log, update_progress)
  -- opts = {folder=, db=, file=, subject=, action=, setting=, qualifier=}
  local cmd = cli() .. " training correct-name --json-progress"
      .. " --folder " .. shell_quote(opts.folder)
      .. " --db " .. shell_quote(opts.db)
      .. " --file " .. shell_quote(opts.file)
      .. " --subject " .. shell_quote(opts.subject)
      .. " --action " .. shell_quote(opts.action)
  if opts.setting ~= "" then cmd = cmd .. " --setting " .. shell_quote(opts.setting) end
  if opts.qualifier ~= "" then cmd = cmd .. " --qualifier " .. shell_quote(opts.qualifier) end
  return M.run_command(cmd, append_log, update_progress)  -- reuse the internal exec+parse helper run_step uses
end
```

(Adapt to runner.lua's actual internals: find the function `run_step` uses to execute a command and stream JSON records into `applicator.apply` — expose/reuse that, do NOT duplicate the popen/parse loop.)

- [ ] **Step 2: Add the panel section**

In `panel.lua`'s `training_tab`, after the correction-loop widgets:

```lua
  local cn_subject   = dt.new_widget("entry") { placeholder = "subject (required)\u{2026}" }
  local cn_action    = dt.new_widget("entry") { placeholder = "action/state (required)\u{2026}" }
  local cn_setting   = dt.new_widget("entry") { placeholder = "setting (optional)\u{2026}" }
  local cn_qualifier = dt.new_widget("entry") { placeholder = "qualifier (optional)\u{2026}" }
  local cn_current   = dt.new_widget("label") { label = "" }

  local cn_apply = dt.new_widget("button") {
    label = "\u{270E} Correct Name",
    tooltip = "Rewrite the selected image's caption as:\n"
           .. "A [qualifier] SUBJECT ACTION [setting]\n"
           .. "Applies immediately and adds a training sample.",
    clicked_callback = function()
      local ok, err = pcall(function()
        save_entries()
        local sel = dt.gui.selection()
        if sel == nil or #sel ~= 1 then
          append_log("[NAME] Select exactly one image to correct.")
          return
        end
        if cn_subject.text == "" or cn_action.text == "" then
          append_log("[NAME] Subject and action are required.")
          return
        end
        local dest = config.read("dest_path")
        runner.run_correct_name({
          folder = get_folder_name_public(dest),   -- expose runner's get_folder_name or recompute
          db = get_db_path_public(dest),
          file = sel[1].filename,
          subject = cn_subject.text, action = cn_action.text,
          setting = cn_setting.text, qualifier = cn_qualifier.text,
        }, append_log, update_progress)
        append_log("[NAME] Applied. Sample added to naming_corrections.jsonl.")
      end)
      if not ok then append_log("[ERROR] correct-name: " .. tostring(err)) end
    end,
  }
```

Show the current caption when the selection changes: extend the existing `selection-changed` listener in `tag_manager.register_selection_listener` is the wrong place (single-purpose); register a second event in panel.lua that sets `cn_current.label = (sel[1].description or ""):match("^[^\n]*")` when exactly one image is selected.

- [ ] **Step 3: Manual verification**

In DT: select a named image → current caption shows; fill subject/action → Apply; confirm the description updates in the metadata panel and a JSONL line appears on the cartridge.

- [ ] **Step 4: Commit**

```bash
git add lua/photonforge/panel.lua lua/photonforge/runner.lua
git commit -m "feat(panel): Correct Name form (semantic formula) in Training tab"
```

---

### Task 4: corpus exporter

**Files:**
- Modify: `src/photo_workflow/pipeline.py` (`training export-naming-corpus`)
- Test: `tests/test_export_naming_corpus.py`

**Interfaces:**
- Consumes: `load_corrections` (Task 1); source photos on the cartridge.
- Produces: a fine-tune-ready directory:
  ```
  <out>/
    captions.jsonl      # {"image": "images/<folder>__<file>.jpg", "caption": ...,
                        #  "old_caption": ..., "split": "train"|"holdout"}
    images/<folder>__<file>.jpg   # RGB, long edge 768 (matches INFER_IMG_SIZE)
  ```
- Every 5th correction (deterministic: sorted by filename, index % 5 == 0) goes to `holdout` — the eval set for Task 5's gate. RAW sources are decoded via `raw_loader.load_rgb` (same loader naming uses).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_export_naming_corpus.py
import json
import numpy as np
import cv2
from click.testing import CliRunner
from photo_workflow.pipeline import cli
from photo_workflow.naming_corrections import CaptionCorrection, append_correction, render_caption


def test_export_writes_images_and_captions(tmp_path):
    src = tmp_path / "SHOOT1"; src.mkdir()
    for i in range(6):
        cv2.imwrite(str(src / f"img{i}.jpg"),
                    np.random.randint(0, 255, (100, 160, 3), dtype=np.uint8))
    corr = tmp_path / "naming_corrections.jsonl"
    for i in range(6):
        append_correction(corr, CaptionCorrection(
            f"img{i}.jpg", "SHOOT1", "old", "red fox", "running", "", "",
            render_caption("red fox", "running"), "2026-07-11T00:00:00", "alex"))
    out = tmp_path / "corpus"

    result = CliRunner().invoke(cli, [
        "training", "export-naming-corpus", "--corrections", str(corr),
        "--source-dir", str(src), "--out", str(out)])
    assert result.exit_code == 0, result.output

    lines = [json.loads(l) for l in (out / "captions.jsonl").read_text().splitlines()]
    assert len(lines) == 6
    assert sum(1 for l in lines if l["split"] == "holdout") == 2  # indices 0 and 5
    for l in lines:
        assert (out / l["image"]).exists()
```

(Holdout count: with `sorted()` order `img0..img5`, indices 0 and 5 satisfy `i % 5 == 0` — keep the test's arithmetic in sync with the implementation.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_export_naming_corpus.py -v`
Expected: FAIL — no such command

- [ ] **Step 3: Implement**

```python
@training.command("export-naming-corpus")
@click.option("--corrections", "corrections_path", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--source-dir", "source_dir", required=True,
              type=click.Path(exists=True, path_type=Path),
              help="Folder containing the referenced photos")
@click.option("--out", "out_dir", required=True, type=click.Path(path_type=Path))
@click.option("--long-edge", default=768, show_default=True)
def export_naming_corpus(corrections_path, source_dir, out_dir, long_edge):
    """Materialize (image, caption) pairs for offline Florence-2 fine-tuning.

    Every 5th correction (sorted by filename) is tagged split=holdout for the
    eval gate. Run on the dev machine; the output directory feeds
    scripts/finetune_florence2.py.
    """
    import cv2
    from .naming_corrections import load_corrections
    from .raw_loader import load_rgb

    corrections = sorted(load_corrections(corrections_path),
                         key=lambda c: (c.source_folder, c.filename))
    (out_dir / "images").mkdir(parents=True, exist_ok=True)
    written = 0
    with open(out_dir / "captions.jsonl", "w", encoding="utf-8") as f:
        for i, corr in enumerate(corrections):
            src = source_dir / corr.filename
            if not src.exists():
                click.echo(f"  skip (missing): {corr.filename}")
                continue
            img = load_rgb(src)
            h, w = img.shape[:2]
            scale = long_edge / max(h, w)
            if scale < 1.0:
                img = cv2.resize(img, (int(w * scale), int(h * scale)))
            rel = f"images/{corr.source_folder}__{Path(corr.filename).stem}.jpg"
            cv2.imwrite(str(out_dir / rel), img)
            f.write(json.dumps({
                "image": rel, "caption": corr.caption,
                "old_caption": corr.old_caption,
                "split": "holdout" if i % 5 == 0 else "train"}) + "\n")
            written += 1
    click.echo(f"Exported {written} pairs to {out_dir}")
```

- [ ] **Step 4: Run tests, commit**

Run: `pytest tests/test_export_naming_corpus.py -v && pytest -m "not slow" -q`
Expected: PASS

```bash
git add src/photo_workflow/pipeline.py tests/test_export_naming_corpus.py
git commit -m "feat(training): export-naming-corpus builds fine-tune pairs"
```

---

### Task 5: eval harness (deployment gate)

**Files:**
- Modify: `src/photo_workflow/pipeline.py` (`training eval-naming`)
- Test: `tests/test_eval_naming.py`

**Interfaces:**
- Consumes: a corpus dir (Task 4), a model dir (`models/florence2_int8` layout), `naming.generate_name`-style inference via `naming.warm_sessions` + internal caption call.
- Produces: per-image and aggregate **content-word recall**: fraction of the reference caption's content words (stopwords stripped) present in the model output; plus mean inference time (KPM-1.2 check). Marked `@pytest.mark.slow`-equivalent: the CLI is the harness, the unit test only covers the metric function.
- Metric function: `caption_recall(reference: str, hypothesis: str) -> float` in `naming_corrections.py`.

- [ ] **Step 1: Write the failing metric test**

```python
# tests/test_eval_naming.py
from photo_workflow.naming_corrections import caption_recall


def test_recall_ignores_stopwords_and_case():
    assert caption_recall("A red fox running in the snow",
                          "a RED FOX is running through snow") == 1.0


def test_recall_partial():
    # content words: red, fox, running, snow -> hypothesis has 2 of 4
    assert abs(caption_recall("A red fox running in the snow",
                              "a fox in the snow") - 0.75) < 1e-6  # fox, snow, +? adjust below
```

Compute the expected value precisely when implementing (define the stopword list first, then fix the test constant — the test must encode the real arithmetic, not a guess).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_eval_naming.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement metric + CLI**

```python
# naming_corrections.py (append)
_STOPWORDS = {"a", "an", "the", "of", "in", "on", "at", "and", "with", "is",
              "are", "to", "through", "over", "under", "by", "for", "its"}


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOPWORDS}


def caption_recall(reference: str, hypothesis: str) -> float:
    ref = _content_words(reference)
    if not ref:
        return 1.0
    return len(ref & _content_words(hypothesis)) / len(ref)
```

CLI:

```python
@training.command("eval-naming")
@click.option("--corpus", "corpus_dir", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--model-dir", default="models/florence2_int8", show_default=True,
              type=click.Path(path_type=Path))
@click.option("--split", default="holdout", show_default=True)
def eval_naming(corpus_dir, model_dir, split):
    """Score a captioner against corrected captions (content-word recall).

    Gate for model swaps: the candidate model must beat the incumbent's
    recall on the holdout split, and mean time must stay <= 2.5s (KPM-1.2).
    """
    import time
    from .naming import generate_name
    from .naming_corrections import caption_recall

    rows = [json.loads(l) for l in
            (Path(corpus_dir) / "captions.jsonl").read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if r["split"] == split]
    if not rows:
        raise click.ClickException(f"No rows in split {split!r}")
    recalls, times = [], []
    for r in rows:
        t0 = time.perf_counter()
        out = generate_name(Path(corpus_dir) / r["image"], model_dir=Path(model_dir))
        times.append(time.perf_counter() - t0)
        hyp = out.split("\n", 1)[0]
        rec = caption_recall(r["caption"], hyp)
        recalls.append(rec)
        click.echo(f"  {r['image']}: recall={rec:.2f}  '{hyp}'")
    click.echo(f"mean recall: {sum(recalls)/len(recalls):.3f}  "
               f"mean time: {sum(times)/len(times):.2f}s  n={len(rows)}")
```

- [ ] **Step 4: Run tests, commit**

Run: `pytest tests/test_eval_naming.py -v && pytest -m "not slow" -q`
Expected: PASS

```bash
git add src/photo_workflow/naming_corrections.py src/photo_workflow/pipeline.py tests/test_eval_naming.py
git commit -m "feat(training): eval-naming recall harness (model-swap gate)"
```

---

### Task 6: offline LoRA fine-tune script (dev machine, provisioning-time)

**Files:**
- Create: `scripts/finetune_florence2.py` (NOT imported by the runtime package; torch/transformers/peft are dev-machine-only deps, documented in the script header, mirroring `scripts/provision_models.sh` conventions)
- Create: `dev-docs/naming-finetune-guide.md` (runbook)

**Interfaces:**
- Consumes: corpus dir (Task 4).
- Produces: `<out>/checkpoint/` (merged fine-tuned HF model) ready for the existing ONNX INT8 export path in `scripts/provision_models.sh`.

This task is a script + runbook, not TDD (no runtime tests — it never runs on the Yoga). Acceptance = the runbook executes end-to-end on the dev machine.

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""Fine-tune Florence-2-base-ft on corrected captions (LoRA), dev machine only.

Prereqs (dev venv, NOT the runtime venv):
    pip install torch transformers peft pillow

Usage:
    python scripts/finetune_florence2.py --corpus <export-naming-corpus out> \
        --base microsoft/Florence-2-base-ft --out build/florence2_ft \
        --epochs 5 --lr 1e-4

Then re-export ONNX INT8 (see scripts/provision_models.sh florence2 section,
pointing it at build/florence2_ft/checkpoint), benchmark with
`photo-workflow training eval-naming` on BOTH the old and new model dirs, and
swap models/florence2_int8 only if holdout recall improves and mean time
stays <= 2.5s (KPM-1.2).

Guidance:
- Under ~100 corrections: prefer more epochs at lower LR (5-8 epochs, 5e-5)
  and expect modest gains; the immediate-apply path (correct-name) is already
  fixing the library regardless.
- LoRA targets the language-model decoder only (q_proj/k_proj/v_proj/o_proj);
  the vision tower stays frozen — content mistakes live in the text decoder,
  and freezing vision keeps the tune stable on tiny corpora.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--base", default="microsoft/Florence-2-base-ft")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch-size", type=int, default=2)
    args = ap.parse_args()

    import torch
    from PIL import Image
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoProcessor

    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = AutoProcessor.from_pretrained(args.base, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.base, trust_remote_code=True).to(device)

    lora = LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05,
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj"])
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    rows = [json.loads(l) for l in
            (args.corpus / "captions.jsonl").read_text(encoding="utf-8").splitlines()]
    train_rows = [r for r in rows if r["split"] == "train"]
    prompt = "What does the image describe?"   # must match naming.CAPTION_PROMPT_TEXT

    optim = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad], lr=args.lr)
    model.train()
    for epoch in range(args.epochs):
        total = 0.0
        for i in range(0, len(train_rows), args.batch_size):
            batch = train_rows[i:i + args.batch_size]
            images = [Image.open(args.corpus / r["image"]).convert("RGB") for r in batch]
            inputs = processor(text=[prompt] * len(batch), images=images,
                               return_tensors="pt", padding=True).to(device)
            labels = processor.tokenizer(
                [r["caption"] for r in batch], return_tensors="pt",
                padding=True).input_ids.to(device)
            loss = model(**inputs, labels=labels).loss
            loss.backward(); optim.step(); optim.zero_grad()
            total += float(loss)
        print(f"epoch {epoch + 1}/{args.epochs}  loss={total / max(len(train_rows), 1):.4f}")

    merged = model.merge_and_unload()
    out = args.out / "checkpoint"
    merged.save_pretrained(out)
    processor.save_pretrained(out)
    print(f"Saved merged checkpoint to {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the runbook** (`dev-docs/naming-finetune-guide.md`)

Cover, in order, with exact commands: export corpus (Task 4 CLI) → run fine-tune → ONNX export + INT8 quantization (point at the exact `provision_models.sh` section/commands used for the original model) → `eval-naming` on old vs new model dirs → KPM-1.2 benchmark on the Yoga via `scripts/remote_test.sh` → swap `models/florence2_int8` → keep the old dir as `models/florence2_int8.prev` for rollback.

- [ ] **Step 3: Commit**

```bash
git add scripts/finetune_florence2.py dev-docs/naming-finetune-guide.md
git commit -m "feat(training): offline Florence-2 LoRA fine-tune script + runbook"
```

---

## Phase 3 sketch (not tasked — the "smaller specialized model" endgame)

Once `naming_corrections.jsonl` reaches ~500+ diverse samples: train a CLIP-prefix captioner (MobileCLIP embedding → 2-layer projection → tiny decoder, e.g. distilGPT2-class, LoRA-tuned) distilled from Florence-2 outputs + corrections. Expected: ~10× faster than Florence-2 on the i7-7500U and one less large model on the cartridge. The eval harness (Task 5) and corpus format (Task 4) are already the right interfaces; only `scripts/` gains a distillation trainer and `naming.py` a second backend selected by model-dir contents. Do not start this before the fine-tune loop has proven the corpus quality.

## Self-Review Notes

- User's three stated advantages map to: better naming (Tasks 1–6), faster naming + smaller model (Phase 3, gated on corpus size — honest sequencing, not scope creep).
- The immediate-apply path (Task 2) delivers value from correction #1; fine-tuning (Task 6) needs ~50–100 corrections minimum to be worth a run — the runbook says so explicitly.
- Cross-plan consistency: `render_caption` output register matches Florence-2's captions ("A ..."), which `consistency.py` (caption-tag plan) also parses — corrected captions improve consistency checking for free.
