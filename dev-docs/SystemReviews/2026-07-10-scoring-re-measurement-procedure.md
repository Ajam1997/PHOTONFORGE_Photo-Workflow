# Scoring Re-Measurement Procedure — Post-Fix Baseline Comparison

**Status:** PROCEDURE DEFINED — awaiting Yoga hardware run
**Date:** 2026-07-10
**Owner:** @verification (execution) / @systems_lead (acceptance)
**Fulfils:** 2026-06-19 scoring-methodology-audit step 4 ("re-measure after
fixes") and release-1 readiness checklist item 1 ("freeze scoring; clean
re-score a reference shoot as the behavior baseline").

The June audit measured 6,716 scored rows and found the aesthetic signal dead
(constant 0.5), symmetry dead, color_contrast aliased, and a compressed master
distribution with zero 5-star frames. PRs #114–#118 fixed the wiring (working
CLIP aesthetic head with degenerate-model self-check, real colorfulness,
2-D sharpness contrast, YOLO NMS, drop-key renormalization, min-gate master,
hybrid percentile stars). This procedure re-measures the same statistics on
current `main` so the fixes are *demonstrated*, not assumed. It needs the
Yoga 910 (or any machine with the cartridge + provisioned models).

## June 2026 baseline (the numbers to beat)

From the [2026-06-19 audit](2026-06-19-scoring-methodology-audit.md),
n = 6,716:

- Master score: mean **0.525**, std **0.119** (min 0.178, median 0.530, max 0.847).
- Star histogram: **{1: 194, 2: 2623, 3: 3465, 4: 434, 5: 0}** — zero 5-star.
- Dead sub-scores (std < 0.05): aesthetic_clip (0.000), face_exposure,
  expression_proxy, behavior_proxy (all 0.5 sentinels), symmetry (0.033);
  color_contrast identical to subject_isolation.

## Procedure

1. **Pick the reference shoot.** Use the same large folder the audit drew from
   (preferred: the full cartridge corpus, or ICELAND as the hard single
   folder). Record folder name, frame count, and `git rev-parse HEAD`.
2. **Clean re-score on current main** (models provisioned, cartridge
   `training_weights.db` present if that's the production config — record
   which):

   ```bash
   photo-workflow score --db <cartridge>/photonforge.db \
     --folder <FOLDER> --source-dir <cartridge>/<FOLDER> \
     --model-dir <repo>/models --force --json-progress > rescore.log
   ```

3. **Export the master/sub-score distributions** from `photonforge.db`
   (`photos` table). Master stats:

   ```sql
   SELECT COUNT(*)                                   AS n,
          ROUND(MIN(master_score), 3)                AS min,
          ROUND(AVG(master_score), 3)                AS mean,
          ROUND(MAX(master_score), 3)                AS max,
          ROUND(SQRT(AVG(master_score*master_score)
                     - AVG(master_score)*AVG(master_score)), 3) AS std
   FROM photos
   WHERE folder = '<FOLDER>' AND is_duplicate = 0
     AND stages LIKE '%score%';
   ```

   Per-sub-score spread (repeat per key, or loop in Python):

   ```sql
   SELECT ROUND(AVG(v), 3) AS mean,
          ROUND(SQRT(AVG(v*v) - AVG(v)*AVG(v)), 3) AS std
   FROM (SELECT CAST(json_extract(sub_scores, '$.aesthetic_clip') AS REAL) AS v
         FROM photos
         WHERE folder = '<FOLDER>' AND is_duplicate = 0
           AND sub_scores != '' AND json_extract(sub_scores, '$.aesthetic_clip') IS NOT NULL);
   ```

   Keys to sweep: `aesthetic_clip, symmetry, color_contrast, subject_isolation,
   face_exposure, expression_proxy, behavior_proxy, eye_sharpness,
   subject_sharpness, sharpness_contrast, composition_rot, leading_lines,
   negative_space, balance, zone_entropy, dynamic_range, exposure_overall,
   highlight_clip`. Note: stored JSON still contains the 0.5 sentinels for
   dropped signals (no-face frames etc.) — additionally compute face_exposure /
   expression_proxy std restricted to frames where
   `json_extract(genres,'$.subject') = 'people'`.

   Hard-reject count:

   ```sql
   SELECT COUNT(*) FROM photos
   WHERE folder = '<FOLDER>' AND json_extract(genres, '$.hard_reject') = 1;
   ```

4. **Star histogram.** Stars are not persisted in photondb (they live in
   Darktable); recompute them from the master distribution with the shipped
   functions:

   ```python
   import sqlite3, json, collections
   from photo_workflow.score_fusion import hybrid_star, _RATING_ABS_FLOOR
   conn = sqlite3.connect("<cartridge>/photonforge.db")
   rows = conn.execute(
       "SELECT master_score, genres FROM photos "
       "WHERE folder=? AND is_duplicate=0 AND stages LIKE '%score%'",
       ("<FOLDER>",)).fetchall()
   def hr(g):
       try: return bool(json.loads(g or "{}").get("hard_reject"))
       except Exception: return False
   kept = sorted(m for m, g in rows if not hr(g) and m >= _RATING_ABS_FLOOR)
   hist = collections.Counter(hybrid_star(m, hr(g), kept) for m, g in rows)
   print(dict(sorted(hist.items())))
   ```

5. **Compare against the June baseline** table above; fill in the Results
   section; post the numbers as a KPM-style comment via
   `scripts/github_comment.py`.

## Acceptance criteria

- [ ] `aesthetic_clip` std **> 0.05** (the head discriminates; June: 0.000).
- [ ] Master-score std **increases** vs 0.119 (range decompression).
- [ ] **5-star count nonzero**, or — if the folder genuinely has no top-decile
      keepers — the percentile banding verified directly (top 10 % of keepers
      map to 5★ in the recomputed histogram).
- [ ] **No sub-score frozen at a constant** (std < 0.05) other than documented
      sentinels evaluated on frames where the signal applies; `color_contrast`
      no longer identical to `subject_isolation`.
- [ ] Hard-reject rate sane (spot-check a sample of rejects for genuine
      technical failures).

Failure of any criterion reopens the corresponding audit finding rather than
shipping the baseline.

## Results

**TODO — pending hardware run.** Record: date, HEAD commit, folder, n,
master stats, sub-score spread table, star histogram, hard-reject count,
pass/fail per criterion, and any anomalies.

**Next action:** @verification to execute on the Yoga 910 once the cartridge
is connected; results land in this doc + an Issue comment.

via: @systems_lead
