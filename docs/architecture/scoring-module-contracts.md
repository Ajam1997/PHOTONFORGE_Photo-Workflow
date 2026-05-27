# Scoring System Module Contracts

**Status:** approved — interfaces locked; implementation pending
**Date:** 2026-05-26
**Supersedes:** the monolithic `score_fusion.py` design

## Background

The two-axis tag system (16 Subjects × 12 Photo Types, per
[photo-tag-taxonomy-research-brief.md](../research/photo-tag-taxonomy-research-brief.md))
invalidates the current single-genre score-fusion design. This document
specifies the modularized replacement.

The architecture is **Approach A + C** from the design discussion:

- **Approach A (axis role separation):** Subject is the *region router* — it
  picks which regions and ROIs matter. Type is the *aesthetic weighter* — it
  picks which sub-scores get what weight. The two axes never co-weight the
  same sub-score.
- **Approach C (technical / aesthetic split):** The fusion shape becomes two
  layered scores — a technical floor (genre-agnostic, gateable) and an
  aesthetic score (Type-weighted). Combined at the top with a swappable
  strategy (default: `min`).

## Resolved design questions

- **Per-Type weight storage:** SQLite in the user library, consistent with
  the rest of the runtime-mutable state. Export/import handled by the
  cartridge manager utility, not the scoring code. `aesthetic_weighter` is
  the sole reader and writer of the weight tables.
- **Aesthetic models in v1:** NIMA (idealo MobileNet variant, ONNX INT8) +
  LAION CLIP-aesthetic head only. `AestheticSubScores.attributes` exists as
  the extensibility seam but stays empty in v1 — AADB-style attribute heads
  deferred until classical composition sub-scores are replaced wholesale,
  not layered on top.
- **Depth estimation:** Subject-gated. `region_router` owns the depth model
  handle and invokes it only for Subjects in {landscape, seascape,
  cityscape}. Average per-image overhead drops from +500 ms unconditional to
  ~+150 ms.
- **Florence-2 captioning:** out of scope for this refactor. Grounded
  captioning tracked separately as
  [issue #80](https://github.com/Ajam1997/PHOTONFORGE_Photo-Workflow/issues/80),
  depends on this refactor landing first.

## Module map

```
SubjectContext + GenreResult  (existing — produced upstream)
            │
            ▼
   ┌─────────────────────┐
   │ region_router       │   Subject → RegionSpec
   │   owns: Subject     │   (also owns depth model handle,
   │   prototypes        │    invoked for landscape/seascape/cityscape only)
   └─────────────────────┘
            │
            ▼
   ┌─────────────────────┐
   │ sub_scores/*        │   (image, RegionSpec) → SubScoreBundle
   │  sharpness          │
   │  exposure           │
   │  composition        │
   │  aesthetic (NIMA +  │
   │    CLIP-aesthetic)  │
   │  faces              │
   └─────────────────────┘
            │
            ▼
   ┌─────────────────────┐   ┌─────────────────────────────┐
   │ technical_gate      │   │ aesthetic_weighter          │
   │ Subject-conditional │   │ Type → weights → score      │
   │ hard gates + floor  │   │ owns: per-Type weight table │
   │                     │   │       in SQLite             │
   └─────────────────────┘   └─────────────────────────────┘
            │                         │
            └───────────┬─────────────┘
                        ▼
              ┌─────────────────────┐
              │ fusion              │  → FusionResult
              │ strategy: min /     │
              │   harmonic / wsum   │
              └─────────────────────┘
```

---

## 1. `RegionSpec` — output of `region_router`

```python
@dataclass(frozen=True)
class RegionSpec:
    """Subject-driven map of which regions matter for scoring this image.

    Produced by region_router. Consumed by every sub_scores/* module.
    All masks are uint8 in {0, 255}, same H×W as the source image.
    A field set to None means 'this region is not relevant for this Subject';
    sub-score modules MUST treat None as 'skip', not 'compute on full frame'.
    """

    subject_tag: str                          # echoes GenreResult.subject

    # Primary region (always present)
    subject_mask: np.ndarray
    subject_bbox: tuple[int, int, int, int]
    subject_area_ratio: float

    # Face/eye routing — populated when subject in {person, people, child}
    face_mask: np.ndarray | None
    eye_rois: list[tuple[int, int, int, int]]
    faces: list[FaceDetection]

    # Animal-eye routing — populated when subject in {wildlife, pet}
    animal_head_bbox: tuple[int, int, int, int] | None

    # Depth routing — populated only when subject in
    # {landscape, seascape, cityscape}. Owned and invoked by region_router.
    depth_bins: np.ndarray | None             # H×W int8, values in {0,1,2}
    depth_bin_coverage: tuple[float, float, float] | None

    # Background region (always present — complement of subject_mask)
    background_mask: np.ndarray

    # Which sub-scores this Subject wants computed. Sub-score modules use
    # this to skip work that won't be weighted downstream.
    enabled_subscores: frozenset[str]
```

---

## 2. `SubScoreBundle` — namespaced, typed sub-score outputs

```python
class BlurType(StrEnum):
    SHARP = "sharp"
    BOKEH = "bokeh"
    MOTION_SUBJECT = "motion_subject"
    MOTION_GLOBAL = "motion_global"
    MISFOCUSED = "misfocused"


class ExposureStyle(StrEnum):
    NORMAL = "normal"
    HIGH_KEY = "high_key"
    LOW_KEY = "low_key"
    SILHOUETTE = "silhouette"


@dataclass(frozen=True)
class SharpnessSubScores:
    subject: float | None
    eye_region: float | None
    background: float
    front_to_back: float | None        # populated when depth_bins present
    sharpness_contrast: float
    blur_type: BlurType
    overall: float


@dataclass(frozen=True)
class ExposureSubScores:
    zone_entropy: float
    zone_diversity: int
    dynamic_range: float
    clipping_shadows: float
    clipping_highlights: float
    midtone_density: float
    face_exposure: float | None
    style: ExposureStyle
    style_confidence: float
    overall: float


@dataclass(frozen=True)
class CompositionSubScores:
    rule_of_thirds: float
    symmetry: float
    leading_lines: float
    negative_space: float
    subject_isolation: float
    balance: float
    color_contrast: float
    overall: float


@dataclass(frozen=True)
class AestheticSubScores:
    """v1: NIMA + LAION CLIP-aesthetic only.  attributes stays empty."""
    nima_mean: float                   # normalized to 0..1
    nima_std: float                    # rating distribution std-dev
    clip_aesthetic: float              # LAION head, normalized
    attributes: dict[str, float]       # empty in v1; extensibility seam


@dataclass(frozen=True)
class FaceSubScores:
    eye_openness: list[float]
    expression_proxy: float
    closed_eyes_all: bool
    face_count: int


@dataclass(frozen=True)
class SubScoreBundle:
    sharpness: SharpnessSubScores
    exposure: ExposureSubScores
    composition: CompositionSubScores
    aesthetic: AestheticSubScores | None
    faces: FaceSubScores | None

    def as_flat_dict(self) -> dict[str, float]:
        """Lossy view for XMP serialization and debugging only.
        NOT used by aesthetic_weighter — that module reads typed fields."""
        ...
```

---

## 3. `TechnicalResult` — output of `technical_gate`

```python
@dataclass(frozen=True)
class GateCheck:
    name: str
    triggered: bool
    value: float
    threshold: float
    enabled_for_subject: bool


@dataclass(frozen=True)
class TechnicalResult:
    technical_score: float             # 0..1; multiplicative floor on master
    hard_reject: bool
    hard_reject_reason: str
    gate_trace: list[GateCheck]        # explainability for correction loop
```

---

## 4. `AestheticResult` — output of `aesthetic_weighter`

```python
@dataclass(frozen=True)
class AestheticResult:
    aesthetic_score: float
    type_tag: str
    weight_profile: dict[str, float]   # weights actually used (from SQLite)
    contributions: dict[str, float]    # weight * sub_score, sums to aesthetic_score
    fallback_used: bool                # True if type_tag had no profile
```

---

## 5. `FusionResult` — final output (backward compatible)

```python
@dataclass(frozen=True)
class FusionResult:
    # --- Existing public surface (unchanged for back-compat) ---
    master_score: float
    subject: str
    subject_confidence: float
    photo_type: str
    type_confidence: float
    sub_scores: dict[str, float]       # = bundle.as_flat_dict()
    hard_reject: bool
    hard_reject_reason: str
    star_rating: int
    color_label: int
    needs_review: bool

    # --- New layered fields (additive) ---
    technical: TechnicalResult
    aesthetic: AestheticResult
    region_spec: RegionSpec | None     # None unless retain_region_spec=True

    @property
    def explanation(self) -> str: ...
```

---

## Module function signatures

```python
# region_router.py
def route(
    context: SubjectContext,
    genre: GenreResult,
    *,
    depth_estimator: DepthModel | None = None,
) -> RegionSpec: ...


# sub_scores/sharpness.py | exposure.py | composition.py | aesthetic.py | faces.py
def score(
    context: SubjectContext,
    regions: RegionSpec,
) -> SharpnessSubScores | ExposureSubScores | ...: ...


# sub_scores/__init__.py
def compute_all(
    context: SubjectContext,
    regions: RegionSpec,
    *,
    enable_aesthetic: bool = True,
) -> SubScoreBundle: ...


# technical_gate.py
def evaluate(
    bundle: SubScoreBundle,
    regions: RegionSpec,
    subject_tag: str,
) -> TechnicalResult: ...


# aesthetic_weighter.py
def score(
    bundle: SubScoreBundle,
    type_tag: str,
    type_confidence: float,
    *,
    weights_db: Path,                  # SQLite path
) -> AestheticResult: ...


# fusion.py — the only function pipeline.py needs to call
def fuse(
    context: SubjectContext,
    genre: GenreResult,
    *,
    config: FusionConfig = DEFAULT_CONFIG,
) -> FusionResult: ...


@dataclass(frozen=True)
class FusionConfig:
    fusion_strategy: Literal["min", "harmonic_mean", "weighted"] = "min"
    technical_weight: float = 0.5
    retain_region_spec: bool = False
    enable_aesthetic_models: bool = True
    weights_db: Path                   # required; passed through to aesthetic_weighter
```

---

## SQLite schema for per-Type weights

`aesthetic_weighter` reads from and writes to a single table in the user
library DB. Cartridge manager handles export/import; scoring code never
touches the file path directly beyond this table.

```sql
CREATE TABLE IF NOT EXISTS aesthetic_weights (
    type_tag       TEXT NOT NULL,           -- one of the 12 Photo Types
    subscore_key   TEXT NOT NULL,           -- e.g. "composition.rule_of_thirds"
    weight         REAL NOT NULL,           -- 0..1, weights per Type sum to 1
    updated_at     INTEGER NOT NULL,        -- unix epoch; for staleness tracking
    correction_count INTEGER NOT NULL DEFAULT 0,  -- how many corrections shaped this
    PRIMARY KEY (type_tag, subscore_key)
);

CREATE INDEX idx_aesthetic_weights_type ON aesthetic_weights(type_tag);
```

A "factory defaults" bootstrap populates this table from the priors in
[scoring-redesign.md §5](../research/scoring-redesign.md) on first run.
The cartridge manager exposes export-to-JSON and import-from-JSON for
sharing tuned weights between machines.

---

## Module state ownership

| Module               | Owns                                  | Updated by                            |
|----------------------|---------------------------------------|---------------------------------------|
| `region_router`      | Subject prototypes + depth model      | Subject corrections (back-training)   |
| `sub_scores/*`       | Model weights (NIMA, CLIP-aesthetic)  | Periodic provisioning runs only       |
| `technical_gate`     | Per-Subject gate thresholds (SQLite)  | Subject corrections of `hard_reject`  |
| `aesthetic_weighter` | Per-Type weight table (SQLite)        | Type corrections (back-training)      |
| `fusion`             | Strategy + score→star→label mapping   | Manual / global config only           |

Correction entries become typed so each one updates exactly one module:

```python
@dataclass
class Correction:
    image_id: str
    layer: Literal["subject", "type", "gate", "weights"]
    old_value: str | bool | float
    new_value: str | bool | float
    sub_score_snapshot: dict[str, float]   # for replay / debugging
```

---

## Migration checklist (6 independently revertable steps)

1. **Add new types** alongside existing ones in `scoring_types.py`. Old
   `SharpnessScores` etc. coexist as deprecated aliases. No behavior change.
2. **Build `region_router`** as a new module. Existing sub-score modules
   ignore `RegionSpec` initially. Unit tests verify routing decisions per
   Subject (including depth gating for landscape/seascape/cityscape only).
3. **Refactor `sub_scores/*`** one family at a time to consume `RegionSpec`
   and return typed bundles. The flat-dict view keeps downstream consumers
   unchanged during the swap. Provision NIMA + CLIP-aesthetic ONNX models
   as part of this step.
4. **Split `score_fusion.py`** into `technical_gate.py` + `aesthetic_weighter.py`
   + a slim `fusion.py`. Create the SQLite `aesthetic_weights` table; bootstrap
   factory defaults from `scoring-redesign.md §5`. The old `fuse_scores()`
   becomes a thin shim.
5. **Migrate the correction loop** to write typed `Correction` records,
   routing each to the correct module's state store. Wire cartridge-manager
   export/import for `aesthetic_weights`.
6. **Delete the deprecated aliases** once `pipeline.py` and the XMP writer
   read the new layered fields directly. Issue #80 (Florence-2 grounding)
   can begin after this step lands.
