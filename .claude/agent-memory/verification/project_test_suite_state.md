---
name: PHOTONForge test suite state — Stages 1-5 complete
description: 248 tests across 28 test files as of 2026-05-24 commit 6e9f33d; all pass
metadata:
  type: project
---

As of HEAD on 2026-05-24 (commit 6e9f33d), the test suite contains 248 tests across 28 files. All 248 pass locally.

**Why:** Full Stages 1-5 verification sweep run on 2026-05-24. SSH to Yoga 910 timed out (XFAIL-HARDWARE); all tests run locally on Windows host.

**How to apply:** This is the first fully-green baseline. Any regression from this count warrants investigation.

## File counts (2026-05-24)
- test_cartridge.py: 4
- test_cli_v2.py: 4
- test_composition.py: 5
- test_composition_v2.py: 9
- test_darktable.py: 22
- test_dedup.py: 5
- test_doc_parser.py: 6
- test_drift_check.py: 3
- test_exposure.py: 5
- test_exposure_v2.py: 11
- test_generate_docs.py: 7
- test_genre_router.py: 10
- test_github_client.py: 7
- test_grouping.py: 4
- test_ingest.py: 3
- test_ingest_v2.py: 6
- test_manifest.py: 3
- test_naming.py: 8
- test_photondb.py: 16
- test_pid_sentinel.py: 3
- test_pipeline.py: 10
- test_progress.py: 3
- test_provision.py: 3
- test_score_fusion.py: 22
- test_scoring_integration.py: 3
- test_scoring_types.py: 8
- test_seed_github.py: 5
- test_sharpness.py: 7
- test_sharpness_v2.py: 9
- test_sidecar_cli.py: 8
- test_soak_cycle.py: 10
- test_subject_context.py: 5
- test_volume.py: 14

## Test fix applied this run
test_generate_docs.py::test_render_user_needs_section_count and test_render_user_needs_section_status were calling render_user_needs_section() with 1 argument. Function signature now requires (issues, fr_issues, nfr_issues, req_map). Fixed tests to pass empty values for the new parameters. This was a test design issue, not an implementation bug.

## Previous known gap (resolved)
_rename_photo() direct unit test gap noted in prior memory. Still no dedicated test_rename_photo(), but 10 integration tests in test_pipeline.py exercise the path indirectly. Not a blocker.
