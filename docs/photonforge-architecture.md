# PhotonForge Systems Architecture

**Autonomous Photography Workstation -- Living Document**

Lenovo Yoga 910-13IKB Glass (Star Wars Special Edition)

Revision 6.0 | April 14, 2026 | Development Platform: Claude Code (Multi-Agent)

*Consolidates: architecture-v4, v5-gui-addendum, v5-vv-addendum*

---

## 1. Executive Summary

PhotonForge is an autonomous ingest-to-edit photography system that transforms a Lenovo Yoga 910-13IKB Glass (Star Wars Special Edition) into a purpose-built photography workstation. The system ingests from SD cards, analyzes and scores images, generates semantic filenames, and syncs results to Darktable -- all offline, all local.

The system architecture spans three layers: (1) a Python analysis pipeline for image intelligence, (2) a host integration layer using udev, Docker, and shell scripts, and (3) a Darktable Lua script that renders a PHOTONForge control panel in the lighttable view. Development uses Claude Code with a five-agent roster: @architect, @engineer, @devops, @verification, and @validation.

---

## 2. Target Hardware

**Platform:** Lenovo Yoga 910-13IKB Glass (Star Wars Special Edition), 80VG series

| Component | Specification | Constraint / Notes |
|:---|:---|:---|
| CPU | Intel Core i7-7500U (2C/4T, 2.7 GHz base, 3.5 GHz turbo) | AVX2 supported. Dual-core limits parallel processing. All benchmarks target this CPU. |
| RAM | 8 GB DDR4-2133 (soldered) | Not upgradeable. Container RSS limit: 1.5 GB (KPM-1.3). Host OS needs ~2-3 GB. |
| USB-C Left (rear) | 1x USB 2.0 (charging + data) | Charging port. Not suitable for high-speed SSD. Excluded from udev SSD matching. |
| USB-C Left (front) | 1x USB 3.1 Gen 1 (5 Gbps) | Primary SSD cartridge port. Single cartridge at a time. |
| USB-A Right | 1x USB 3.0 Always On (5 Gbps) | SD card reader ingest path. |
| Display | 13.9" FHD IPS (1920x1080) | No scaling required. Touch-enabled for tablet mode. |
| Storage | 256 GB M.2 SSD | OS + tools only. All photo libraries on external SSD cartridges. |
| Wireless | Lenovo 2x2 802.11ac + BT 4.1 | Offline at runtime (NFR-2.1). Wi-Fi for initial setup only. |

### 2.1 Hardware Delta from Original Spec

The original specification targeted a Yoga 920 (i7-8550U, 16 GB, Thunderbolt 3). Revision 4.0 corrected to the actual Yoga 910. Key impacts: half the CPU cores (2C vs 4C), half the RAM (8 GB vs 16 GB), single USB 3.1 port (vs dual Thunderbolt), FHD display (vs 4K requiring 200% scaling).

### 2.2 Memory Budget (8 GB System)

| Component | Allocation | Notes |
|:---|:---|:---|
| Linux kernel + OS | ~1.0 GB | Minimal Ubuntu 24.04 footprint |
| Docker daemon | ~0.3 GB | Container runtime overhead |
| Darktable | ~2.0 GB | Largest single consumer |
| Analyzer container | 1.5 GB (hard limit) | KPM-1.3: Florence-2 INT8 + image buffers |
| Darktable Lua panel | ~0 MB | Runs inside Darktable process, no separate allocation |
| System buffer/cache | ~3.2 GB | Reclaimable under pressure |
| **TOTAL** | **8.0 GB** | No swap -- zram only (SSD wear concern) |

### 2.3 USB Port Topology

| Port | Location | Speed | Assignment | udev Strategy |
|:---|:---|:---|:---|:---|
| USB-C (rear) | Left side, rear | USB 2.0 | Power/charging | Excluded from SSD matching |
| USB-C (front) | Left side, front | USB 3.1 Gen 1 (5 Gbps) | SSD cartridge | Match by ID_FS_LABEL=PHOTON-*. Mount to /mnt/photon_ssd/XXX |
| USB-A | Right side | USB 3.0 (5 Gbps) | SD card reader | Match by vendor 05e3:0749. Trigger rsync ingest |

### 2.4 Linux-Specific Considerations

- **Wi-Fi:** Lenovo 2x2 AC may require firmware updates on Ubuntu 24.04 LTS.
- **Tablet Mode:** Watchband hinge with 360-degree rotation. Kernel modules for auto-rotation TBD.
- **Display:** FHD at 13.9" -- no scaling needed.
- **USB-C:** Only front left port is USB 3.1. udev rules use ENV{DEVTYPE}, systemd-mount for mounting, and wrapper scripts (no inline shell in RUN values).

---

## 3. Requirements

### 3.1 Functional Requirements

<!-- AUTO:fr_table -->
| ID | Description | Implementation | Status |
|:---|:---|:---|:---|
| [FR-1.1](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/56) | Automated Media Ingest | udev-triggered rsync from SD to SSD cartridge | DEFINED |
| [FR-1.10](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/58) | Safe Ejection | WAL flush, sync, unmount via safe_eject.sh | DEFINED |
| [FR-1.2](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/49) | Spatio-Temporal Grouping | Cluster if temporal delta < 500ms AND Hamming distance near 0 | DEFINED |
| [FR-1.3](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/50) | Perceptual Deduplication | dHash near-duplicate detection (Hamming distance <= 2) | DEFINED |
| [FR-1.4](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/51) | Sharpness Scoring | Normalized Laplacian Variance | DEFINED |
| [FR-1.5](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/52) | Compositional Evaluation | Rule-of-Thirds centroid proximity via saliency maps | DEFINED |
| [FR-1.6](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/53) | Exposure Assessment | 11-zone luminance segmentation; entropy vs. IEA40K threshold | DEFINED |
| [FR-1.7](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/54) | Local Semantic Naming | Florence-2-base-ft INT8 ONNX: 4-model pipeline (vision encoder, embed tokens, encoder, decoder merged). 5-word descriptive slugs. | DEFINED |
| [FR-1.8](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/55) | Darktable Integration | SQLite writes to library.db + .xmp sidecar generation | DEFINED |
| [FR-1.9](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/57) | Library Cartridge Management | Physical Independent Volumes. ext4 labeled PHOTON-XXX. Each carries own DB + config. | DEFINED |
<!-- /AUTO:fr_table -->

### 3.2 Non-Functional Requirements

<!-- AUTO:nfr_table -->
| ID | Description | Specification | Status |
|:---|:---|:---|:---|
| [NFR-2.1](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/59) | Internet Independence | 100% offline at runtime. Initial provisioning (OS, packages, models) may use internet. Cloud export (Phase 3) user-opt-in only. | DEFINED |
| [NFR-2.3](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/61) | Database Portability | Darktable library.db + user config on external SSD, not host filesystem. | DEFINED |
| [NFR-2.4](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/62) | Interactive UI Prompts | zenity dialogs if SD inserted without SSD connected. | DEFINED |
| [NFR-2.4](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/60) | Interactive UI Prompts | zenity dialogs if SD inserted without SSD connected. | DEFINED |
<!-- /AUTO:nfr_table -->

### 3.3 Key Performance Measures

<!-- AUTO:kpm_table -->
| KPM | Metric | Target | Owner | Verified By | Last Measured | Status |
|:---|:---|:---|:---|:---|:---|:---|
| [KPM-1.1](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/64) | Ingest Latency | >= 80% USB 3.0 bandwidth | @devops | @verification | untested | untested |
| [KPM-1.2](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/63) | Inference Speed | <= 2.5s per image (Florence-2 INT8) | @engineer | @verification | untested | untested |
| [KPM-1.4](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/65) | Data Integrity | Zero SQLite corruption over 50 eject cycles | @devops | @validation | untested | untested |
<!-- /AUTO:kpm_table -->

---

## 4. Intelligence Engine

The inference subsystem targets the i7-7500U's AVX2 instruction set with a 4-model ONNX pipeline.

- **Runtime:** onnxruntime CPU provider, AVX2 optimized. No CUDA, no OpenVINO.
- **Model:** Florence-2-base-ft from onnx-community/Florence-2-base-ft.
- **ONNX Sessions:** vision_encoder_int8.onnx, embed_tokens_int8.onnx, encoder_model_int8.onnx, decoder_model_merged_int8.onnx
- **Config Files:** tokenizer.json, tokenizer_config.json, preprocessor_config.json, generation_config.json, config.json
- **Memory Budget:** All 4 sessions + image buffers within 1.5 GB RSS (KPM-1.3).
- **Threading:** ORT_NUM_THREADS=2 to match physical core count. Avoid oversubscription.
- **Inference Pipeline:** Image -> vision_encoder (pixel_values -> image_features) -> embed_tokens (prompt IDs -> text_embeds) -> encoder (concat embeds -> hidden state) -> decoder (greedy generation with KV cache, empty past_key_values on first step [1, 12, 0, 64]) -> tokenizer decode -> 5-word slug

---

## 5. Agent Roster

| Agent | Model | Tools | Scope | Memory | Color |
|:---|:---|:---|:---|:---|:---|
| @architect | opus | Read, Grep, Glob (read-only) | CLAUDE.md, architecture, interface contracts, dependency decisions | user | blue |
| @engineer | sonnet | All tools | src/, tests/test_*.py, models/ | project | green |
| @devops | sonnet | All tools | deploy/, scripts/ | project | orange |
| @verification | sonnet | All tools | tests/test_*.py, docs/VerificationReports/ | project | yellow |
| @validation | sonnet | All tools | tests/e2e/, docs/ValidationReports/, living-user-needs.md (by ID) | project | cyan |

### 5.1 @verification (Requirements Enforcer)

**Trigger:** @engineer commit to main
**Input:** git diff HEAD~1 + @architect handoff brief (requirement IDs only)

- **Unit test generation:** Create/extend pytest cases from diffs. Never modifies src/.
- **KPM benchmarks:** KPM-1.2 timing, KPM-1.3 RSS, KPM-1.1 bandwidth.
- **Context rules:** Diff-only reads. Single-failure file read on test failure. No full repo scans.
- **Writes:** tests/test_*.py (new/extended), docs/VerificationReports/
- **On failure:** Error report to @engineer. Never rewrites source code.

### 5.2 @validation (User Needs Advocate)

**Trigger:** Merge to main (milestone) or manual invocation
**Input:** UN-XXX requirement IDs from living-user-needs.md + CLI/pipeline output

- **E2E testing:** SD ingest through Darktable output. Black-box only.
- **KPM-1.4 soak test:** 50-cycle plug/eject with prompt-and-wait pattern for physical actions.
- **Edge cases:** Empty SD, no images, SSD unmounted, corrupt EXIF.
- **Context rules:** UN-ID grep only. Never reads src/ implementation.
- **Writes:** tests/e2e/, docs/ValidationReports/, soak-test-log.md
- **On failure:** Escalate to @architect for requirement reassessment.
- **Hardware-absent:** XFAIL-HARDWARE marker. Never silent skip.

### 5.3 Escalation Paths

| Failure Source | Target | Action |
|:---|:---|:---|
| @verification test failure | @engineer | Error report with failing test, diff, requirement ID |
| @validation E2E failure | @architect | Workflow compliance report with UN-ID mismatch |
| Hardware-absent test | XFAIL-HARDWARE | Marked, logged in soak-test-log.md for manual execution |
| KPM regression | @engineer (1.2/1.3) or @devops (1.1/1.4) | Benchmark report with measured vs. target values |

### 5.4 Token Optimization Guardrails

- **Diff-only context:** V&V agents read git diff HEAD~1, not full files.
- **UN-ID grep:** @validation pulls specific IDs from living-user-needs.md, never the full document.
- **Test generation vs. execution:** Agents write tests. Tests execute via CLI. LLM analyzes output only on failure.
- **Cache awareness:** No relevant diff = skip re-run. Report "no changes."

---

## 6. UI Architecture: Darktable Lua Plugin

### 6.1 Product Vision

PhotonForge integrates directly into Darktable as a Lua plugin that renders a collapsible control panel in the lighttable left sidebar. There is no separate application process -- Darktable is the host, and PHOTONForge is a plugin. Lua is pure UI glue: it builds the panel, launches `photo-workflow` subcommands as subprocesses, reads their JSON stdout line-by-line, and applies results to Darktable images via the native Lua API. All computation stays in Python.

### 6.2 Why Lua Plugin (Supersedes Tauri)

| Concern | Tauri (v5 plan) | Darktable Lua (v6) |
|:---|:---|:---|
| RAM overhead | 30-50 MB idle | ~0 MB (runs in Darktable process) |
| Library browsing | Custom thumbnail grid | Darktable lighttable (native) |
| Export | Custom Rust copy logic | Darktable export module (native) |
| Darktable handoff | Subprocess launch + re-focus | No handoff needed -- already inside Darktable |
| DB writes | Custom SQLite upserts | Darktable Lua API (rating, color labels, metadata) |
| Development effort | Rust backend + web frontend (weeks) | Lua plugin (days) |
| Maintenance | Two apps to update | One plugin directory |

### 6.3 Plugin File Layout

```
<darktable-lua-dir>/photonforge/
  main.lua          -- entry point; registers panel with darktable
  panel.lua         -- sidebar widget tree and event handlers
  runner.lua        -- subprocess launch + stdout JSON parsing
  applicator.lua    -- JSON result → darktable.image API calls
  config.lua        -- load/save settings via darktable.preferences
```

One line added to `luarc`: `require "photonforge/main"`

See `docs/mockups/PhotonForgePanel.jsx` for the interactive reference mockup.

### 6.4 Panel Layout

Left sidebar, collapsible section labelled **PHOTONForge**:

- **Configuration fields:** SD card path, destination, model dir, manifest path, TZ offset
- **Step toggles:** Ingest, Dedup, Score, Name, Sync -- each with checkbox and last-run status chip
- **Run / Stop buttons:** Run executes enabled steps sequentially; Stop kills subprocess, manifest checkpoint preserves progress for resume
- **Progress bar:** Updated via `_progress` JSON lines from Python subprocess
- **Live log viewer:** Scrolling log of per-image results

### 6.5 JSON Progress Protocol

Each Python subcommand accepts `--json-progress`. When set, all stdout is newline-delimited JSON. The Lua runner parses these lines and dispatches to the applicator.

Key line types:
- `status: ok` -- applicator writes results to Darktable API
- `status: duplicate` -- applicator sets red color label, rating 0
- `status: error` -- logged to panel log viewer, image skipped
- `step: _progress` -- updates progress bar (done/total)

### 6.6 Applicator -- JSON to Darktable API

| JSON field | Darktable API call |
|:---|:---|
| `stars` | `image.rating = value` |
| `color_label` (int 0-4) | `darktable.colorlabels` table assignment |
| `semantic_name` | `image:set_metadata("description", value)` |
| `status = "duplicate"` | `image.rating = 0` + red color label (0) |
| Ingest complete | `darktable.films.scan(dest_dir)` -- adds files to library |
| `step = "name", dest` | `image:move(dest_dir, new_filename)` |

### 6.7 Plugin Requirements

| ID | Description | Specification |
|:---|:---|:---|
| LUA-1.1 | Panel location | Lighttable left sidebar, collapsible |
| LUA-1.2 | Pipeline feedback | Real-time progress via `--json-progress` subprocess stdout |
| LUA-1.3 | Step toggles | Individual enable/disable per pipeline step with last-run status |
| LUA-1.4 | Config persistence | All fields saved via `darktable.preferences.register()` under namespace `photonforge` |
| LUA-1.5 | Stop / Resume | Kill subprocess on Stop; JSONL manifest checkpoint enables resume on next Run |
| LUA-1.6 | Offline operation | No network calls. Plugin files bundled with Darktable config. |
| LUA-1.7 | Error display | Per-image errors logged to live log viewer; step marked failed in status chip |

### 6.8 What Darktable Provides Natively

These features from the old Tauri plan are no longer needed -- Darktable handles them:

- **Library browsing:** Lighttable filmstrip + grid with star ratings, color labels, tags
- **Export/sharing:** Darktable export module (local directory, USB, network)
- **Dark theme:** Darktable's default theme
- **Image editing:** Darkroom view
- **Metadata display:** Image information panel

Full design spec: `docs/superpowers/specs/2026-05-13-darktable-lua-plugin-design.md`

---

## 7. Project Structure

```
photo-workflow/
  CLAUDE.md                      # Project spec + task sequencing
  pyproject.toml                 # Package definition, dependencies
  .claude/agents/
    architect.md                 # Read-only, opus (blue)
    engineer.md                  # All tools, sonnet (green)
    devops.md                    # All tools, sonnet (orange)
    verification.md              # All tools, sonnet (yellow)
    validation.md                # All tools, sonnet (cyan)
  src/photo_workflow/
    pipeline.py                  # AnalysisPipeline orchestrator + staged CLI (scan/dedup/score/name/sync/status)
    manifest.py                  # JSONL manifest read/write/checkpoint for staged pipeline
    progress.py                  # Terminal progress counter (throughput, ETA, RSS)
    ingest.py                    # FR-1.1: rsync trigger
    grouping.py                  # FR-1.2: spatio-temporal clustering
    dedup.py                     # FR-1.3: dHash dedup (Hamming <= 2)
    sharpness.py                 # FR-1.4: Laplacian variance
    composition.py               # FR-1.5: rule-of-thirds + saliency
    exposure.py                  # FR-1.6: 11-zone luminance entropy
    naming.py                    # FR-1.7: Florence-2 INT8 4-model pipeline
    darktable_bridge.py          # FR-1.8: SQLite + XMP sidecar sync
    cartridge.py                 # FR-1.9: SSD volume management
  scripts/
    safe_eject.sh                # FR-1.10: WAL flush + unmount
    manage_ssd.sh                # SSD detection + volume remap
    install_udev.sh              # udev rule + wrapper script installer
    provision_models.sh          # One-time ONNX download + config fetch
    remote_test.sh               # Automated test runner (JSON output)
    on_ssd_add.sh                # udev wrapper: cartridge mount
    on_ssd_remove.sh             # udev wrapper: cartridge remove log
    on_sd_add.sh                 # udev wrapper: SD mount/symlink
    on_sd_remove.sh              # udev wrapper: SD remove log
  deploy/
    Dockerfile                   # Container (Ubuntu 24.04)
    docker-compose.yml           # Service orchestration
    udev/
      99-photo-ssd.rules         # PHOTON-* label matching
      99-photo-sd.rules          # SD reader vendor matching
  tests/
    fixtures/                    # Test images, mock library.db
    test_*.py                    # Unit tests (@verification)
    e2e/                         # E2E tests (@validation)
  models/florence2_int8/          # Vendored ONNX + configs (.gitignore'd)
  docs/
    living-user-needs.md         # UN-001 through UN-032
    VerificationReports/         # Per-commit pass/fail (@verification)
    ValidationReports/           # Per-milestone compliance (@validation)
      soak-test-log.md           # KPM-1.4 persistent cycle tracker
  lua/photonforge/
    main.lua                     # Plugin entry point; registers panel
    panel.lua                    # Sidebar widget tree + event handlers
    runner.lua                   # Subprocess launch + JSON parsing
    applicator.lua               # JSON result → Darktable API calls
    config.lua                   # Preferences persistence
  docs/mockups/
    PhotonForgePanel.jsx         # Interactive React reference mockup
```

---

## 8. Execution Roadmap

| Stage | Owner | Scope | Acceptance Criteria | UN-IDs |
|:---|:---|:---|:---|:---|
| 1. Scaffold | @architect | Project init, CLAUDE.md, pyproject.toml, agents | pip install -e . succeeds; pytest discovers tests; claude agents lists 5 | UN-001, UN-002 |
| 2. Core Engine | @engineer | FR-1.2 through FR-1.6 | All tests pass; memory < 500 MB per module | UN-010 to UN-014 |
| 3. Inference + Bridge | @engineer | FR-1.7 (Florence-2 4-model naming) + FR-1.8 (Darktable SQLite/XMP) | KPM-1.2 <= 2.5s/image; zero DB corruption | UN-020, UN-021 |
| 4. Host Integration | @devops | FR-1.1, FR-1.9, FR-1.10: udev, cartridge, safe eject, Docker | KPM-1.1 >= 80% BW; KPM-1.4 50 safe removals | UN-030 to UN-032 |
| 5. Parallel Build | @engineer + @devops | Concurrent Stage 2-4 (agent teams) | All individual stage criteria met | All Stage 2-4 |
| 5.1 Batch CLI | @engineer | Stage-based CLI (scan/dedup/score/name/sync/status), JSONL manifest, resume/checkpoint, progress display | All subcommands work independently; 7000-photo batch completes with resume | UN-050 to UN-054 |
| 6. Integration | @architect (lead) | Full pipeline E2E on Yoga 910 | All KPMs verified; SD-to-Darktable autonomous | All UN-IDs |
| 7.1 Lua Panel | @engineer | Darktable Lua script: 3-tab panel (Ingest, Status, Cartridge), pipeline subprocess invocation | Panel renders in lighttable, pipeline runs from UI, cartridge eject works | -- |
| 7.2 Polish | @engineer + @devops | Progress streaming, warning display, library refresh after sync | Real-time stage feedback, low-score warnings shown, lighttable refreshes | -- |

---

## 9. Living User Need Document

The Living User Need Document (docs/living-user-needs.md) is the sole input for @validation compliance checks. Requirements numbered UN-001 through UN-054. The @validation agent pulls only specific UN-IDs relevant to the current milestone via grep.

---

## 10. Decision Log

| Decision | Chosen | Rejected | Rationale |
|:---|:---|:---|:---|
| UI approach | Darktable Lua plugin (left sidebar) | Tauri (v5), Electron | Zero RAM overhead. Darktable already running -- no second process. Eliminates library browser, export, dark theme, and Darktable launcher features (all native). Lua plugin directory vs. Rust+web frontend. |
| Sharing model | Darktable export module (native) | Custom Rust copy logic | Darktable's export module already handles local/USB/network targets. No custom code needed. |
| DB writes | Lua applicator via Darktable API | Python SQLite upserts | Darktable owns its DB. Writing via Lua API avoids corruption risk and keeps DB portable. Python `sync` subcommand writes XMP sidecars only. |
| Progress protocol | `--json-progress` flag on all subcommands | Human-readable stdout | Structured JSON enables Lua parser to update progress bar, status chips, and log viewer. Human output preserved as default. |
| V&V execution | SSH to Yoga 910 via Claude Code | Manual copy-paste | Native SSH sessions eliminate manual terminal relay. |
| SSD cartridge identity | Hidden metadata file `.photonforge/cartridge.json` | Filesystem label (PHOTON-*) | Label is now cosmetic; identity survives label changes. Detection is mount-path-agnostic, works with udisks2 auto-mount at any path. |
| Device detection | Metadata file presence + `/proc/mounts` poll | udev label rules | udisks2 won out over custom udev mounting in practice; polling is simpler and reliable. |
| Multi-cartridge support | Deferred — data model is Vec (ready) | Not in scope | `DeviceState.cartridges` is already an array; destination picker UI deferred until a hub use case is validated. |
| Batch CLI architecture | Stage-based subcommands with JSONL manifest | Monolithic single-command; sidecar wrapper | 7000-photo batches need per-stage resume, independent execution, and crash-safe checkpoints. Sidecar is GUI-coupled. |

---

## 11. Development Workflow

### 11.1 Automated vs. Manual

| Claude Code (Automated) | Manual (Requires Yoga 910) |
|:---|:---|
| Python module implementation + tests | udev rule testing on USB topology |
| Shell script generation | ONNX weight acquisition (provision_models.sh) |
| Dockerfile + docker-compose | Physical SSD mount/eject cycles |
| SQLite fixture generation | Wi-Fi driver configuration |
| Linting, formatting, type checking | Darktable UI verification |
| pytest execution and iteration | KPM-1.4 soak test (physical plug/unplug) |
| V&V agent test generation | Hardware-absent test manual execution |

### 11.2 Remote Execution

Client-side testing runs via SSH to alex@10.27.27.10. The Yoga 910 hosts the runtime environment with mounted PHOTON cartridges and SD reader. Use scripts/remote_test.sh as the standard entry point. Physical hardware actions (plug/unplug) require human intervention -- agents use prompt-and-wait pattern for these.

### 11.3 V&V Execution Model

@architect defines requirements -> @engineer implements -> @verification validates implementation against requirements (loop to @engineer on failure) -> merge to main -> @validation validates workflow against user needs (loop to @architect if feature works but misses user need).

Both V&V agents execute via Claude Code SSH sessions against the Yoga 910 for hardware-coupled validation.

---

## 12. References

1. pHash in Python | Hashing and Validation -- SSOJet (accessed April 7, 2026)
2. Open source image recognition with Luminoth | Opensource.com (accessed April 7, 2026)
3. Best lightweight Linux distro of 2025 -- TechRadar (accessed April 7, 2026)
4. How to compact the library? -- darktable -- discuss.pixls.us (accessed April 7, 2026)
5. Meet BLIP: The Vision-Language Model Powering Image Captioning -- PyImageSearch (accessed April 7, 2026)
6. Intel Core i7-7500U Specifications -- Intel ARK (accessed April 10, 2026)
7. Lenovo Yoga 910-13IKB Convertible Review -- NotebookCheck (accessed April 10, 2026)
8. onnx-community/Florence-2-base-ft -- Hugging Face (accessed April 10, 2026)
9. Tauri Framework -- https://tauri.app (accessed April 13, 2026)
10. gnome-kiosk-script-session -- GNOME kiosk session configuration
11. Ubuntu Frame -- Canonical embedded graphics shell
12. Buildroot -- https://buildroot.org (Tier 3 contingency)
13. Cage -- Minimal Wayland compositor for kiosk/single-app use
14. INCOSE Systems Engineering Handbook, 5th Edition -- V&V framework
15. Claude Code SSH Documentation -- code.claude.com/docs/en/desktop
