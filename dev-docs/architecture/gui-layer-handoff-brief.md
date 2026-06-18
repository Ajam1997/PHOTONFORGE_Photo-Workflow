# PHOTONForge GUI Layer — Handoff Brief

**Date:** 2026-05-27
**Branch:** `feature/gui-layer` (from `main` @ `ab88401`)
**Author:** @architect session — brainstorming + architecture design
**Status:** Design complete, no implementation code yet

---

## 1. What This Is

A lightweight DearPyGui application that orchestrates two headless engines:

- **PHOTONForge** (Python) — AI scoring, naming, genre classification, edit suggestions
- **darktable-cli** (native C) — raw decoding, pixel processing, rendered output

The GUI does no image processing itself. It is a thin display and orchestration layer.
XMP sidecars are the shared contract between all three components.

```
+-------------------------------------+
|     GUI Process (DearPyGui, native)  |
|  Library | Single Image | Edit views |
+------+---------------------+--------+
       |                     |
  subprocess            subprocess
       |                     |
+------v------+     +--------v--------+
| PHOTONForge |     | darktable-cli   |
| (headless)  |     | (headless)      |
| AI engine   |     | pixel engine    |
+------+------+     +--------^--------+
       |                     |
       +-------- XMP --------+
       +--- photonforge.db --+
```

---

## 2. Why This Architecture

The previous integration was one-directional: PHOTONForge scores/names photos, writes
XMP sidecars and SQLite metadata, then the user manually opens Darktable to edit.
There was no programmatic control of the editing step.

This architecture closes the loop: PHOTONForge analysis drives edit suggestions
(exposure compensation, tone mapping, color grading), which are written as Darktable
XMP history stack entries and rendered via `darktable-cli`. The user sees AI-proposed
edits and tweaks from there. "AI proposes, user disposes."

### Why Not Fork/Plugin Darktable

- **Plugin path (Option 1):** Darktable's Lua API can't touch the pixel pipeline.
  C IOP modules are per-pixel transforms, not orchestration layers. Would require
  full C++ rewrite of PHOTONForge for capabilities the API doesn't expose.
- **Headless fork (Option 2):** Nobody has successfully extracted Darktable's pixel
  pipeline into a library. The ~90 IOP modules assume a running `darktable_t` singleton.
  4-8 month effort, perpetual upstream merge burden, lethal for a solo developer.
- **Pure Python raw editor (Option 3):** Libraries exist (rawpy, lensfunpy) but denoise
  and tone mapping quality would lag Darktable's 15 years of hand-tuned C code.
  Performance marginal on i7-7500U (15-45s per 24MP image).

The hybrid approach ships AI-driven editing in weeks, not months.

---

## 3. Technology Choices

| Component | Choice | Rationale |
|---|---|---|
| GUI framework | **DearPyGui >= 2.0** | Built-in texture management, image display, DPI scaling. No manual OpenGL wiring. Wheels exist for Python 3.11 Linux x86_64 and Windows. |
| Python bindings | N/A (DearPyGui is the binding) | Chose over pyimgui because DearPyGui handles texture upload, GL context, and input routing out of the box. pyimgui would require manual SDL2+OpenGL setup. |
| IPC to engines | **subprocess + filesystem + SQLite** | Both engines are CLI tools. darktable-cli only outputs to files. Preview render cadence is ~1-2fps, not 30fps — disk I/O for a 2MP JPEG is ~5ms. Shared memory complexity not justified. |
| Image format (previews) | **JPEG** | Fast decode, small on disk, sufficient for screen preview. Full quality stays in the raw file. |
| Threading | **ThreadPoolExecutor(max_workers=2)** | Workers are I/O-bound (subprocess wait, disk reads). GIL not a bottleneck — CPU work happens in subprocesses. |

---

## 4. Target Hardware Constraints

These are hard constraints from the existing project. The GUI must operate within them.

| Constraint | Value | Source |
|---|---|---|
| CPU | Intel i7-7500U / i7-8550U (2C/4T, AVX2) | NFR target |
| RAM | 8 GB total | Hardware |
| GPU | Intel UHD 620 (shared memory, 128MB-1GB from system RAM) | Hardware |
| RSS cap | **1.5 GB** total across all processes | NFR-2.2 |
| CPU affinity | **<= 80%** | NFR-2.2 |
| Network | **None at runtime** (100% offline) | NFR-2.1 |
| Database location | photonforge.db lives on external SSD, not host | NFR-2.3 |

### Memory Budget

| Component | Budget | Notes |
|---|---|---|
| GUI process (Python + DearPyGui) | ~80 MB | Baseline |
| Thumbnail textures (50 visible) | ~24 MB | 400x300 RGB float x 50 |
| Preview textures (1-2 active) | ~16 MB | 1920x1080 RGB float x 2 |
| SQLite read cache | ~5 MB | WAL mode reader |
| **GUI subtotal** | **~125 MB** | |
| PHOTONForge inference (subprocess) | ~800 MB | Florence-2 + CLIP + YOLO |
| darktable-cli (subprocess) | ~300-500 MB | Varies by module pipeline |

**Critical:** PHOTONForge inference and darktable-cli must never run simultaneously.
A semaphore in the worker pool enforces mutual exclusion. During editing (darktable-cli
active), inference is idle. During scoring (inference active), preview rendering pauses.

---

## 5. Process Model

```
GUI Process (native Python, NOT in Docker)
|
+-- Main Thread: DearPyGui render loop (vsync, 30fps target)
|   +-- polls queue.Queue for completed work items
|   +-- updates textures via dpg.set_value() (must be main thread)
|   +-- reads photonforge.db (SQLite WAL mode, read-only)
|
+-- Worker "engine" (ThreadPoolExecutor):
|   +-- runs PHOTONForge CLI stages as subprocesses
|   +-- parses --json-progress stdout (NDJSON, line by line)
|   +-- posts WorkItem results to main-thread queue
|
+-- Worker "renderer" (ThreadPoolExecutor):
    +-- runs darktable-cli for preview renders
    +-- generates thumbnails (rawpy half_size or darktable-cli)
    +-- posts rendered image paths to main-thread queue
```

### Why GUI Runs Native (Not Docker)

PHOTONForge's Docker container was designed for the headless udev-triggered pipeline.
The GUI needs:
- GPU access for DearPyGui rendering (Intel UHD 620 via Mesa/OpenGL)
- Direct filesystem access for darktable-cli and XMP sidecars
- Low-latency input handling

Docker continues to serve the autonomous ingest pipeline. The GUI is a separate
entry point that can invoke PHOTONForge either natively (`python -m photo_workflow`)
or via Docker (`docker exec photonforge photo-workflow`), controlled by config flag.

---

## 6. Three Views

### 6.1 Library View

Thumbnail grid with PHOTONForge metadata overlays.

**Data source:** `SELECT * FROM [folder_table] ORDER BY master_score DESC`
from photonforge.db.

**Per-thumbnail overlays:**
- Star rating (from `master_score`: 0-0.2 = 1 star, ..., 0.8-1.0 = 5 stars)
- Primary genre badge (from `genre` column)
- Color dot matching Darktable color label
- "DUP" watermark for `is_duplicate=1`
- "!" badge for `needs_review=1` (low-confidence genre classification)

**Interactions:**
- Single click: select, show metadata in sidebar
- Double click: open Single Image View
- Filter bar: by genre, score range, duplicate status
- Sort: by score (desc), by name, by EXIF timestamp

### 6.2 Single Image View

Full-size preview with analysis panel.

**Left panel:** Screen-resolution preview rendered by darktable-cli
(`--width 1920 --height 1080 --hq true`). Cached on disk; invalidated when XMP changes.

**Right panel:** PHOTONForge analysis readout:
- Genre + confidence
- Sharpness / composition / exposure scores with bar charts
- Master score
- Semantic name (Florence-2 caption)
- All sub-scores (eye_sharpness, subject_isolation, zone_entropy, etc.)
- [Edit >>] button to enter Edit View

### 6.3 Edit View

Sliders mapped to Darktable module parameters with debounced live preview.

**Left panel:** Preview image, re-rendered via darktable-cli on slider change.

**Right panel:** Module sliders:
- Exposure: EV compensation (-3 to +3), black point (0-100)
- White Balance: temperature (2500-10000K), tint (0.5-2.0)
- Filmic RGB: white relative EV, black relative EV, contrast
- Sharpening: amount, radius, threshold
- Color Balance RGB: shadows/midtones/highlights lift

**Debounce:** 500ms after last slider movement, write XMP and invoke darktable-cli.
On slider release, fire immediately. Expected render latency: 1-3s per re-render.

**"Apply AI Preset" button:** Populates all sliders with PHOTONForge-suggested values
based on the image's analysis scores and genre. User tweaks from there.

**"Before/After" toggle:** Two cached previews — original (no edits) and current.

---

## 7. Image Flow

```
SD Card
  |
  v
[PHOTONForge ingest] --> Photos land on SSD (e.g., H:\ICELAND\)
  |
  v
[PHOTONForge scan + dedup + score + name]
  |
  +--> photonforge.db updated (scores, genres, semantic names)
  +--> XMP sidecars written (photon:* namespace)
  |
  v
GUI reads photonforge.db
  |
  +-- Library View: thumbnails from preview cache
  |     Thumbnails generated lazily:
  |       rawpy half_size decode --> Pillow resize --> JPEG --> disk cache
  |       OR: darktable-cli <raw> <xmp> <thumb.jpg> --width 400 --height 300
  |
  +-- Single Image View: screen-res preview
  |     darktable-cli <raw> <xmp> <preview.jpg> --width 1920 --height 1080
  |     Cached on disk; invalidated when XMP mtime changes
  |
  +-- Edit View: user adjusts sliders
        |
        +-- GUI constructs XMP history stack entries (xmp_builder.py)
        +-- darktable-cli re-renders preview (debounced)
        +-- GUI loads new preview JPEG, uploads as texture
```

### Thumbnail Cache

**Location:** `<ssd_root>/.photonforge/thumbs/<folder>/<filename>_400.jpg`

Lives on the SSD so the cache travels with the cartridge (NFR-2.3 compliant).
Uses relative paths internally for mount-point portability.

**Invalidation:** Hash or mtime of the XMP sidecar. If XMP changes, thumbnail is stale.

---

## 8. XMP History Stack Construction

This is the critical integration surface. Darktable stores processing parameters
as a history stack in XMP sidecars.

### 8.1 Darktable XMP Format

Each history entry is an `<rdf:li>` element:

```xml
<darktable:history>
  <rdf:Seq>
    <rdf:li
      darktable:operation="exposure"
      darktable:enabled="1"
      darktable:modversion="7"
      darktable:params="[base64-encoded binary blob]"
      darktable:multi_name=""
      darktable:multi_priority="0"
      darktable:blendop_version="13"
      darktable:blendop_params="[base64-encoded binary blob]" />
  </rdf:Seq>
</darktable:history>
```

The `darktable:params` blob is a C struct specific to each module and version.
For example, `exposure` module version 7 is `struct { float exposure; float black; }`.

### 8.2 XmpHistoryBuilder Design

```python
@dataclass
class DtModuleParams:
    operation: str          # "exposure", "temperature", "filmicrgb"
    modversion: int         # must match installed Darktable version
    enabled: bool
    params: dict[str, float | int | str]  # human-readable params

class XmpHistoryBuilder:
    def __init__(self, darktable_version: str = "5.0"): ...
    def set_exposure(self, ev: float, black: float = 0.0) -> None: ...
    def set_white_balance(self, temperature: int, tint: float) -> None: ...
    def set_filmic(self, white_ev: float, black_ev: float, contrast: float) -> None: ...
    def set_sharpen(self, amount: float, radius: float) -> None: ...
    def build_xmp(self, base_xmp_path: Path) -> str: ...
    def _encode_params(self, module: DtModuleParams) -> str: ...
```

**Phase 1 modules** (the 80/20 set):

| Module | Key Params | Why First |
|---|---|---|
| `exposure` | EV, black point | Most fundamental edit |
| `temperature` | temperature (K), tint | White balance |
| `filmicrgb` | white/black relative EV, contrast, latitude | Primary tone mapper |
| `sharpen` | amount, radius, threshold | Maps from sharpness score |
| `colorbalancergb` | shadows/midtones/highlights lift | Color grading |

### 8.3 HIGHEST RISK: Binary Param Encoding

The `darktable:params` blobs are C struct layouts that change between Darktable
versions. Reverse-engineering the struct definitions requires reading Darktable's
source code (`src/iop/*.c`, each module defines `dt_iop_*_params_t`).

**Timebox:** 2 days for the research spike. If binary encoding proves too fragile,
**fallback** to Darktable's Lua scripting interface to apply presets/styles
instead of raw XMP manipulation.

**Version detection:** `darktable-cli --version` at GUI startup. Only support
the installed version. Store param struct definitions in a version-keyed registry.

---

## 9. AI-Suggested Edits

```python
def suggest_edits(record_row: sqlite3.Row) -> list[DtModuleParams]:
    """Generate Darktable edit suggestions from PHOTONForge analysis."""
```

Maps analysis scores to concrete edit parameters:

| Score Signal | Edit Action |
|---|---|
| `zone_entropy < 0.5` (underexposed) | `exposure` EV += 0.5 + (0.5 - zone_entropy) |
| `dynamic_range < 0.4` | `filmicrgb` contrast boost, wider latitude |
| `genre == "portrait"` | Softer sharpening, warmer WB shift |
| `genre == "landscape"` | Higher contrast, cooler WB, stronger sharpen |
| `face_exposure < 0.5` (dark faces) | Targeted exposure lift |
| `exposure_style == "high_key"` | Preserve bright look, gentle filmic |

These are starting-point heuristics. The long-term vision is learning per-genre
tone curves from the user's own Darktable edit exports.

---

## 10. Existing Codebase Integration Points

### 10.1 photonforge.db Schema (per-folder table)

```sql
CREATE TABLE [folder_name] (
    filename        TEXT PRIMARY KEY,
    original_name   TEXT NOT NULL,
    exif_timestamp  TEXT,
    session_id      TEXT DEFAULT '',
    is_duplicate    INTEGER DEFAULT 0,
    sharpness       REAL,
    composition     REAL,
    exposure        REAL,
    semantic_name   TEXT DEFAULT '',
    stages          TEXT DEFAULT '',
    error           TEXT DEFAULT '',
    genre           TEXT DEFAULT '',
    genre_confidence REAL DEFAULT 0.0,
    master_score    REAL DEFAULT 0.0,
    sub_scores      TEXT DEFAULT '',   -- JSON blob
    dhash           TEXT DEFAULT ''
);
```

**Important:** Currently uses `PRAGMA journal_mode=DELETE` (line 34 of photondb.py).
The GUI requires **WAL mode** for concurrent read (GUI) + write (PHOTONForge subprocess).
Add WAL activation when the GUI is the consumer.

### 10.2 XMP Sidecar (photon:* namespace)

The existing `darktable_bridge.py` writes XMP with these PHOTONForge-specific fields:

- `photon:SharpnessScore`, `photon:CompositionScore`, `photon:ExposureScore`
- `photon:MasterScore`, `photon:Genre`, `photon:GenreConfidence`
- `photon:SemanticName`, `photon:SessionID`, `photon:IsDuplicate`
- `photon:EyeSharpness`, `photon:SubjectSharpness`, `photon:SubjectIsolation`
- `photon:ZoneEntropy`, `photon:DynamicRange`, `photon:ExposureStyle`
- `photon:AestheticScore`, `photon:BlurType`, `photon:NeedsReview`
- `photon:Genres` (rdf:Bag of genre labels)

The GUI's `xmp_builder.py` must **merge** Darktable history stack entries into
these existing XMP sidecars, not replace them.

### 10.3 Key Dataclasses

From `scoring_types.py`:

- **`PhotoRecord`** — pipeline state per image (path, scores, genre, sub_scores dict)
- **`FusionResult`** — final scored output (master_score, subject, photo_type, star_rating, color_label)
- **`GenreResult`** — two-axis classification (subject x photo_type)
- **`SharpnessScores`**, **`CompositionScores`**, **`ExposureScores`** — per-module breakdowns

### 10.4 CLI Entry Points

```bash
# Full pipeline
photo-workflow --source-dir /mnt/sd --output-dir /mnt/ssd/FOLDER --darktable-db /path/library.db

# With JSON progress (for GUI consumption)
photo-workflow --source-dir ... --output-dir ... --json-progress

# Cartridge management
photo-cartridge provision --label ICELAND /mnt/ssd
```

### 10.5 Score Fusion Weights

`score_fusion.py` defines per-subject and per-photo-type weight profiles.
The GUI's AI edit suggestions should reference the same taxonomy:

- **Subjects (16):** person, people, child, wildlife, cat, dog, bird, insect, vehicle, building, food, flower, signage, product, abstract, general
- **Photo Types (12):** portrait, street, landscape, event, macro, architecture, waterfall, documentary, night, sports, studio, general

---

## 11. Module Layout

```
src/photo_workflow/
    gui/
        __init__.py           # Import guard: fail fast if dearpygui not installed
        app.py                # DearPyGui bootstrap, viewport setup, main()
        state.py              # AppState dataclass: current folder, selected image, view mode
        views/
            __init__.py
            library.py        # Thumbnail grid, filtering, sorting
            single.py         # Full-size preview + analysis panel
            edit.py           # Slider panel + live preview
            components.py     # Shared widgets: score bars, genre badges, star ratings
        engine_bridge.py      # Subprocess wrapper for PHOTONForge CLI
        renderer_bridge.py    # Subprocess wrapper for darktable-cli (debounced)
        xmp_builder.py        # XMP history stack construction
        preview_cache.py      # Thumbnail/preview generation and disk cache
        texture_manager.py    # DearPyGui texture lifecycle (create, update, free)
        suggest.py            # AI-suggested edit generation from scores
        constants.py          # DT module versions, param struct definitions
```

### pyproject.toml Addition

```toml
[project.optional-dependencies]
gui = [
    "dearpygui>=2.0",
]

[project.scripts]
photonforge-gui = "photo_workflow.gui.app:main"
```

The GUI is an optional dependency. The headless pipeline never installs `dearpygui`.

---

## 12. Build Sequence (10 Steps)

| Step | Description | Depends On | Effort |
|---|---|---|---|
| GUI-1 | Scaffold `gui/` package, DearPyGui hello-world, pyproject.toml `[gui]` extra | -- | 1 day |
| GUI-2 | `texture_manager.py` + `preview_cache.py`: rawpy thumbnails, disk cache, texture upload | GUI-1 | 2-3 days |
| GUI-3 | Library view: thumbnail grid from photonforge.db, filtering, sorting | GUI-2 | 3-4 days |
| GUI-4 | `engine_bridge.py`: subprocess wrapper for PHOTONForge CLI with NDJSON progress | GUI-1 | 1-2 days |
| GUI-5 | `renderer_bridge.py`: darktable-cli subprocess wrapper, debounced re-render | GUI-1 | 1-2 days |
| GUI-6 | Single image view: full preview via darktable-cli, analysis panel from DB | GUI-3, GUI-5 | 2-3 days |
| **GUI-7** | **`xmp_builder.py`: reverse-engineer DT 5.0 param structs for Phase 1 modules** | **Research spike** | **2 days (timeboxed)** |
| GUI-8 | Edit view: sliders mapped to XMP builder, debounced preview re-render | GUI-6, GUI-7 | 3-4 days |
| GUI-9 | `suggest.py`: AI edit suggestions from scores, "Apply AI Preset" button | GUI-8 | 2-3 days |
| GUI-10 | Performance tuning: memory semaphore, WAL mode, texture upload optimization | GUI-8 | 2-3 days |

**Total estimated effort: 4-6 weeks**

**GUI-7 is the research spike.** If binary param encoding is too fragile, pivot to
Darktable Lua scripting as the edit application mechanism.

---

## 13. Key Interfaces

```python
# gui/app.py
def main() -> None:
    """Entry point: photonforge-gui CLI command."""

# gui/engine_bridge.py
class EngineBridge:
    def __init__(self, use_docker: bool = False, container_name: str = "photonforge"): ...
    def run_stage(self, stage: str, folder: str, db_path: Path,
                  on_progress: Callable[[dict], None]) -> None: ...

# gui/renderer_bridge.py
class RendererBridge:
    def render_preview(self, raw_path: Path, xmp_path: Path, output_path: Path,
                       width: int, height: int, hq: bool = False,
                       on_complete: Callable[[Path], None]) -> None: ...

# gui/preview_cache.py
class PreviewCache:
    def get_thumbnail(self, photo_path: Path, folder: str) -> Path | None: ...
    def generate_thumbnail(self, photo_path: Path, folder: str) -> Path: ...
    def get_preview(self, photo_path: Path, xmp_path: Path) -> Path | None: ...
    def invalidate(self, photo_path: Path) -> None: ...

# gui/xmp_builder.py
class XmpHistoryBuilder:
    def set_exposure(self, ev: float, black: float = 0.0) -> None: ...
    def set_white_balance(self, temperature: int, tint: float) -> None: ...
    def set_filmic(self, white_ev: float, black_ev: float, contrast: float) -> None: ...
    def build_xmp(self, base_xmp_path: Path) -> str: ...

# gui/suggest.py
def suggest_edits(record_row: sqlite3.Row) -> list[DtModuleParams]: ...

# gui/state.py
@dataclass
class AppState:
    current_folder: str
    current_db: Path
    current_source_dir: Path
    selected_image: str | None
    view_mode: Literal["library", "single", "edit"]
    use_docker: bool
```

---

## 14. Open Questions To Resolve During Implementation

1. **DT param binary format (GUI-7):** The `darktable:params` base64 blobs are C
   struct layouts. Must reverse-engineer from Darktable 5.0 source (`src/iop/*.c`,
   each module defines `dt_iop_*_params_t`). Fallback: Lua scripting interface.

2. **darktable-cli preview quality vs speed:** `--hq true` applies full pipeline
   (slower). `--hq false` is faster but skips some processing. Benchmark both on
   i7-7500U to pick the right mode for interactive editing vs final export.

3. **DearPyGui texture update perf:** `dpg.set_value()` for 1920x1080x3 floats
   is ~24MB as a Python list. May take 10-50ms. If > 16ms (one frame), consider
   `add_static_texture` recreation pattern or accept a dropped frame.

4. **WAL mode migration:** photondb.py line 34 uses `PRAGMA journal_mode=DELETE`.
   Must switch to WAL when GUI is running for concurrent reader+writer access.
   The headless pipeline can stay on DELETE.

5. **rawpy vs darktable-cli for thumbnails:** rawpy `half_size` is ~200ms, darktable-cli
   is ~1-3s. Colors will differ. Recommended: rawpy for initial fast thumbnails,
   background job replaces with darktable-cli rendered thumbnails over time.

6. **Genre-specific AI edit presets:** The `suggest_edits()` mappings need
   photographic judgment (what does "a good portrait preset" mean in Darktable terms?).
   Start with conservative defaults, iterate with real photos.

7. **Darktable version coupling:** If Darktable upgrades, `modversion` and param
   structs may change. XmpHistoryBuilder needs version detection (`darktable-cli --version`)
   and per-version param struct registry. Support only the installed version.

8. **Cartridge portability:** Preview cache on SSD must use relative paths so
   cartridges work at different mount points.

---

## 15. Long-Term Vision (Beyond This Phase)

### Phase 2: Lightweight Python Processing Chain
rawpy + lensfunpy + numpy filmic curve + OpenCV denoise for fast AI preview
loops. darktable-cli remains the final output renderer.

### Phase 3: ONNX Processing Modules
Replace traditional processing modules with neural networks, one at a time:
- **Denoise:** NAFNet or SCUNet, INT8 ONNX, ~50ms per 512x512 tile
- **Tone mapping:** MLP trained on user's own Darktable edit exports
- **Color grading:** 3D LUT prediction from CLIP embedding
- **Super-resolution:** Real-ESRGAN-lite for crop recovery

The strategic bet: neural models will surpass hand-tuned C modules for most
photography use cases within 2-3 years. Building the AI orchestration layer now
in Python positions us to swap in better models as they appear.

---

## 16. Quick Start for New Session

```bash
# 1. Check out the branch
git checkout feature/gui-layer

# 2. Install with GUI extras
pip install -e ".[gui]"

# 3. Verify DearPyGui works
python -c "import dearpygui.dearpygui as dpg; dpg.create_context(); print('OK')"

# 4. Start with GUI-1: scaffold the gui/ package
#    Create __init__.py, app.py with hello-world viewport, update pyproject.toml

# 5. Verify darktable-cli is available
darktable-cli --version
```

### Files to Read First
1. This document
2. `CLAUDE.md` (project constraints, conventions, agent roster)
3. `src/photo_workflow/photondb.py` (DB schema)
4. `src/photo_workflow/darktable_bridge.py` (existing XMP writer)
5. `src/photo_workflow/scoring_types.py` (dataclasses)
6. `src/photo_workflow/pipeline.py` (PhotoRecord, PipelineConfig, CLI flags)
7. `src/photo_workflow/score_fusion.py` (genre weight taxonomy)
