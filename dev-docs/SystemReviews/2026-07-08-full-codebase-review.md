# Full Codebase, PR, and Documentation Review — 2026-07-08

**Scope:** all of `src/photo_workflow/` (26 modules), `tools/cartridge_manager/`,
`lua/photonforge/`, `scripts/`, `deploy/`, `tests/`, all 31 PRs, all of
`dev-docs/`, plus a feasibility study for a standalone application.
**Method:** six parallel deep-review passes (core pipeline, storage/bridge/host,
documentation drift, duplication, PR history, standalone-app research), with the
highest-impact findings independently re-verified against HEAD (`87ee17e`).
Findings below marked **CONFIRMED** were verified by re-reading the code path or
reproducing the behavior; "plausible" items were not fully verifiable (usually
model-dependent).

---

## Executive summary

1. **Main is red and there is no CI gate.** `tests/test_seed_github.py` has had a
   broken import since the 2026-06-17 template migration (pytest cannot even
   collect), and unpinned OpenCV 5.0 breaks 13 more tests on a fresh install.
   No GitHub Actions workflow runs pytest — all "N tests pass" claims in PR
   bodies are self-reported.
2. **The scoring engine has confirmed wiring bugs that silently degrade quality**
   — most notably, faces are never passed into fusion (the eyes-closed reject
   gate and all face-specific portrait weights are dead in production), and
   masked-region sharpness scales with mask *area*, so small sharp subjects can
   be falsely hard-rejected.
3. **The Linux host layer largely does not work on the target platform.** Drive
   root detection, volume-label reading, the panel's cartridge buttons, the
   sidecar's Darktable sync, and the deploy container all fail on Linux —
   several of these failures are silent.
4. **Two real data-loss paths exist in ingest and provisioning.**
5. The June scoring-methodology audit was a model response to a systemic problem
   (silent model degradation) and its six findings were all fixed — but the
   prescribed *re-measurement* of the score distribution never happened, and the
   fleet-wide model self-check was only partially implemented.
6. Documentation has drifted badly (Stage-6 modular plan silently bypassed,
   taxonomy is 15×11 not 16×12, auto-generated docs corrupted by generator
   bugs, V&V matrix contradicts the release-1 review).
7. **A standalone app is feasible** via the "own the culling UI, delegate RAW
   development to `darktable-cli` through native XMP" architecture (~8–14
   person-months), and "AI predicts develop parameters" is commercially proven
   with **no open-source darktable equivalent** — an open niche this codebase's
   SceneRecord/active-learning work is unusually well positioned for.

---

## 1. Confirmed bugs (ranked)

### P0 — data loss / destroys hardware state

| # | Bug | Location |
|---|---|---|
| 1 | **Ingest records "done" before the copy is durable.** DB row + `scan` stage are committed *before* `shutil.copy2` + rename; a crash or yanked SD in that window means the next run's resume logic skips the photo forever, and the workflow then encourages wiping the SD. No fsync before rename either. | `ingest.py:135-147`, resume check `ingest.py:97-116` |
| 2 | **`provision_cartridge` wipes existing cartridges even when "preserving" partitions**: with `has_partitions=True` and no `--force-repartition` it still runs `wipefs -a` on device and partition, then `mkfs.ext4` through a stale kernel node — cartridge appears fine until replug, then the partition table is gone. Also `{device}1` is wrong for nvme/mmcblk (`p1`), and no `udevadm settle` between `parted` and `mkfs`. | `provision.py:52,150-176` |
| 3 | **Name collision at ingest destination silently drops the source file** — `if dest.exists(): seq += 1; continue` advances to the *next source file* instead of retrying with the new sequence. | `ingest.py:126-128` |
| 4 | **Cartridge Manager mutates the production DB on open**: `db_ops.py` still implements the pre-2026-06 table-per-folder schema; on a current DB it lists `photos`/`embeddings` as "folders" and `_migrate_all_tables` ALTERs legacy columns (incl. resurrected `genre`) into them on every launch. | `tools/cartridge_manager/db_ops.py:20-94` vs `photondb.py:60-101` |

### P1 — scoring correctness (silent quality degradation)

| # | Bug | Location |
|---|---|---|
| 5 | **Faces never reach fusion.** Both `fuse_scores` call sites omit `faces=ctx.faces, image_gray=ctx.image_gray`. The `all_eyes_closed` hard gate can never fire, and `face_exposure` (0.12–0.15) + `expression_proxy` (0.15–0.20) weights are *always dropped* for people/portrait/documentary even when YuNet found faces. Unit tests pass faces directly, so nothing catches the seam. One-line fix per site. | `pipeline.py:163-170, 558-565`; gate logic `score_fusion.py:438-443,495-498` |
| 6 | **`--skip-genre` crashes internally on every image** — `row.get(...)` on a `sqlite3.Row` (no `.get`) raises, is swallowed at `pipeline.py:632`, and every image silently falls to legacy scoring, *discarding* the genres the flag was meant to preserve. | `pipeline.py:531` |
| 7 | **Masked-region sharpness scales with mask area, not sharpness** — Tenengrad/SML mean is taken over the whole frame after zeroing non-mask pixels; a tack-sharp bird at 5% of frame scores ~5% of its true value → misclassified `misfocused`/`motion_global` → can trip hard-reject. Reproduced empirically (0.011× at 1% area). | `sharpness.py:77-88`, thresholds `sharpness.py:22`, gates `score_fusion.py:434-436` |
| 8 | **`sharpness_contrast` computed via Sobel on 1-D boolean-indexed pixel arrays** — cv2 treats the flattened masked pixels as a 1×N image; the result is noise, and it feeds both the genre router and the macro profile (weight 0.20). | `subject_context.py:508-509` |
| 9 | **YOLO postprocessing has no NMS** — every anchor above 0.3 survives; one person yields tens of boxes; `person_count >= 3` then routes lone-subject portraits toward documentary (×2.0) / street (×1.5). | `subject_context.py:391-410`, `genre_router.py:435-513` |
| 10 | **`"general"` genre silently scores with people/portrait weights** — fallback substitutes `SUBJECTS[0]`/`PHOTO_TYPES[0]`; worst possible default for landscapes. | `pipeline.py:197,531`, `score_fusion.py:327-330` |
| 11 | **`_classify_blur` can never return `motion_subject`** (both branches return `"bokeh"`), so `behavior_proxy` is always dropped and its drop-condition is dead. | `sharpness.py:113-116`, `score_fusion.py:280,502` |
| 12 | **Relative re-rating percentile pool includes hard-rejected frames** (and the schema default `master_score REAL DEFAULT 0.0` means unscored rows carry 0.0, not NULL). | `pipeline.py:669-676`, `photondb.py:78` |

### P2 — host integration / Linux target broken

| # | Bug | Location |
|---|---|---|
| 13 | **Lua plugin's `get_drive_root` returns `/` on Linux** — `--db /photonforge.db` etc. fail `click.Path(exists=True)` instantly; worse, the Provision button runs `pkexec photo-cartridge provision '/'` (only safe today because that subcommand doesn't exist). The Windows branch is correct; Linux was never wired. | `runner.lua:20-28,287` |
| 14 | **Volume label detection never works on Linux** — `lsblk -no LABEL -J` emits only the `label` key, so the mountpoint match never hits; every cartridge becomes `000` and all files are named `P000…`, breaking cartridge-ID uniqueness. (`cartridge.detect_cartridges` shows the correct invocation.) | `volume.py:46-68` vs `cartridge.py:29` |
| 15 | **Panel Provision/Archive/Restore buttons invoke subcommands that don't exist** (`photo-cartridge` has only `init`). Dead UI. | `runner.lua:287,335,352`, `cartridge.py:78-116` |
| 16 | **`sidecar_cli` Darktable sync always crashes** — calls `sync_to_darktable(records, db_path=…)` and unpacks a tuple; real signature is `(records, verbose=False) -> int`. Tests mask it with a mock returning `(2, 2)`. | `sidecar_cli.py:169`, `darktable_bridge.py:395`, `tests/test_sidecar_cli.py:72,173` |
| 17 | **Deploy container can never run the pipeline** — compose passes `run`-subcommand flags to the click *group*; `manage_ssd.sh` therefore mounts, no-ops, and unmounts. | `deploy/docker-compose.yml:25-28`, `pipeline.py:230-233` |
| 18 | **`json.lua` cannot decode `\uXXXX`** — Python emits `ensure_ascii=True` JSON, so any non-ASCII filename/caption is garbled and `applicator.find_image` misses → ratings/tags silently not applied. Also `null` in arrays truncates them. | `lua/photonforge/json.lua:16-24,65-80` |
| 19 | **rsync itemize parsing off-by-N** — modern rsync emits an 11-char field; `line[10:]` leaves a stray `"+ "` prefix → nonexistent paths into scoring/naming. | `sidecar_cli.py:105-112` |
| 20 | **XMP writer**: no XML escaping of captions (`&`/`<` → malformed XMP), and writes `IMG_0001.xmp` instead of Darktable's `IMG_0001.ARW.xmp` — RAW+JPEG pairs collide on one sidecar and DT won't associate the file anyway. | `darktable_bridge.py:121,137-163` |
| 21 | **Three incompatible "Darktable schemas" coexist**: `photo-cartridge init` creates a toy library.db (no `data.db`, no `position` column) that makes the bridge's keyword sync a silent no-op forever; `db_ops.update_darktable_folder` needs an `images.folder` column only the toy schema has. | `cartridge.py:92-113`, `darktable_bridge.py:194-201,336`, `db_ops.py:232-242` |
| 22 | **library.db writes have no lock discipline** — no `busy_timeout`, no `library.db.lock` check, per-row commits, clear+write as two separate transactions (kill between them strips photon tags), image lookup by bare `filename` (ambiguous across film rolls), errors swallowed. | `darktable_bridge.py:212,251,289-342` |
| 23 | **`training_io.py` targets a training-DB schema the pipeline never creates** (`genre_corrections`/`genre_adapter`/`custom_genres` vs actual `genre_prototypes`/`genre_adapter_linear`/`aesthetic_weights`); exports/previews error, and merge silently drops the tables the scorer actually uses. Import "replace" strategy blind-copies over the local DB with no backup. | `training_io.py:26-31,177-214,761-808` |
| 24 | **`rollback_to_version` loses prototypes** (rows only at versions `<` target are never reactivated) and ignores adapters/weights. | `training_weights_db.py:280-297` |
| 25 | Smaller confirmed: `pkill -f 'photo-workflow'` can kill unrelated processes; fixed-name sentinels in shared temp break under two concurrent runs (`runner.lua:214-255`); `remote_test.sh` dies without its JSON summary if naming fails (`remote_test.sh:74-87`); `extract_cartridge_id` truncates 4-digit IDs to 3 (`volume.py:78`); `photondb.update_stages`/`clear_stage` are unlocked read-modify-write (`photondb.py:133-153,211-223`); `file_ops.rollback_pending` recovery journal is dead code and the journal is cleared even on error (`file_ops.py:183-203`, `app.py:215`); Cartridge Manager folder delete is `rmtree(ignore_errors=True)` with no trash/journal (`app.py:150-153`). |

**Plausible (verify with real models/hardware):** RMBG-1.4 input normalization
([0,1] vs reference [-0.5,0.5]); YuNet parser assumes a post-NMS `[N,15]`
tensor; `genre_trainer` SQL-variable limits and bare-filename corpus keys.

---

## 2. Performance low-hanging fruit

| Impact | Finding |
|---|---|
| **High** | Full-res float64 Sobel passes run 7+ times per image (subject/background/eye in sharpness, recomputed in composition, again in `_negative_space_score`) — ~hundreds of MB of transients per 24 MP image; the main NFR-2.2 (≤1.5 GB RSS) risk. Compute on a ≤1024 px float32 downscale, crop to mask bbox, and share results between sharpness and composition. (`sharpness.py:137-178`, `composition.py:209-211,317-320`) |
| **High** | Every image is decoded twice in the one-shot pipeline (context build + naming), and the legacy fallback decodes **three** times — for RAW that's multiple full demosaics per image on the i7-7500U, directly hurting KPM-1.2. Bug #6 makes the triple-decode path the norm under `--skip-genre`. (`pipeline.py:139,189,193-195`, `naming.py:229`) |
| **High** | `SubjectContext` pins full-res BGR + gray + RGB (~170 MB per 24 MP image) through all model runs; the RGB copy is only needed at model input sizes. (`subject_context.py:515-528`) |
| Med | EXIF parsed from disk 3× per image (context, naming, grouping re-read after ingest already read it). |
| Med | Florence-2 no-cache decode fallback is O(n²) in tokens — can alone blow the 2.5 s KPM if the merged decoder is absent. (`naming.py:363-405`) |
| Med | Per-image `commit()` with `journal_mode=DELETE` = one fsync + journal create/delete per image on the external SSD; WAL gives the same safety far cheaper (weigh against the eject workflow). (`photondb.py:56`, `pipeline.py:590,640`) |
| Low-Med | Pure-Python O(n²) Hamming loop in dedup; the `session_0000` catch-all bucket can hold thousands. (`dedup.py:65-69`, `grouping.py:63-64`) |
| Low | `get_pending` SELECTs `clip_embedding` blobs for the whole folder every stage; no-NMS YOLO makes genre evidence loops iterate junk boxes; dry-run still burns full decode/fallback work per image. |

Positive notes: model sessions are created once and reused; dedup uses embedded
RAW thumbnails; Florence-2 KV-cache decode and warm-up are properly done;
intra-op threads are pinned to physical cores.

---

## 3. Pipeline methodology assessment

**What's sound.** Staged CLI with per-stage DB state and resumability; embedded
thumbnails for dedup; the June audit's empirical, measure-first method; the
correction/recalibration loop; per-shoot percentile star rating (right call for
a culling tool); centralizing taxonomy in `genre_router`.

**Flaws in the development logic:**

1. **Signals ship without end-to-end signal validation.** The audit's P1 (dead
   aesthetic axis for the feature's entire life) and today's bug #5 (faces never
   wired into fusion) are the same shape: unit tests validate plumbing with
   hand-passed inputs, and no test asserts the *pipeline* delivers real inputs
   to fusion. The recommended fleet-wide provision-time model self-check
   (audit's cross-cutting item) landed only for the CLIP aesthetic head.
   A distribution-level smoke test (score N fixture images, assert sub-score
   variance > ε) would catch this whole class.
2. **The re-measurement loop is still open.** Audit step 4 and release-1 item #1
   both prescribe a clean re-score of a reference shoot after the fixes; no doc
   records it, all release-1 checklist items are still TODO, and every KPM is
   untested on target hardware. Nobody currently knows whether the fixes
   restored discrimination.
3. **Weighted taxonomy churn outpaces calibration.** 8 genres → 16×12 → 13×11 →
   15×11 → rename, in ~5 weeks, each step needing DB/prototype/weights
   migrations, while the taxonomy brief's own estimate is 30–50 corrections per
   class to calibrate — a moving target that has never been tuned. Meanwhile the
   R2 SceneRecord/per-region direction may obsolete the per-Type weight table
   entirely. Decide before spending calibration effort.
4. **Silent fallback as a design idiom.** Broad `except → neutral default /
   legacy path` appears in the aesthetic head (historically), `--skip-genre`,
   the bridge's tag writes, and the Lua applicator. Every one of these turned a
   loud bug into a silent quality regression. Fallbacks should be loud
   (log-once + surfaced counter in `PipelineSummary`).
5. **Repo-vs-deployed drift on the plugin surface** (`tag_manager.lua` shipped
   deployed-but-uncommitted; four fix-of-fix panel PRs in 48 h). The plugin
   needs a scripted deploy step and at minimum a Lua smoke harness (headless
   `dt-cli` or busted-based unit tests for json/config/tag_manager).
6. **Process gaps:** no pytest CI gate; long-lived branch merged as 4 sequential
   PRs in 48 h (trunk-based development wearing PR clothing); significant work
   committed directly to main bypassing PRs; PR-promised follow-ups (#102
   contracts-doc cleanup, #105 safe-eject/weights-inspector) untracked and
   dropped; spike code parked in `.claude/r2_spike/` where it is easy to lose.
7. **min(technical, aesthetic) rests on one uncalibrated axis.** The aesthetic
   side is a single CLIP head with known AVA domain shift; `min` makes the
   master score only as good as the weaker axis. Fine for R1 with percentile
   banding, but the contracts doc presents `min` as the endpoint without
   recording this caveat.

---

## 4. Duplication and consolidation

Top consolidations by value/risk (full detail in the review transcripts):

1. **One image-extension source of truth.** Ten disagreeing sets across
   `raw_loader`, `ingest`, `pipeline`, `sidecar_cli`, `sharpness`,
   cartridge_manager, and scripts. Concrete bug: `.RAF` passes `PHOTO_EXTS`
   scanning but `raw_loader.is_raw()` is False → `cv2.imread` fails → every
   Fuji RAF errors in `score`. Export `RAW_EXTENSIONS`/`IMAGE_EXTENSIONS` from
   `raw_loader` and import everywhere. (low risk)
2. **Rewrite `tools/cartridge_manager/db_ops.py` against `photondb`** (bug #4)
   and make `training_io` import the real `training_weights_db` schema (bug #23).
3. **Extract a shared `score_one()`** — `AnalysisPipeline.run()` and the `score`
   command are parallel implementations of the same hot path (byte-similar
   aesthetic guards, separate fallbacks); `sidecar_cli` is a stale third copy
   with the broken sync call. Fix once, call thrice — or retire the sidecar.
   (`pipeline.py:133-199` vs `517-631`, `sidecar_cli.py:144-169`)
4. **One rawpy preview loader** — three verbatim copies (preview_tab, labeler,
   label_corpus) plus a robust-load variant duplicated in subject_context and
   the r2 spike; add a `preview=True` profile to `raw_loader.load_pil`.
5. **One volume/naming stack** — `file_ops.py` wholesale duplicates
   `volume.py` (`extract_cartridge_id`, `derive_trip_code`, `format_photo_name`,
   `get_next_sequence`, label reader) and the copies have already diverged.
6. **One stars/color-label mapping** — three divergent master-score→stars/label
   mappings (`_score_to_stars`, `absolute_star`/`hybrid_star`,
   `compute_color_label`); a photo's label depends on which entry point ran.
7. **SQLite helpers** — connection boilerplate ~12×, Darktable ATTACH 3×+1,
   four lsblk JSON walkers, `photon|subject|`/`photon|type|` prefixes in 4
   places across 2 languages.
8. **EXIF readers** — three DateTimeOriginal readers and four shooting-summary
   formatters.
9. **Delete verified-dead code (~250+ LOC):** `manifest.py`, `progress.py`,
   `photondb.mark_duplicate`/`_PHOTO_COLUMNS`, `darktable_bridge.compute_color_label`
   (+ unused import at `pipeline.py:466`), `darktable_bridge.main`,
   `genre_router.GENRES`, dead `--resume` flags, quasi-dead `--threshold` on
   sharpness, `file_ops.rollback_pending`.
10. **Tests:** move `_make_jpg` (4 copies) and a `SubjectContext` factory
    (6+ copies) into `conftest.py`.
11. **Lua:** factor `with_models`/`with_training_db` helpers in `runner.lua`
    (5×/3× repeated blocks).

---

## 5. Documentation and process findings

- **CLAUDE.md needs a refresh:** Stage-6 paragraph describes a five-module split
  that was bypassed (behavior shipped inside `score_fusion.py`; no supersession
  note anywhere); taxonomy is 15×11 not 16×12 (also wrong in
  `genre_router.py:4-5` docstring, contracts doc, IF-3.1,
  subject-enabled-subscores); "Target CPU: i7-8550U" contradicts its own header
  and the KPMs (i7-7500U); layout lists 10 of 23 src modules and a
  `scripts/install_udev.sh` / `deploy/udev/` that don't exist (udev lost to
  udisks2 polling per the decision log, never reflected); FR-1.7 doesn't note
  the recorded R2 captioner decision (LFM2-VL-450M grounded, SmolVLM fallback).
- **Auto-generated docs are corrupted:** `living-user-needs.md` duplicates
  every KPM/Stage block and appends `Stage: ?`; roadmap shows "Done 0/10" /
  "Not Started" for shipped stages; the V&V matrix marks NFRs with "(none yet)"
  evidence as ✓ and claims 38/48 verified while the release-1 review says **0
  UNs validated, all 10 KPMs untested** and `tests/e2e/` contains only
  `__init__.py`. Fix `scripts/generate_docs.py` before trusting any AUTO block.
- **ICD drift:** IF-1.1's stage whitelist is behind the code (missing
  `suggest-training-set`, `refresh-review`, `training recalibrate`, rescore);
  IF-2.1 points to the contracts doc whose `aesthetic_weights` schema doesn't
  match `training_weights_db.py`.
- **Stale docs to archive:** `dev-docs/migration/` (~150 one-shot files),
  `stage-6-engineer-brief.md` (+ supersession banner on
  `scoring-module-contracts.md` — also still specifies NIMA + depth, both
  contradicted by code and the R2 doc, and #102 promised this cleanup),
  EXAMPLE-3d-printer doc, superseded Tauri-era GUI specs,
  `photonforge-architecture.md §7` (pre-rename agent files, nonexistent paths),
  `.claude/agent-memory/engineer/` (pre-rename name), start-work-checklist's
  EE/ME boilerplate.
- **Missing docs:** install/provisioning guide (UN-003; `docs/` is empty),
  a current scoring-architecture doc (the only written designs are the
  unimplemented contracts doc and the audit), ADRs for
  stage-6-bypass/taxonomy/udev→udisks2/Florence-2→LFM2, anything at all on
  `tools/cartridge_manager/` (10 files, zero mentions), and a training-loop
  user doc.
- **PR hygiene:** open PRs #108 (R2 pixel-engine decisions, docs-only) and #110
  (plugin theme) are clean and 18 days stale — merge or close; PR #5's closure
  is properly accounted for; `.claude/r2_spike/` should graduate or be archived.

---

## 6. Standalone application feasibility

**Question:** standalone app keeping the sorting/grading workflow + native
Darktable-grade RAW development + AI-assisted editing.

**Ground truth about the current architecture:** the Lua plugin is a thin shell
(builds `photo-workflow <step> --json-progress` commands, tails a JSONL log);
all intelligence is in the Python package, which is already GUI-agnostic.
The Darktable coupling is metadata-only (ratings/labels/tags/custom-namespace
XMP + direct library.db writes) and is demonstrably the most fragile layer in
this review. Nothing in the codebase touches RAW *development* — that half is
greenfield under any architecture.

**Key external facts (researched, cited in the feasibility transcript):**
- There is **no libdarktable**; the supported headless path is `darktable-cli`,
  which runs the real pixelpipe from an XMP history stack. Caveats: slow
  per-invocation startup, PID lockfile (needs a private `--library`), native-DT
  history stacks only.
- Writing history stacks externally is possible (precedent:
  `darkroom-xmp-tools`) but module params are version-pinned binary structs —
  robust strategy is `.dtstyle` styles via `--style` plus a handful of stable
  modules (exposure, temperature, colorbalancergb, filmic/sigmoid).
- **Licensing:** invoking `darktable-cli` as a subprocess is mere aggregation
  (app license stays free choice); linking the engine forces GPL-3.
- No permissively-licensed, embeddable, darktable-grade develop engine exists.
  vkdt (BSD-2, has a CLI) is the only future candidate but requires a Vulkan
  GPU with ≥4 GB VRAM — disqualified on the current target hardware.
- **AI-parameter editing is commercially proven** (Imagen AI predicts 30+
  Lightroom sliders from a photographer's own edit history; Aftershoot adaptive
  profiles) and academically mature (Exposure TOG'18, MonetGPT TOG'25). **No
  open-source project targets darktable** — an open niche. The R2 `SceneRecord`
  (per-region scores, objects, faces, EXIF, dominant colors) is exactly the
  conditioning input such a parameter-prediction head needs, and the
  correction/recalibration loop is the learn-from-user scaffold.
- GUI: PySide6/QML `GridView` + async image provider + embedded-preview
  decoding is the right stack for fast grids on 8 GB (Narrative Select is the
  UX bar; Electron's memory overhead doesn't fit the target).

**Three architectures:**

| | A — Darktable companion (evolve today) | B — Standalone culling app, RAW dev delegated to darktable-cli via XMP | C — Full standalone, own RAW engine |
|---|---|---|---|
| Effort | ~2–4 pm | ~8–14 pm | ~30–60+ pm |
| License | unchanged | free choice (bundle GPL dt-cli as separate program) | free choice only if built on LibRaw+OIIO (permissive) |
| Code reuse | ~95% | ~85% (bridge's library.db/Lua hacks *deleted* — the most fragile code retires) | same ~85% |
| Key risk | still a guest in DT's UX; binary-param drift | interactivity ceiling (cli renders in seconds, not ms); pin bundled dt version | image quality treadmill; person-years on a commodity; Filmulator cautionary tale |
| Verdict | cheapest path to AI-edit, fails "standalone" | **feasible; best effort/value** | economically unjustifiable at this scale |

**Recommendation: B, staged through A.** Ship AI-parameter editing inside the
existing plugin first (~2–4 pm — derisks the two novel pieces: the prediction
head and the darktable-native XMP history writer, at zero GUI cost). Then lift
into the standalone Qt app (+8–12 pm), where both pieces carry over unchanged.
Keep C off the roadmap unless vkdt's hardware floor and the target hardware
converge.

---

## 7. Next steps (prioritized)

**Now — stop the bleeding (days):**
1. Fix `tests/test_seed_github.py` import; pin `opencv-python-headless>=4.9,<5`
   (or port `composition.py:168` for cv2 5.x); add a minimal pytest GitHub
   Actions workflow so main can never silently go red again.
2. Land the one-line scoring fixes: wire `faces=ctx.faces,
   image_gray=ctx.image_gray` into both `fuse_scores` call sites; fix
   `row.get()` in `--skip-genre`.
3. Fix the two data-loss paths: ingest copy-then-record (+ collision retry
   loop, fsync before rename); provisioning wipefs guard + `p1` suffix +
   `udevadm settle`.
4. Fix Linux host basics: `volume._get_label_linux` lsblk columns;
   `runner.lua` Linux drive root (derive cartridge root from the mounted
   library path); disable or guard the Provision/Archive/Restore buttons until
   subcommands exist (never pass `/`).

**Next — restore signal integrity (1–2 weeks):**
5. Fix mask-area sharpness dilution + 1-D Sobel contrast (also the biggest RSS
   win); add YOLO NMS; fix `_classify_blur`'s dead `motion_subject`; exclude
   hard-rejects from the percentile pool; pick a neutral fallback profile for
   `"general"`.
6. Add the fleet-wide provision-time model self-check and a distribution-level
   pipeline smoke test (sub-score variance assertions on fixtures).
7. **Run the audit's unfinished re-measurement**: clean re-score of a reference
   shoot, compare distributions to the June baseline, record in a SystemReview.

**Then — consolidate (2–4 weeks, one PR per item):**
8. Extension sets → `raw_loader`; shared `score_one()`; fix-or-retire
   `sidecar_cli`; `db_ops`/`training_io` schema unification; one stars/labels
   mapping; delete dead code; conftest fixture consolidation; `runner.lua`
   helpers; bridge lock discipline (busy_timeout + single transaction +
   film-roll-qualified lookup) and dt-convention sidecar names with XML
   escaping.
9. Docs: fix `generate_docs.py`, refresh CLAUDE.md, supersession-stamp the
   contracts doc + stage-6 brief, reconcile taxonomy counts and IF-1.1, archive
   `dev-docs/migration/`, merge/close #108 and #110, file issues for #105's
   dropped follow-ups.

**Strategic (this quarter):**
10. Decide per-Type weights vs R2 SceneRecord per-region scoring *before*
    investing calibration effort; record as an ADR.
11. Start Architecture A's AI-edit spike: SceneRecord-conditioned parameter
    head + `.dtstyle`/XMP writer, validated through `darktable-cli` renders.
12. If the spike lands, green-light the Architecture B standalone app (PySide6
    culling UI, own catalog, dt-cli render service) and retire the library.db
    write path.

---

## Addendum (2026-07-10): resolution status of §1 bugs

The confirmed bugs above were burned down by PRs #111–#118 immediately after
this review. Recorded here so readers do not re-chase fixed bugs; the body
above is unchanged history.

| §1 # | Bug (short) | Status |
|---|---|---|
| 1 | Ingest records before copy durable | **Fixed** — copy-then-record (#114) |
| 2 | Provisioning wipefs / nvme suffix / no settle | **Fixed** — wipefs guard, `p1` suffix, `udevadm settle` (#114) |
| 3 | Ingest name collision drops source file | **Fixed** — collision retry (#114) |
| 4 | Cartridge Manager mutates production DB | **Mooted** — Tk cartridge manager deleted (#117) |
| 5 | Faces never reach fusion | **Fixed** — both call sites pass `faces`/`image_gray` (#114) |
| 6 | `--skip-genre` sqlite3.Row crash | **Fixed** (#114) |
| 7 | Mask-area sharpness dilution | **Fixed** (#115) |
| 8 | 1-D `sharpness_contrast` Sobel | **Fixed** — 2-D computation (#115) |
| 9 | YOLO without NMS | **Fixed** — NMS added (#115) |
| 10 | `"general"` scores with people/portrait weights | **Open** — fallback still substitutes `SUBJECTS[0]`/`PHOTO_TYPES[0]` (`score_fusion.py:328-330`) |
| 11 | `_classify_blur` never returns `motion_subject` | **Fixed** — gradient-anisotropy motion classification (#115) |
| 12 | Hard-rejects in percentile pool | **Fixed** — excluded (#115) |
| 13 | `get_drive_root` returns `/` on Linux | **Fixed** — Linux drive root in runner.lua (#116) |
| 14 | Linux volume labels never detected | **Fixed** — `lsblk` with `LABEL,MOUNTPOINT` columns (#114) |
| 15 | Dead Provision/Archive/Restore buttons | **Fixed** — cartridge buttons guarded (#116) |
| 16 | `sidecar_cli` sync signature crash | **Fixed** in #116, then **mooted** — module deleted |
| 17 | Compose passes run-flags to the click group | **Fixed** — `run` subcommand (#116) |
| 18 | `json.lua` `\uXXXX` / null truncation | **Fixed** — `\uXXXX` decode + `M.null` (#116) |
| 19 | rsync itemize off-by-N | **Mooted** — `sidecar_cli.py` deleted |
| 20 | XMP escaping + sidecar naming | **Fixed** — `IMG_0001.ARW.xmp` convention + XML escaping (#116) |
| 21 | Three incompatible Darktable schemas | **Partially mooted** — `db_ops.py` deleted (#117); the `photo-cartridge init` toy schema remains to reconcile |
| 22 | library.db lock discipline | **Fixed** — lockfile guard + single transaction (#116) |
| 23 | `training_io.py` wrong schema | **Mooted** — cartridge-manager tooling deleted (#117) |
| 24 | `rollback_to_version` loses prototypes | **Open** — `training_weights_db.py:280-297` unchanged |
| 25 | Smaller confirmed batch | **Partial** — file_ops/app.py items mooted by #117; pkill scope, shared-temp sentinels, `remote_test.sh` JSON, `extract_cartridge_id` truncation, photondb read-modify-write remain open |

§4 consolidation items landed in #118 (extension-set unification fixing
`.RAF`, shared `score_one()` for both scoring paths, EXIF-reader/label-mapping
unification, dead-code deletion). §5 documentation findings are being executed
as the 2026-07-09 docs overhaul plan (Phases 1–3 landed as of this addendum).

**Next action:** open FR issues for the remaining items (§1 #10, #24, #25
residuals, #21 toy schema) or fold them into the next scoring/host PR.

via: @systems_lead
