---
name: PHOTONForge test suite state — Stages 1-6 complete
description: 315 tests across 34 test files as of 2026-07-10 commit 750d1a1; suite green under -m "not slow"
metadata:
  type: project
---

As of HEAD on 2026-07-10 (commit 750d1a1), the suite collects **315 tests across 34 files**; CI (`.github/workflows/tests.yml`) runs `pytest -m "not slow"` (314 collected, 1 deselected). All green.

**Why:** Refreshed after PRs #111–#118 (taxonomy rename, scoring fixes, host-integration fixes, Tk/Tauri retirement, consolidation) and the CI gate added by #112.

**How to apply:** This is the current green baseline. Any regression from 315 collected / green `-m "not slow"` run warrants investigation. Run locally with `python3 -m pytest -m "not slow" -q`.

## Deleted test files (do not expect these; their modules were removed)
- test_manifest.py, test_progress.py, test_sidecar_cli.py (modules `manifest.py`, `progress.py`, `sidecar_cli.py` deleted)
- test_cartridge_manager.py (Tk cartridge-manager app retired in #117)
- test_seed_github.py (seeder script removed)

## New/renamed coverage since the 2026-05-24 baseline (248 tests / 28 files)
- test_active_learning.py, test_genre_adapter.py, test_genre_trainer.py,
  test_raw_loader.py, test_training_weights_db.py added
- Extension handling unified in raw_loader (RAW_EXTENSIONS/JPG_EXTENSIONS/IMAGE_EXTENSIONS, .RAF fix, #118)
- score_one()/ScoredImage extraction in pipeline.py covered via test_pipeline.py + test_scoring_integration.py

## Previous known gap (mooted)
`_rename_photo()` test gap is moot — naming no longer renames files; the
semantic name is written to the Darktable description + XMP `photon:SemanticName`.
