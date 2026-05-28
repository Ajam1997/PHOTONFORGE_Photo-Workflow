# Ingest Pipeline — Full Pipeline with Stage Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the `ingest` sidecar command to run the full analysis pipeline (dedup → scoring → naming → Darktable sync) with per-stage skip flags, eject the SD card after copy, and update the IngestDashboard to show per-stage progress with persistent checkbox settings.

**Architecture:** The sidecar `ingest` command is rewritten in-place: it gains `--skip-*` flags and inline calls to the pipeline module functions after rsync finishes. A new `pipeline.ts` Svelte store persists stage settings to `localStorage`. The `ingest.ts` store gains `stageDone` and `sdEjected` fields so the running view can render each stage's status. `IngestDashboard.svelte` gains a pipeline checkbox section (idle) and a stage list (running).

**Tech Stack:** Python 3.11+, click, pytest, TypeScript, Svelte, localStorage

---

### File Map

| Action | Path |
|--------|------|
| Modify | `src/photo_workflow/sidecar_cli.py` |
| Modify | `tests/test_sidecar_cli.py` |
| Create | `photonforge-gui/src/stores/pipeline.ts` |
| Modify | `photonforge-gui/src/stores/ingest.ts` |
| Modify | `photonforge-gui/src/lib/sidecar.ts` |
| Modify | `photonforge-gui/src/panels/IngestDashboard.svelte` |

---

### Task 1: Add `_eject_sd()` helper to sidecar_cli.py

**Files:**
- Modify: `src/photo_workflow/sidecar_cli.py`
- Modify: `tests/test_sidecar_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sidecar_cli.py — add after existing imports

from unittest.mock import call


def test_eject_sd_calls_udisksctl_with_parent_disk(tmp_path: Path) -> None:
    """_eject_sd resolves partition to parent disk and calls udisksctl power-off."""
    from photo_workflow.sidecar_cli import _eject_sd

    fake_mounts = "/dev/mmcblk0p1 /media/alex/SD_CARD vfat rw 0 0\n"
    with patch("photo_workflow.sidecar_cli.Path") as mock_path_cls, \
         patch("photo_workflow.sidecar_cli.subprocess.run") as mock_run:
        mock_path_cls.return_value.read_text.return_value = fake_mounts
        _eject_sd("/media/alex/SD_CARD")

    mock_run.assert_called_once_with(
        ["udisksctl", "power-off", "-b", "/dev/mmcblk0"],
        check=False,
    )


def test_eject_sd_strips_partition_suffix_for_usb(tmp_path: Path) -> None:
    """_eject_sd handles /dev/sda1 → /dev/sda correctly."""
    from photo_workflow.sidecar_cli import _eject_sd

    fake_mounts = "/dev/sda1 /media/alex/CARD vfat rw 0 0\n"
    with patch("photo_workflow.sidecar_cli.Path") as mock_path_cls, \
         patch("photo_workflow.sidecar_cli.subprocess.run") as mock_run:
        mock_path_cls.return_value.read_text.return_value = fake_mounts
        _eject_sd("/media/alex/CARD")

    mock_run.assert_called_once_with(
        ["udisksctl", "power-off", "-b", "/dev/sda"],
        check=False,
    )


def test_eject_sd_is_silent_when_mount_not_found() -> None:
    """_eject_sd does nothing and does not raise if mount point not in /proc/mounts."""
    from photo_workflow.sidecar_cli import _eject_sd

    with patch("photo_workflow.sidecar_cli.Path") as mock_path_cls, \
         patch("photo_workflow.sidecar_cli.subprocess.run") as mock_run:
        mock_path_cls.return_value.read_text.return_value = ""
        _eject_sd("/media/alex/NONEXISTENT")

    mock_run.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sidecar_cli.py::test_eject_sd_calls_udisksctl_with_parent_disk tests/test_sidecar_cli.py::test_eject_sd_strips_partition_suffix_for_usb tests/test_sidecar_cli.py::test_eject_sd_is_silent_when_mount_not_found -v`
Expected: FAIL with `ImportError: cannot import name '_eject_sd'`

- [ ] **Step 3: Add `_eject_sd()` to sidecar_cli.py**

Add `import re` to the existing imports at the top of `src/photo_workflow/sidecar_cli.py`, then add after the `emit()` function:

```python
import re


def _eject_sd(mount_point: str) -> None:
    """Resolve SD card block device from mount point and power it off. Non-fatal."""
    try:
        device = None
        for line in Path("/proc/mounts").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == mount_point:
                device = parts[0]
                break
        if not device:
            return
        disk = re.sub(r"p?\d+$", "", device)
        subprocess.run(["udisksctl", "power-off", "-b", disk], check=False)
    except Exception:  # noqa: BLE001
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sidecar_cli.py::test_eject_sd_calls_udisksctl_with_parent_disk tests/test_sidecar_cli.py::test_eject_sd_strips_partition_suffix_for_usb tests/test_sidecar_cli.py::test_eject_sd_is_silent_when_mount_not_found -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/photo_workflow/sidecar_cli.py tests/test_sidecar_cli.py
git commit -m "feat: add _eject_sd() helper to sidecar_cli"
```

---

### Task 2: Rewrite `ingest` sidecar command with full pipeline and skip flags

**Files:**
- Modify: `src/photo_workflow/sidecar_cli.py`
- Modify: `tests/test_sidecar_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sidecar_cli.py — add after existing tests

from unittest.mock import MagicMock
from photo_workflow.pipeline import PhotoRecord


def _make_mock_popen(rsync_lines: list[str]) -> MagicMock:
    """Return a mock subprocess.Popen that yields rsync itemize-changes lines."""
    mock_proc = MagicMock()
    mock_proc.stdout = iter(rsync_lines)
    mock_proc.stderr.read.return_value = ""
    mock_proc.returncode = 0
    mock_proc.wait.return_value = 0
    return mock_proc


def _fake_records(paths: list[Path]) -> list[PhotoRecord]:
    return [PhotoRecord(path=p) for p in paths]


def test_ingest_full_pipeline_emits_sd_ejected_and_all_stage_dones(tmp_path: Path) -> None:
    """Full ingest emits sd_ejected and stage_done for each enabled stage."""
    fake_paths = [tmp_path / "DSC_0001.ARW", tmp_path / "DSC_0002.ARW"]
    for p in fake_paths:
        p.write_bytes(b"x")

    rsync_lines = [
        ">f+++++++++ DSC_0001.ARW\n",
        ">f+++++++++ DSC_0002.ARW\n",
    ]
    records = _fake_records(fake_paths)

    runner = CliRunner()
    with patch("photo_workflow.sidecar_cli.subprocess.Popen", return_value=_make_mock_popen(rsync_lines)), \
         patch("photo_workflow.sidecar_cli._eject_sd"), \
         patch("photo_workflow.sidecar_cli.cluster_sessions", return_value=records), \
         patch("photo_workflow.sidecar_cli.deduplicate", return_value=records), \
         patch("photo_workflow.sidecar_cli.score_sharpness", return_value=0.8), \
         patch("photo_workflow.sidecar_cli.score_composition", return_value=0.7), \
         patch("photo_workflow.sidecar_cli.score_exposure", return_value=0.9), \
         patch("photo_workflow.sidecar_cli.generate_name", return_value="golden-sunset"), \
         patch("photo_workflow.sidecar_cli.sync_to_darktable", return_value=(2, 2)):
        result = runner.invoke(cli, [
            "ingest",
            "--source", str(tmp_path),
            "--output", str(tmp_path),
            "--db", str(tmp_path / "library.db"),
        ])

    assert result.exit_code == 0, result.output
    events = parse_events(result.output)
    types = [e["type"] for e in events]
    assert "sd_ejected" in types
    stage_dones = {e["stage"] for e in events if e["type"] == "stage_done"}
    assert stage_dones == {"copy", "dedup", "scoring", "naming", "darktable"}
    done = next(e for e in events if e["type"] == "done")
    assert done["summary"]["total"] == 2
    assert done["summary"]["named"] == 2
    assert done["summary"]["xmp_written"] == 2


def test_ingest_skip_naming_and_darktable_omits_those_stage_dones(tmp_path: Path) -> None:
    """--skip-naming --skip-darktable produces no naming/darktable stage_done events."""
    fake_paths = [tmp_path / "DSC_0001.ARW"]
    fake_paths[0].write_bytes(b"x")
    records = _fake_records(fake_paths)

    runner = CliRunner()
    with patch("photo_workflow.sidecar_cli.subprocess.Popen", return_value=_make_mock_popen([">f+++++++++ DSC_0001.ARW\n"])), \
         patch("photo_workflow.sidecar_cli._eject_sd"), \
         patch("photo_workflow.sidecar_cli.cluster_sessions", return_value=records), \
         patch("photo_workflow.sidecar_cli.deduplicate", return_value=records), \
         patch("photo_workflow.sidecar_cli.score_sharpness", return_value=0.8), \
         patch("photo_workflow.sidecar_cli.score_composition", return_value=0.7), \
         patch("photo_workflow.sidecar_cli.score_exposure", return_value=0.9):
        result = runner.invoke(cli, [
            "ingest",
            "--source", str(tmp_path),
            "--output", str(tmp_path),
            "--db", str(tmp_path / "library.db"),
            "--skip-naming",
            "--skip-darktable",
        ])

    assert result.exit_code == 0, result.output
    events = parse_events(result.output)
    stage_dones = {e["stage"] for e in events if e["type"] == "stage_done"}
    assert "naming" not in stage_dones
    assert "darktable" not in stage_dones
    assert "copy" in stage_dones
    assert "scoring" in stage_dones
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sidecar_cli.py::test_ingest_full_pipeline_emits_sd_ejected_and_all_stage_dones tests/test_sidecar_cli.py::test_ingest_skip_naming_and_darktable_omits_those_stage_dones -v`
Expected: FAIL (imports not found / wrong command signature)

- [ ] **Step 3: Rewrite the `ingest` command in sidecar_cli.py**

Replace the entire `ingest` function and add the new imports. The full replacement for `src/photo_workflow/sidecar_cli.py` — add these imports at the top (after existing imports):

```python
from photo_workflow.grouping import cluster_sessions
from photo_workflow.dedup import deduplicate
from photo_workflow.sharpness import score_sharpness
from photo_workflow.composition import score_composition
from photo_workflow.exposure import score_exposure
from photo_workflow.naming import generate_name
from photo_workflow.darktable_bridge import sync_to_darktable
from photo_workflow.pipeline import PhotoRecord
```

Replace the entire `ingest` function:

```python
@cli.command()
@click.option("--source", required=True, help="Source mount path (SD card)")
@click.option("--output", required=True, help="Destination mount path (SSD)")
@click.option("--db", required=True, help="Path to library.db on SSD")
@click.option("--model-dir", default="models/florence2_int8", show_default=True, help="Florence-2 model directory")
@click.option("--skip-dedup", is_flag=True, default=False)
@click.option("--skip-scoring", is_flag=True, default=False)
@click.option("--skip-naming", is_flag=True, default=False)
@click.option("--skip-darktable", is_flag=True, default=False)
def ingest(
    source: str,
    output: str,
    db: str,
    model_dir: str,
    skip_dedup: bool,
    skip_scoring: bool,
    skip_naming: bool,
    skip_darktable: bool,
) -> None:
    """Ingest photos from SD to SSD and run the full analysis pipeline."""
    source_path = Path(source)
    output_path = Path(output)

    try:
        start = time.monotonic()

        # ── Copy ──────────────────────────────────────────────────────────────
        emit({"type": "progress", "step": "copying", "current": 0, "total": 0, "message": "Scanning…"})
        dcim_path = source_path / "DCIM"
        scan_root = dcim_path if dcim_path.is_dir() else source_path
        all_raws = [f for f in scan_root.rglob("*") if f.is_file() and f.suffix.lower() in RAW_EXTS]
        total = len(all_raws)
        emit({"type": "progress", "step": "copying", "current": 0, "total": total, "message": f"Found {total} RAW files"})

        copied_paths: list[Path] = []

        if total > 0:
            output_path.mkdir(parents=True, exist_ok=True)
            cmd = ["rsync", "--archive", "--itemize-changes", "--include=*/"]
            for ext in RAW_EXTS:
                cmd += [f"--include=*{ext}", f"--include=*{ext.upper()}"]
            cmd += ["--exclude=*", "--", str(scan_root) + "/", str(output_path) + "/"]

            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip()
                if line and not line.startswith("cd"):
                    fname = line[10:].strip() if len(line) > 10 else line
                    dest = output_path / fname
                    if dest.suffix.lower() in RAW_EXTS:
                        copied_paths.append(dest)
                    emit({"type": "progress", "step": "copying", "current": len(copied_paths), "total": total, "message": fname})
            proc.wait()
            if proc.returncode != 0:
                stderr = proc.stderr.read() if proc.stderr else ""  # type: ignore[union-attr]
                raise RuntimeError(stderr.strip() or f"rsync exited {proc.returncode}")

        emit({"type": "stage_done", "stage": "copy", "copied": len(copied_paths)})

        # Eject SD immediately — non-blocking, non-fatal
        _eject_sd(source)
        emit({"type": "sd_ejected"})

        if not copied_paths:
            elapsed = time.monotonic() - start
            emit({"type": "done", "summary": {"total": 0, "duplicates_skipped": 0, "scored": 0, "named": 0, "xmp_written": 0, "db_upserted": 0, "elapsed_seconds": round(elapsed, 2)}})
            return

        records = [PhotoRecord(path=p, metadata={"original_filename": p.name}) for p in copied_paths]

        # Session grouping always runs (prereq for dedup, fast)
        records = cluster_sessions(records)

        # ── Dedup ─────────────────────────────────────────────────────────────
        dupes_found = 0
        if not skip_dedup:
            emit({"type": "progress", "step": "dedup", "current": 0, "total": len(records), "message": f"Analysing {len(records)} files…"})
            records = deduplicate(records)
            dupes_found = sum(1 for r in records if r.is_duplicate)
            emit({"type": "stage_done", "stage": "dedup", "dupes_found": dupes_found})

        active = [r for r in records if not r.is_duplicate]

        # ── Scoring ───────────────────────────────────────────────────────────
        scored = 0
        if not skip_scoring:
            for i, record in enumerate(active):
                record.sharpness_score = score_sharpness(record.path)
                record.composition_score = score_composition(record.path)
                record.exposure_score = score_exposure(record.path)
                scored += 1
                emit({"type": "progress", "step": "scoring", "current": i + 1, "total": len(active), "message": record.path.name})
            emit({"type": "stage_done", "stage": "scoring", "scored": scored})

        # ── Naming ────────────────────────────────────────────────────────────
        named = 0
        if not skip_naming:
            model_path = Path(model_dir)
            for i, record in enumerate(active):
                record.semantic_name = generate_name(record.path, model_dir=model_path)
                named += 1
                emit({"type": "progress", "step": "naming", "current": i + 1, "total": len(active), "message": record.path.name})
            emit({"type": "stage_done", "stage": "naming", "named": named})

        # ── Darktable sync ────────────────────────────────────────────────────
        xmp_written = 0
        db_upserted = 0
        if not skip_darktable:
            xmp_written, db_upserted = sync_to_darktable(records, db_path=Path(db))
            emit({"type": "stage_done", "stage": "darktable", "xmp_written": xmp_written, "db_upserted": db_upserted})

        elapsed = time.monotonic() - start
        emit({
            "type": "done",
            "summary": {
                "total": len(records),
                "duplicates_skipped": dupes_found,
                "scored": scored,
                "named": named,
                "xmp_written": xmp_written,
                "db_upserted": db_upserted,
                "elapsed_seconds": round(elapsed, 2),
            },
        })
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "message": str(exc)})
        sys.exit(1)
```

- [ ] **Step 4: Run all sidecar tests**

Run: `pytest tests/test_sidecar_cli.py -v`
Expected: All pass. (The old `test_ingest_emits_progress_and_done_events` may fail — if so, update it in step 5.)

- [ ] **Step 5: Fix `test_ingest_emits_progress_and_done_events` if broken**

Replace the old test with a version compatible with the new ingest signature:

```python
def test_ingest_emits_progress_and_done_events(tmp_path: Path) -> None:
    """ingest streams progress and done events, exits 0."""
    fake_paths = [tmp_path / "DSC_0001.ARW", tmp_path / "DSC_0002.ARW"]
    for p in fake_paths:
        p.write_bytes(b"x")
    records = _fake_records(fake_paths)

    runner = CliRunner()
    with patch("photo_workflow.sidecar_cli.subprocess.Popen", return_value=_make_mock_popen([
            ">f+++++++++ DSC_0001.ARW\n",
            ">f+++++++++ DSC_0002.ARW\n",
        ])), \
         patch("photo_workflow.sidecar_cli._eject_sd"), \
         patch("photo_workflow.sidecar_cli.cluster_sessions", return_value=records), \
         patch("photo_workflow.sidecar_cli.deduplicate", return_value=records), \
         patch("photo_workflow.sidecar_cli.score_sharpness", return_value=0.8), \
         patch("photo_workflow.sidecar_cli.score_composition", return_value=0.7), \
         patch("photo_workflow.sidecar_cli.score_exposure", return_value=0.9), \
         patch("photo_workflow.sidecar_cli.generate_name", return_value="slug"), \
         patch("photo_workflow.sidecar_cli.sync_to_darktable", return_value=(2, 2)):
        result = runner.invoke(cli, [
            "ingest",
            "--source", str(tmp_path),
            "--output", str(tmp_path),
            "--db", str(tmp_path / "library.db"),
        ])

    assert result.exit_code == 0, result.output
    events = parse_events(result.output)
    types = [e["type"] for e in events]
    assert "progress" in types
    assert "done" in types
    done = next(e for e in events if e["type"] == "done")
    assert done["summary"]["total"] == 2
    assert "elapsed_seconds" in done["summary"]
```

- [ ] **Step 6: Run all sidecar tests to confirm green**

Run: `pytest tests/test_sidecar_cli.py -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/photo_workflow/sidecar_cli.py tests/test_sidecar_cli.py
git commit -m "feat: rewrite ingest command with full pipeline, skip flags, and SD ejection"
```

---

### Task 3: Create pipeline settings store

**Files:**
- Create: `photonforge-gui/src/stores/pipeline.ts`

- [ ] **Step 1: Create the file**

```typescript
// photonforge-gui/src/stores/pipeline.ts
import { writable } from "svelte/store";

export interface PipelineSettings {
  dedup: boolean;
  scoring: boolean;
  naming: boolean;
  darktable: boolean;
}

const STORAGE_KEY = "photon.pipeline";

const defaults: PipelineSettings = {
  dedup: true,
  scoring: true,
  naming: true,
  darktable: true,
};

function load(): PipelineSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...defaults, ...JSON.parse(raw) };
  } catch { /* ignore parse errors */ }
  return { ...defaults };
}

export const pipelineSettings = writable<PipelineSettings>(load());

pipelineSettings.subscribe((value) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch { /* ignore write errors */ }
});
```

- [ ] **Step 2: Verify TypeScript compiles**

Run from `photonforge-gui/`: `npx tsc --noEmit`
Expected: No errors for the new file.

- [ ] **Step 3: Commit**

```bash
git add photonforge-gui/src/stores/pipeline.ts
git commit -m "feat: add pipeline settings store with localStorage persistence"
```

---

### Task 4: Update ingest.ts store and sidecar.ts event types

**Files:**
- Modify: `photonforge-gui/src/stores/ingest.ts`
- Modify: `photonforge-gui/src/lib/sidecar.ts`

- [ ] **Step 1: Update `ingest.ts` — add `stageDone` and `sdEjected` to state**

Replace the entire content of `photonforge-gui/src/stores/ingest.ts`:

```typescript
import { writable } from "svelte/store";
import type { DoneEvent } from "../lib/sidecar";
import type { Command } from "@tauri-apps/plugin-shell";

export type IngestPhase = "idle" | "running" | "done";

export interface IngestState {
  phase: IngestPhase;
  step: string;
  current: number;
  total: number;
  summary: DoneEvent["summary"] | null;
  errorMsg: string;
  activeCmd: Command<string> | null;
  stageDone: Record<string, Record<string, unknown>>;
  sdEjected: boolean;
}

const initial: IngestState = {
  phase: "idle",
  step: "copying",
  current: 0,
  total: 0,
  summary: null,
  errorMsg: "",
  activeCmd: null,
  stageDone: {},
  sdEjected: false,
};

export const ingestState = writable<IngestState>({ ...initial });

export function resetIngest() {
  ingestState.set({ ...initial });
}
```

- [ ] **Step 2: Update `sidecar.ts` — add new event types and update `runIngest()`**

Add these interfaces after `ReformatDoneEvent` in `photonforge-gui/src/lib/sidecar.ts`:

```typescript
export interface StageDoneEvent {
  type: "stage_done";
  stage: "copy" | "dedup" | "scoring" | "naming" | "darktable";
  copied?: number;
  dupes_found?: number;
  scored?: number;
  named?: number;
  xmp_written?: number;
  db_upserted?: number;
}

export interface SdEjectedEvent {
  type: "sd_ejected";
}
```

Update the `DoneEvent` interface to include `named`:

```typescript
export interface DoneEvent {
  type: "done";
  summary: {
    total: number;
    duplicates_skipped: number;
    scored: number;
    named: number;
    xmp_written: number;
    db_upserted: number;
    elapsed_seconds: number;
  };
}
```

Add `StageDoneEvent` and `SdEjectedEvent` to the `SidecarEvent` union:

```typescript
export type SidecarEvent =
  | ProgressEvent
  | DoneEvent
  | ErrorEvent
  | CartridgesEvent
  | ReformatDoneEvent
  | ProvisionDoneEvent
  | StageDoneEvent
  | SdEjectedEvent;
```

Update `runIngest()` to accept skip options and pass them as CLI flags:

```typescript
export async function runIngest(
  source: string,
  output: string,
  db: string,
  onEvent: (event: SidecarEvent) => void,
  options: {
    skipDedup?: boolean;
    skipScoring?: boolean;
    skipNaming?: boolean;
    skipDarktable?: boolean;
    modelDir?: string;
  } = {},
): Promise<Command<string>> {
  const args = ["ingest", "--source", source, "--output", output, "--db", db];
  if (options.modelDir) args.push("--model-dir", options.modelDir);
  if (options.skipDedup) args.push("--skip-dedup");
  if (options.skipScoring) args.push("--skip-scoring");
  if (options.skipNaming) args.push("--skip-naming");
  if (options.skipDarktable) args.push("--skip-darktable");

  const cmd = Command.sidecar("binaries/photo-workflow-sidecar", args);

  let buffer = "";
  cmd.stdout.on("data", (chunk: string) => {
    buffer += chunk;
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const event = parseLine(line.trim());
      if (event) onEvent(event);
    }
  });

  await cmd.spawn();
  return cmd;
}
```

- [ ] **Step 3: Verify TypeScript compiles**

Run from `photonforge-gui/`: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add photonforge-gui/src/stores/ingest.ts photonforge-gui/src/lib/sidecar.ts
git commit -m "feat: add StageDoneEvent/SdEjectedEvent types, update runIngest() with skip options"
```

---

### Task 5: Update IngestDashboard.svelte

**Files:**
- Modify: `photonforge-gui/src/panels/IngestDashboard.svelte`

- [ ] **Step 1: Replace the entire file with the updated version**

```svelte
<script lang="ts">
  import { deviceState } from "../stores/devices";
  import { ingestState, resetIngest } from "../stores/ingest";
  import { pipelineSettings } from "../stores/pipeline";
  import { runIngest, type SidecarEvent, type StageDoneEvent } from "../lib/sidecar";

  $: canStart = $deviceState.sd_mounted && $deviceState.ssd_mounted;
  $: sourceLabel = $deviceState.sd_path ?? "No SD card";
  $: destLabel = $deviceState.ssd_label ?? "No cartridge";

  // Stage definitions — order matches execution order
  const STAGE_DEFS = [
    { key: "copying",   label: "Copy",           required: true  },
    { key: "dedup",     label: "Deduplication",  required: false },
    { key: "scoring",   label: "Scoring",        required: false },
    { key: "naming",    label: "AI Naming",      required: false },
    { key: "darktable", label: "Darktable sync", required: false },
  ] as const;

  type StageKey = typeof STAGE_DEFS[number]["key"];
  type StageStatus = "pending" | "active" | "done" | "skipped";

  interface StageEntry {
    key: StageKey;
    label: string;
    required: boolean;
    status: StageStatus;
    current: number;
    total: number;
    meta: Record<string, unknown> | undefined;
  }

  function isEnabled(key: StageKey): boolean {
    if (key === "copying") return true;
    return $pipelineSettings[key as keyof typeof $pipelineSettings] as boolean;
  }

  function stageStatus(key: StageKey): StageStatus {
    if (!isEnabled(key)) return "skipped";
    if ($ingestState.stageDone[key]) return "done";
    if ($ingestState.step === key) return "active";
    return "pending";
  }

  $: stageList = STAGE_DEFS.map((s): StageEntry => ({
    ...s,
    status: stageStatus(s.key),
    current: $ingestState.step === s.key ? $ingestState.current : 0,
    total: $ingestState.step === s.key ? $ingestState.total : 0,
    meta: $ingestState.stageDone[s.key],
  }));

  function stageMeta(entry: StageEntry): string {
    if (!entry.meta) return "";
    const m = entry.meta;
    if (entry.key === "copying")   return `${m.copied ?? 0} files`;
    if (entry.key === "dedup")     return `${m.dupes_found ?? 0} dupes removed`;
    if (entry.key === "scoring")   return `${m.scored ?? 0} scored`;
    if (entry.key === "naming")    return `${m.named ?? 0} named`;
    if (entry.key === "darktable") return `${m.xmp_written ?? 0} XMP, ${m.db_upserted ?? 0} DB rows`;
    return "";
  }

  function stageIcon(status: StageStatus): string {
    if (status === "done")    return "✓";
    if (status === "active")  return "▶";
    if (status === "skipped") return "—";
    return "○";
  }

  async function startIngest() {
    if (!canStart) return;
    const sd  = $deviceState.sd_path!;
    const ssd = $deviceState.ssd_mount_point!;
    const db  = `${ssd}/library.db`;

    ingestState.update(s => ({
      ...s,
      phase: "running",
      step: "copying",
      current: 0,
      total: 0,
      errorMsg: "",
      summary: null,
      activeCmd: null,
      stageDone: {},
      sdEjected: false,
    }));

    try {
      const cmd = await runIngest(sd, ssd, db, (event: SidecarEvent) => {
        if (event.type === "progress") {
          ingestState.update(s => ({ ...s, step: event.step, current: event.current, total: event.total }));
        } else if (event.type === "stage_done") {
          const e = event as StageDoneEvent;
          ingestState.update(s => ({
            ...s,
            stageDone: { ...s.stageDone, [e.stage]: e as unknown as Record<string, unknown> },
          }));
        } else if (event.type === "sd_ejected") {
          ingestState.update(s => ({ ...s, sdEjected: true }));
        } else if (event.type === "done") {
          ingestState.update(s => ({ ...s, phase: "done", summary: event.summary, activeCmd: null }));
        } else if (event.type === "error") {
          ingestState.update(s => ({ ...s, phase: "idle", errorMsg: event.message, activeCmd: null }));
        }
      }, {
        skipDedup:     !$pipelineSettings.dedup,
        skipScoring:   !$pipelineSettings.scoring,
        skipNaming:    !$pipelineSettings.naming,
        skipDarktable: !$pipelineSettings.darktable,
      });
      ingestState.update(s => ({ ...s, activeCmd: cmd }));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      ingestState.update(s => ({ ...s, phase: "idle", errorMsg: `Failed to start: ${msg}`, activeCmd: null }));
    }
  }

  function cancelIngest() {
    $ingestState.activeCmd?.kill().catch(() => {});
    ingestState.update(s => ({ ...s, phase: "idle", activeCmd: null }));
  }
</script>

<div class="ingest-panel">
  {#if $ingestState.phase === "idle"}
    <div class="idle-view">
      <h2>Ingest Photos</h2>

      <div class="device-row">
        <span class="label">Source</span>
        <span class="value" class:missing={!$deviceState.sd_mounted}>
          {$deviceState.sd_mounted ? sourceLabel : "Insert SD card"}
        </span>
      </div>
      <div class="device-row">
        <span class="label">Destination</span>
        <span class="value" class:missing={!$deviceState.ssd_mounted}>
          {$deviceState.ssd_mounted ? destLabel : "No cartridge mounted"}
        </span>
      </div>

      {#if $ingestState.errorMsg}
        <p class="error">{$ingestState.errorMsg}</p>
      {/if}

      <div class="pipeline-section">
        <h3>Pipeline</h3>
        {#each STAGE_DEFS as stage}
          <div class="stage-checkbox-row">
            {#if stage.required}
              <input type="checkbox" checked disabled />
            {:else}
              <input
                type="checkbox"
                checked={$pipelineSettings[stage.key as keyof typeof $pipelineSettings]}
                on:change={(e) => pipelineSettings.update(s => ({ ...s, [stage.key]: e.currentTarget.checked }))}
              />
            {/if}
            <span class="stage-checkbox-label">{stage.label}</span>
            {#if stage.required}
              <span class="required-badge">Required</span>
            {/if}
          </div>
        {/each}
      </div>

      <button class="primary-btn" disabled={!canStart} on:click={startIngest}>
        Start Ingest
      </button>
    </div>

  {:else if $ingestState.phase === "running"}
    <div class="running-view">
      <h2>Processing…</h2>

      <div class="stage-list">
        {#each stageList as entry (entry.key)}
          <div class="stage-row"
            class:stage-active={entry.status === "active"}
            class:stage-done={entry.status === "done"}
            class:stage-skipped={entry.status === "skipped"}
          >
            <span class="stage-icon">{stageIcon(entry.status)}</span>
            <span class="stage-name">{entry.label}</span>
            {#if entry.status === "active"}
              <div class="stage-progress">
                <span class="stage-count">{entry.current} / {entry.total}</span>
                <div class="mini-bar">
                  <div class="mini-fill" style="width: {entry.total > 0 ? (entry.current / entry.total) * 100 : 0}%"></div>
                </div>
              </div>
            {:else if entry.status === "done"}
              <span class="stage-meta">{stageMeta(entry)}</span>
            {:else if entry.status === "skipped"}
              <span class="stage-meta">(skipped)</span>
            {/if}
          </div>
        {/each}

        {#if $ingestState.sdEjected}
          <div class="sd-ejected-row">
            <span class="stage-icon eject-icon">⏏</span>
            <span class="stage-name">SD card ejected</span>
            <span class="stage-meta">you can continue shooting</span>
          </div>
        {/if}
      </div>

      <button class="cancel-btn" on:click={cancelIngest}>Cancel</button>
    </div>

  {:else if $ingestState.phase === "done" && $ingestState.summary}
    <div class="done-view">
      <h2>Ingest Complete</h2>
      <div class="summary-card">
        <div class="summary-row"><span>Total files</span><strong>{$ingestState.summary.total}</strong></div>
        <div class="summary-row"><span>Duplicates skipped</span><strong>{$ingestState.summary.duplicates_skipped}</strong></div>
        <div class="summary-row"><span>Images scored</span><strong>{$ingestState.summary.scored}</strong></div>
        <div class="summary-row"><span>Images named</span><strong>{$ingestState.summary.named}</strong></div>
        <div class="summary-row"><span>XMP written</span><strong>{$ingestState.summary.xmp_written}</strong></div>
        <div class="summary-row"><span>DB rows upserted</span><strong>{$ingestState.summary.db_upserted}</strong></div>
        <div class="summary-row"><span>Elapsed</span><strong>{$ingestState.summary.elapsed_seconds.toFixed(1)}s</strong></div>
      </div>
      <button class="primary-btn" on:click={resetIngest}>New Ingest</button>
    </div>
  {/if}
</div>

<style>
  .ingest-panel {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 1.5rem;
    padding: 2.5rem 3rem;
  }
  .idle-view, .running-view, .done-view {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1rem;
    width: 100%;
    max-width: 480px;
  }
  h2 { color: var(--text-primary, #fff); font-size: 1.5rem; margin: 0; }
  h3 { color: var(--text-primary, #fff); font-size: 1rem; margin: 0; align-self: flex-start; }
  .device-row {
    display: flex; justify-content: space-between;
    width: 100%; padding: 0.5rem 0;
    border-bottom: 1px solid var(--border, #333);
  }
  .label { color: var(--text-muted, #888); }
  .value { color: var(--text-primary, #fff); }
  .value.missing { color: var(--warning, #f59e0b); }

  /* Pipeline checkboxes */
  .pipeline-section {
    width: 100%;
    background: var(--surface, #1a1a1a);
    border-radius: 0.5rem;
    padding: 1rem;
    display: flex; flex-direction: column; gap: 0.6rem;
  }
  .stage-checkbox-row {
    display: flex; align-items: center; gap: 0.6rem;
    color: var(--text-primary, #fff); font-size: 0.9rem;
  }
  .stage-checkbox-label { flex: 1; }
  .required-badge {
    font-size: 0.7rem; padding: 0.1rem 0.4rem;
    background: rgba(99,102,241,0.2); color: var(--accent, #6366f1);
    border-radius: 0.25rem;
  }

  /* Stage list */
  .stage-list { width: 100%; display: flex; flex-direction: column; gap: 0.5rem; }
  .stage-row {
    display: flex; align-items: center; gap: 0.75rem;
    padding: 0.5rem 0.75rem;
    border-radius: 0.375rem;
    background: var(--surface, #1a1a1a);
    font-size: 0.9rem;
  }
  .stage-row.stage-active  { background: rgba(99,102,241,0.1); border: 1px solid rgba(99,102,241,0.3); }
  .stage-row.stage-done    { opacity: 0.8; }
  .stage-row.stage-skipped { opacity: 0.4; }
  .stage-icon { width: 1.2rem; text-align: center; color: var(--text-muted, #888); }
  .stage-row.stage-done  .stage-icon { color: #4ade80; }
  .stage-row.stage-active .stage-icon { color: var(--accent, #6366f1); }
  .stage-name { flex: 1; color: var(--text-primary, #fff); }
  .stage-meta { color: var(--text-muted, #888); font-size: 0.8rem; }
  .stage-progress { display: flex; align-items: center; gap: 0.5rem; }
  .stage-count { color: var(--text-muted, #888); font-size: 0.8rem; white-space: nowrap; }
  .mini-bar { width: 80px; height: 4px; background: var(--border, #333); border-radius: 2px; overflow: hidden; }
  .mini-fill { height: 100%; background: var(--accent, #6366f1); transition: width 0.2s; }
  .sd-ejected-row {
    display: flex; align-items: center; gap: 0.75rem;
    padding: 0.5rem 0.75rem;
    border-radius: 0.375rem;
    background: rgba(99,102,241,0.08);
    font-size: 0.9rem;
  }
  .eject-icon { color: var(--accent, #6366f1); }

  /* Buttons */
  .primary-btn {
    padding: 0.75rem 2rem; background: var(--accent, #6366f1);
    color: #fff; border: none; border-radius: 0.5rem;
    font-size: 1rem; cursor: pointer; width: 100%;
  }
  .primary-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .cancel-btn {
    padding: 0.75rem 2rem; background: transparent;
    color: var(--warning, #f59e0b); border: 1px solid var(--warning, #f59e0b);
    border-radius: 0.5rem; font-size: 1rem; cursor: pointer; width: 100%;
  }

  /* Summary */
  .summary-card {
    width: 100%; background: var(--surface, #1a1a1a);
    border-radius: 0.5rem; padding: 1rem;
    display: flex; flex-direction: column; gap: 0.5rem;
  }
  .summary-row { display: flex; justify-content: space-between; color: var(--text-muted, #888); }
  .summary-row strong { color: var(--text-primary, #fff); }
  .error { color: var(--error, #ef4444); }
</style>
```

- [ ] **Step 2: Verify TypeScript compiles**

Run from `photonforge-gui/`: `npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add photonforge-gui/src/panels/IngestDashboard.svelte
git commit -m "feat: add pipeline stage checkboxes, stage list progress view, and updated summary"
```

---

### Task 6: Rebuild sidecar binary and verify on Yoga

**Files:**
- Rebuild: `photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu`

- [ ] **Step 1: Push all commits to GitHub**

```bash
git push origin main
```

- [ ] **Step 2: Pull and rebuild binary on Yoga**

```bash
ssh alex@10.27.27.10 'cd ~/PHOTONFORGE_Photo-Workflow && git pull --ff-only && source .venv/bin/activate && pyinstaller --onefile --name photo-workflow-sidecar --distpath photonforge-gui/src-tauri/binaries --workpath /tmp/pyinstaller-build --specpath /tmp/pyinstaller-build src/photo_workflow/sidecar_cli.py && mv photonforge-gui/src-tauri/binaries/photo-workflow-sidecar photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu && chmod +x photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu && echo "Build OK"'
```

Expected: `Build OK`

- [ ] **Step 3: Dry-run smoke test on Yoga**

```bash
ssh alex@10.27.27.10 'cd ~/PHOTONFORGE_Photo-Workflow && photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu ingest --source /tmp --output /tmp/out --db /tmp/out/library.db --skip-darktable 2>&1 | head -5'
```

Expected: First few JSON progress lines, exits cleanly (total=0 if no RAW files in /tmp).

- [ ] **Step 4: Copy binary back to Windows and commit**

```bash
scp "alex@10.27.27.10:~/PHOTONFORGE_Photo-Workflow/photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu" "photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu"
git add photonforge-gui/src-tauri/binaries/photo-workflow-sidecar-x86_64-unknown-linux-gnu
git commit -m "chore: rebuild sidecar binary with full pipeline ingest command"
git push origin main
```

- [ ] **Step 5: Restart Tauri dev app on Yoga**

```bash
ssh alex@10.27.27.10 'pkill -f "target/debug/photonforge" 2>/dev/null; export PATH="/home/alex/.nvm/versions/node/v20.20.2/bin:/home/alex/.cargo/bin:$PATH" && cd ~/PHOTONFORGE_Photo-Workflow/photonforge-gui && nohup npm run tauri dev > /tmp/tauri-dev.log 2>&1 & until grep -qE "Running \`target" /tmp/tauri-dev.log 2>/dev/null; do sleep 3; done; echo "App ready"'
```

Expected: `App ready`

---

## Self-Review

**Spec coverage:**
- ✓ Copy → Dedup → Scoring → Naming → Darktable skip flags (Task 2)
- ✓ SD ejected after copy (Task 2, `_eject_sd`)
- ✓ `sd_ejected` event emitted (Task 2)
- ✓ `stage_done` events for each stage (Task 2)
- ✓ `pipeline.ts` store with localStorage (Task 3)
- ✓ `ingest.ts` `stageDone` + `sdEjected` (Task 4)
- ✓ `StageDoneEvent`, `SdEjectedEvent` types (Task 4)
- ✓ `runIngest()` accepts skip options (Task 4)
- ✓ Idle view checkboxes (Task 5)
- ✓ Running view stage list with per-stage progress (Task 5)
- ✓ SD ejected row in running view (Task 5)
- ✓ Updated summary card with `named`, `xmp_written`, `db_upserted` (Task 5)
- ✓ Binary rebuild (Task 6)

**Type consistency:** `StageDoneEvent` defined in Task 4 and imported in Task 5. `PipelineSettings` keys (`dedup`, `scoring`, `naming`, `darktable`) match `STAGE_DEFS` keys and `runIngest()` option names throughout. `stageDone` record keys match sidecar stage names (`copy`, `dedup`, `scoring`, `naming`, `darktable`).
