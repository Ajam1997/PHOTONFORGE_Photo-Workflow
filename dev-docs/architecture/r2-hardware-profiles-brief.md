# PHOTONForge R2 Hardware Decision Brief — Two Deployment Profiles

**Date:** 2026-06-18
**Status:** Decisions recorded, no procurement yet. R2 is post-R1; this is forward-looking.
**Author:** @systems_lead session — hardware target selection for R2
**Related:** `gui-layer-handoff-brief.md` (the GUI/edit layer Profile 2 hosts)

---

## 1. What This Is

R2 ships **one software stack** on **two hardware profiles**, differentiated by a single
question: *does the user want to edit on the go, or only ingest and curate?*

| | **Profile 1 — Cartridge Appliance** | **Profile 2 — Field-Edit Laptop** |
|---|---|---|
| Hardware | Intel N150 (LattePanda Iota, 16GB) | AI laptop: NPU + OpenCL iGPU (Lunar Lake reference) |
| User intent | "Ingest & curate now, edit later" | "Score *and* edit on the go" |
| Workload | pipeline only (ingest→dedup→score→name) | pipeline **+ interactive AI editing** |
| Inference | onnxruntime CPU (AVX2/VNNI), **unchanged** | CPU pipeline **+ NPU via OpenVINO EP** in edit layer |
| Form | headless, battery, fanless; phone = remote viewer | full DearPyGui GUI on-device |
| Power ceiling | **hard ≤10W** (bag/battery) | **none** — plugged / actively cooled |
| Cost | ~$150–200 | ~$300+++ (laptop class) |

The two profiles are **not a fork.** They are the same modules behind a different entry
point (per `gui-layer-handoff-brief.md`, the GUI runs native as a separate entry point
from the Dockerized headless pipeline) and, for Profile 2, a different execution provider.
§2 records the discipline that keeps them sharing code.

---

## 2. Shared-Stack Discipline (applies to both profiles)

1. **The autonomous pipeline stays CPU-only on both profiles.** Florence-2/CLIP/YOLO
   scoring runs fine on `onnxruntime` CPU provider (AVX2/VNNI). Profile 2's NPU is **not**
   required to run the pipeline — so the pipeline code is identical across profiles and
   never imports an NPU dependency.

2. **The NPU requirement belongs to the *edit layer*, not the pipeline.** What demands the
   NPU is the interactive editing loop — fast scoring feedback and the Phase 3 neural edit
   modules (ONNX denoise / tone-map / LUT, see `gui-layer-handoff-brief.md §15`). The
   OpenVINO execution-provider abstraction therefore lives in the GUI/edit modules only.
   On Profile 1 those modules are absent; on Profile 2 they're present and NPU-backed.

3. **Bridges stay UI- and host-agnostic** (`engine_bridge`, `renderer_bridge`,
   `xmp_builder`, `suggest` — no DearPyGui imports, no same-process assumptions). This is
   what lets the same code serve the headless appliance, the on-device laptop GUI, and a
   future phone client without a rewrite.

---

## 3. Profile 1 — Cartridge Appliance (Intel N150 / LattePanda Iota, 16GB)

### 3.1 What It Is

A battery-powered, in-bag appliance: insert a full SD card, drop it in your bag, and it
ingests → dedups → scores → (optionally) names photos autonomously, then notifies a phone
over local wireless. The phone is a remote viewer + approve/export client. **Interactive
raw editing is not an in-bag workload** — that's Profile 2's job.

### 3.2 Why N150, not the original ZimaBlade

The ZimaBlade 7700 ships an **Intel Atom E3950 (Apollo Lake) — SSE4.2 only, no AVX2**.
The INT8 ONNX stack is tuned for AVX2; on Apollo Lake `onnxruntime` falls to a slow
reference/SSE path and **KPM-1.2 (Florence-2 ≤ 2.5s/image) is unreachable** (est.
8–20s/image, before in-bag thermal throttling at 6W). See §5 for the full rejection.

The **N150 (Twin Lake, Gracemont core) has AVX2 *and* AVX-VNNI** — the 256-bit vector
unit plus the INT8 dot-product instruction quantized models want. The existing x86 /
`onnxruntime` CPU stack runs **unchanged** — no CLAUDE.md edits, no EP abstraction. Turbo
to 3.6GHz helps Florence-2's latency-bound single-image path vs. the ZimaBlade's 2.0GHz.

### 3.3 LattePanda Iota Fit

| Feature | Value | Relevance |
|---|---|---|
| CPU | N150, 4C/4T, up to 3.6GHz | AVX2 + VNNI; revives KPM-1.2 |
| RAM | 8/16GB LPDDR5-4800, **in-band ECC** | **Buy 16GB** (soldered, §3.4); ECC helps KPM-1.4 |
| iGPU | Intel Graphics, 24 EU @ 1GHz | Adequate for darktable-cli / DearPyGui when docked |
| TDP | **6W–15W configurable** | 6W fanless in bag / 15W + fan when docked (§3.5) |
| USB | 3× USB 3.2 Gen2 Type-A (10Gbps) | SD reader + SSD cartridge ingest; KPM-1.1 headroom |
| Power in | USB-C PD 15V **or** PH2.0 4-pin **10–15V DC** | DC input feeds a battery pack directly (§3.5) |
| Storage | 64/128GB eMMC 5.1 | OS only; `library.db` stays on external SSD (NFR-2.3) |
| OS | Ubuntu 22.04 & 24.04 supported | Matches container OS target exactly |
| M.2 | **1× E-Key 2230 (PCIe/CNVio)** | WiFi/BT slot — see §3.4 correction |
| Misc | RTC battery, DIP auto-power-on, PWM fan port, RP2040 MCU | Appliance behaviors (§3.5, §3.7) |

Approx. cost: ~$130–200 (16GB SKU) + ~$15–20 CNVi WiFi+BT card.

### 3.4 Hard Constraints / Corrections

1. **RAM is soldered LPDDR5 — no upgrade ever.** Buy the **16GB** SKU. The RSS budget
   (NFR-2.2, 1.5GB) is tight once inference (~800MB) + darktable-cli + OS + WAL cache
   coexist; 8GB leaves no margin and cannot be expanded later.

2. **One M.2 slot, and it is E-Key (PCIe/CNVio) — a WiFi slot, not an NPU/NVMe slot.**
   CNVio expects an **Intel CNVi WiFi+BT module** (AX201/AX211-class), which provides the
   R2 phone link. An earlier assumption that a Hailo/LLM accelerator could be added later
   is **retracted**: the E-Key slot is consumed by WiFi, and the secondary PCIe 3.0 x1 FPC
   connector is too bandwidth-/form-limited to be a clean accelerator path. **Treat the
   N150 CPU as the entire inference budget for this board.** Needing more inference on the
   go is the trigger to move to Profile 2 — not to bolt an accelerator onto the appliance.

3. **WiFi/BT is not onboard** — it comes via the E-Key card above. Budget for it; the
   whole wireless-to-phone story depends on it.

### 3.5 Power & Thermal Policy (two operating *modes*)

| Mode | TDP | Cooling | Power source | Workload |
|---|---|---|---|---|
| **Bag** | 6W (cTDP-down) | Passive / fanless | Battery on PH2.0 DC input (10–15V) | Ingest, dedup, scoring, (slow) naming as background |
| **Dock** | 15W | PWM fan (fan port) | Wall via USB-C PD or DC | Fast inference, darktable-cli previews |

- **Battery sizing:** measure sustained draw during a full-card soak at 6W, then size the
  pack for a realistic "full card" runtime. Open until benchmarked (§6).
- **Thermal:** a bag is an insulator. Validate the passive heatsink SKU holds clocks under
  a 30+ min sustained scoring soak *inside the actual bag*, at 6W. If it throttles, naming
  becomes a deferred/docked workload (acceptable — see §3.1).
- **Auto-power-on:** the DIP switch enables power-on when the battery is applied — no
  button press needed in the bag.
- **Offline clock:** with NFR-2.1 forbidding network at runtime there is **no NTP**. The
  **RTC battery connector** keeps the clock correct so EXIF/session timestamps stay sane.

### 3.6 NFR Changes Forced by the Headless Appliance

These do not change R1; they apply to the Profile 1 build of the system.

- **NFR-2.1 (100% offline at runtime):** relaxes from "no network" to **"no internet."**
  The appliance hosts a **local wireless link** (own AP or direct pairing) for phone
  notifications and the remote viewer. Bulk photo transfer goes over WiFi, **not BT** (BT
  is too slow for 24MP raws; reserve it, if used at all, for the notification ping).

- **NFR-2.4 (zenity dialog when SD inserted without SSD):** a headless in-bag device has
  **no screen**, so the zenity dialog is meaningless. The alert mutates to a **hardware
  indicator (RP2040-driven LED/buzzer, §3.7) and/or a push to the phone**. Track as an
  appliance-profile variant of NFR-2.4.

### 3.7 The RP2040 Coprocessor — Roles in This Stack

The Iota carries an onboard **RP2040 (133MHz dual-core Cortex-M0+, 264KB SRAM, 8MB
flash)** wired to the GPIO / analog inputs / PWM / fan port. It runs **independently of
the x86 host** (including while the host is asleep or booting), and bridges to the host
over an internal USB-CDC serial link. That independence is exactly what an unattended,
battery-powered appliance needs. Highest-value roles, roughly in priority order:

1. **Battery-aware safe shutdown — protects KPM-1.4 (zero SQLite corruption).** RP2040
   reads battery voltage on an analog input; on low-battery it signals the host to flush
   WAL and shut down *gracefully before power dies*. A battery dying mid-write is the most
   likely real-world cause of library corruption in the bag — the single most important
   RP2040 job. Independent silicon means it works even if the x86 pipeline is wedged.

2. **Headless status indicator — the NFR-2.4 replacement.** Always-on LED/buzzer (or a
   small I2C OLED) showing state: idle / ingesting / done / error / "SD without SSD."
   Driven by the RP2040 so it's instant and works while the x86 is asleep.

3. **Card-insert wake / power gating — battery life + true appliance UX.** Card-detect
   line → RP2040 → power-on the x86 only when there's work, then let it sleep again.
   Turns "a small PC that's always on" into "an appliance that wakes to ingest."

4. **External hardware watchdog.** Host emits a heartbeat over the serial link; if it
   stops (inference deadlock, OOM), RP2040 alerts and/or power-cycles. More robust than a
   software watchdog because it's a separate processor.

5. **Physical controls.** A debounced button to trigger `scripts/safe_eject.sh` (eject the
   SSD cartridge cleanly) or start/stop ingest — tactile, no screen required.

6. **Fan control during boot/early life.** RP2040 can drive the PWM fan port from temp
   readings even before the OS is up; the host takes over once running.

**Architecture & scope note (read before committing):**

- **Host-side integration** is a small serial protocol owned by @software_lead's
  host-integration scope (`scripts/`, udev): the host talks to the RP2040 over a serial
  port like any other device.
- **Firmware is a scope expansion.** CLAUDE.md declares Profile A (tool stack) as
  software-only, *"No EE/ME/firmware tooling."* Flashing RP2040 firmware adds an embedded
  toolchain. Mitigate with **MicroPython** on the RP2040 (keeps it Python-flavored) rather
  than C/Pico-SDK. This is a deliberate, recorded deviation for the R2 appliance — flag it
  to @systems_lead before building; do not absorb it silently.
- **Start minimal.** Roles 1 + 2 (safe shutdown + status indicator) deliver most of the
  appliance value for the least firmware. Add 3–6 only if R2 demand justifies the burden.

---

## 4. Profile 2 — Field-Edit Laptop (NPU + OpenCL iGPU)

### 4.1 What It Is

For the user who wants to **score *and* edit on the go**: the full DearPyGui application
(`gui-layer-handoff-brief.md`) running on-device, with AI-assisted editing — Apply-AI-Preset,
debounced live darktable-cli previews, and (Phase 3) neural edit modules. The sub-10W bag
ceiling does **not** apply here; this is a plugged-in / actively-cooled laptop.

### 4.2 Hardware as a Capability Requirement (not a single SKU)

Write the requirement by capability so it ages past one vendor's roadmap:

> **Profile 2 host = x86-64 + an NPU exposed through an onnxruntime execution provider
> (OpenVINO) + an OpenCL-capable iGPU for darktable acceleration, ≥16GB RAM.**

- **Reference design:** Intel **Lunar Lake (Core Ultra 200V)** — 8–17W configurable, **NPU
  4.0 ≈ 47 TOPS**, strong **Arc Xe2 iGPU** with OpenCL. Hits both needs in one efficient package.
- **Also qualifies:** AMD **Ryzen AI** (XDNA2 NPU + RDNA iGPU) via DirectML/Vitis EPs.
- **Does *not* qualify on its own:** an NPU-only board with a weak iGPU (see §4.4 — the
  iGPU is half the win); or an ARM/Windows-on-ARM machine (see §5 — darktable does not run).

**Confirmed reference machine (2026-06-18 survey): ASUS Vivobook S14 — Core Ultra 7 258V,
32GB LPDDR5X, Arc 140V iGPU, 14" OLED, ~$1,239.** Chosen over the cheaper Ultra 5 226V /
16GB Vivobook 14 Flip ($888) for two reasons that can't be fixed after purchase:

- **RAM is on-package and permanently soldered on all Lunar Lake.** 32GB is the spec to get
  right at buy time; 16GB *works* for the edit loop but leaves little slack for darktable +
  inference + previews + OS. This is the single most important Profile 2 buying decision.
- **Ultra 7 258V carries the higher-tier Arc 140V** (8 Xe2 cores) vs the 226V's Arc 130V (7),
  which directly lowers darktable OpenCL preview latency (§4.4).

The 226V **Flip** has one advantage the S14 lacks — a convertible **touch** form factor,
nice for a future tablet-style culling/review UX. But darktable editing is mouse/keyboard
driven, so form is a nice-to-have while soldered-RAM headroom is not. Pick the Flip only if
touch/tablet mode outweighs headroom.

**Verify at purchase (any SKU):** exact NPU TOPS + Arc tier on Intel ARK; RAM size (soldered);
and — for third-party Amazon sellers — that the **ASUS manufacturer warranty** is honored.

### 4.3 Why the NPU — and Why It's Edit-Layer, Not Pipeline

The autonomous pipeline runs fine on CPU (§2.1), so the NPU is **not** there to make
scoring possible. It exists for the **interactive editing loop**:

- Fast, repeated scoring/feedback as the user iterates.
- **Phase 3 neural edit modules** (ONNX denoise / tone-map / 3D-LUT prediction) — these
  are the workloads that only become viable in real time on an NPU.

So the OpenVINO EP and these models live in the GUI/edit modules (§2.2). On Profile 1 they
simply aren't installed.

### 4.4 Why the iGPU Matters as Much as the NPU

Interactive preview latency is bounded by **darktable-cli's pixel pipeline, which is
OpenCL/CPU — not ONNX.** A strong iGPU (Lunar Lake Xe2, ~67 TOPS, OpenCL) accelerates
darktable's path; the N150's 24-EU iGPU does not. **The NPU alone will not fix slider→
re-render lag** — that's the iGPU's job. A correct Profile 2 host needs *both*. This is the
single most common way to mis-spec an "AI laptop" for this use case.

### 4.5 Software Deltas vs. Profile 1

- Adds the **OpenVINO execution provider** behind the EP abstraction (edit layer only) — a
  recorded CLAUDE.md amendment to the "CPU provider only / no GPU paths" rule, **scoped to
  the GUI/edit layer**, not the headless pipeline.
- Runs the **full DearPyGui GUI on-device** (native entry point) instead of phone-as-client.
- No RP2040 / appliance-power / safe-eject-button hardware (those are Profile 1 only).
- **32GB RAM strongly preferred** (16GB is the workable floor). Lunar Lake RAM is on-package
  and never upgradeable, so size it at purchase. The 1.5GB RSS cap (NFR-2.2) is a Profile 1
  constraint, relaxed here.

---

## 5. Alternatives Considered & Rejected

- **ZimaBlade 7700 (Intel Atom E3950, Apollo Lake) — REJECTED.** SSE4.2 only, **no AVX2**.
  `onnxruntime` INT8 falls to a slow kernel path; KPM-1.2 unreachable (est. 8–20s/image).
  Original appliance target; replaced by the N150.

- **Arduino Uno Q (Qualcomm QRB2210 quad Cortex-A53 + STM32U585) — REJECTED.**
  (a) *As an appliance host:* **ARM, not x86** — abandons the `onnxruntime`-CPU/AVX2/VNNI
  stack; A53 is a weak in-order core (slower than the ZimaBlade for transformer inference);
  2/4GB LPDDR4 is far below the ~800MB-inference + 1.5GB budget; its NPU/DSP is reachable
  only via Qualcomm QNN/SNPE (full inference rewrite). (b) *As an RP2040 replacement:*
  redundant — the Iota already carries an RP2040 onboard; adding a second Linux SBC to act
  as an MCU is more cost/power/OS-maintenance for a job a Cortex-M0+ does better.

- **Snapdragon X / X2 (Copilot+ PCs: IdeaPad Slim 5x, Yoga Slim 7x, ThinkPad T14s G6) —
  REJECTED for Profile 2.** **ARM64 / Windows-on-ARM.** The asymmetry is the point: the
  *pipeline* would actually run — `onnxruntime-qnn` has ARM64 wheels and the Hexagon NPU is
  ~2–4× CPU ([onnxruntime-qnn](https://pypi.org/project/onnxruntime-qnn/)) — but the
  *editing* does not. There is **no working Windows-ARM64 darktable** (builds but fails to
  load, missing DLLs — [darktable #17562](https://github.com/darktable-org/darktable/issues/17562)),
  and Adreno OpenCL on Windows-ARM is unsupported/manual. So the machine you'd buy *to edit
  on the go* can't run the editing engine, while the pipeline it *can* run is already covered
  by the $150 N150 appliance — backwards. Also forces a third EP (QNN, not OpenVINO) and has
  no x86 Linux Docker/CI path. (The Yoga's OLED is the best photo *display* of the three; the
  T14s's 32GB is the most RAM — neither offsets the missing editor.)

- **Sub-10W CPU step-up — 8-core Twin Lake (N355/N305 @ ~9W cTDP-down) — HELD, not adopted.**
  Same Gracemont arch, AVX2+VNNI, **stack unchanged**; ~2× *batch* throughput (drain a card
  faster) but ~flat *single-image* latency at 9W (power-starved), so KPM-1.2 is roughly a
  wash. Worth revisiting only if Profile 1 needs faster whole-card throughput. Not a
  requirement.

- **General finding — below 10W, CPU scaling is nearly flat.** The N150 is near the
  practical *CPU* ceiling for the bag's power budget. The only *meaningful* inference
  step-up under 10W is a **dedicated NPU** (NPUs deliver TOPS at 2–5W) — and that is
  precisely **Profile 2's domain**, a product decision (editing on the go), not an
  appliance upgrade.

---

## 6. Profile 1 Verification Checklist (run on board arrival)

- [ ] **Florence-2 INT8 benchmark on N150** — time ≥10 representative raws end-to-end;
      confirm KPM-1.2 (≤ 2.5s/image) or record the real number. Go/no-go on in-bag naming.
      *(Harness to be wired to the naming entrypoint.)*
- [ ] **Scoring-stage benchmark** — sharpness/composition/exposure timing at 6W cTDP.
- [ ] **Thermal soak** — 30+ min sustained scoring inside the actual bag at 6W; watch for
      throttling.
- [ ] **Sustained power draw at 6W** → size the battery pack for a full-card runtime.
- [ ] **RSS under concurrent load** (inference + darktable-cli mutual-exclusion held) ≤
      1.5GB on the 16GB board (NFR-2.2).
- [ ] **CNVi WiFi+BT card** enumerates under Ubuntu 24.04; local AP + phone link works.
- [ ] **RTC** keeps time across a power cycle with no network (NFR-2.1).
- [ ] **USB 3.2 ingest BW** meets KPM-1.1 (≥ 80% USB 3.0 BW) from SD reader + SSD.

---

## 7. Open Questions (carry-forward, in priority order)

These are *decided-to-defer*, not undecided. Nothing below blocks recording the hardware
direction; each is the next concrete step toward making R2 buildable.

1. **Florence-2 benchmark on the N150 — the go/no-go number.** Time ≥10 representative raws
   end-to-end (harness wired to the naming entrypoint) and confirm KPM-1.2 (≤ 2.5s/image).
   This decides whether in-bag naming is viable or must be **deferred to the dock**. Highest
   priority because it can change Profile 1's job description. See the §6 checklist.

2. **Profile 2 execution-provider abstraction.** Design the onnxruntime EP seam in the edit
   layer (CPU default → **OpenVINO** on NPU hosts) and the **CLAUDE.md amendment** scoping
   the "CPU-only / no GPU paths" exception to the GUI/edit modules only. Prerequisite before
   any Phase 3 neural-module work.

3. **Profile 1 physical build-out.** Three coupled sub-items:
   - **Battery** chemistry/capacity + DC-input wiring (PH2.0 10–15V), sized from the §6
     sustained-draw measurement.
   - **Local wireless** design (own AP vs. direct pairing) + notification protocol — must
     keep the `gui-layer-handoff-brief.md` bridges UI-agnostic so the phone is a client,
     not a rewrite.
   - **RP2040 firmware** language (MicroPython recommended) + host↔MCU serial protocol —
     needs a **@systems_lead scope sign-off** (§3.7) before any firmware work begins.
