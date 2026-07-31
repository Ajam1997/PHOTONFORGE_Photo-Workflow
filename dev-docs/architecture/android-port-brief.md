# PHOTONForge Android Port — Phase 1 Analysis & Plan

**Date:** 2026-07-17
**Status:** Phase 1 (analysis, no app code) — awaiting operator review before Phase 2.
**Author:** @systems_lead session — Android port kickoff
**Related:** PR #140 (self-contained portable drive plan,
`dev-docs/superpowers/plans/2026-07-17-portable-drive-plan.md` — the companion desktop
half of the same cartridge), `r2-hardware-profiles-brief.md` (R2 deployment profiles;
this brief adds a direct-attach mobile profile), PR #108 (pixel-engine selection),
UN-031 (cartridges as portable libraries), FR-1.9 (cartridge format).

---

## 1. What This Is

A Kotlin Android app that runs the PHOTONForge sorting pipeline **on-device** against
photos on a USB-C drive / SD reader, plus a **viewer/culling UI** the desktop stack does
not need: grid review of processed images, sort/filter by PHOTONForge tags and basic
metadata, keep/reject overrides, and **quick JPEG exports to the phone** (share-sheet →
Google Photos). darktable does not run on Android, so the app is **ingest + cull + review
+ export only** — no editing, no pixel-engine work (see §9 for how this meshes with the
R2/pixel-engine plan).

Target device: Pixel 9 Pro XL (Tensor G4, Android 15+). A Pixel 11 Pro is expected later,
so acceleration stays behind an interface (§7.4). Constraints taken as given (researched,
not relitigated): W^X (all native code ships in the APK), Storage Access Framework /
libaums for external media, ONNX Runtime Android with XNNPACK CPU baseline (NNAPI is
deprecated; the Tensor TPU is not third-party accessible), and the workload is
**decode-bound, not inference-bound**.

---

## 2. Reference Pipeline Summary (as-built, from source)

Stage order (staged CLI, resumable via `stages` tokens in `photonforge.db`):
**ingest → scan → dedup → score → name**.

| Stage | What it does | Pixels consumed |
|---|---|---|
| `ingest` (`ingest.py`) | SD→SSD copy: crash-safe `.tmp` + fsync + atomic rename; rename to `P{cart:3}{trip:3}{seq:07d}.ARW` (`volume.py:111`); skip already-ingested by `(original_name, exif_timestamp)` | none |
| `scan` (`pipeline.py:310`) | rglob images, EXIF DateTimeOriginal → DB rows | none (EXIF only) |
| `dedup` (`dedup.py`) | sessions = EXIF gaps > 30 min (`grouping.py:12`); dHash (9×8, 64-bit) on the **embedded RAW preview** (`load_thumbnail`); Hamming ≤ 2 within a session = duplicate (FR-1.3) | embedded JPEG preview |
| `score` (`pipeline.py:477`) | `build_subject_context` → 4 ONNX models + classical CV → two-axis genre routing → weighted fusion → master score, stars, color label, hard-reject gates | RAW decoded **half-size** via rawpy (`raw_loader.py:30`) |
| `name` (`naming.py`) | Florence-2-base-ft INT8 caption → `semantic_name` (goes to DT *description*, not filename) | 768×768 |

Scoring internals that the port must reproduce exactly (`score_fusion.py`):

- Sub-scores from sharpness (Tenengrad/SML on full-res gray, subject/eye regions from
  RMBG mask + YuNet landmarks), composition (spectral-residual saliency @64px, symmetry
  NCC ≤256px, Hough leading lines ≤1024px, Hasler-Süsstrunk colorfulness, Lab isolation),
  exposure (11-zone luma histogram, clip <4/>251, DR = P99.5−P0.5), optional CLIP
  aesthetic head.
- Genre: 15 subjects × 11 photo-types. Learned linear adapter (`softmax(W·emb + b)`) if
  present in the training DB, else product-of-experts with CLIP-dominant weights
  [4,1,1,1,1], smoothing 0.20, CLIP temperature 0.35. EXIF motion-blur gate at shutter
  ≥ 0.5 s. `needs_review` when top-2 margin < 0.02 on either axis.
- Fusion: effective weights = 0.5 × subject profile + 0.5 × type profile (profiles in
  `aesthetic_weights` SQLite, hardcoded fallback); **master = min(technical bucket,
  aesthetic bucket)**; hard-reject gates (global motion blur + subject sharp < 0.2;
  misfocused + eye region < 0.15; all eyes closed < 0.15).
- Stars: absolute floor 0.25; live `absolute_star` (0.40/0.50/0.60 cuts), final
  `hybrid_star` per-shoot percentile (≥90% → 5★, ≥70% → 4★, ≥40% → 3★). Color labels:
  5★→blue, 4★→green, ≤1★→yellow; **purple reserved for the user** — never auto-set.

State: `photonforge.db` at the cartridge root (SQLite, `journal_mode=DELETE`, single
`photos` table keyed `(folder, filename)` with scores, `sub_scores` JSON, dhash, genres
JSON, CLIP embedding BLOB, `stages`). Training DB (`training_weights.db` /bundled
`genre_weights.db`): versioned `genre_prototypes`, `genre_adapter_linear`,
`aesthetic_weights` tables.

---

## 3. Model Inventory (all ONNX, CPU EP, INT8 unless noted)

No weights are committed; `scripts/provision_scoring_models.py` + `provision_models.sh`
produce them. Sizes are expected provisioned sizes.

| Model | File | Size | Input | Output | Calls/img |
|---|---|---|---|---|---|
| MobileCLIP-S2 vision | `mobileclip_s2_int8/vision_encoder.onnx` | ~35 MB | 1×3×**256×256** RGB, /255, **no mean/std** | 512-d L2-normed embedding | 1 |
| RMBG-1.4 (IS-Net) | `rmbg14_int8/model.onnx` | ~44 MB | 1×3×**320×320** RGB, /255 | subject mask, binarized @0.5 | 1 |
| YuNet face | `yunet/face_detection_yunet.onnx` | ~0.34 MB (FP32) | model-declared shape, **BGR, raw 0–255** | faces + 5 landmarks, conf 0.5 | 1 |
| YOLOv8n | `yolov8n_int8/model.onnx` | ~3–4 MB | 1×3×**640×640** RGB, /255, **plain resize, no letterbox** | [1,84,8400] → NMS 0.3/0.45, COCO-80 | 1 |
| CLIP aesthetic MLP | `clip_aesthetic_head/aesthetic_mlp.onnx` | <1 MB (FP32) | the 512-d CLIP embedding | [0,1] scalar | 1 |
| Florence-2-base-ft | `florence2_int8/onnx/` — 4 files: vision_encoder (uint8), embed_tokens, encoder, decoder_merged (KV-cache) | ~200–350 MB | 1×3×**768×768** RGB, mean/std from `preprocessor_config.json` | greedy decode ≤30 tokens (caption) | 1 + ≤31 decoder steps |
| Genre prototypes | `genre_prototypes.npy` (26×512) + `genre_weights.db` | ~250 KB | — (precomputed CLIP text embeddings) | — | loaded once |

**Total ≈ 285–435 MB; Florence-2 is 70–80% of it.** The four scoring models + assets are
**~85 MB** — that is the APK payload for cull/score. The CLIP *text* encoder is never
needed at runtime (prototypes are precomputed). Florence-2 additionally needs
`tokenizer.json` (BPE decode), `preprocessor_config.json`, and the 4-session
autoregressive loop — by far the highest-effort component to port.

**Recommendation: naming ships as an in-app toggle, default OFF** (operator decision,
PR #141 review). Culling doesn't need captions, and keeping Florence-2 out of the APK
drops the bundled payload ~4× — so the APK carries only the scoring models, and the
naming toggle activates when the Florence-2 files are reachable: loaded straight from
the cartridge's `models/florence2_int8/` (ONNX files are data — W^X permits this) or
from a one-time on-device provision copy. Expectation-setting: there is **no accessible
NPU on the Pixel** (Tensor TPU is closed, NNAPI deprecated — kickoff constraint #3), so
naming runs on CPU/XNNPACK; Florence-2 INT8 does ~2.5 s/image on an AVX2 i7, so plan for
**roughly 3–8 s/image on the Tensor G4's CPU** until Phase 2 measures it. With the
toggle on, naming runs as a low-priority pass after scoring (batch/charging-friendly);
`semantic_name` can still be filled in later by the desktop/appliance over the same
cartridge (the `stages` column already models "scored but not named").

---

## 4. Decode Path — Preview Extraction vs Full RAW Decode

### 4.1 What the reference actually consumes

- rawpy decodes RAW at **half size** (`half_size=True`, `raw_loader.py:30`): the a6700's
  6192×4128 (26 MP) is processed at **3096×2064 (~6.4 MP)**. The pipeline never touches
  full sensor resolution.
- Every ONNX input is ≤ **768 px** (and with naming deferred, ≤ **640 px**).
- Classical metrics run at the decode resolution or below (lines ≤1024 px, symmetry
  ≤256 px, saliency 64 px); only sharpness + exposure statistics use the full decoded
  frame.
- **dedup already uses the embedded preview** (`load_thumbnail`), so the preview path is
  bit-identical there by construction.

### 4.2 The numbers

Sony ARW embeds a **1616×1080 JPEG preview** (~0.5–1 MB, tag 0x2001) plus a 160×120
thumbnail. (Verify the a6700's exact preview size on-device in Phase 2 — the harness
logs it; Sony bodies to date ship 1616×1080.)

| Per frame | Full LibRaw decode (NDK) | Embedded preview |
|---|---|---|
| I/O over USB/SAF | 25–35 MB (whole ARW) | ~1–1.5 MB (header IFD + preview bytes) |
| Decode CPU (Tensor G4) | est. 2–4 s (single-threaded demosaic of 26 MP) + memory ~150 MB | ~10–30 ms (hardware/libjpeg-turbo, 1616×1080) |
| Resolution delivered | 3096×2064 (half-size parity) | 1616×1080 |

That is roughly a **50–100× reduction in decode cost and ~25× less I/O** — on a
decode-bound workload, this is the whole ballgame. A 500-frame card goes from ~25–35 min
of decode to well under a minute.

### 4.3 Fidelity caveat and mitigation

The embedded JPEG has the camera's tone curve/sharpening applied, vs rawpy's
camera-WB/no-auto-bright output — absolute sharpness/exposure sub-scores will shift.
Mitigations, in order of leverage:

1. **The final star rating is per-shoot percentile** (`hybrid_star`), so a consistent
   bias across a shoot largely cancels. Absolute artifacts to check: the 0.25 keep floor,
   the absolute-star cuts, and the three hard-reject gate thresholds.
2. **Phase 2 harness runs an A/B**: desktop Python pipeline (rawpy path) vs Android
   preview path over the same test card; compare `sub_scores` JSON per frame
   (`photonforge.db` is the fixture generator). Recalibrate the handful of absolute
   thresholds if drift exceeds tolerance.
3. The decoder sits behind an interface (§7.4); an NDK LibRaw module can be added later
   for a "high-fidelity" mode or full-res export without touching pipeline code.

### 4.4 Recommendation

**Extract the embedded preview as the primary decode path. Do not build NDK LibRaw in
Phase 2.** Preview location needs a small TIFF/IFD parser (~200 lines: follow SubIFD tags
0x0201/0x0202 `PreviewImageStart/Length`) with `androidx.exifinterface` as thumbnail
fallback. LibRaw enters later, only if (a) A/B calibration fails, or (b) full-resolution
export quality is wanted (§8, Phase 5 stretch).

---

## 5. Runtime Decision — Kotlin Port (recommended) vs Chaquopy

**Recommendation: native Kotlin port.** The Chaquopy route collapses under its own
dependency math:

- `rawpy` has no Android wheels — the decode path is rewritten either way (given).
- **`onnxruntime` has no Android Python wheel either** (not in Chaquopy's package repo);
  on Android, ORT ships as the Java/Kotlin AAR (`onnxruntime-android`). So under
  Chaquopy, *both* heavy ends — decode and inference — cross the JNI boundary into
  Java-land anyway, leaving Python holding only the glue math while adding ~60–80 MB of
  CPython + numpy + opencv to the APK and a Python↔Java marshalling layer in the hot
  loop.
- What Python would actually keep (fusion arithmetic, genre routing, dHash, grouping) is
  the *easy* part: pure, well-specified math with exact constants (§2), a few hundred
  lines in Kotlin, verifiable against golden vectors.

Port stack:

| Concern | Python | Kotlin/Android |
|---|---|---|
| Inference | onnxruntime CPU | **ONNX Runtime Android AAR** (XNNPACK/CPU EP), INT8 models unchanged |
| Classical CV | OpenCV (cv2) | **OpenCV Android SDK** (Sobel/Canny/Hough/DFT/Lab/NMS parity; revisit size later — per-ABI ~15 MB) |
| RAW preview | rawpy `extract_thumb` | IFD parser + `BitmapFactory`/libjpeg-turbo |
| EXIF | exifread | `androidx.exifinterface` (supports ARW) |
| dHash | imagehash | hand-rolled 9×8 (trivial, spec'd) |
| XMP | string template (overwrite!) | **Adobe XMPCore (Java)** parse-modify-write (§6) |
| DB | sqlite3 | `android.database.sqlite` (cartridge DB snapshot) + Room (app state) |
| CLI/progress NDJSON | click / stdout | in-process Kotlin flows; NDJSON schema kept for the debug log |

Scoring-parity strategy: generate golden vectors by running the Python pipeline on a
reference card (its `sub_scores` JSON per frame), then unit-test the Kotlin fusion/
routing/rating math to tolerance. Weight profiles + prototypes + adapter export from
`genre_weights.db` via a small build-time script into an app asset.

---

## 6. Output Format — XMP Round-Trip Design

Phase 1 finding that changes the design: **the desktop pipeline's sidecars do not carry
ratings.** The reference splits outputs across two channels:

1. XMP sidecars (`darktable_bridge.py`) carry **only `photon:*` analysis properties**
   (namespace `https://photonforge.local/xmp/1.0/`, sidecar name **`file.ARW.xmp`** —
   append style, never replace-extension). Crucially the desktop writer is
   **overwrite-only** (`write_text` on a template) — it would clobber darktable edit
   history. The Android app must NOT copy this behavior.
2. Stars, color labels, and `photon|subject|*` / `photon|type|*` hierarchical tags land
   in **darktable's `library.db`/`data.db`**, applied by the Lua applicator from NDJSON
   progress records — a channel that does not exist on Android.

Therefore the Android app writes **standard XMP that desktop darktable ingests from
sidecars**, alongside the `photon:*` block, via **parse-modify-write (XMPCore)**:

- `xmp:Rating` — −1 (reject) … 5, from `hybrid_star`/reject flag; user overrides too.
- `xmp:Label` — color-label string (Blue/Green/Yellow per `stars_to_color_label`;
  purple never auto-written).
- `lr:hierarchicalSubject` + `dc:subject` — `photon|subject|<name>`,
  `photon|type|<name>`, `photon|needs_review` (single tag per axis, matching
  `tag_manager.lua`'s invariant).
- The full `photon:*` property set as the desktop template (SharpnessScore …
  AestheticScore, Genres rdf:Bag, SessionID, IsDuplicate, OriginalFilename).
- **Preservation rule:** never touch nodes outside the properties above — in particular
  `darktable:history_*`, `darktable:masks_*`, and any unknown namespaces survive
  verbatim. If a sidecar exists, read → merge → atomic write (temp + rename via SAF).

darktable reads `xmp:Rating`/`xmp:Label`/`lr:hierarchicalSubject` on import ("look for
updated XMP files on startup" reconciles later changes), so cull results made on the
phone appear as stars/labels/tags on the desktop with zero extra tooling. This is a
strict superset of what the desktop writer emits today — and fixes the clobber hazard on
the Android side.

---

## 7. App Architecture

### 7.1 Modules

```
app/            Compose UI (dark), review grid, debug/benchmark screen
core-pipeline/  pure Kotlin: fusion, routing, rating, grouping, dHash, session state
inference/      InferenceEngine interface + OrtCpuEngine (ORT Android, XNNPACK)
decode/         Decoder interface + PreviewDecoder (IFD parser); LibRawDecoder later
io/             RawSource interface + SafSource (DocumentFile); LibaumsSource optional
xmp/            XMPCore parse-modify-write, photon namespace, tag taxonomy
db/             photonforge.db snapshot sync + Room app cache
```

### 7.2 Storage access

SAF (`ACTION_OPEN_DOCUMENT_TREE` + persisted permission) is the baseline: Pixel mounts
exFAT/FAT32 USB media natively and camera SD cards are exFAT. libaums stays a fallback
for readers Android refuses to mount. **See §9.2 for the cartridge-filesystem problem
(ext4).**

`photonforge.db` cannot be opened through a `content://` URI, so the app snapshots it to
app storage on session start, works there, and checks it back in (temp + rename) on
session end / eject — same crash-safety idiom as `ingest.py`. XMP sidecars remain the
canonical interchange; the DB write-back keeps `stages` continuity so desktop/appliance
runs don't redo work.

### 7.3 Instrumentation (Phase 2 deliverable, not nice-to-have)

Per frame: preview-locate ms, preview-decode ms, per-model preprocess + inference ms,
classical-CV ms, XMP write ms, total wall clock; plus `PowerManager.getThermalHeadroom`
sampled per batch, battery temp, and throttle events. Emitted as NDJSON to logcat + a
CSV on the device — this doubles as the benchmark harness and the A/B calibration tool
(§4.3).

### 7.4 Acceleration seam — NPU-ready for the Pixel 11 (operator decision, PR #141)

The operator will upgrade to a Pixel 11, expected to open third-party NPU access. The
app is built so that adopting it is a bounded engine swap, not a refactor:

- **`InferenceEngine` is the single seam**: `load(model): Session` / `run(session,
  tensors)`, selected **per model** at session creation. Pipeline code never imports an
  engine — it asks an `EngineRegistry` that probes device capabilities at startup and
  applies a per-model preference list (e.g. `florence → [npu, cpu]`, `yunet → [cpu]`).
- **Automatic CPU fallback**: any engine load/run failure demotes that model to
  `OrtCpuEngine` (XNNPACK) for the session and logs it — the pipeline never hard-fails
  on an acceleration bug. CPU stays the correctness reference.
- **Models stay NPU-friendly**: all inference is ONNX INT8 with plain conv/attention ops
  (no custom ops in any of the five scoring models), which is exactly what NPU compilers
  want. No model change is anticipated for the swap; per-vendor compiled/cached variants
  slot in beside the `.onnx` files if the eventual SDK wants them.
- **Delivery vehicle is deliberately undecided** until the real Pixel 11 SDK exists:
  candidates are an ONNX Runtime vendor EP (QNN-style), LiteRT/TFLite with an NPU
  delegate (requires ONNX→TFLite conversion), or whatever Google ships. Nothing in app
  code assumes CPU beyond the `OrtCpuEngine` class itself.
- **The Phase 2 harness logs timings per engine per model**, so the day the NPU engine
  lands, its win is measured with the same instrument — and the naming toggle (§3) is
  the biggest beneficiary (Florence-2 is the one genuinely inference-heavy stage).

Today's baseline remains CPU/XNNPACK; GPU EPs remain a profiling-gated option. Still no
NNAPI (deprecated) and no Tensor-TPU attempts on the Pixel 9 (closed).

---

## 8. Phased Plan

| Phase | Scope | Exit criterion |
|---|---|---|
| **1 — Analysis** (this doc) | repo summary, model inventory, decode + runtime recommendation | operator review |
| **2 — Headless core** | `core-pipeline` + `inference` + `decode` + `xmp`; debug screen: pick tree URI → enumerate ARW → preview → 4 models + classical CV → fusion → XMP; full instrumentation (§7.3) | per-frame numbers on real hardware from a real a6700 card; A/B score drift report vs desktop pipeline |
| **3 — Ingest** | SAF/libaums, new-file detection (`(original_name, exif_timestamp)` parity), foreground service + progress notification, resume-on-interrupt (stage tokens), safe-eject flow | full card processed unattended with screen off; interrupted run resumes |
| **4 — Review UI** | Compose dark grid of previews; sort/filter: stars, subject, type, needs_review, session, date, master score; keep/reject + star overrides → `xmp:Rating` parse-modify-write | cull a real shoot end-to-end on the phone; overrides visible in desktop darktable |
| **5 — Export & share** | Quick JPEG export = embedded preview + EXIF copy → MediaStore `Pictures/PhotonForge` (instant); share-sheet intent (Google Photos target) single/multi-select | export + "send to Google Photos" works offline-then-sync; stretch: full-res export via LibRaw NDK |
| **6 — Stretch** | Florence-2 naming toggle (default off; models from cartridge `models/` or on-device provision; settings switch lands in the Phase 4 UI, engine lands here); GPU delegate eval (profiling-gated); **Pixel 11 NPU engine** behind `InferenceEngine` (§7.4, hardware-gated on the device/SDK shipping); user-calibrated `training_weights.db` consumption from cartridge | naming produces desktop-identical `semantic_name` on a sample set; toggle honored mid-batch; NPU engine ≥2× CPU on Florence-2 or it stays off by default |

Google Photos: the share-sheet (`ACTION_SEND`/`SEND_MULTIPLE` with `image/jpeg`) reaches
Google Photos with zero permissions, no OAuth, and no cloud code in the app — that is the
Phase 5 deliverable. A direct Google Photos Library API upload (OAuth, network) is
deliberately out of scope unless requested later.

---

## 9. Continuity with the Portable-Cartridge / R2 Plan

### 9.1 Where this sits among the R2 profiles

The R2 brief defines Profile 1 (N150 cartridge appliance, **phone = remote viewer**) and
Profile 2 (field-edit laptop). This app adds a third deployment shape — call it
**Profile 3: Direct-Attach Mobile** — the phone hosts the pipeline itself when a card or
cartridge is plugged straight into it. It does not replace Profile 1 (an appliance still
wins for unattended in-bag ingest and battery); it removes the appliance as a
*prerequisite* for field culling. The shared-stack discipline holds: same models, same
INT8 ONNX artifacts, same thresholds, same XMP contract — different execution substrate
(Kotlin/ORT-Android instead of Python/onnxruntime-CPU).

The pixel-engine question (PR #108) is **orthogonal and unaffected**: the phone never
renders edits — it displays embedded previews only. darktable-cli/RawTherapee/own-pipeline
remain desktop/appliance decisions.

### 9.2 Cartridge filesystem (FR-1.9) — resolved by the portable-drive plan (PR #140)

FR-1.9 specifies cartridges as **ext4** labeled `PHOTON-XXX`. Android does not mount
ext4 external media, and libaums implements FAT/exFAT only — so a phone cannot read an
ext4 PHOTON cartridge. (Camera SD cards are exFAT and work fine, so Phases 2–3 are
unblocked regardless.)

**The self-contained portable-drive plan (PR #140) independently reached the same
answer for Windows compatibility: cartridges become a single GPT exFAT partition**
(`mkfs.exfat` default in `provision.py`, ext4 kept behind `--fs ext4`), with an ADR
(`ADR-00X-exfat-cross-os-cartridge`) recording the decision. Android compatibility is a
second, mutually reinforcing justification for that ADR — one filesystem decision
unblocks Windows, macOS, *and* the phone. Two Android-specific riders on that plan:

- **KPM-1.4 re-validation on exFAT** (already in PR #140's checklist) should count the
  phone as a host: 50 safe-eject cycles must include SAF-mediated writes from Android.
- The Android app treats the PR #140 drive layout as read-mostly: it reads shoot folders,
  `models/`, `photonforge.db`, and writes **XMP sidecars only** — never
  `dt-config/library.db` (desktop darktable reconciles from XMP). `apps/`, `runtime/`,
  `dt-config/` are desktop-only payloads the phone ignores. Bonus: since `.onnx` files
  are data (not executables), W^X permits loading the models straight from the
  cartridge's `models/` dir — the APK's bundled copies become a fallback for SD-only
  sessions, not the only source.

### 9.3 Sidecar hardening feeds back to desktop

§6's parse-modify-write requirement exposed that the desktop `_write_xmp` is
overwrite-only and would destroy darktable edit history in any sidecar it rewrites.
That's a desktop bug worth its own fix regardless of the port (per PR conventions, it
trips complexity triggers → separate PR, not the roundup).

---

## 10. Risks & Open Questions

1. **a6700 preview resolution unverified** (assumed 1616×1080). Phase 2 harness logs it;
   if smaller than 640 px on the short side, YOLO input quality degrades → fallback is
   LibRaw earlier than planned.
2. **Score drift preview-vs-rawpy** (§4.3). Bounded by the A/B report; absolute
   thresholds may need a one-time recalibration recorded in the training DB.
3. **SAF throughput** on some card readers is poor (MTP-class). Mitigation: libaums raw
   USB path; Phase 2 measures both.
4. **OpenCV Android SDK size** (~15 MB/ABI). Acceptable v1; replaceable by hand-rolled
   kernels later (all uses are enumerable).
5. **Thermals**: sustained multi-model inference + decode on a phone in the field.
   `getThermalHeadroom` instrumentation is in from day one; batch pacing if needed.
6. **Cartridge exFAT migration** (§9.2) — decided in the portable-drive plan (PR #140);
   residual risk is the KPM-1.4 exFAT soak, shared with that plan.

---

## 11. KPM Candidates (Android profile)

To be baselined by the Phase 2 harness on the Pixel 9 Pro XL:

- **KPM-A.1**: end-to-end per-frame cull latency (preview + 4 models + CV + fusion + XMP)
  — target ≤ 500 ms/frame sustained.
- **KPM-A.2**: 500-frame card, cold start → all scored, ≤ 6 min, no thermal shutdown.
- **KPM-A.3**: zero XMP corruption / darktable round-trip losses over 50 cycles
  (KPM-1.4 analogue).
- **KPM-A.4**: battery drain per 500-frame batch ≤ 15%.
