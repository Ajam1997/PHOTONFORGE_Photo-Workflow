# Color-Label Semantics Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop color labels from duplicating what stars already say; make each color carry orthogonal *workflow* information the star axis cannot express.

**Architecture:** Today `stars_to_color_label` maps 5★→blue, 4★→green, ≤1★→yellow — pure redundancy with the rating. The min-gate in `_compute_master_score` already computes exactly the information a photographer wants next: *which bucket (technical vs aesthetic) capped this photo*. We expose the two bucket scores on `FusionResult`, then assign labels as reason codes: **red = duplicate** (unchanged), **yellow = needs human input** (genre ambiguity / review flags), **blue = AI-rescue candidate** (strong aesthetics capped by a technical failure that Darktable 5.6's neural restore can plausibly fix), **green = portfolio pick** (top of shoot, technically clean), **purple = untouched user flag** (unchanged, never auto-written).

**Tech Stack:** Python 3.11, numpy, pytest. No Lua changes required — the applicator already consumes an integer `color_label` and never writes purple.

## Global Constraints

- PURPLE (`_DT_PURPLE = 4`) stays reserved for the user; the pipeline must never emit it (`applicator.lua` also refuses it today — keep both guards).
- RED stays the duplicate marker set by the dedup step (`applicator.lua:114-117`); the score step must never emit red.
- Hard rejects keep the DT reject flag and **no** color label (existing behavior).
- The Lua protocol is unchanged: `color_label` is an int in {-1, 0, 1, 2, 3} in score-step JSON records.
- PRs that change code must update affected docs (docs-impact matrix in `dev-docs/architecture/doc-maintenance-protocol.md`); the label legend must land in `dev-docs/getting-started.md` and `dev-docs/training-loop-guide.md`.

## New Label Semantics (the contract)

| Label | Meaning | Set by | Cleared by |
|---|---|---|---|
| RED | Near-duplicate of a kept frame | dedup step | re-run dedup |
| YELLOW | Needs human input: genre `needs_review`, or caption/tag inconsistency (future — see the 2026-07-11 caption-tag-consistency plan, which reuses this label) | score step | re-score after correction |
| GREEN | Portfolio pick: 5★ after per-shoot percentile AND technically clean (`technical ≥ 0.55`) | score step (final re-rating pass) | re-score |
| BLUE | AI-rescue candidate: aesthetic bucket ≥ 0.55 but technical bucket capped the master (gap ≥ 0.15) and failure mode is restorable (soft/misfocused/noise — NOT global motion blur) | score step | re-score |
| PURPLE | User's own mark (e.g. mark-for-edit/export) | user only | user only |

Decision rationale recorded here for future readers:
- Blue targets Darktable 5.6's neural restore (denoise / raw denoise / upscale). Global motion blur is excluded because restore models don't fix it; those frames are hard-rejected anyway when severe.
- Yellow absorbs the `photon|needs_review` signal so review triage is visible in the lighttable without opening the tag panel. The tag remains (filtering works better with tags); the label is the at-a-glance layer.
- Green is deliberately stricter than "5 stars": a 5★ frame that is 5★ only because the shoot was weak (percentile rating) but technically soft should NOT be green — green means "safe to spend editing time on".

---

### Task 1: Expose bucket scores on FusionResult

**Files:**
- Modify: `src/photo_workflow/scoring_types.py` (FusionResult: two new defaulted fields)
- Modify: `src/photo_workflow/score_fusion.py:306-360` (`_compute_master_score` returns buckets; `fuse_scores` stores them)
- Test: `tests/test_score_fusion.py`

**Interfaces:**
- Produces: `FusionResult.technical_score: float | None` and `FusionResult.aesthetic_score: float | None` (None when the bucket had no weighted signals — mirrors the internal None semantics).
- Produces: `_compute_master_score(...) -> tuple[float, float | None, float | None]` (master, technical, aesthetic). All callers are inside `score_fusion.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_score_fusion.py (append; reuse the module's existing fixture helpers
# for SharpnessScores/CompositionScores/ExposureScores/GenreResult construction)
def test_fusion_exposes_bucket_scores(sharp_ok, comp_ok, expo_ok, genre_wildlife):
    from photo_workflow.score_fusion import fuse_scores
    result = fuse_scores(sharp_ok, comp_ok, expo_ok, genre_wildlife, aesthetic=0.8)
    assert result.technical_score is not None
    assert result.aesthetic_score is not None
    assert abs(result.master_score
               - min(result.technical_score, result.aesthetic_score)) < 1e-4
```

(If the existing test module has no such fixtures, build them inline exactly as the nearest existing `fuse_scores` test does — copy its construction verbatim.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_score_fusion.py::test_fusion_exposes_bucket_scores -v`
Expected: FAIL with AttributeError (`technical_score`)

- [ ] **Step 3: Implement**

`scoring_types.py` — append to `FusionResult` (after `needs_review: bool = False`):

```python
    # min-gate bucket scores (None = bucket had no weighted signals)
    technical_score: float | None = None
    aesthetic_score: float | None = None
```

`score_fusion.py` — change `_compute_master_score`'s tail:

```python
    technical = tech_num / tech_den if tech_den > 0 else None
    aesthetic = aes_num / aes_den if aes_den > 0 else None
    if technical is None and aesthetic is None:
        return 0.0, None, None
    if technical is None:
        master = aesthetic
    elif aesthetic is None:
        master = technical
    else:
        master = min(technical, aesthetic)
    return max(0.0, min(1.0, master)), technical, aesthetic
```

and in `fuse_scores`:

```python
    master_score, technical, aesthetic_bucket = _compute_master_score(
        sub_scores, genre, weight_profiles, drop_keys=tuple(drop))
    ...
    return FusionResult(
        ...,
        technical_score=None if technical is None else round(technical, 4),
        aesthetic_score=None if aesthetic_bucket is None else round(aesthetic_bucket, 4),
    )
```

- [ ] **Step 4: Run the fusion tests**

Run: `pytest tests/test_score_fusion.py -v`
Expected: PASS (existing tests unaffected — the function's master value is unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/photo_workflow/scoring_types.py src/photo_workflow/score_fusion.py tests/test_score_fusion.py
git commit -m "feat(scoring): expose technical/aesthetic bucket scores on FusionResult"
```

---

### Task 2: Reason-code label classifier

**Files:**
- Modify: `src/photo_workflow/score_fusion.py` (new `label_for` function; deprecate `stars_to_color_label` and `_score_to_color_label`)
- Test: `tests/test_score_fusion.py`

**Interfaces:**
- Consumes: `FusionResult` with bucket scores (Task 1).
- Produces: `label_for(fusion: FusionResult, final_stars: int) -> int` — returns `_DT_YELLOW` / `_DT_BLUE` / `_DT_GREEN` / `_DT_NONE`. Called with the FINAL (hybrid) star, so green reflects the per-shoot percentile.
- Thresholds as module constants: `_RESCUE_AES_MIN = 0.55`, `_RESCUE_GAP_MIN = 0.15`, `_CLEAN_TECH_MIN = 0.55`.

- [ ] **Step 1: Write the failing tests**

```python
def _fusion(subject="wildlife", tech=0.7, aes=0.7, needs_review=False,
            hard_reject=False, blur="sharp"):
    from photo_workflow.scoring_types import FusionResult
    return FusionResult(
        master_score=min(tech, aes), subject=subject, subject_confidence=0.9,
        photo_type="scenic", type_confidence=0.9,
        sub_scores={"blur_type": blur}, hard_reject=hard_reject,
        hard_reject_reason="", star_rating=3, color_label=-1,
        needs_review=needs_review, technical_score=tech, aesthetic_score=aes)


def test_label_yellow_for_needs_review():
    from photo_workflow.score_fusion import label_for, _DT_YELLOW
    assert label_for(_fusion(needs_review=True), final_stars=3) == _DT_YELLOW


def test_label_blue_for_rescue_candidate():
    from photo_workflow.score_fusion import label_for, _DT_BLUE
    # gorgeous but soft: aesthetic 0.70, technical 0.35 capped the master
    assert label_for(_fusion(tech=0.35, aes=0.70), final_stars=2) == _DT_BLUE


def test_label_not_blue_for_global_motion_blur():
    from photo_workflow.score_fusion import label_for, _DT_BLUE
    f = _fusion(tech=0.35, aes=0.70, blur="motion_global")
    assert label_for(f, final_stars=2) != _DT_BLUE


def test_label_green_only_for_clean_five_star():
    from photo_workflow.score_fusion import label_for, _DT_GREEN, _DT_NONE
    assert label_for(_fusion(tech=0.60, aes=0.62), final_stars=5) == _DT_GREEN
    # 5-star of a weak shoot but technically soft: not green
    assert label_for(_fusion(tech=0.40, aes=0.62), final_stars=5) == _DT_NONE


def test_label_none_for_hard_reject_and_midfield():
    from photo_workflow.score_fusion import label_for, _DT_NONE
    assert label_for(_fusion(hard_reject=True), final_stars=1) == _DT_NONE
    assert label_for(_fusion(tech=0.5, aes=0.5), final_stars=3) == _DT_NONE
```

Note: `blur_type` is not in the real `sub_scores` dict (it lives on `SharpnessScores`); therefore `label_for` must take the blur type from the sub-score dict only if present, with the pipeline passing it explicitly — see Step 3 signature (`blur_type` parameter with default `""`), and adjust the tests to pass `blur_type="motion_global"` instead of stuffing it into sub_scores. Keep the FusionResult helper minimal.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_score_fusion.py -k label_for -v`
Expected: FAIL with ImportError (`label_for`)

- [ ] **Step 3: Implement**

```python
# score_fusion.py (near stars_to_color_label)
_RESCUE_AES_MIN = 0.55   # aesthetic bucket floor for a rescue candidate
_RESCUE_GAP_MIN = 0.15   # how much the technical bucket must lag the aesthetic
_CLEAN_TECH_MIN = 0.55   # technical floor for a "portfolio pick" green


def label_for(fusion: FusionResult, final_stars: int, blur_type: str = "") -> int:
    """Reason-code color label (orthogonal to stars).

    YELLOW  needs human input (genre ambiguity / review flags)
    BLUE    AI-rescue candidate: aesthetics capped by a restorable technical fault
    GREEN   portfolio pick: 5-star AND technically clean
    none    everything else. RED (duplicates) is set by dedup; PURPLE is user-only.
    """
    if fusion.hard_reject:
        return _DT_NONE
    if fusion.needs_review:
        return _DT_YELLOW
    tech, aes = fusion.technical_score, fusion.aesthetic_score
    if (
        tech is not None and aes is not None
        and aes >= _RESCUE_AES_MIN
        and (aes - tech) >= _RESCUE_GAP_MIN
        and blur_type != "motion_global"
    ):
        return _DT_BLUE
    if final_stars >= 5 and tech is not None and tech >= _CLEAN_TECH_MIN:
        return _DT_GREEN
    return _DT_NONE
```

Mark the old mappers deprecated (do not delete yet — the legacy fallback path in the score command still uses `stars_to_color_label` until Task 3):

```python
def stars_to_color_label(stars: int, hard_reject: bool = False) -> int:
    """DEPRECATED: star-redundant mapping, replaced by label_for (reason codes)."""
```

- [ ] **Step 4: Run tests, commit**

Run: `pytest tests/test_score_fusion.py -v` — Expected: PASS

```bash
git add src/photo_workflow/score_fusion.py tests/test_score_fusion.py
git commit -m "feat(scoring): reason-code color labels (label_for)"
```

---

### Task 3: Pipeline emits reason-code labels

**Files:**
- Modify: `src/photo_workflow/pipeline.py:487-696` (score command: live emit + hybrid re-rating pass; legacy fallback keeps no label)
- Modify: `src/photo_workflow/score_fusion.py` (`fuse_scores` line 506: stop calling `_score_to_color_label`; store `label_for(...)` result — but note `fuse_scores` does not know final stars, so store the PROVISIONAL label and document it)
- Test: `tests/test_pipeline_labels.py`

**Interfaces:**
- Consumes: `label_for` (Task 2), `absolute_star`/`hybrid_star` (existing).
- Produces: score-step JSON records where `color_label` follows the new contract. The re-rating pass must re-emit when EITHER the star OR the label changed (today it re-emits only on star change at `pipeline.py:687`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_labels.py
# Integration-lite: drive the two emit sites' label logic directly.
from photo_workflow.score_fusion import label_for, _DT_BLUE


def test_reemit_when_label_changes_even_if_stars_same():
    # Simulates the re-rating pass guard: prov label none -> final green
    prov_stars, final_stars = 5, 5
    f = __import__("tests.test_score_fusion", fromlist=["_fusion"])._fusion(
        tech=0.6, aes=0.62)
    prov_label = label_for(f, prov_stars)
    final_label = label_for(f, final_stars)
    # identical here — the real assertion is on the pipeline guard, below
    assert (final_stars != prov_stars) or (final_label != prov_label) or True
```

The meaningful test is the guard change itself; simplest honest check is a unit test of the extracted guard. Extract it:

```python
# pipeline.py
def _rerate_should_emit(prov_stars: int, stars: int, prov_label: int, label: int) -> bool:
    return stars != prov_stars or label != prov_label
```

```python
def test_rerate_guard():
    from photo_workflow.pipeline import _rerate_should_emit
    assert not _rerate_should_emit(3, 3, -1, -1)
    assert _rerate_should_emit(3, 4, -1, -1)
    assert _rerate_should_emit(5, 5, -1, 2)   # label appeared: must re-emit
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_labels.py -v`
Expected: FAIL with ImportError (`_rerate_should_emit`)

- [ ] **Step 3: Implement the pipeline changes**

In the score command:

1. Live emit (line ~612): replace `color_label=stars_to_color_label(stars, False)` with `color_label=label_for(fusion, stars, blur_type=scored.sharpness.blur_type)`.
2. Buffer (`rated.append`, line ~621): also store `"prov_label": <that label>, "blur_type": scored.sharpness.blur_type, "tech": fusion.technical_score, "aes": fusion.aesthetic_score, "needs_review_flag": fusion.needs_review, "hard_reject": False`.
3. Re-rating pass (line ~686): rebuild a minimal label input and guard:

```python
        for item in rated:
            stars = hybrid_star(item["master"], False, kept_sorted)
            label = label_for_values(
                needs_review=item["needs_review"], tech=item["tech"],
                aes=item["aes"], final_stars=stars, blur_type=item["blur_type"])
            if not _rerate_should_emit(item["prov"], stars, item["prov_label"], label):
                continue
            emit("score", item["filename"], ..., stars=stars, color_label=label, ...)
```

To avoid reconstructing a FusionResult, refactor `label_for` into a thin wrapper over a values-based core:

```python
# score_fusion.py
def label_for_values(*, needs_review: bool, tech: float | None, aes: float | None,
                     final_stars: int, blur_type: str = "",
                     hard_reject: bool = False) -> int:
    if hard_reject:
        return _DT_NONE
    if needs_review:
        return _DT_YELLOW
    if (tech is not None and aes is not None and aes >= _RESCUE_AES_MIN
            and (aes - tech) >= _RESCUE_GAP_MIN and blur_type != "motion_global"):
        return _DT_BLUE
    if final_stars >= 5 and tech is not None and tech >= _CLEAN_TECH_MIN:
        return _DT_GREEN
    return _DT_NONE


def label_for(fusion: FusionResult, final_stars: int, blur_type: str = "") -> int:
    return label_for_values(
        needs_review=fusion.needs_review, tech=fusion.technical_score,
        aes=fusion.aesthetic_score, final_stars=final_stars,
        blur_type=blur_type, hard_reject=fusion.hard_reject)
```

4. Legacy fallback path (line ~643): emit `color_label=-1` (no reason codes without bucket data).
5. `fuse_scores` (line ~506): set `color_label=label_for(<self>, star_rating, blur_type=sharpness.blur_type)` so `FusionResult.color_label` follows the new contract for non-CLI callers (`AnalysisPipeline.run`).

- [ ] **Step 4: Run everything**

Run: `pytest -m "not slow" -q`
Expected: PASS. Fix any test that asserted the old star-redundant labels — update the assertion to the new contract, not the code.

- [ ] **Step 5: Commit**

```bash
git add src/photo_workflow/pipeline.py src/photo_workflow/score_fusion.py tests/test_pipeline_labels.py
git commit -m "feat(scoring): pipeline emits reason-code color labels"
```

---

### Task 4: Retire dead mappers + docs

**Files:**
- Modify: `src/photo_workflow/score_fusion.py` (delete `stars_to_color_label` and `_score_to_color_label` once no caller remains; `grep -rn "stars_to_color_label\|_score_to_color_label" src/ tests/` must come back empty outside score_fusion.py first)
- Modify: `dev-docs/getting-started.md`, `dev-docs/training-loop-guide.md` (label legend table from "New Label Semantics" above)
- Modify: `lua/photonforge/applicator.lua:126-136` (comment only: update the "Automatic scoring colors" note to the reason-code meanings)

- [ ] **Step 1: Verify no remaining callers, delete, run suite**

Run: `pytest -m "not slow" -q` — Expected: PASS

- [ ] **Step 2: Update docs + Lua comment, commit**

```bash
git add -A
git commit -m "docs: color labels are reason codes; remove deprecated star-redundant mappers"
```

---

## Self-Review Notes

- The applicator needs zero functional changes: ints in {-1,0,1,2,3} flow through, purple already refused, red already dedup-only.
- Threshold values (0.55/0.15) are first guesses calibrated to the documented master range (~0.25–0.65 under the min-gate, see `_RATING_ABS_FLOOR` comment block). Expect one tuning pass on a real shoot; that is a constant tweak, not a design change.
- Interaction with the caption-tag-consistency plan: that plan also emits YELLOW via `needs_review` — no protocol conflict, it reuses this exact path.
