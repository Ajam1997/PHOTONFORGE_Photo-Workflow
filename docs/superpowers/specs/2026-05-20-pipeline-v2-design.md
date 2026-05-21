# PHOTONForge Pipeline v2 Design Spec

## Goal

Replace the fragile JSONL manifest with a per-cartridge SQLite database, eliminate the sync step by importing photos into Darktable at scan time, add sequential file naming at ingest with cartridge/trip prefixes, write semantic names to Darktable description (not tags), and simplify the Lua panel UI.

## Architecture

The pipeline remains a staged CLI (`photo-workflow ingest|scan|dedup|score|name`) invoked by the Darktable Lua plugin via background subprocess. The JSONL manifest is replaced by `photonforge.db` at the cartridge root. Each trip subdirectory gets its own table inside that database. Darktable import happens at scan time, eliminating the sync step entirely.

Data flows: SD card -> ingest (copy + rename) -> scan (EXIF + DB insert + Darktable import) -> dedup (dHash grouping) -> score (sharpness/composition/exposure) -> name (Florence-2 semantic caption to description).

## Tech Stack

- Python 3.11+, click CLI, SQLite via stdlib `sqlite3`
- rawpy for ARW/raw thumbnail extraction
- onnxruntime (Florence-2 INT8) for captioning
- Darktable Lua API for UI panel and library integration

---

## 1. SQLite Pipeline Database

### 1.1 Location

One `photonforge.db` file at the cartridge root (e.g., `H:\photonforge.db`). Travels with the SSD cartridge. The path is derived from the destination path's drive root or mount point.

### 1.2 Schema

Each subdirectory (trip folder) gets its own table. Table name is the sanitized folder name (alphanumeric + underscore only, e.g., `ICELAND`, `WEDDING_2026`).

```sql
CREATE TABLE IF NOT EXISTS {folder_name} (
    filename       TEXT PRIMARY KEY,   -- P003ICE0000001.ARW
    original_name  TEXT NOT NULL,      -- DSC03056.ARW
    exif_timestamp TEXT,               -- ISO 8601 (2026-05-10T14:32:01)
    session_id     TEXT DEFAULT '',
    is_duplicate   INTEGER DEFAULT 0,
    sharpness      REAL,
    composition    REAL,
    exposure       REAL,
    semantic_name  TEXT DEFAULT '',
    stages         TEXT DEFAULT '',    -- comma-separated: "scan,dedup,score,name"
    error          TEXT DEFAULT ''
);
```

### 1.3 Stage Tracking

Each pipeline step appends its name to the `stages` column (comma-separated). Resumption queries filter on `stages NOT LIKE '%score%'` etc. Force mode clears the relevant stage string from all rows before processing.

### 1.4 Module: `src/photo_workflow/photondb.py`

New module replacing `manifest.py`. Public API:

- `open_db(dest_path: Path) -> Connection` — opens/creates `photonforge.db` at the drive root of `dest_path`
- `ensure_table(conn, folder_name: str)` — creates table if not exists
- `insert_photo(conn, table, filename, original_name, exif_timestamp)` — insert after ingest/scan
- `update_stages(conn, table, filename, stage: str)` — append stage to stages column
- `get_pending(conn, table, stage: str) -> list[Row]` — files missing a given stage
- `update_scores(conn, table, filename, sharpness, composition, exposure)` — write scoring results
- `update_semantic(conn, table, filename, semantic_name)` — write Florence-2 result
- `mark_duplicate(conn, table, filename)` — set is_duplicate=1

All writes use transactions for atomicity.

---

## 2. Revised Pipeline Stages

### 2.1 Ingest (modified)

**Command:** `photo-workflow ingest --source <sd> --dest <dest>`

Copies files from SD card to destination directory. New behavior:

1. Read the volume label of the source drive to extract cartridge ID (e.g., PHOTONFORGE-003 -> `003`).
2. Derive trip code from destination folder name: first 3 uppercase characters (ICELAND -> `ICE`).
3. Sort discovered files by EXIF capture timestamp.
4. Rename during copy to `P{cart}{trip}{seq7}.{ext}` format.
   - Example: `P003ICE0000001.ARW`, `P003ICE0000002.ARW`
   - Sequence is 7 digits, zero-padded, starting at 1 (or continuing from highest existing sequence in destination).
5. Skip files already present in destination (by original name lookup in photonforge.db if it exists).

**Volume label detection:**
- Windows: Python `ctypes.windll.kernel32.GetVolumeInformationW()` — reads volume label directly via Win32 API, no subprocess, no terminal flash.
- Linux: `lsblk --output LABEL --noheadings /dev/sdX`

### 2.2 Scan (modified)

**Command:** `photo-workflow scan --source <dest> --db <photonforge.db>`

Discovers all supported image files in the destination directory. For each file:

1. Read EXIF timestamp.
2. Insert row into photonforge.db (table = folder name) with filename, original_name, exif_timestamp.
3. Mark `stages = "scan"`.

After scan completes, the Lua applicator calls `dt.films.new(dest_path)` to import/rescan the folder into Darktable's library. This creates Darktable's own XMP sidecars and makes photos visible in lighttable.

**Manifest CLI option removed.** Replaced by `--db` pointing to photonforge.db.

### 2.3 Dedup (unchanged logic, new storage)

**Command:** `photo-workflow dedup --db <photonforge.db> --folder <folder_name>`

Reads all scanned photos from the DB table. Runs session clustering (EXIF time gaps) and dHash deduplication using embedded JPEG thumbnails. Updates `session_id`, `is_duplicate`, and `stages` in the DB.

Applicator sets `rating=0` and `red=true` on duplicates in Darktable.

### 2.4 Score (unchanged logic, new storage)

**Command:** `photo-workflow score --db <photonforge.db> --folder <folder_name>`

Scores non-duplicate photos for sharpness, composition, and exposure. Writes results to DB. Applicator sets star ratings (0-5) and color labels in Darktable.

Uses `load_gray` / `load_rgb` from `raw_loader.py` for raw file support.

### 2.5 Name (modified output target)

**Command:** `photo-workflow name --db <photonforge.db> --folder <folder_name> --model-dir <path>`

Generates Florence-2 semantic captions. Writes the semantic name to:
- `semantic_name` column in photonforge.db
- Darktable image description field via applicator (`img:set_metadata("description", name)`)

**NOT** written to tags. NOT used for file renaming (files already named at ingest).

### 2.6 Sync (REMOVED)

No longer needed. Darktable import at scan time creates XMP sidecars. Score/dedup/name results are applied to Darktable images via the Lua applicator in real time.

---

## 3. File Naming Convention

### 3.1 Format

```
P{CCC}{TTT}{NNNNNNN}.{ext}
```

- `P` — fixed prefix identifying PHOTONForge-managed files
- `CCC` — 3-digit cartridge number from volume label (e.g., `003`)
- `TTT` — 3-character trip code from folder name (e.g., `ICE`)
- `NNNNNNN` — 7-digit zero-padded sequence number (e.g., `0000001`)
- `.ext` — preserved original extension (e.g., `.ARW`)

### 3.2 Sequence Assignment

Files are sorted by EXIF capture timestamp before sequence assignment. If the destination already contains PHOTONForge-named files, the sequence continues from the highest existing number + 1.

### 3.3 Cartridge ID Extraction

Parse volume label string: `PHOTONFORGE-003` -> extract digits after the last hyphen -> zero-pad to 3 digits. If the volume label doesn't match the `PHOTONFORGE-` pattern, fall back to `000`.

### 3.4 Trip Code Derivation

Take the destination folder's basename, uppercase it, strip non-alpha characters, take first 3 characters. If fewer than 3 characters remain, right-pad with `X`. Examples:
- `ICELAND` -> `ICE`
- `My Trip` -> `MYT`
- `AB` -> `ABX`

---

## 4. Lua Plugin UI Changes

### 4.1 Panel Layout (top to bottom)

1. **SD card path** — text entry + Browse button (folder picker)
2. **Destination** — text entry + Browse button (folder picker)
3. **TZ offset (hrs)** — text entry (unchanged)
4. **Run mode** — combobox: resume / force / fresh (unchanged)
5. **Step checkboxes** — ingest, scan, dedup, score, name (sync removed)
6. **Run / Stop buttons** (unchanged)
7. **Log view** (unchanged)

### 4.2 Browse Button

Each Browse button launches a native folder picker. On Windows, this must avoid `io.popen` (which flashes a terminal window). Instead, use a helper approach:

1. Write a tiny VBScript to `%TEMP%\photonforge_browse.vbs` that opens a `BrowseForFolder` COM dialog and writes the result to `%TEMP%\photonforge_browse.txt`.
2. Launch via `os.execute('wscript "' .. vbs_path .. '"')` — `wscript` is a GUI host, no console window.
3. Read the result file.

```vbs
Set objShell = CreateObject("Shell.Application")
Set objFolder = objShell.BrowseForFolder(0, "Select folder", &H0001)
If Not objFolder Is Nothing Then
    Set fso = CreateObject("Scripting.FileSystemObject")
    Set f = fso.CreateTextFile(fso.GetSpecialFolder(2) & "\photonforge_browse.txt", True)
    f.WriteLine objFolder.Self.Path
    f.Close
End If
```

On Linux, fall back to `zenity --file-selection --directory`.

### 4.3 Removed Fields

- **Model dir** — hardcoded to `models/florence2_int8` in the Python pipeline. Not user-configurable.
- **Manifest** — replaced by photonforge.db, path derived from destination drive root automatically.

### 4.4 Config Key Changes

**Removed from config.lua DEFS:**
- `model_dir`
- `manifest`

**Added to config.lua DEFS:**
- `step_scan` stays (already exists)

**Removed:**
- `step_sync`
- `last_run_sync`

### 4.5 Runner Changes

`build_cmd()` updated for new CLI interface:
- scan, dedup, score, name now take `--db` and `--folder` instead of `--manifest`
- DB path derived: destination drive root + `photonforge.db`
- Folder name derived: basename of destination path
- `model_dir` hardcoded, not read from config
- No sync step

---

## 5. Applicator Changes

### 5.1 Updated Step Handling

The `applicator.apply(rec, dest)` function already handles dedup, score, and name results. Changes:

- **scan step**: After scan completes, call `dt.films.new(dest)` to import folder into Darktable library (already done in `run_all` after ingest; move to post-scan).
- **name step**: Write `rec.semantic_name` to `img:set_metadata("description", name)` (already does this). Confirm it does NOT write to tags.
- **sync step**: Remove handler (step eliminated).

### 5.2 Image Lookup

Applicator finds images via `dt.database` iteration, matching by filename. Since files are renamed at ingest, the filenames in pipeline JSON output match Darktable's imported filenames.

---

## 6. Migration Path

### 6.1 Existing Manifest Data

The old `manifest.jsonl` files can be ignored. Users re-run scan + dedup + score + name with `--force` to repopulate the new SQLite DB. This is a clean break, not a migration.

### 6.2 Already-Renamed Files

Files already ingested with old naming (YYYYMMDD_ prefix or original camera names) are not retroactively renamed. The new naming convention applies to new ingests only.

---

## 7. Constraints

- NFR-2.1: 100% offline at runtime. No network calls. SQLite is local.
- NFR-2.2: RSS <= 1.5 GB. SQLite adds negligible memory overhead.
- NFR-2.3: photonforge.db lives on the cartridge SSD, not the host.
- All raw file operations use rawpy for decode, embedded JPEG thumbnails for hashing.
- Florence-2 INT8 ONNX via onnxruntime AVX2, <= 2.5s/image target.
