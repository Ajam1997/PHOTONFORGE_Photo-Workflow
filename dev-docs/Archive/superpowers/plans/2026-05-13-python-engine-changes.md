# Python Engine Changes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--json-progress` flag to all CLI subcommands, replace semantic-slug filenames with per-folder sequence numbers, strip DB-write code from `darktable_bridge.py`, and switch green label threshold to mean-score ≥ 0.5.

**Architecture:** Each subcommand gains a `--json-progress` flag that switches `click.echo` output to newline-delimited JSON. A shared `emit()` helper in `pipeline.py` handles the switch. The `name` subcommand scans the destination folder for existing sequence numbers and renames files to `{counter:05d}{ext}` rather than the semantic slug. `darktable_bridge.py` is stripped to XMP-write-only.

**Tech Stack:** Python 3.11, click 8.1, pytest 8.0, existing `manifest.py` / `darktable_bridge.py`

---

## File Map

| File | Change |
|---|---|
| `src/photo_workflow/pipeline.py` | Add `emit()` helper; add `--json-progress` to all subcommands; replace slug rename with sequence rename in `name` |
| `src/photo_workflow/darktable_bridge.py` | Remove all DB-write functions; keep `_write_xmp`, `validate_xmp`, `sync_to_darktable` (XMP only); switch green threshold to mean ≥ 0.5 |
| `tests/test_pipeline_json.py` | New — tests for `--json-progress` output and sequence numbering |
| `tests/test_darktable.py` | Remove DB-write tests; add XMP-only and green-threshold tests |

---

## Task 1: Add `emit()` helper to `pipeline.py`

**Files:**
- Modify: `src/photo_workflow/pipeline.py` (add after imports, before `PHOTO_EXTS`)
- Test: `tests/test_pipeline_json.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/test_pipeline_json.py`:

```python
import json
from photo_workflow.pipeline import emit


def test_emit_json_mode(capsys):
    emit("score", "DSC001.ARW", "ok", json_progress=True, sharpness=0.82, stars=3)
    out = capsys.readouterr().out
    line = json.loads(out.strip())
    assert line["step"] == "score"
    assert line["file"] == "DSC001.ARW"
    assert line["status"] == "ok"
    assert line["sharpness"] == 0.82
    assert line["stars"] == 3


def test_emit_human_mode(capsys):
    emit("score", "DSC001.ARW", "ok", json_progress=False, sharpness=0.82, stars=3)
    out = capsys.readouterr().out
    # human mode: not valid JSON, contains filename
    assert "DSC001.ARW" in out
    try:
        json.loads(out.strip())
        assert False, "Should not be JSON in human mode"
    except json.JSONDecodeError:
        pass


def test_emit_error_status(capsys):
    emit("score", "DSC002.ARW", "error", json_progress=True, message="decode failed")
    out = capsys.readouterr().out
    line = json.loads(out.strip())
    assert line["status"] == "error"
    assert line["message"] == "decode failed"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_pipeline_json.py -v
```
Expected: `ImportError: cannot import name 'emit'`

- [ ] **Step 3: Add `emit()` to `pipeline.py`**

Add this function after the `PipelineSummary` dataclass (around line 51), before `_rename_photo`:

```python
def emit(
    step: str,
    file: str,
    status: str,
    json_progress: bool = False,
    **fields: object,
) -> None:
    """Print a progress line — JSON when json_progress=True, human text otherwise."""
    if json_progress:
        import json as _json
        click.echo(_json.dumps({"step": step, "file": file, "status": status, **fields}))
    else:
        extras = "  ".join(f"{k}={v}" for k, v in fields.items())
        click.echo(f"  {step} {file} [{status}]  {extras}")
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_pipeline_json.py -v
```
Expected: all 3 PASS

- [ ] **Step 5: Commit**

```
git add src/photo_workflow/pipeline.py tests/test_pipeline_json.py
git commit -m "feat: add emit() helper for JSON/human progress output"
```

---

## Task 2: Wire `--json-progress` to `ingest` subcommand

**Files:**
- Modify: `src/photo_workflow/pipeline.py` — `ingest` function (currently lines 199–212)
- Test: `tests/test_pipeline_json.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_json.py`:

```python
from click.testing import CliRunner
from photo_workflow.pipeline import cli
from pathlib import Path
import json, tempfile, shutil


def test_ingest_json_progress(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    (src / "DSC001.ARW").write_bytes(b"fake")
    runner = CliRunner()
    result = runner.invoke(cli, [
        "ingest", "--source", str(src), "--dest", str(dest), "--json-progress"
    ])
    assert result.exit_code == 0
    lines = [l for l in result.output.strip().splitlines() if l.startswith("{")]
    assert len(lines) >= 1
    rec = json.loads(lines[0])
    assert rec["step"] == "ingest"
    assert rec["status"] == "ok"
    assert "DSC001.ARW" in rec["file"]
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_pipeline_json.py::test_ingest_json_progress -v
```
Expected: FAIL — `--json-progress` not a recognised option

- [ ] **Step 3: Update `ingest` subcommand**

Replace the `ingest` function (lines 199–212 of `pipeline.py`) with:

```python
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
        emit("ingest", p.name, "ok", json_progress=json_progress,
             dest=str(p))
    if not json_progress:
        verb = "Would copy" if dry_run else "Copied"
        click.echo(f"{verb} {len(copied)} photos to {dest}")
    else:
        click.echo(json.dumps({"step": "_progress", "done": len(copied), "total": len(copied)}))
```

Also add `import json` at the top of `pipeline.py` (after `import os`).

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_pipeline_json.py::test_ingest_json_progress -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```
git add src/photo_workflow/pipeline.py tests/test_pipeline_json.py
git commit -m "feat: add --json-progress to ingest subcommand"
```

---

## Task 3: Wire `--json-progress` to `scan` subcommand

**Files:**
- Modify: `src/photo_workflow/pipeline.py` — `scan` function (lines 215–244)
- Test: `tests/test_pipeline_json.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_json.py`:

```python
def test_scan_json_progress(tmp_path):
    src = tmp_path / "photos"
    src.mkdir()
    (src / "DSC001.ARW").write_bytes(b"fake")
    (src / "DSC002.ARW").write_bytes(b"fake")
    manifest = tmp_path / "manifest.jsonl"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "scan", "--source", str(src), "--manifest", str(manifest), "--json-progress"
    ])
    assert result.exit_code == 0
    lines = [l for l in result.output.strip().splitlines() if l.startswith("{")]
    assert len(lines) >= 2
    for line in lines:
        rec = json.loads(line)
        if rec["step"] == "scan":
            assert rec["status"] == "ok"
            assert rec["file"].endswith(".ARW")
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_pipeline_json.py::test_scan_json_progress -v
```
Expected: FAIL — `--json-progress` not recognised

- [ ] **Step 3: Update `scan` subcommand**

Replace the `scan` function (lines 215–244) with:

```python
@cli.command()
@click.option("--source", required=True, type=click.Path(exists=True, path_type=Path),
              help="Directory containing photos to process.")
@click.option("--manifest", "manifest_path", default="manifest.jsonl",
              type=click.Path(path_type=Path), show_default=True,
              help="Path to the JSONL manifest file.")
@click.option("--recursive", is_flag=True, default=False,
              help="Recurse into subdirectories.")
@click.option("--json-progress", "json_progress", is_flag=True, default=False,
              help="Emit newline-delimited JSON progress lines.")
def scan(source: Path, manifest_path: Path, recursive: bool, json_progress: bool) -> None:
    """Discover photos and create the manifest."""
    from .grouping import _read_exif_datetime
    from .manifest import ManifestEntry, save_manifest

    glob_fn = source.rglob if recursive else source.glob
    photos = sorted(
        p for p in glob_fn("*")
        if p.is_file() and p.suffix.lower() in PHOTO_EXTS
    )

    entries: list[ManifestEntry] = []
    for p in photos:
        dt = _read_exif_datetime(p)
        entries.append(ManifestEntry(
            path=str(p),
            exif_timestamp=dt.isoformat() if dt else None,
            stages_completed=["scan"],
        ))
        emit("scan", p.name, "ok", json_progress=json_progress)

    save_manifest(entries, manifest_path)
    if not json_progress:
        click.echo(f"Scanned {len(entries)} photos -> {manifest_path}")
    else:
        click.echo(json.dumps({"step": "_progress", "done": len(entries), "total": len(entries)}))
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_pipeline_json.py::test_scan_json_progress -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```
git add src/photo_workflow/pipeline.py tests/test_pipeline_json.py
git commit -m "feat: add --json-progress to scan subcommand"
```

---

## Task 4: Wire `--json-progress` to `dedup` subcommand

**Files:**
- Modify: `src/photo_workflow/pipeline.py` — `dedup` function (lines 247–307)
- Test: `tests/test_pipeline_json.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_json.py`:

```python
def test_dedup_json_progress(tmp_path):
    from photo_workflow.manifest import ManifestEntry, save_manifest
    manifest = tmp_path / "manifest.jsonl"
    entries = [
        ManifestEntry(path=str(tmp_path / "DSC001.ARW"), stages_completed=["scan"]),
        ManifestEntry(path=str(tmp_path / "DSC002.ARW"), stages_completed=["scan"]),
    ]
    save_manifest(entries, manifest)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "dedup", "--manifest", str(manifest), "--json-progress"
    ])
    assert result.exit_code == 0
    lines = [l for l in result.output.strip().splitlines() if l.startswith("{")]
    assert len(lines) >= 2
    statuses = {json.loads(l)["status"] for l in lines if json.loads(l).get("step") == "dedup"}
    assert statuses <= {"ok", "duplicate"}
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_pipeline_json.py::test_dedup_json_progress -v
```
Expected: FAIL — `--json-progress` not recognised

- [ ] **Step 3: Update `dedup` subcommand**

Add `--json-progress` option and emit lines. In the `dedup` function, add the option decorator and update the per-record loop (after `records = deduplicate(...)`):

```python
@cli.command()
@click.option("--manifest", "manifest_path", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--force", is_flag=True, default=False)
@click.option("--json-progress", "json_progress", is_flag=True, default=False,
              help="Emit newline-delimited JSON progress lines.")
def dedup(manifest_path: Path, force: bool, json_progress: bool) -> None:
    """Group photos into sessions and flag duplicates."""
    from .manifest import load_manifest, save_manifest
    from .grouping import cluster_sessions
    from .dedup import deduplicate
    import sys

    entries = load_manifest(manifest_path)

    not_scanned = [e for e in entries if "scan" not in e.stages_completed]
    if not_scanned:
        raise click.ClickException(
            f"{len(not_scanned)} photos have not been through 'scan'. "
            "Run 'photo-workflow scan' first."
        )

    if force:
        for e in entries:
            e.stages_completed = [s for s in e.stages_completed if s != "dedup"]
            e.is_duplicate = False
            e.session_id = None

    to_process = [e for e in entries if "dedup" not in e.stages_completed]
    if not to_process:
        if not json_progress:
            click.echo("All photos already deduped. Use --force to redo.")
        return

    records = [
        PhotoRecord(path=Path(e.path), session_id=e.session_id)
        for e in entries
    ]
    records = cluster_sessions(records)
    total = len(records)

    if not json_progress:
        def _progress(n: int) -> None:
            sys.stderr.write(f"\rDeduping {n}/{total} ({n * 100 // total}%)   ")
            sys.stderr.flush()
        records = deduplicate(records, progress_callback=_progress)
        sys.stderr.write("\n")
    else:
        records = deduplicate(records)

    for entry, record in zip(entries, records):
        entry.session_id = record.session_id
        entry.is_duplicate = record.is_duplicate
        entry.keeper_path = str(record.keeper_path) if record.keeper_path else None
        if "dedup" not in entry.stages_completed:
            entry.stages_completed.append("dedup")
        status = "duplicate" if record.is_duplicate else "ok"
        extra = {"keeper": str(record.keeper_path)} if record.is_duplicate and record.keeper_path else {}
        emit("dedup", Path(entry.path).name, status, json_progress=json_progress, **extra)

    save_manifest(entries, manifest_path)

    if not json_progress:
        sessions = len({e.session_id for e in entries})
        dupes = sum(1 for e in entries if e.is_duplicate)
        click.echo(f"Grouped into {sessions} sessions, flagged {dupes} duplicates")
    else:
        click.echo(json.dumps({"step": "_progress", "done": len(entries), "total": len(entries)}))
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_pipeline_json.py::test_dedup_json_progress -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```
git add src/photo_workflow/pipeline.py tests/test_pipeline_json.py
git commit -m "feat: add --json-progress to dedup subcommand"
```

---

## Task 5: Wire `--json-progress` to `score` subcommand

**Files:**
- Modify: `src/photo_workflow/pipeline.py` — `score` function (lines 310–398)
- Test: `tests/test_pipeline_json.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_json.py`:

```python
def test_score_json_progress(tmp_path):
    import shutil
    from photo_workflow.manifest import ManifestEntry, save_manifest
    # Use a real fixture image from tests/fixtures if available, else a minimal JPEG
    fixture = Path("tests/fixtures")
    jpgs = list(fixture.glob("*.jpg")) + list(fixture.glob("*.JPG")) if fixture.exists() else []
    if not jpgs:
        pytest.skip("no fixture images available")
    img = tmp_path / jpgs[0].name
    shutil.copy(jpgs[0], img)
    manifest = tmp_path / "manifest.jsonl"
    entries = [ManifestEntry(
        path=str(img), stages_completed=["scan", "dedup"]
    )]
    save_manifest(entries, manifest)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "score", "--manifest", str(manifest), "--json-progress"
    ])
    assert result.exit_code == 0
    lines = [l for l in result.output.strip().splitlines() if l.startswith("{")]
    score_lines = [json.loads(l) for l in lines if json.loads(l).get("step") == "score"]
    assert len(score_lines) >= 1
    rec = score_lines[0]
    assert rec["status"] == "ok"
    assert "sharpness" in rec
    assert "stars" in rec
    assert "color_label" in rec
    assert isinstance(rec["color_label"], int)
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_pipeline_json.py::test_score_json_progress -v
```
Expected: FAIL — `--json-progress` not recognised

- [ ] **Step 3: Update `score` subcommand**

Add `--json-progress` option. Inside the per-entry loop, after computing scores, add the emit call. The `color_label` value is computed using the mean-score rule (see Task 9 for threshold constants — for now import them from `darktable_bridge`):

```python
@cli.command()
@click.option("--manifest", "manifest_path", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--resume", is_flag=True, default=False)
@click.option("--force", is_flag=True, default=False)
@click.option("--verbose", is_flag=True, default=False)
@click.option("--quiet", is_flag=True, default=False)
@click.option("--json-progress", "json_progress", is_flag=True, default=False,
              help="Emit newline-delimited JSON progress lines.")
def score(
    manifest_path: Path, resume: bool, force: bool,
    verbose: bool, quiet: bool, json_progress: bool
) -> None:
    """Score photos for sharpness, composition, and exposure."""
    import cv2 as _cv2
    from .manifest import load_manifest, save_manifest, checkpoint
    from .progress import ProgressTracker
    from .sharpness import score_sharpness_bgr
    from .composition import score_composition_bgr
    from .exposure import score_exposure_bgr
    from .raw_preview import load_image_bgr
    from .darktable_bridge import compute_color_label

    _SCORE_MAX_WIDTH = 1024

    entries = load_manifest(manifest_path)

    not_deduped = [e for e in entries if "dedup" not in e.stages_completed]
    if not_deduped:
        raise click.ClickException(
            f"{len(not_deduped)} photos have not been through 'dedup'. "
            "Run 'photo-workflow dedup' first."
        )

    to_score = [
        e for e in entries
        if not e.is_duplicate and (force or "score" not in e.stages_completed)
    ]

    if not to_score and not force:
        if not json_progress:
            click.echo("All non-duplicate photos already scored. Use --resume or --force.")
        return

    tracker = ProgressTracker(stage="score", total=len(to_score))
    errors = 0

    for i, entry in enumerate(to_score, 1):
        p = Path(entry.path)
        try:
            bgr = load_image_bgr(p)
            if bgr is None:
                raise RuntimeError(f"Could not load image: {p}")
            h, w = bgr.shape[:2]
            if w > _SCORE_MAX_WIDTH:
                scale = _SCORE_MAX_WIDTH / w
                bgr = _cv2.resize(bgr, (int(w * scale), int(h * scale)),
                                  interpolation=_cv2.INTER_AREA)
            entry.sharpness = score_sharpness_bgr(bgr)
            entry.composition = score_composition_bgr(bgr)
            entry.exposure = score_exposure_bgr(bgr)
            entry.error = None
            if "score" not in entry.stages_completed:
                entry.stages_completed.append("score")

            mean = (entry.sharpness + entry.composition + entry.exposure) / 3.0
            stars = min(5, round(mean * 5))
            color_label = compute_color_label(entry.sharpness, entry.composition, entry.exposure)

            if json_progress:
                emit("score", p.name, "ok", json_progress=True,
                     sharpness=round(entry.sharpness, 4),
                     composition=round(entry.composition, 4),
                     exposure=round(entry.exposure, 4),
                     stars=stars,
                     color_label=color_label)
            elif verbose:
                click.echo(
                    f"  {p.name}: sharp={entry.sharpness:.4f} "
                    f"comp={entry.composition:.4f} exp={entry.exposure:.4f}"
                )
        except Exception as exc:
            entry.error = str(exc)
            errors += 1
            logger.warning("Score failed for %s: %s", p, exc)
            if json_progress:
                emit("score", p.name, "error", json_progress=True, message=str(exc))

        if not quiet and not json_progress:
            tracker.update(i)

        if i % 50 == 0:
            checkpoint(entries, manifest_path)

    if not quiet and not json_progress:
        tracker.finish()

    save_manifest(entries, manifest_path)

    if not json_progress:
        scored = len(to_score) - errors
        click.echo(f"Scored {scored}/{len(to_score)} photos. {errors} errors.")
    else:
        click.echo(json.dumps({"step": "_progress", "done": len(to_score), "total": len(to_score)}))
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_pipeline_json.py::test_score_json_progress -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```
git add src/photo_workflow/pipeline.py tests/test_pipeline_json.py
git commit -m "feat: add --json-progress to score subcommand"
```

---

## Task 6: Wire `--json-progress` to `name` subcommand (semantic name → description only, no file rename yet)

**Files:**
- Modify: `src/photo_workflow/pipeline.py` — `name` function (lines 401–511)
- Test: `tests/test_pipeline_json.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_json.py`:

```python
def test_name_json_progress_emits_semantic_name(tmp_path, monkeypatch):
    from photo_workflow.manifest import ManifestEntry, save_manifest
    import photo_workflow.pipeline as pipeline_mod

    monkeypatch.setattr(
        "photo_workflow.naming.generate_name",
        lambda path, model_dir, tz_offset=0: "a-blue-waterfall"
    )

    img = tmp_path / "DSC001.ARW"
    img.write_bytes(b"fake")
    manifest = tmp_path / "manifest.jsonl"
    entries = [ManifestEntry(
        path=str(img), stages_completed=["scan", "dedup", "score"],
        sharpness=0.7, composition=0.6, exposure=0.7
    )]
    save_manifest(entries, manifest)

    runner = CliRunner()
    result = runner.invoke(cli, [
        "name", "--manifest", str(manifest),
        "--model-dir", str(tmp_path),
        "--json-progress"
    ])
    assert result.exit_code == 0
    lines = [l for l in result.output.strip().splitlines() if l.startswith("{")]
    name_lines = [json.loads(l) for l in lines if json.loads(l).get("step") == "name"]
    assert len(name_lines) == 1
    assert name_lines[0]["semantic_name"] == "a-blue-waterfall"
    assert name_lines[0]["status"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_pipeline_json.py::test_name_json_progress_emits_semantic_name -v
```
Expected: FAIL — `--json-progress` not recognised

- [ ] **Step 3: Add `--json-progress` option to `name` subcommand**

Add the option decorator and emit line inside the per-entry loop. After `entry.semantic_name = slug` and before `tracker.update(i)`, add:

```python
@click.option("--json-progress", "json_progress", is_flag=True, default=False,
              help="Emit newline-delimited JSON progress lines.")
```

And update the function signature to include `json_progress: bool`. Inside the loop after `entry.semantic_name = slug`:

```python
            if json_progress:
                emit("name", p.name, "ok", json_progress=True,
                     semantic_name=slug)
            elif verbose:
                marker = " (fallback)" if is_fallback else ""
                click.echo(f"  {p.name} -> {slug}{marker}")
```

For errors:
```python
        except Exception as exc:
            entry.error = str(exc)
            errors += 1
            logger.warning("Name failed for %s: %s", p, exc)
            if json_progress:
                emit("name", p.name, "error", json_progress=True, message=str(exc))
```

Replace the final summary echo:
```python
    if not json_progress:
        named = len(to_name) - errors
        click.echo(f"Named {named}/{len(to_name)} photos. {errors} errors.")
    else:
        click.echo(json.dumps({"step": "_progress", "done": len(to_name), "total": len(to_name)}))
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_pipeline_json.py::test_name_json_progress_emits_semantic_name -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```
git add src/photo_workflow/pipeline.py tests/test_pipeline_json.py
git commit -m "feat: add --json-progress to name subcommand"
```

---

## Task 7: Wire `--json-progress` to `sync` subcommand

**Files:**
- Modify: `src/photo_workflow/pipeline.py` — `sync` function (lines 514–593)
- Test: `tests/test_pipeline_json.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_json.py`:

```python
def test_sync_json_progress(tmp_path):
    from photo_workflow.manifest import ManifestEntry, save_manifest

    img = tmp_path / "00001.ARW"
    img.write_bytes(b"fake")
    manifest = tmp_path / "manifest.jsonl"
    entries = [ManifestEntry(
        path=str(img),
        stages_completed=["scan", "dedup", "score", "name"],
        sharpness=0.7, composition=0.6, exposure=0.7,
        semantic_name="a-blue-waterfall"
    )]
    save_manifest(entries, manifest)

    runner = CliRunner()
    result = runner.invoke(cli, [
        "sync", "--manifest", str(manifest),
        "--db", str(tmp_path / "nonexistent.db"),
        "--json-progress"
    ])
    assert result.exit_code == 0
    lines = [l for l in result.output.strip().splitlines() if l.startswith("{")]
    sync_lines = [json.loads(l) for l in lines if json.loads(l).get("step") == "sync"]
    assert len(sync_lines) == 1
    assert sync_lines[0]["status"] == "ok"
    assert sync_lines[0]["xmp"].endswith(".xmp")
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_pipeline_json.py::test_sync_json_progress -v
```
Expected: FAIL — `--json-progress` not recognised

- [ ] **Step 3: Update `sync` subcommand**

Add `--json-progress` decorator and update the emit calls. After `xmp_written, db_upserted = sync_to_darktable(...)`, replace the final echo with per-record JSON emits by modifying `sync_to_darktable` to return a list of written XMP paths (see Task 9). For now, emit one line per record before calling sync:

```python
@click.option("--json-progress", "json_progress", is_flag=True, default=False,
              help="Emit newline-delimited JSON progress lines.")
def sync(manifest_path: Path, db_path: Path, dry_run: bool, verbose: bool, json_progress: bool) -> None:
    """Write XMP sidecars and sync to Darktable library.db."""
    from .manifest import load_manifest, save_manifest
    from .darktable_bridge import sync_to_darktable

    entries = load_manifest(manifest_path)

    not_named = [
        e for e in entries
        if not e.is_duplicate and "name" not in e.stages_completed
    ]
    if not_named:
        raise click.ClickException(
            f"{len(not_named)} photos have not been through 'name'. "
            "Run 'photo-workflow name' first."
        )

    keeper_index: dict[str, ManifestEntry] = {
        e.path: e for e in entries if not e.is_duplicate
    }
    keeper_dup_count: dict[str, int] = {}

    records = []
    for e in entries:
        if e.is_duplicate and e.keeper_path and e.keeper_path in keeper_index:
            keeper = keeper_index[e.keeper_path]
            keeper_dup_count[e.keeper_path] = keeper_dup_count.get(e.keeper_path, 1) + 1
            n = keeper_dup_count[e.keeper_path]
            base_name = keeper.semantic_name or Path(keeper.path).stem
            dup_name = f"{base_name}-{n}"
            rec = PhotoRecord(
                path=Path(e.path),
                session_id=e.session_id,
                is_duplicate=True,
                keeper_path=Path(e.keeper_path),
                sharpness_score=keeper.sharpness or 0.0,
                composition_score=keeper.composition or 0.0,
                exposure_score=keeper.exposure or 0.0,
                semantic_name=dup_name,
                metadata={"original_filename": Path(e.path).name},
            )
        else:
            rec = PhotoRecord(
                path=Path(e.path),
                session_id=e.session_id,
                is_duplicate=e.is_duplicate,
                sharpness_score=e.sharpness or 0.0,
                composition_score=e.composition or 0.0,
                exposure_score=e.exposure or 0.0,
                semantic_name=e.semantic_name or "",
                metadata={"original_filename": Path(e.path).name},
            )
        records.append(rec)

    if dry_run:
        non_dupes = sum(1 for r in records if not r.is_duplicate)
        click.echo(f"Dry run: would write {non_dupes} XMP sidecars")
        return

    xmp_written = sync_to_darktable(records, verbose=verbose)

    for record in records:
        xmp_path = record.path.with_suffix(".xmp")
        emit("sync", record.path.name, "ok", json_progress=json_progress,
             xmp=str(xmp_path))

    for entry in entries:
        if not entry.is_duplicate and "sync" not in entry.stages_completed:
            entry.stages_completed.append("sync")
    save_manifest(entries, manifest_path)

    if not json_progress:
        click.echo(f"Wrote {xmp_written} XMP sidecars")
    else:
        click.echo(json.dumps({"step": "_progress", "done": xmp_written, "total": xmp_written}))
```

Note: `sync_to_darktable` signature changes in Task 9 — it no longer takes `db_path` and returns only `xmp_count`. Implement Task 9 before Task 7 if running tasks out of order. Also add `from .manifest import ManifestEntry` to the sync imports since it is used in the keeper_index type annotation.

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_pipeline_json.py::test_sync_json_progress -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```
git add src/photo_workflow/pipeline.py tests/test_pipeline_json.py
git commit -m "feat: add --json-progress to sync subcommand"
```

---

## Task 8: Add sequence numbering to `name` subcommand

**Files:**
- Modify: `src/photo_workflow/pipeline.py` — `name` function
- Test: `tests/test_pipeline_json.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_json.py`:

```python
def test_name_sequence_numbering(tmp_path, monkeypatch):
    from photo_workflow.manifest import ManifestEntry, save_manifest, load_manifest

    monkeypatch.setattr(
        "photo_workflow.naming.generate_name",
        lambda path, model_dir, tz_offset=0: "a-blue-waterfall"
    )

    # Create 3 photos; existing file 00001.ARW already present (highest = 1)
    (tmp_path / "00001.ARW").write_bytes(b"existing")
    photos = []
    for i in range(2, 5):
        p = tmp_path / f"DSC0000{i}.ARW"
        p.write_bytes(b"fake")
        photos.append(p)

    manifest = tmp_path / "manifest.jsonl"
    entries = [ManifestEntry(
        path=str(p), stages_completed=["scan", "dedup", "score"],
        sharpness=0.7, composition=0.6, exposure=0.7
    ) for p in photos]
    save_manifest(entries, manifest)

    runner = CliRunner()
    result = runner.invoke(cli, [
        "name", "--manifest", str(manifest),
        "--model-dir", str(tmp_path),
    ])
    assert result.exit_code == 0

    updated = load_manifest(manifest)
    new_paths = [Path(e.path).name for e in updated]
    # Should be 00002.ARW, 00003.ARW, 00004.ARW (starts after existing 00001)
    assert "00002.ARW" in new_paths
    assert "00003.ARW" in new_paths
    assert "00004.ARW" in new_paths
    # Original files renamed
    assert (tmp_path / "00002.ARW").exists()
    assert not (tmp_path / "DSC00002.ARW").exists()


def test_name_sequence_no_collision_on_rerun(tmp_path, monkeypatch):
    from photo_workflow.manifest import ManifestEntry, save_manifest, load_manifest

    monkeypatch.setattr(
        "photo_workflow.naming.generate_name",
        lambda path, model_dir, tz_offset=0: "a-blue-waterfall"
    )

    p = tmp_path / "DSC00001.ARW"
    p.write_bytes(b"fake")
    manifest = tmp_path / "manifest.jsonl"
    entries = [ManifestEntry(
        path=str(p), stages_completed=["scan", "dedup", "score"],
        sharpness=0.7, composition=0.6, exposure=0.7
    )]
    save_manifest(entries, manifest)

    runner = CliRunner()
    runner.invoke(cli, ["name", "--manifest", str(manifest), "--model-dir", str(tmp_path)])
    # Second run with --force should not collide
    result = runner.invoke(cli, [
        "name", "--manifest", str(manifest), "--model-dir", str(tmp_path), "--force"
    ])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_pipeline_json.py::test_name_sequence_numbering tests/test_pipeline_json.py::test_name_sequence_no_collision_on_rerun -v
```
Expected: FAIL — files not being renamed to sequence numbers

- [ ] **Step 3: Add sequence-number rename logic to `name` subcommand**

Add a helper function before the `name` subcommand definition:

```python
def _next_sequence_counter(directory: Path, ext: str) -> int:
    """Return highest existing 5-digit sequence number + 1, or 1 if none exist."""
    max_seq = 0
    for p in directory.iterdir():
        if p.suffix.lower() == ext.lower() and p.stem.isdigit():
            max_seq = max(max_seq, int(p.stem))
    return max_seq + 1
```

Then inside the `name` subcommand, before the per-entry loop, add:

```python
    # Determine starting sequence counter for this destination folder
    if to_name:
        dest_dir = Path(to_name[0].path).parent
        dest_ext = Path(to_name[0].path).suffix
        counter = _next_sequence_counter(dest_dir, dest_ext)
    else:
        counter = 1
```

Inside the per-entry loop, after `entry.semantic_name = slug`, add the rename:

```python
            # Rename to sequence number — semantic name goes to manifest/XMP only
            p = Path(entry.path)
            new_name = f"{counter:05d}{p.suffix}"
            new_path = p.parent / new_name
            if not new_path.exists() or new_path == p:
                try:
                    os.rename(p, new_path)
                    entry.path = str(new_path)
                except OSError as exc:
                    logger.warning("Could not rename %s to %s: %s", p, new_path, exc)
            counter += 1
```

Also update the JSON emit to include the new filename:

```python
            if json_progress:
                emit("name", new_name, "ok", json_progress=True,
                     semantic_name=slug, original=p.name)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_pipeline_json.py::test_name_sequence_numbering tests/test_pipeline_json.py::test_name_sequence_no_collision_on_rerun -v
```
Expected: both PASS

- [ ] **Step 5: Commit**

```
git add src/photo_workflow/pipeline.py tests/test_pipeline_json.py
git commit -m "feat: rename photos to 5-digit sequence numbers in name subcommand"
```

---

## Task 9: Strip DB writes from `darktable_bridge.py`; add `compute_color_label()`; switch green to mean ≥ 0.5

**Files:**
- Modify: `src/photo_workflow/darktable_bridge.py`
- Test: `tests/test_darktable.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_darktable.py` (or create it if it doesn't exist):

```python
from photo_workflow.darktable_bridge import compute_color_label, sync_to_darktable
from photo_workflow.pipeline import PhotoRecord
from pathlib import Path
import inspect


def test_compute_color_label_green_mean_above_half():
    # All scores above individual thresholds, mean >= 0.5 → green (2)
    assert compute_color_label(0.7, 0.6, 0.7) == 2


def test_compute_color_label_yellow_low_sharpness():
    # sharpness < 0.3 → yellow (1)
    assert compute_color_label(0.2, 0.6, 0.7) == 1


def test_compute_color_label_blue_low_exposure():
    # exposure < 0.5 → blue (3)
    assert compute_color_label(0.7, 0.6, 0.4) == 3


def test_compute_color_label_purple_low_composition():
    # composition < 0.2 → purple (4)
    assert compute_color_label(0.7, 0.1, 0.7) == 4


def test_compute_color_label_no_green_below_mean():
    # mean = (0.4+0.4+0.4)/3 = 0.4 < 0.5, nothing flagged → no label (-1 or 0)
    label = compute_color_label(0.4, 0.4, 0.4)
    assert label == -1  # -1 means no color label


def test_sync_to_darktable_xmp_only(tmp_path):
    img = tmp_path / "00001.ARW"
    img.write_bytes(b"fake")
    record = PhotoRecord(
        path=img, session_id="s1",
        sharpness_score=0.7, composition_score=0.6, exposure_score=0.7,
        semantic_name="a-blue-waterfall",
        metadata={"original_filename": "DSC001.ARW"}
    )
    count = sync_to_darktable([record])
    xmp = tmp_path / "00001.xmp"
    assert xmp.exists()
    assert count == 1


def test_sync_to_darktable_no_db_param():
    # sync_to_darktable must NOT accept a db_path parameter
    sig = inspect.signature(sync_to_darktable)
    assert "db_path" not in sig.parameters
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_darktable.py::test_compute_color_label_green_mean_above_half tests/test_darktable.py::test_sync_to_darktable_no_db_param -v
```
Expected: `ImportError: cannot import name 'compute_color_label'` and `AssertionError` on db_path

- [ ] **Step 3: Rewrite `darktable_bridge.py`**

Replace the entire file with:

```python
"""FR-1.8: XMP sidecar writer for Darktable integration."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from .pipeline import PhotoRecord

logger = logging.getLogger(__name__)

_PHOTON_NS = "https://photonforge.local/xmp/1.0/"

XMP_TEMPLATE = """\
<?xpacket begin='﻿' id='W5M0MpCehiHzreSzNTczkc9d'?>
<x:xmpmeta xmlns:x='adobe:ns:meta/' x:xmptk='PHOTONForge'>
  <rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>
    <rdf:Description rdf:about=''
      xmlns:xmp='http://ns.adobe.com/xap/1.0/'
      xmlns:dc='http://purl.org/dc/elements/1.1/'
      xmlns:photon='https://photonforge.local/xmp/1.0/'>
      <photon:SharpnessScore>{sharpness}</photon:SharpnessScore>
      <photon:CompositionScore>{composition}</photon:CompositionScore>
      <photon:ExposureScore>{exposure}</photon:ExposureScore>
      <photon:SemanticName>{semantic_name}</photon:SemanticName>
      <photon:OriginalFilename>{original_filename}</photon:OriginalFilename>
      <photon:SessionID>{session_id}</photon:SessionID>
      <photon:IsDuplicate>{is_duplicate}</photon:IsDuplicate>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
<?xpacket end='w'?>
"""

# Color label constants (Darktable: 0=red,1=yellow,2=green,3=blue,4=purple,-1=none)
_DT_RED    = 0
_DT_YELLOW = 1
_DT_GREEN  = 2
_DT_BLUE   = 3
_DT_PURPLE = 4
_DT_NONE   = -1

# Per-score warning thresholds
_THRESH_SHARPNESS   = 0.3
_THRESH_EXPOSURE    = 0.5
_THRESH_COMPOSITION = 0.2
# Green: mean score must reach this with no individual flags
_THRESH_GREEN_MEAN  = 0.5


def compute_color_label(sharpness: float, composition: float, exposure: float) -> int:
    """Return the Darktable color label int for a set of scores.

    Priority: yellow > blue > purple > green > none.
    Returns -1 if no label applies.
    """
    if sharpness < _THRESH_SHARPNESS:
        return _DT_YELLOW
    if exposure < _THRESH_EXPOSURE:
        return _DT_BLUE
    if composition < _THRESH_COMPOSITION:
        return _DT_PURPLE
    mean = (sharpness + composition + exposure) / 3.0
    if mean >= _THRESH_GREEN_MEAN:
        return _DT_GREEN
    return _DT_NONE


def _write_xmp(record: "PhotoRecord") -> None:
    xmp_path = record.path.with_suffix(".xmp")
    original_filename = record.metadata.get("original_filename", record.path.name)
    xmp_content = XMP_TEMPLATE.format(
        sharpness=record.sharpness_score,
        composition=record.composition_score,
        exposure=record.exposure_score,
        semantic_name=record.semantic_name,
        original_filename=original_filename,
        session_id=record.session_id,
        is_duplicate=str(record.is_duplicate).lower(),
    )
    xmp_path.write_text(xmp_content, encoding="utf-8")


def validate_xmp(xmp_path: Path) -> bool:
    """Parse an XMP sidecar and verify it contains required PHOTONForge fields."""
    try:
        tree = ET.parse(xmp_path)
        root = tree.getroot()
        if "xmpmeta" not in root.tag:
            logger.warning("XMP root is not xmpmeta in %s", xmp_path)
            return False
        xml_str = xmp_path.read_text(encoding="utf-8")
        if f"{{{_PHOTON_NS}}}SharpnessScore" not in xml_str and "SharpnessScore" not in xml_str:
            logger.warning("XMP missing SharpnessScore in %s", xmp_path)
            return False
        if "SemanticName" not in xml_str:
            logger.warning("XMP missing SemanticName in %s", xmp_path)
            return False
        ns = {"photon": _PHOTON_NS}
        score_el = root.find(".//{%s}SharpnessScore" % _PHOTON_NS)
        if score_el is not None and score_el.text is not None:
            float(score_el.text)
        return True
    except ET.ParseError as e:
        logger.warning("XMP parse error in %s: %s", xmp_path, e)
        return False
    except ValueError as e:
        logger.warning("XMP field value error in %s: %s", xmp_path, e)
        return False


def sync_to_darktable(records: list["PhotoRecord"], verbose: bool = False) -> int:
    """Write XMP sidecars for all records. Returns count written."""
    xmp_count = 0
    for record in records:
        try:
            _write_xmp(record)
            xmp_count += 1
            if verbose:
                click.echo(f"  XMP {Path(record.path).name} -> {record.semantic_name}")
        except Exception as e:
            logger.error("XMP write failed for %s: %s", record.path, e)
    logger.info("XMP written: %d", xmp_count)
    return xmp_count


@click.command("darktable-sync")
@click.argument("xmp_dir", type=click.Path(path_type=Path))
@click.option("--dry-run", is_flag=True, help="Validate XMP sidecars without writing.")
def main(xmp_dir: Path, dry_run: bool) -> None:
    """Validate XMP sidecars in XMP_DIR."""
    xmp_files = sorted(xmp_dir.glob("*.xmp"))
    click.echo(f"Found {len(xmp_files)} XMP sidecar(s)")
    for xmp in xmp_files:
        valid = validate_xmp(xmp)
        click.echo(f"  {xmp.name}: {'OK' if valid else 'INVALID'}")
```

- [ ] **Step 4: Run all darktable tests**

```
pytest tests/test_darktable.py -v
```
Expected: all PASS

- [ ] **Step 5: Run full test suite to check nothing broke**

```
pytest --tb=short -q
```
Expected: no new failures (some existing DB tests may need removal — delete any test that calls `sync_to_darktable` with a `db_path` argument)

- [ ] **Step 6: Commit**

```
git add src/photo_workflow/darktable_bridge.py tests/test_darktable.py
git commit -m "refactor: strip DB writes from darktable_bridge; add compute_color_label; mean-score green threshold"
```

---

## Task 10: Run full suite and verify

- [ ] **Step 1: Run full test suite**

```
pytest --tb=short -q
```
Expected: all pass (or only pre-existing failures unrelated to this work)

- [ ] **Step 2: Smoke test `--json-progress` end-to-end**

```
photo-workflow scan --source tests/fixtures --manifest /tmp/smoke.jsonl --json-progress
```
Expected: one JSON line per photo, each with `"step": "scan", "status": "ok"`, followed by a `_progress` line.

- [ ] **Step 3: Commit**

```
git add -p
git commit -m "test: verify full suite passes after engine changes"
```
