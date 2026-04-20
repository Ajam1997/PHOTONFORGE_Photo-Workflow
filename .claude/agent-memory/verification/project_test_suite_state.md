---
name: PHOTONForge test suite state at Stages 1-3 baseline
description: 70 tests across 12 test files as of 2026-04-17; _rename_photo() has no direct unit test
type: project
---

As of HEAD on 2026-04-17 (commit 108a6e7), the test suite contains:

- test_cartridge.py: 4 tests
- test_composition.py: 5 tests
- test_darktable.py: 9 tests
- test_dedup.py: 4 tests
- test_exposure.py: 5 tests
- test_grouping.py: 4 tests
- test_ingest.py: 4 tests
- test_memory.py: slow-marked, uses stdlib resource module (NOT memory_profiler)
- test_naming.py: 8 tests (includes test_build_empty_past_kv_returns_zero_tensors, test_caption_to_slug_strips_task_prefix added in ff5cb9b)
- test_pipeline.py: 10 integration tests
- test_sharpness.py: 7 tests
- test_soak_cycle.py: 10 tests

Coverage gap identified: `_rename_photo()` added to pipeline.py in commit ff5cb9b
has no direct unit test. The 10 pipeline integration tests may exercise this path
indirectly, but no `test_rename_photo` function exists.

**Why:** The function was added in ff5cb9b but tests/ changes in that commit only
added test_naming.py tests for the naming module, not pipeline.py.

**How to apply:** When verifying pipeline.py changes, check for _rename_photo coverage.
Flag if still missing after next @engineer session.

Pre-existing concern: prior docs mentioned memory_profiler as potentially missing.
Current test_memory.py does NOT use memory_profiler — uses stdlib resource module.
This concern is resolved in current HEAD.
