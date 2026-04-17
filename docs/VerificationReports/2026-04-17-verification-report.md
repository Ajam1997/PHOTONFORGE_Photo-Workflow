---
# Verification Report -- 2026-04-17 (Stages 1-3 Baseline)

## Commit

```
108a6e7  feat: notify operator on Yoga 910 display during soak cycle plug/unplug
9190718  engineer: KPM-1.2 fix -- uint8 vision encoder + 512px input reduces latency to ~1.5s
ff5cb9b  engineer: fix Florence-2 caption quality + file rename + XMP original filename
```

Triggering commits for this verification pass:
- `ff5cb9b` -- naming.py, darktable_bridge.py, pipeline.py (KPM-1.2, KPM-1.3 triggered)
- `9190718` -- naming.py (KPM-1.2 triggered)
- `108a6e7` -- scripts/soak_cycle.py only (no src/ or models/ changes; KPM triggers not activated)

## Changed Files (src/ and models/ only, across triggering commits)

| Commit | File | Change Summary |
|--------|------|---------------|
| ff5cb9b | src/photo_workflow/naming.py | Replace <cap> task token with text prompt; add KV-cache decode path; add decoder_model_merged priority |
| ff5cb9b | src/photo_workflow/darktable_bridge.py | Add OriginalFilename to XMP template; add dup_count debug log |
| ff5cb9b | src/photo_workflow/pipeline.py | Add _rename_photo(); store original_filename in PhotoRecord.metadata |
| 9190718 | src/photo_workflow/naming.py | Add INFER_IMG_SIZE=512; add uint8 vision_encoder priority in _resolve_onnx_path() |

## BLOCKER: SSH Access Failure

> **RESOLVED 2026-04-17:** SSH access restored. New key: `~/.ssh/photonforge_yoga`. Re-trigger @verification to execute blocked tests and KPM benchmarks.

**All remote test execution (Steps 1-3) could not be performed.**

Diagnosis: The SSH public key at `~/.ssh/photonforge_yoga`
(ED25519 SHA256:tALHFuqpCYLTKwZQJBVKkaV4mRIIIC65d/FKDVj7Pls) is offered to
the Yoga 910 at `10.27.27.10` but rejected with `Permission denied (publickey,password)`.

The host is reachable (ping RTT ~33-53ms, SSH-2.0-OpenSSH_9.6p1 Ubuntu-3ubuntu13.15
confirmed in handshake). The key is not in `~/.ssh/authorized_keys` on the Yoga 910,
or `authorized_keys` was modified since the key was provisioned.

**Network:** Reachable (0% packet loss, ~43ms avg RTT)
**SSH server:** Running (OpenSSH_9.6p1 Ubuntu-3ubuntu13.15)
**Key type:** ED25519 (valid, loads cleanly)
**Auth result:** Server rejects key -- not a passphrase issue, not a local agent issue

Action required before next verification run (now resolved):
  SSH key has been updated to `photonforge_yoga`.
  Key is accepted by Yoga 910 SSH server.
  Alternatively, regenerate the key pair and re-provision.

## Step 0: Diff Analysis (from local git history)

Changed files in src/ across triggering commits: naming.py, darktable_bridge.py, pipeline.py.

KPM trigger mapping:
- naming.py changed --> KPM-1.2 TRIGGERED (inference speed <= 2.5s/image)
- pipeline.py changed --> KPM-1.3 TRIGGERED (RSS <= 1.5 GB)
- ingest.py NOT changed --> KPM-1.1 NOT TRIGGERED

## Step 1: Test Results

**BLOCKED -- SSH access failure. Tests could not be run on Yoga 910.**

Expected test files for this diff scope (full suite per Stages 1-3 baseline pass):

| Test File | Module | Tests | Status |
|-----------|--------|-------|--------|
| test_cartridge.py | cartridge.py | 4 | NOT EXECUTED |
| test_composition.py | composition.py | 5 | NOT EXECUTED |
| test_darktable.py | darktable_bridge.py | 9 | NOT EXECUTED |
| test_dedup.py | dedup.py | 4 | NOT EXECUTED |
| test_exposure.py | exposure.py | 5 | NOT EXECUTED |
| test_grouping.py | grouping.py | 4 | NOT EXECUTED |
| test_ingest.py | ingest.py | 4 | NOT EXECUTED |
| test_memory.py | pipeline.py | (slow mark) | NOT EXECUTED |
| test_naming.py | naming.py | 8 | NOT EXECUTED |
| test_pipeline.py | pipeline.py | 10 | NOT EXECUTED |
| test_sharpness.py | sharpness.py | 7 | NOT EXECUTED |
| test_soak_cycle.py | soak_cycle.py | 10 | NOT EXECUTED |

Total tests in suite: 70 (excludes test_memory.py slow-marked tests pending count).

Last known test state (from commit history): commit `ff5cb9b` message reports
"all 8 naming tests green"; commit `33a8d52` (Stage 3) reports "22 tests passing".
This is engineer-stated evidence, not @verification-measured evidence.

### Pre-existing Failure Note

`test_memory.py` is expected to be excluded or have limited coverage if
`memory_profiler` is not installed. However, inspection of the current
`test_memory.py` source confirms it does NOT import `memory_profiler` --
it uses the stdlib `resource` module. The pre-existing failure referenced in
the trigger brief may have been from an older revision. Current HEAD
`test_memory.py` uses `resource.getrusage()` and marks the slow test with
`@pytest.mark.slow`. This needs live execution to confirm behavior.

## Step 2: KPM Benchmarks

### KPM-1.2 -- Inference Speed (target: <= 2.5s/image)

**BLOCKED -- SSH access failure.**

Supporting evidence from git history (engineer-reported, not @verification-measured):

- Commit `9190718` message: "Measured end-to-end: 1525ms on Yoga 910 -- passes
  KPM-1.2 (<=2.5s) with margin."
- Commit `85ac9ae` message: "Validation of KPMs KPM-1.2 now passes"
- The uint8 vision encoder path and 512px resize are now in HEAD source code.
  The INFER_IMG_SIZE=512 constant and `vision_encoder_uint8.onnx` priority in
  `_resolve_onnx_path()` are confirmed present in the diff.

**Status: NOT EXECUTED by @verification. Engineer-reported ~1525ms. Formal
measurement deferred pending SSH access restoration.**

### KPM-1.3 -- Memory RSS (target: RSS <= 1.5 GB / 1,572,864 KB)

**BLOCKED -- SSH access failure.**

`/usr/bin/time -v` command against the full pipeline over tests/fixtures/
could not be run. No RSS measurement obtained.

**Status: NOT EXECUTED by @verification. No prior measurement on record.**

### KPM-1.1 -- Ingest Bandwidth (target: >= 500 MB/s USB 3.0)

NOT TRIGGERED by this diff (ingest.py not changed).

**Status: NOT TRIGGERED**

## Step 3: New Tests Generated

Checked coverage for functions added in the triggering commits:

- `_resolve_onnx_path()` -- extended to handle `vision_encoder` uint8 priority.
  `test_naming.py` contains `test_missing_model_falls_back_to_stem()` which
  exercises path resolution. Targeted coverage for the new uint8 branch could
  not be verified without live execution.

- `_build_empty_past_kv()` -- commit `ff5cb9b` message states "Add 2 new tests:
  `_build_empty_past_kv` shape/dtype validation, `_caption_to_slug` edge cases".
  These are confirmed present in HEAD `test_naming.py` via local inspection:
  `test_build_empty_past_kv_returns_zero_tensors` and
  `test_caption_to_slug_strips_task_prefix`.

- `_rename_photo()` (added to pipeline.py in ff5cb9b) -- no test function named
  `test_rename_photo` found in `test_pipeline.py`. Pipeline integration tests
  (`test_integration_naming_fallback`, `test_integration_xmp_sidecars`) may
  exercise this path indirectly but direct unit test is not present.

**New test needed:** `tests/test_pipeline.py::test_rename_photo` to directly
test the `_rename_photo()` function added in `ff5cb9b`. Cannot write and
execute without SSH access.

**New tests generated this run: NONE** (SSH access required to write and
immediately run per agent protocol).

## Step 4: Failures

No failures recorded (no tests executed). See BLOCKER section.

## Step 5: XMP Output Evidence (supplementary)

The repo contains validated XMP sidecars in
`docs/ValidationReports/PhotoWorkFlowTestOutput/` produced during prior
Yoga 910 runs. Inspection of `DSC04937.xmp` shows:

```xml
<photon:SemanticName>answering-does-not-require-reading</photon:SemanticName>
```

This is the pre-fix bad caption from before `ff5cb9b`. These XMP files were
produced by a pre-fix pipeline run and are NOT representative of current HEAD
behavior. The caption quality fix (text prompt replacing `<cap>` token 51269)
was committed at `ff5cb9b` after these outputs were generated.

The OriginalFilename XMP field added in `ff5cb9b` is also absent from these
files, confirming they predate the fix.

## KPM Results Summary

| KPM | Target | Measured | Status |
|-----|--------|----------|--------|
| KPM-1.1 | >= 500 MB/s | N/A | NOT TRIGGERED |
| KPM-1.2 | <= 2.5s/image | ~1525ms (engineer-reported, not verified) | BLOCKED-SSH |
| KPM-1.3 | RSS <= 1.5 GB | Not measured | BLOCKED-SSH |

## Overall Status

**BLOCKED-SSH -- All live measurements pending SSH access restoration.**

The previous ED25519 key was rejected by the Yoga 910 SSH server; replaced with `photonforge_yoga`.
No pytest runs, KPM benchmarks, or new test writes could be executed.

### Required Actions Before Next Verification Run

1. **@engineer / @devops**: Restore SSH access. Verify
   `~/.ssh/authorized_keys` on Yoga 910 contains the
   Previous key public key fingerprint (now replaced with `photonforge_yoga`)
   `SHA256:tALHFuqpCYLTKwZQJBVKkaV4mRIIIC65d/FKDVj7Pls`.

2. **@engineer**: Add a unit test for `_rename_photo()` in
   `tests/test_pipeline.py`. This function was added in `ff5cb9b`
   and has no direct test coverage.

3. **Re-trigger @verification** after SSH access is restored to execute:
   - Full pytest suite (70 tests across 12 test files)
   - KPM-1.2 benchmark (`generate_name()` timing against a fixture image)
   - KPM-1.3 benchmark (`/usr/bin/time -v` RSS measurement via pipeline run)

---
*Generated by @verification agent (claude-sonnet-4-6) on 2026-04-17.*
*This is the first formal verification report for PHOTONForge (Stages 1-3 baseline).*
