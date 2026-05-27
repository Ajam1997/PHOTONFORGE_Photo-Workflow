# Stage-Based CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `photo-workflow` CLI from a monolithic command into a staged subcommand group (scan/dedup/score/name/sync/status) with JSONL manifest checkpointing and resume capability for 7000+ photo batch processing.

**Architecture:** New `manifest.py` handles JSONL read/write/checkpoint. New `progress.py` provides terminal progress display. `pipeline.py:main()` is refactored from `click.command` to `click.Group` with six subcommands that delegate to existing analysis modules. The `AnalysisPipeline` class and its dataclasses remain for backward compatibility but are not used by the new CLI path.

**Tech Stack:** Python 3.11+, click 8.1+, JSONL (stdlib json), existing analysis modules unchanged.

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/photo_workflow/manifest.py` | Create | JSONL manifest CRUD: `ManifestEntry` dataclass, `create_manifest()`, `load_manifest()`, `save_manifest()`, `checkpoint()` |
| `src/photo_workflow/progress.py` | Create | `ProgressTracker` class: in-place terminal counter with throughput, ETA, RSS |
| `src/photo_workflow/pipeline.py` | Modify | Refactor `main()` from `click.command` to `click.Group` with 6 subcommands. Keep `AnalysisPipeline` class intact. |
| `tests/test_manifest.py` | Create | Unit tests for manifest read/write/checkpoint/atomic-replace |
| `tests/test_progress.py` | Create | Unit tests for progress tracker formatting |
| `tests/test_cli_stages.py` | Create | Integration tests for subcommand flow with fixture images |

---

### Task 1: Manifest Module — Data Model and I/O

**Files:**
- Create: `src/photo_workflow/manifest.py`
- Create: `tests/test_manifest.py`

- [ ] **Step 1: Write failing test for ManifestEntry round-trip**

```python
# tests/test_manifest.py
"""Tests for the JSONL manifest module."""

from __future__ import annotations

import json
from pathlib import Path

from photo_workflow.manifest import ManifestEntry, save_manifest, load_manifest


def test_manifest_entry_round_trip(tmp_path: Path) -> None:
    """A ManifestEntry survives serialize -> write -> read -> deserialize."""
    entry = ManifestEntry(
        path=str(tmp_path / "IMG_0001.jpg"),
        exif_timestamp="2026-04-01T10:00:00",
    )
    manifest_path = tmp_path / "manifest.jsonl"
    save_manifest([entry], manifest_path)
    loaded = load_manifest(manifest_path)
    assert len(loaded) == 1
    assert loaded[0].path == entry.path
    assert loaded[0].exif_timestamp == entry.exif_timestamp
    assert loaded[0].stages_completed == ["scan"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_manifest.py::test_manifest_entry_round_trip -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'photo_workflow.manifest'`

- [ ] **Step 3: Write ManifestEntry dataclass and save/load functions**

```python
# src/photo_workflow/manifest.py
"""JSONL manifest for staged pipeline checkpointing."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ManifestEntry:
    """Per-photo state tracked across pipeline stages."""

    path: str
    exif_timestamp: str | None = None
    session_id: str = ""
    is_duplicate: bool = False
    sharpness: float | None = None
    composition: float | None = None
    exposure: float | None = None
    semantic_name: str | None = None
    error: str | None = None
    stages_completed: list[str] = field(default_factory=lambda: ["scan"])


def _entry_to_json(entry: ManifestEntry) -> str:
    """Serialize a ManifestEntry to a JSON string."""
    return json.dumps(asdict(entry), ensure_ascii=False)


def _entry_from_json(line: str) -> ManifestEntry:
    """Deserialize a JSON string to a ManifestEntry."""
    data = json.loads(line)
    return ManifestEntry(**data)


def save_manifest(entries: list[ManifestEntry], path: Path) -> None:
    """Write entries to a JSONL file using atomic replace."""
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(_entry_to_json(entry) + "\n")
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_manifest(path: Path) -> list[ManifestEntry]:
    """Read all entries from a JSONL manifest file."""
    entries: list[ManifestEntry] = []
    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(_entry_from_json(line))
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Manifest line %d: %s", line_num, exc)
    return entries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_manifest.py::test_manifest_entry_round_trip -v`
Expected: PASS

- [ ] **Step 5: Write test for checkpoint flush**

```python
# tests/test_manifest.py (append)


def test_checkpoint_flush(tmp_path: Path) -> None:
    """checkpoint() writes current state without losing data on re-read."""
    from photo_workflow.manifest import checkpoint

    entries = [
        ManifestEntry(path=str(tmp_path / f"IMG_{i:04d}.jpg"))
        for i in range(100)
    ]
    manifest_path = tmp_path / "manifest.jsonl"
    save_manifest(entries, manifest_path)

    # Mutate entry 50 and checkpoint
    entries[50].sharpness = 0.85
    entries[50].stages_completed.append("score")
    checkpoint(entries, manifest_path)

    reloaded = load_manifest(manifest_path)
    assert len(reloaded) == 100
    assert reloaded[50].sharpness == 0.85
    assert "score" in reloaded[50].stages_completed
    # Unmutated entry still intact
    assert reloaded[0].sharpness is None
```

- [ ] **Step 6: Implement checkpoint function**

```python
# src/photo_workflow/manifest.py (append)


def checkpoint(entries: list[ManifestEntry], path: Path) -> None:
    """Flush current in-memory entries to disk via atomic replace.

    Identical to save_manifest — callers use this name to signal
    that it's a mid-stage flush rather than a final write.
    """
    save_manifest(entries, path)
```

- [ ] **Step 7: Run all manifest tests**

Run: `pytest tests/test_manifest.py -v`
Expected: 2 PASSED

- [ ] **Step 8: Write test for atomic replace safety**

```python
# tests/test_manifest.py (append)


def test_atomic_replace_preserves_old_on_disk(tmp_path: Path) -> None:
    """If the process reads a manifest, the file on disk is valid JSONL at all times."""
    manifest_path = tmp_path / "manifest.jsonl"

    original = [ManifestEntry(path=str(tmp_path / "a.jpg"))]
    save_manifest(original, manifest_path)

    # Overwrite with new data
    updated = [
        ManifestEntry(path=str(tmp_path / "a.jpg"), sharpness=0.5),
        ManifestEntry(path=str(tmp_path / "b.jpg")),
    ]
    save_manifest(updated, manifest_path)

    reloaded = load_manifest(manifest_path)
    assert len(reloaded) == 2
    assert reloaded[0].sharpness == 0.5

    # No .tmp files left behind
    assert list(tmp_path.glob("*.tmp")) == []
```

- [ ] **Step 9: Run all manifest tests**

Run: `pytest tests/test_manifest.py -v`
Expected: 3 PASSED

- [ ] **Step 10: Commit**

```bash
git add src/photo_workflow/manifest.py tests/test_manifest.py
git commit -m "feat: add JSONL manifest module with atomic checkpoint

ManifestEntry dataclass tracks per-photo state across pipeline stages.
save/load/checkpoint functions with atomic file replace for crash safety."
```

---

### Task 2: Progress Tracker

**Files:**
- Create: `src/photo_workflow/progress.py`
- Create: `tests/test_progress.py`

- [ ] **Step 1: Write failing test for progress line formatting**

```python
# tests/test_progress.py
"""Tests for the terminal progress tracker."""

from __future__ import annotations

from photo_workflow.progress import ProgressTracker


def test_progress_format_line() -> None:
    """format_line() produces the expected counter string."""
    tracker = ProgressTracker(stage="score", total=100)
    # Simulate 25 items done at 2.0 img/s
    line = tracker.format_line(current=25, elapsed_seconds=12.5, rss_mb=512)
    assert "[score]" in line
    assert "25/100" in line
    assert "25.0%" in line
    assert "img/s" in line
    assert "RSS" in line
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_progress.py::test_progress_format_line -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ProgressTracker**

```python
# src/photo_workflow/progress.py
"""Terminal progress display for long-running pipeline stages."""

from __future__ import annotations

import os
import sys
import time


def _get_rss_mb() -> int:
    """Return current process RSS in MB (Linux/Windows)."""
    try:
        import psutil
        return psutil.Process().memory_info().rss // (1024 * 1024)
    except ImportError:
        pass
    # Fallback for Linux: read /proc/self/status
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except (FileNotFoundError, ValueError):
        pass
    return 0


class ProgressTracker:
    """In-place terminal progress counter with throughput and ETA."""

    def __init__(self, stage: str, total: int) -> None:
        self.stage = stage
        self.total = total
        self._start_time = time.monotonic()
        self._current = 0

    def format_line(
        self,
        current: int,
        elapsed_seconds: float | None = None,
        rss_mb: int | None = None,
    ) -> str:
        """Build the progress string without printing it."""
        if elapsed_seconds is None:
            elapsed_seconds = time.monotonic() - self._start_time
        if rss_mb is None:
            rss_mb = _get_rss_mb()

        pct = (current / self.total * 100) if self.total > 0 else 0.0
        rate = current / elapsed_seconds if elapsed_seconds > 0 else 0.0
        remaining = self.total - current
        eta_seconds = remaining / rate if rate > 0 else 0
        eta_min = int(eta_seconds // 60)

        return (
            f"[{self.stage}] {current}/{self.total} ({pct:.1f}%) "
            f"| {rate:.1f} img/s | ETA {eta_min}m | RSS {rss_mb}MB"
        )

    def update(self, current: int) -> None:
        """Print an in-place progress line to stderr."""
        self._current = current
        line = self.format_line(current)
        sys.stderr.write(f"\r{line}")
        sys.stderr.flush()

    def finish(self) -> None:
        """Print final newline so the summary line doesn't overwrite progress."""
        sys.stderr.write("\n")
        sys.stderr.flush()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_progress.py::test_progress_format_line -v`
Expected: PASS

- [ ] **Step 5: Write test for ETA calculation**

```python
# tests/test_progress.py (append)


def test_progress_eta_calculation() -> None:
    """ETA decreases as more items complete."""
    tracker = ProgressTracker(stage="name", total=1000)
    line_early = tracker.format_line(current=100, elapsed_seconds=250.0)
    line_late = tracker.format_line(current=900, elapsed_seconds=2250.0)
    # Both should contain ETA; early ETA > late ETA
    assert "ETA" in line_early
    assert "ETA" in line_late
    # At 0.4 img/s, 900 remaining = 2250s = 37m; 100 remaining = 250s = 4m
    assert "37m" in line_early
    assert "4m" in line_late


def test_progress_zero_total() -> None:
    """Zero total doesn't crash — shows 0.0%."""
    tracker = ProgressTracker(stage="scan", total=0)
    line = tracker.format_line(current=0, elapsed_seconds=1.0)
    assert "0.0%" in line
```

- [ ] **Step 6: Run all progress tests**

Run: `pytest tests/test_progress.py -v`
Expected: 3 PASSED

- [ ] **Step 7: Commit**

```bash
git add src/photo_workflow/progress.py tests/test_progress.py
git commit -m "feat: add terminal progress tracker with throughput and ETA

ProgressTracker displays in-place counter with img/s, ETA, and RSS.
No external dependencies — uses stdlib only."
```

---

### Task 3: Scan Subcommand

**Files:**
- Modify: `src/photo_workflow/pipeline.py`
- Create: `tests/test_cli_stages.py`

- [ ] **Step 1: Write failing test for scan subcommand**

```python
# tests/test_cli_stages.py
"""Integration tests for the staged CLI subcommands."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image

from photo_workflow.manifest import load_manifest
from photo_workflow.pipeline import cli


@pytest.fixture()
def photo_dir(tmp_path: Path) -> Path:
    """Create 4 synthetic JPEG images in a flat directory."""
    d = tmp_path / "photos"
    d.mkdir()

    def save_jpg(arr: np.ndarray, name: str, dt_str: str) -> None:
        p = d / name
        img = Image.fromarray(arr.astype(np.uint8))
        exif = img.getexif()
        exif[0x0132] = dt_str
        img.save(p, "JPEG", quality=95, exif=exif.tobytes())

    checker = (np.indices((64, 64)).sum(axis=0) % 2 * 255).astype(np.uint8)
    checker_rgb = np.stack([checker] * 3, axis=2)
    save_jpg(checker_rgb, "IMG_0001.jpg", "2026:04:01 10:00:00")

    # Duplicate of IMG_0001
    shutil.copy2(d / "IMG_0001.jpg", d / "IMG_0002.jpg")

    gray = np.full((64, 64, 3), 128, dtype=np.uint8)
    save_jpg(gray, "IMG_0003.jpg", "2026:04:01 10:05:00")

    rng = np.random.default_rng(42)
    noise = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
    save_jpg(noise, "IMG_0004.jpg", "2026:04:01 14:00:00")

    return d


@pytest.fixture()
def manifest_path(tmp_path: Path) -> Path:
    return tmp_path / "manifest.jsonl"


def test_scan_creates_manifest(photo_dir: Path, manifest_path: Path) -> None:
    """scan subcommand discovers JPEGs and writes a manifest."""
    runner = CliRunner()
    result = runner.invoke(cli, ["scan", "--source", str(photo_dir), "--manifest", str(manifest_path)])
    assert result.exit_code == 0, result.output
    assert manifest_path.exists()

    entries = load_manifest(manifest_path)
    assert len(entries) == 4
    assert all("scan" in e.stages_completed for e in entries)
    assert "Scanned 4" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_stages.py::test_scan_creates_manifest -v`
Expected: FAIL — `ImportError: cannot import name 'cli'` (currently `main` is the entry point, not a group named `cli`)

- [ ] **Step 3: Refactor pipeline.py main() into click.Group with scan subcommand**

Open `src/photo_workflow/pipeline.py`. The current `main()` function (lines 158–188) defines a `@click.command()` named `cli`. Replace it with a `click.Group` and add the `scan` subcommand. Keep the `AnalysisPipeline` class and its dataclasses intact above.

Replace the `main()` function (lines 158–188) with:

```python
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
              help="Directory containing photos to process.")
@click.option("--manifest", "manifest_path", default="manifest.jsonl",
              type=click.Path(path_type=Path), show_default=True,
              help="Path to the JSONL manifest file.")
@click.option("--recursive", is_flag=True, default=False,
              help="Recurse into subdirectories.")
def scan(source: Path, manifest_path: Path, recursive: bool) -> None:
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

    save_manifest(entries, manifest_path)
    click.echo(f"Scanned {len(entries)} photos -> {manifest_path}")


def main() -> None:
    cli()
```

Also add `import click` at the top of the file if not already imported (it's currently imported inside `main()` — move it to module level):

Add after the existing imports at the top of pipeline.py:
```python
import click
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_stages.py::test_scan_creates_manifest -v`
Expected: PASS

- [ ] **Step 5: Write test for scan with --recursive flag**

```python
# tests/test_cli_stages.py (append)


def test_scan_recursive(photo_dir: Path, manifest_path: Path) -> None:
    """scan --recursive finds images in subdirectories."""
    sub = photo_dir / "subdir"
    sub.mkdir()
    shutil.copy2(photo_dir / "IMG_0001.jpg", sub / "IMG_0005.jpg")

    runner = CliRunner()
    result = runner.invoke(cli, [
        "scan", "--source", str(photo_dir), "--manifest", str(manifest_path), "--recursive",
    ])
    assert result.exit_code == 0
    entries = load_manifest(manifest_path)
    assert len(entries) == 5  # 4 original + 1 in subdir
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_cli_stages.py::test_scan_recursive -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/photo_workflow/pipeline.py tests/test_cli_stages.py
git commit -m "feat: refactor CLI to click.Group, add scan subcommand

photo-workflow is now a staged CLI with subcommands.
scan discovers photos, extracts EXIF timestamps, writes JSONL manifest."
```

---

### Task 4: Dedup Subcommand

**Files:**
- Modify: `src/photo_workflow/pipeline.py`
- Modify: `tests/test_cli_stages.py`

- [ ] **Step 1: Write failing test for dedup subcommand**

```python
# tests/test_cli_stages.py (append)


def test_dedup_groups_and_flags(photo_dir: Path, manifest_path: Path) -> None:
    """dedup assigns session IDs and flags duplicates."""
    runner = CliRunner()
    runner.invoke(cli, ["scan", "--source", str(photo_dir), "--manifest", str(manifest_path)])

    result = runner.invoke(cli, ["dedup", "--manifest", str(manifest_path)])
    assert result.exit_code == 0, result.output

    entries = load_manifest(manifest_path)
    assert all("dedup" in e.stages_completed for e in entries)

    # IMG_0002 is a byte-copy of IMG_0001 — should be flagged
    by_path = {Path(e.path).name: e for e in entries}
    assert by_path["IMG_0002.jpg"].is_duplicate is True
    assert by_path["IMG_0001.jpg"].is_duplicate is False

    # Session IDs assigned
    assert all(e.session_id != "" for e in entries)

    assert "sessions" in result.output.lower() or "duplicate" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_stages.py::test_dedup_groups_and_flags -v`
Expected: FAIL — `Error: No such command 'dedup'`

- [ ] **Step 3: Implement dedup subcommand in pipeline.py**

Add after the `scan` command definition in `pipeline.py`:

```python
@cli.command()
@click.option("--manifest", "manifest_path", required=True,
              type=click.Path(exists=True, path_type=Path),
              help="Path to the JSONL manifest file.")
def dedup(manifest_path: Path) -> None:
    """Group photos into sessions and flag duplicates."""
    from .manifest import ManifestEntry, load_manifest, save_manifest

    entries = load_manifest(manifest_path)

    # Check prerequisite: all entries must have scan completed
    not_scanned = [e for e in entries if "scan" not in e.stages_completed]
    if not_scanned:
        raise click.ClickException(
            f"{len(not_scanned)} photos have not been through 'scan'. "
            f"Run 'photo-workflow scan' first."
        )

    # Skip already-deduped entries
    to_process = [e for e in entries if "dedup" not in e.stages_completed]
    if not to_process:
        click.echo("All photos already deduped. Use --force to redo.")
        return

    # Build PhotoRecords for the grouping/dedup modules
    from .grouping import cluster_sessions
    from .dedup import deduplicate

    records = [
        PhotoRecord(path=Path(e.path), session_id=e.session_id)
        for e in entries
    ]

    records = cluster_sessions(records)
    records = deduplicate(records)

    # Write back to manifest entries
    for entry, record in zip(entries, records):
        entry.session_id = record.session_id
        entry.is_duplicate = record.is_duplicate
        if "dedup" not in entry.stages_completed:
            entry.stages_completed.append("dedup")

    save_manifest(entries, manifest_path)

    sessions = len({e.session_id for e in entries})
    dupes = sum(1 for e in entries if e.is_duplicate)
    click.echo(f"Grouped into {sessions} sessions, flagged {dupes} duplicates")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_stages.py::test_dedup_groups_and_flags -v`
Expected: PASS

- [ ] **Step 5: Write test for prerequisite enforcement**

```python
# tests/test_cli_stages.py (append)


def test_dedup_rejects_without_scan(tmp_path: Path) -> None:
    """dedup errors if manifest entries haven't been scanned."""
    from photo_workflow.manifest import ManifestEntry, save_manifest

    manifest_path = tmp_path / "manifest.jsonl"
    save_manifest([ManifestEntry(path="/fake.jpg", stages_completed=[])], manifest_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["dedup", "--manifest", str(manifest_path)])
    assert result.exit_code != 0
    assert "scan" in result.output.lower()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_cli_stages.py::test_dedup_rejects_without_scan -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/photo_workflow/pipeline.py tests/test_cli_stages.py
git commit -m "feat: add dedup subcommand with session grouping

Groups photos into sessions via EXIF timestamps, flags duplicates
via dHash. Enforces scan prerequisite. Updates manifest in place."
```

---

### Task 5: Score Subcommand

**Files:**
- Modify: `src/photo_workflow/pipeline.py`
- Modify: `tests/test_cli_stages.py`

- [ ] **Step 1: Write failing test for score subcommand**

```python
# tests/test_cli_stages.py (append)


def test_score_scores_non_duplicates(photo_dir: Path, manifest_path: Path) -> None:
    """score assigns sharpness/composition/exposure to non-duplicate photos."""
    runner = CliRunner()
    runner.invoke(cli, ["scan", "--source", str(photo_dir), "--manifest", str(manifest_path)])
    runner.invoke(cli, ["dedup", "--manifest", str(manifest_path)])

    result = runner.invoke(cli, ["score", "--manifest", str(manifest_path)])
    assert result.exit_code == 0, result.output

    entries = load_manifest(manifest_path)
    non_dupes = [e for e in entries if not e.is_duplicate]
    dupes = [e for e in entries if e.is_duplicate]

    for e in non_dupes:
        assert e.sharpness is not None
        assert e.composition is not None
        assert e.exposure is not None
        assert "score" in e.stages_completed

    for e in dupes:
        assert e.sharpness is None
        assert "score" not in e.stages_completed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_stages.py::test_score_scores_non_duplicates -v`
Expected: FAIL — `Error: No such command 'score'`

- [ ] **Step 3: Implement score subcommand**

Add after the `dedup` command in `pipeline.py`:

```python
@cli.command()
@click.option("--manifest", "manifest_path", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--resume", is_flag=True, default=False,
              help="Skip photos already scored.")
@click.option("--force", is_flag=True, default=False,
              help="Re-score all photos regardless of prior completion.")
@click.option("--verbose", is_flag=True, default=False)
@click.option("--quiet", is_flag=True, default=False)
def score(manifest_path: Path, resume: bool, force: bool, verbose: bool, quiet: bool) -> None:
    """Score photos for sharpness, composition, and exposure."""
    from .manifest import load_manifest, save_manifest, checkpoint
    from .progress import ProgressTracker
    from .sharpness import score_sharpness
    from .composition import score_composition
    from .exposure import score_exposure

    entries = load_manifest(manifest_path)

    # Prerequisite check
    not_deduped = [e for e in entries if "dedup" not in e.stages_completed]
    if not_deduped:
        raise click.ClickException(
            f"{len(not_deduped)} photos have not been through 'dedup'. "
            f"Run 'photo-workflow dedup' first."
        )

    # Select photos to process
    to_score = [
        e for e in entries
        if not e.is_duplicate and (force or "score" not in e.stages_completed)
    ]

    if not to_score and not force:
        if resume:
            click.echo("All non-duplicate photos already scored.")
        else:
            click.echo("All non-duplicate photos already scored. Use --resume or --force.")
        return

    if resume and not force:
        already = sum(1 for e in entries if not e.is_duplicate and "score" in e.stages_completed)
        if already > 0:
            click.echo(f"Resuming: {already} already scored, {len(to_score)} remaining")

    tracker = ProgressTracker(stage="score", total=len(to_score))
    errors = 0

    for i, entry in enumerate(to_score, 1):
        p = Path(entry.path)
        try:
            entry.sharpness = score_sharpness(p)
            entry.composition = score_composition(p)
            entry.exposure = score_exposure(p)
            entry.error = None
            if "score" not in entry.stages_completed:
                entry.stages_completed.append("score")
            if verbose:
                click.echo(
                    f"  {p.name}: sharp={entry.sharpness:.4f} "
                    f"comp={entry.composition:.4f} exp={entry.exposure:.4f}"
                )
        except Exception as exc:
            entry.error = str(exc)
            errors += 1
            logger.warning("Score failed for %s: %s", p, exc)

        if not quiet:
            tracker.update(i)

        if i % 50 == 0:
            checkpoint(entries, manifest_path)

    if not quiet:
        tracker.finish()

    save_manifest(entries, manifest_path)

    scored = len(to_score) - errors
    click.echo(f"Scored {scored}/{len(to_score)} photos. {errors} errors.")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_stages.py::test_score_scores_non_duplicates -v`
Expected: PASS

- [ ] **Step 5: Write test for score --resume**

```python
# tests/test_cli_stages.py (append)


def test_score_resume_skips_completed(photo_dir: Path, manifest_path: Path) -> None:
    """score --resume skips already-scored photos."""
    runner = CliRunner()
    runner.invoke(cli, ["scan", "--source", str(photo_dir), "--manifest", str(manifest_path)])
    runner.invoke(cli, ["dedup", "--manifest", str(manifest_path)])
    runner.invoke(cli, ["score", "--manifest", str(manifest_path)])

    # Run again with --resume — should skip all
    result = runner.invoke(cli, ["score", "--manifest", str(manifest_path), "--resume"])
    assert result.exit_code == 0
    assert "already scored" in result.output.lower()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_cli_stages.py::test_score_resume_skips_completed -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/photo_workflow/pipeline.py tests/test_cli_stages.py
git commit -m "feat: add score subcommand with resume and progress

Scores sharpness, composition, and exposure for non-duplicate photos.
Checkpoints every 50 photos. Supports --resume and --force flags."
```

---

### Task 6: Name Subcommand

**Files:**
- Modify: `src/photo_workflow/pipeline.py`
- Modify: `tests/test_cli_stages.py`

- [ ] **Step 1: Write failing test for name subcommand**

```python
# tests/test_cli_stages.py (append)


def test_name_assigns_semantic_names(photo_dir: Path, manifest_path: Path) -> None:
    """name assigns semantic names and renames files on disk (falls back to stem without model)."""
    runner = CliRunner()
    runner.invoke(cli, ["scan", "--source", str(photo_dir), "--manifest", str(manifest_path)])
    runner.invoke(cli, ["dedup", "--manifest", str(manifest_path)])
    runner.invoke(cli, ["score", "--manifest", str(manifest_path)])

    result = runner.invoke(cli, [
        "name", "--manifest", str(manifest_path),
        "--model-dir", "models/nonexistent",
    ])
    assert result.exit_code == 0, result.output

    entries = load_manifest(manifest_path)
    non_dupes = [e for e in entries if not e.is_duplicate]

    for e in non_dupes:
        assert e.semantic_name is not None
        assert e.semantic_name != ""
        assert "name" in e.stages_completed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_stages.py::test_name_assigns_semantic_names -v`
Expected: FAIL — `Error: No such command 'name'`

- [ ] **Step 3: Implement name subcommand**

Add after the `score` command in `pipeline.py`:

```python
@cli.command()
@click.option("--manifest", "manifest_path", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--model-dir", default="models/florence2_int8", show_default=True,
              type=click.Path(path_type=Path),
              help="Path to the Florence-2 INT8 ONNX model directory.")
@click.option("--resume", is_flag=True, default=False,
              help="Skip photos already named.")
@click.option("--force", is_flag=True, default=False,
              help="Re-name all photos regardless of prior completion.")
@click.option("--verbose", is_flag=True, default=False)
@click.option("--quiet", is_flag=True, default=False)
def name(
    manifest_path: Path,
    model_dir: Path,
    resume: bool,
    force: bool,
    verbose: bool,
    quiet: bool,
) -> None:
    """Generate semantic filenames via Florence-2 and rename files on disk."""
    from .manifest import load_manifest, save_manifest, checkpoint
    from .progress import ProgressTracker
    from .naming import generate_name

    entries = load_manifest(manifest_path)

    # Prerequisite check
    not_scored = [
        e for e in entries
        if not e.is_duplicate and "score" not in e.stages_completed
    ]
    if not_scored:
        raise click.ClickException(
            f"{len(not_scored)} photos have not been through 'score'. "
            f"Run 'photo-workflow score' first."
        )

    to_name = [
        e for e in entries
        if not e.is_duplicate and (force or "name" not in e.stages_completed)
    ]

    if not to_name and not force:
        if resume:
            click.echo("All non-duplicate photos already named.")
        else:
            click.echo("All non-duplicate photos already named. Use --resume or --force.")
        return

    if resume and not force:
        already = sum(
            1 for e in entries
            if not e.is_duplicate and "name" in e.stages_completed
        )
        if already > 0:
            click.echo(f"Resuming: {already} already named, {len(to_name)} remaining")

    tracker = ProgressTracker(stage="name", total=len(to_name))
    errors = 0

    for i, entry in enumerate(to_name, 1):
        p = Path(entry.path)
        try:
            slug = generate_name(p, model_dir=model_dir)
            entry.semantic_name = slug

            # Rename on disk
            new_path = _rename_photo_by_slug(p, slug)
            if new_path != p:
                entry.path = str(new_path)

            entry.error = None
            if "name" not in entry.stages_completed:
                entry.stages_completed.append("name")

            if verbose:
                click.echo(f"  {p.name} -> {slug}")
        except Exception as exc:
            entry.error = str(exc)
            errors += 1
            logger.warning("Name failed for %s: %s", p, exc)

        if not quiet:
            tracker.update(i)

        if i % 50 == 0:
            checkpoint(entries, manifest_path)

    if not quiet:
        tracker.finish()

    save_manifest(entries, manifest_path)

    named = len(to_name) - errors
    click.echo(f"Named {named}/{len(to_name)} photos. {errors} errors.")
```

Also add this helper function above the `cli` group definition (near the existing `_rename_photo` function):

```python
def _rename_photo_by_slug(path: Path, slug: str) -> Path:
    """Rename a photo on disk using a semantic slug. Returns the new path."""
    if not slug:
        return path
    directory = path.parent
    suffix = path.suffix
    candidate = directory / f"{slug}{suffix}"
    counter = 2
    while candidate.exists() and candidate != path:
        candidate = directory / f"{slug}_{counter}{suffix}"
        counter += 1
    if candidate == path:
        return path
    try:
        os.rename(path, candidate)
        logger.info("Renamed %s -> %s", path.name, candidate.name)
        return candidate
    except OSError as exc:
        logger.warning("Could not rename %s: %s", path, exc)
        return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_stages.py::test_name_assigns_semantic_names -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photo_workflow/pipeline.py tests/test_cli_stages.py
git commit -m "feat: add name subcommand with Florence-2 inference and file rename

Generates semantic slugs via Florence-2, renames files on disk,
updates manifest paths. Checkpoints every 50 photos for crash safety."
```

---

### Task 7: Sync Subcommand

**Files:**
- Modify: `src/photo_workflow/pipeline.py`
- Modify: `tests/test_cli_stages.py`

- [ ] **Step 1: Write failing test for sync subcommand**

```python
# tests/test_cli_stages.py (append)


def test_sync_writes_xmp_and_db(photo_dir: Path, manifest_path: Path, tmp_path: Path) -> None:
    """sync writes XMP sidecars and upserts into Darktable DB."""
    from conftest import make_darktable_db
    import sqlite3

    db_path = tmp_path / "library.db"
    make_darktable_db(db_path)

    runner = CliRunner()
    runner.invoke(cli, ["scan", "--source", str(photo_dir), "--manifest", str(manifest_path)])
    runner.invoke(cli, ["dedup", "--manifest", str(manifest_path)])
    runner.invoke(cli, ["score", "--manifest", str(manifest_path)])
    runner.invoke(cli, ["name", "--manifest", str(manifest_path), "--model-dir", "models/nonexistent"])

    result = runner.invoke(cli, ["sync", "--manifest", str(manifest_path), "--db", str(db_path)])
    assert result.exit_code == 0, result.output

    entries = load_manifest(manifest_path)
    non_dupes = [e for e in entries if not e.is_duplicate]

    # XMP sidecars exist
    for e in non_dupes:
        xmp = Path(e.path).with_suffix(".xmp")
        assert xmp.exists(), f"XMP missing for {e.path}"

    # DB has rows
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    assert count == len(non_dupes)

    assert "sync" in entries[0].stages_completed or entries[0].is_duplicate
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_stages.py::test_sync_writes_xmp_and_db -v`
Expected: FAIL — `Error: No such command 'sync'`

- [ ] **Step 3: Implement sync subcommand**

Add after the `name` command in `pipeline.py`:

```python
@cli.command()
@click.option("--manifest", "manifest_path", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--db", "db_path", required=True,
              type=click.Path(path_type=Path),
              help="Path to Darktable library.db.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Print what would happen without writing.")
def sync(manifest_path: Path, db_path: Path, dry_run: bool) -> None:
    """Write XMP sidecars and sync to Darktable library.db."""
    from .manifest import load_manifest, save_manifest
    from .darktable_bridge import sync_to_darktable

    entries = load_manifest(manifest_path)

    # Prerequisite: all non-duplicate entries must be named
    not_named = [
        e for e in entries
        if not e.is_duplicate and "name" not in e.stages_completed
    ]
    if not_named:
        raise click.ClickException(
            f"{len(not_named)} photos have not been through 'name'. "
            f"Run 'photo-workflow name' first."
        )

    # Build PhotoRecords for the darktable_bridge
    records = []
    for e in entries:
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
        click.echo(f"Dry run: would write {non_dupes} XMP sidecars and upsert {non_dupes} DB rows")
        return

    xmp_written, db_upserted = sync_to_darktable(records, db_path=db_path)

    # Mark sync complete in manifest
    for entry in entries:
        if not entry.is_duplicate and "sync" not in entry.stages_completed:
            entry.stages_completed.append("sync")
    save_manifest(entries, manifest_path)

    click.echo(f"Wrote {xmp_written} XMP sidecars, upserted {db_upserted} DB rows")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_stages.py::test_sync_writes_xmp_and_db -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photo_workflow/pipeline.py tests/test_cli_stages.py
git commit -m "feat: add sync subcommand for XMP + Darktable DB upsert

Writes XMP sidecars and upserts into library.db for all non-duplicate
photos. Supports --dry-run. Enforces name prerequisite."
```

---

### Task 8: Status Subcommand

**Files:**
- Modify: `src/photo_workflow/pipeline.py`
- Modify: `tests/test_cli_stages.py`

- [ ] **Step 1: Write failing test for status subcommand**

```python
# tests/test_cli_stages.py (append)


def test_status_reports_progress(photo_dir: Path, manifest_path: Path) -> None:
    """status prints a summary of per-stage completion."""
    runner = CliRunner()
    runner.invoke(cli, ["scan", "--source", str(photo_dir), "--manifest", str(manifest_path)])
    runner.invoke(cli, ["dedup", "--manifest", str(manifest_path)])

    result = runner.invoke(cli, ["status", "--manifest", str(manifest_path)])
    assert result.exit_code == 0
    assert "4" in result.output  # total photos
    assert "scanned" in result.output.lower() or "scan" in result.output.lower()
    assert "dedup" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_stages.py::test_status_reports_progress -v`
Expected: FAIL — `Error: No such command 'status'`

- [ ] **Step 3: Implement status subcommand**

Add after the `sync` command in `pipeline.py`:

```python
@cli.command()
@click.option("--manifest", "manifest_path", required=True,
              type=click.Path(exists=True, path_type=Path))
def status(manifest_path: Path) -> None:
    """Show manifest summary: per-stage completion and error count."""
    from .manifest import load_manifest

    entries = load_manifest(manifest_path)
    total = len(entries)
    dupes = sum(1 for e in entries if e.is_duplicate)

    stage_counts = {}
    for stage in ("scan", "dedup", "score", "name", "sync"):
        stage_counts[stage] = sum(1 for e in entries if stage in e.stages_completed)

    error_count = sum(1 for e in entries if e.error)

    click.echo(f"Manifest: {manifest_path}")
    click.echo(f"  Total photos:  {total}")
    click.echo(f"  Duplicates:    {dupes}")
    click.echo(f"  Scan:          {stage_counts['scan']}/{total}")
    click.echo(f"  Dedup:         {stage_counts['dedup']}/{total}")
    click.echo(f"  Score:         {stage_counts['score']}/{total - dupes} (non-duplicate)")
    click.echo(f"  Name:          {stage_counts['name']}/{total - dupes} (non-duplicate)")
    click.echo(f"  Sync:          {stage_counts['sync']}/{total - dupes} (non-duplicate)")
    click.echo(f"  Errors:        {error_count}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_stages.py::test_status_reports_progress -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photo_workflow/pipeline.py tests/test_cli_stages.py
git commit -m "feat: add status subcommand for manifest summary

Displays per-stage completion counts, duplicate count, and error count."
```

---

### Task 9: Full Pipeline Integration Test

**Files:**
- Modify: `tests/test_cli_stages.py`

- [ ] **Step 1: Write end-to-end integration test**

```python
# tests/test_cli_stages.py (append)


@pytest.mark.integration
def test_full_staged_pipeline(photo_dir: Path, manifest_path: Path, tmp_path: Path) -> None:
    """Full staged pipeline: scan -> dedup -> score -> name -> sync."""
    from conftest import make_darktable_db
    import sqlite3

    db_path = tmp_path / "library.db"
    make_darktable_db(db_path)

    runner = CliRunner()

    # Run all stages sequentially
    r1 = runner.invoke(cli, ["scan", "--source", str(photo_dir), "--manifest", str(manifest_path)])
    assert r1.exit_code == 0, r1.output

    r2 = runner.invoke(cli, ["dedup", "--manifest", str(manifest_path)])
    assert r2.exit_code == 0, r2.output

    r3 = runner.invoke(cli, ["score", "--manifest", str(manifest_path)])
    assert r3.exit_code == 0, r3.output

    r4 = runner.invoke(cli, ["name", "--manifest", str(manifest_path), "--model-dir", "models/nonexistent"])
    assert r4.exit_code == 0, r4.output

    r5 = runner.invoke(cli, ["sync", "--manifest", str(manifest_path), "--db", str(db_path)])
    assert r5.exit_code == 0, r5.output

    # Verify final state
    entries = load_manifest(manifest_path)
    non_dupes = [e for e in entries if not e.is_duplicate]

    # All non-dupes have all stages
    for e in non_dupes:
        assert set(e.stages_completed) == {"scan", "dedup", "score", "name", "sync"}
        assert e.sharpness is not None
        assert e.composition is not None
        assert e.exposure is not None
        assert e.semantic_name is not None

    # XMP files exist
    for e in non_dupes:
        assert Path(e.path).with_suffix(".xmp").exists()

    # DB has correct count
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    assert count == len(non_dupes)

    # Status works
    r6 = runner.invoke(cli, ["status", "--manifest", str(manifest_path)])
    assert r6.exit_code == 0
    assert "Errors:        0" in r6.output
```

- [ ] **Step 2: Run the integration test**

Run: `pytest tests/test_cli_stages.py::test_full_staged_pipeline -v -m integration`
Expected: PASS

- [ ] **Step 3: Run the full test suite to check for regressions**

Run: `pytest tests/ -v --tb=short -m "not slow"`
Expected: All tests PASS. The old `test_pipeline.py` tests still work because `AnalysisPipeline` class is unchanged.

- [ ] **Step 4: Commit**

```bash
git add tests/test_cli_stages.py
git commit -m "test: add full staged pipeline integration test

Runs scan -> dedup -> score -> name -> sync end-to-end with synthetic
fixtures. Verifies manifest state, XMP sidecars, and DB rows."
```

---

### Task 10: Backward Compatibility — Legacy Single-Command

**Files:**
- Modify: `src/photo_workflow/pipeline.py`
- Verify: existing `test_pipeline.py` still passes

- [ ] **Step 1: Add legacy run-all subcommand for backward compat**

Add a `run` subcommand that wraps the existing `AnalysisPipeline` for users who want the old monolithic behavior:

```python
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
```

- [ ] **Step 2: Verify existing pipeline tests still pass**

Run: `pytest tests/test_pipeline.py -v -m integration`
Expected: All 10 integration tests PASS

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/photo_workflow/pipeline.py
git commit -m "feat: add 'run' subcommand for legacy monolithic pipeline

Preserves backward compatibility — 'photo-workflow run' invokes the
original AnalysisPipeline with the same options as the old CLI."
```

---

## Verification Checklist

After all tasks are complete, run these final checks:

```bash
# All tests pass
pytest tests/ -v --tb=short

# CLI help works
photo-workflow --help
photo-workflow scan --help
photo-workflow status --help

# Ruff lint passes
ruff check src/photo_workflow/manifest.py src/photo_workflow/progress.py src/photo_workflow/pipeline.py

# Type check passes
mypy src/photo_workflow/manifest.py src/photo_workflow/progress.py
```
