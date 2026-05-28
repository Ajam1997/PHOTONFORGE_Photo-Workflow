# Genre-Aware Scoring Redesign

**Date**: 2026-05-21
**Status**: Approved
**Author**: Alex Meyer
**Approach**: Layered Replacement (Approach A)

## Summary

Redesign PHOTONForge's scoring pipeline from three independent global metrics (Laplacian variance, FFT saliency + RoT, zone entropy) into a genre-aware system with subject-region scoring, multiple sub-scores per dimension, and genre-specific weight fusion. Adds MobileCLIP genre routing, RMBG-1.4 subject masking, YuNet face detection, and YOLOv8n object detection to the ONNX model stack.

## Constraints

- **Time budget**: 3-5 seconds per image for scoring (Florence-2 naming is separate)
- **RSS budget**: <= 1.5 GB total pipeline (new models add ~193MB loaded)
- **Inference**: ONNX INT8, CPU-only, i7-7500U with AVX2
- **Offline**: All models vendored locally; no runtime network calls (NFR-2.1)

## Genre Priority Order

1. Cats/Wildlife
2. Landscapes
3. Portraits
4. Street
5. Architecture
6. Macro
7. Event

## Architecture

### Module Map

```
src/photo_workflow/
  subject_context.py   [NEW]  — Runs all models once, shared context
  genre_router.py      [NEW]  — CLIP + EXIF + YOLO → genre classification
  score_fusion.py      [NEW]  — Genre-weighted combination → master score
  sharpness.py         [ENHANCED] — Tenengrad+SML, subject-aware, blur classification
  composition.py       [ENHANCED] — RoT + symmetry + lines + negative space + isolation
  exposure.py          [ENHANCED] — Zones + clipping + DR + style + face exposure
  pipeline.py          [MODIFIED] — Wire new scoring flow
  darktable_bridge.py  [MODIFIED] — New XMP fields, updated color label mapping
```

### Pipeline Flow

```
1. ingest_volume()
2. cluster_sessions()
3. deduplicate()
4. For each non-duplicate image:
   a. ctx = build_subject_context(path, model_sessions)   [~725ms]
   b. genre = route_genre(ctx)                            [~5ms, reuses CLIP embedding]
   c. sharp = score_sharpness(image, ctx)                 [~80ms]
   d. comp = score_composition(image, ctx)                [~150ms]
   e. expo = score_exposure(image, ctx)                   [~40ms]
   f. aesthetic = clip_aesthetic_score(ctx.clip_embedding) [~5ms]
   g. result = fuse_scores(sharp, comp, expo, genre, aesthetic)
5. sync_to_darktable(records)
6. Return (records, summary)
```

Total per-image: ~1.0-1.5s typical — well within 3-5s budget.

---

## Module 1: Subject Context (`subject_context.py`)

Runs all neural models once per image. Results shared by all scoring modules.

### SubjectContext Dataclass

```python
@dataclass
class SubjectContext:
    image_bgr: np.ndarray           # Full-res BGR
    image_gray: np.ndarray          # Grayscale
    thumbnail_rgb: np.ndarray       # 384-512px for model input

    # RMBG-1.4
    subject_mask: np.ndarray        # Binary mask at full resolution
    subject_area_ratio: float       # Fraction of image that is subject

    # YuNet
    faces: list[FaceDetection]      # bbox, landmarks (eyes/nose/mouth), confidence

    # YOLOv8n
    detections: list[ObjectDetection]  # class_id, class_name, bbox, confidence
    primary_subject_bbox: tuple | None # Largest salient detection

    # MobileCLIP
    clip_embedding: np.ndarray      # 512-dim image embedding

    # EXIF
    exif: dict                      # focal_length, aperture, shutter, iso, timestamp, camera_model
```

### FaceDetection / ObjectDetection

```python
@dataclass
class FaceDetection:
    bbox: tuple[int, int, int, int]     # x, y, w, h
    landmarks: dict[str, tuple[int, int]]  # "left_eye", "right_eye", "nose", "mouth_left", "mouth_right"
    confidence: float

@dataclass
class ObjectDetection:
    class_id: int
    class_name: str
    bbox: tuple[int, int, int, int]     # x, y, w, h
    confidence: float
```

### Builder

```python
def build_subject_context(path: Path, model_sessions: ModelSessions) -> SubjectContext:
```

Execution order:
1. Load image + extract EXIF (~20ms)
2. Resize to model input size (~5ms)
3. MobileCLIP image encode (~200ms)
4. RMBG-1.4 inference (~300ms)
5. YuNet face detection (~50ms)
6. YOLOv8n object detection (~150ms)

Total: ~725ms.

### ModelSessions

```python
class ModelSessions:
    """Lazy-loaded, long-lived ONNX sessions. One per pipeline run."""

    def __init__(self, model_dir: Path): ...

    @property
    def clip_vision(self) -> ort.InferenceSession: ...
    @property
    def rmbg(self) -> ort.InferenceSession: ...
    @property
    def yunet(self) -> ort.InferenceSession: ...
    @property
    def yolo(self) -> ort.InferenceSession: ...
    @property
    def clip_aesthetic_head(self) -> ort.InferenceSession: ...
```

### Graceful Degradation

| Missing Model | Behavior |
|---|---|
| MobileCLIP | Genre defaults to "general", aesthetic = 0.5 |
| RMBG-1.4 | Subject mask = full image (global metrics only) |
| YuNet | No face detection; eye_sharpness = subject_sharpness |
| YOLOv8n | No object evidence for genre; no animal head detection |

Missing models log a warning but do not crash. Sub-scores depending on a missing model return 0.5 (neutral).

---

## Module 2: Genre Router (`genre_router.py`)

### Genre Taxonomy

```
wildlife | landscape | portrait | street | architecture | macro | event | general
```

### Evidence Sources

**1. MobileCLIP zero-shot (primary):**

Precomputed prototype vectors (one per genre) from averaged text prompt embeddings:

- **Wildlife**: "a photograph of a cat", "a photograph of an animal in nature", "a wildlife photograph of a bird", "a close-up of a pet"
- **Landscape**: "a wide landscape photograph", "a scenic vista with mountains or water", "a sunset or sunrise scene"
- **Portrait**: "a portrait of a person", "a headshot photograph", "a close-up of a face"
- **Street**: "a candid street photograph", "people on a city street", "an urban scene"
- **Architecture**: "a photograph of a building", "architectural interior", "geometric structure"
- **Macro**: "an extreme close-up photograph", "a macro photograph of a small object"
- **Event**: "a group of people at a gathering", "a wedding or party photograph"

At inference: cosine similarity of image embedding to each prototype, softmax → probabilities.

**2. EXIF log-Gaussian prior:**

Multivariate Gaussian over (log_focal_length, log_aperture, log_shutter, log_iso) per genre. Hardcoded mean/std derived from research doc Table 4.4. Missing EXIF fields → uniform prior.

**3. YOLO class evidence (rules):**

| Detection | Genre boost |
|---|---|
| Cat/dog/bird/animal, area > 5% | wildlife |
| Person(s), largest > 15% | portrait |
| Multiple persons, none dominant | event/street |
| No living subjects + outdoor cues | landscape |
| No living subjects + strong vertical lines | architecture |

**Fusion:**

```python
P(genre | image) proportional to P_CLIP(genre) * P_EXIF(genre) * P_YOLO(genre)
```

Normalize to sum to 1.

### Output

```python
@dataclass
class GenreResult:
    genre: str                    # Top predicted genre
    confidence: float             # Probability of top genre
    distribution: dict[str, float]  # All 8 probabilities
```

**Fallback**: If top confidence < 0.3, tag as "general" (equal weights).

---

## Module 3: Enhanced Sharpness (`sharpness.py`)

### Output

```python
@dataclass
class SharpnessScores:
    subject: float           # Tenengrad+SML on subject mask region
    eye_region: float        # Tenengrad+SML on detected eye region
    background: float        # Tenengrad+SML on inverse mask
    sharpness_contrast: float  # subject / background ratio
    blur_type: str           # "sharp"|"bokeh"|"motion_subject"|"motion_global"|"misfocused"
    overall: float           # Genre-independent weighted combination
```

### Core Metric: Tenengrad + SML Geometric Mean

- **Tenengrad**: Sobel gradient magnitude squared. Best noise robustness.
- **SML**: Absolute second derivatives summed along x and y. High sensitivity.

Compute both, normalize by image area and mean luminance. Final = geometric mean.

### Region-Aware Computation

Three regions derived from SubjectContext:
1. **Subject region**: Pixels inside RMBG mask
2. **Eye region**: For portraits → YuNet face bbox cropped to eye landmarks. For wildlife → YOLO animal head bbox upper third (eye approximation).
3. **Background**: Inverse of subject mask

### Blur Type Classification (Rule-Based)

```
subject_sharp = subject_sharpness > threshold
bg_sharp = background_sharpness > threshold
ratio = subject_sharpness / max(background_sharpness, epsilon)

if ratio > 3.0 and subject_sharp       → "bokeh"
if ratio ~ 1.0 and neither sharp       → "motion_global" (camera shake)
if bg_sharp and not subject_sharp       → "misfocused"
if subject_sharp and not bg_sharp       → "bokeh" or "motion_subject"
if both sharp                           → "sharp"
```

Motion_subject vs bokeh: check if low-sharpness tiles show directional gradient (motion is directional; bokeh is uniform).

### Eyes-Open Heuristic

When YuNet detects face landmarks, compute the eye aspect ratio (EAR) from the eye landmark positions. EAR below a threshold (~0.2) indicates closed eyes. This feeds `expression_proxy` in the fusion layer. No separate model needed — YuNet's 5-point landmarks (left_eye, right_eye, nose, mouth_left, mouth_right) provide sufficient signal for a binary open/closed classification.

### RAW Handling

Extract embedded JPEG preview via `rawpy` for sharpness scoring. Camera-applied sharpening on preview is more representative of perceived sharpness than linear demosaic.

### Backward Compatibility

`score_sharpness(path)` convenience wrapper returns `SharpnessScores.overall` as float. Existing tests pass unchanged.

---

## Module 4: Enhanced Composition (`composition.py`)

### Output

```python
@dataclass
class CompositionScores:
    rule_of_thirds: float       # Saliency mass at power points (Gaussian falloff)
    symmetry: float             # Bilateral symmetry (Loy-Eklundh with ORB)
    leading_lines: float        # Hough lines converging toward subject
    negative_space: float       # Clean empty area surrounding subject
    subject_isolation: float    # Color + sharpness + luma contrast
    balance: float              # Visual weight centroid distance from center
    overall: float              # Equal-weighted combination
```

### Sub-Score Algorithms

**Rule of Thirds (improved):**
Gaussian falloff from salient region centroids to nearest power point. `score = exp(-d^2 / 2*sigma^2)`, d normalized by diagonal, sigma = 0.1. Max over all power points and salient regions.

**Symmetry (Loy-Eklundh, simplified):**
1. ORB keypoints (faster than SIFT)
2. Compute horizontally-mirrored descriptors
3. Match mirrored descriptors (BFMatcher + ratio test)
4. Matched pairs vote for reflection axis in polar (r, theta) accumulator
5. Score = peak inlier votes / total keypoints

~50-100ms at 1024px long edge. OpenCV-native.

**Leading Lines (Probabilistic Hough):**
1. Canny edges
2. `cv2.HoughLinesP`, filter by length > 0.15 * diagonal
3. Check if extended segments pass within 15% of diagonal from subject centroid
4. Score = sum(length * convergence_weight), normalized

**Negative Space:**
```python
negative_space_ratio = 1.0 - (salient_pixels / total_pixels)
```
Background smoothness multiplier: inverse of mean gradient magnitude in non-salient pixels.

**Subject Isolation:**
```python
isolation = 0.4 * sharpness_contrast + 0.35 * color_contrast_deltaE + 0.25 * luma_contrast
```
All derived from subject mask vs background. Color contrast in Lab (CIE76 DeltaE).

**Balance:**
Weight pixels by saliency * local_contrast. Compute weighted centroid. Score = `1 - (dist_from_center / (diagonal / 2))`.

### Performance

~100-150ms total (all OpenCV/NumPy, no model calls).

---

## Module 5: Enhanced Exposure (`exposure.py`)

### Output

```python
@dataclass
class ExposureScores:
    zone_entropy: float          # Normalized Shannon entropy over 11 zones
    zone_diversity: int          # Count of non-empty zones (0-11)
    clipping_shadows: float      # Fraction pixels < 4 (lower = better)
    clipping_highlights: float   # Fraction pixels > 251 (lower = better)
    dynamic_range: float         # (P99.5 - P0.5) / 255
    midtone_density: float       # Fraction in zones III-VII
    face_exposure: float         # Face luma vs ideal band; -1.0 if no face
    style: str                   # "normal"|"high_key"|"low_key"|"silhouette"
    style_confidence: float      # 0.0-1.0
    overall: float               # Combined score accounting for style
```

### Style Detection (Rule-Based)

```python
high_zones = sum(zones[7:]) / total    # zones VII-X
low_zones = sum(zones[:5]) / total     # zones 0-IV

if high_zones > 0.70 and low_zones < 0.10 → "high_key"
if low_zones > 0.70 and high_zones < 0.10 and bright_accent_exists → "low_key"
if shadow_mass > 0.25 in subject AND highlight_mass > 0.25 in background → "silhouette"
```

When style detected with confidence > 0.7, corresponding clipping penalty is disabled.

### Face-Region Exposure

- Human faces (YuNet): median luma of face bbox, scored against [110, 220] band
- Animals (YOLO head bbox): wider tolerance [80, 230]
- No face detected: `face_exposure = -1.0` (ignored in fusion)

### Overall Score Computation

```python
score = zone_entropy
if style != "silhouette": score -= clipping_shadows * 2.0
if style != "high_key": score -= clipping_highlights * 2.0
if style == "normal": score += (dynamic_range - 0.5) * 0.3
if face_exposure >= 0 and face_exposure < 0.5: score -= (0.5 - face_exposure) * 0.4
clamp [0.0, 1.0]
```

### Performance

~30-50ms (histogram/NumPy on luma channel already in memory).

---

## Module 6: Score Fusion (`score_fusion.py`)

### Genre-Specific Weight Profiles

```python
GENRE_WEIGHTS = {
    "wildlife": {
        "eye_sharpness": 0.28, "subject_sharpness": 0.12,
        "subject_isolation": 0.10, "composition_rot": 0.10,
        "negative_space": 0.08, "exposure_overall": 0.12,
        "blur_type_penalty": 0.08, "aesthetic_clip": 0.07,
        "behavior_proxy": 0.05,
    },
    "landscape": {
        "zone_entropy": 0.12, "dynamic_range": 0.12,
        "front_to_back_sharp": 0.16, "composition_rot": 0.10,
        "leading_lines": 0.10, "negative_space": 0.08,
        "balance": 0.08, "highlight_clip": 0.10,
        "aesthetic_clip": 0.08, "symmetry": 0.06,
    },
    "portrait": {
        "eye_sharpness": 0.25, "face_exposure": 0.12,
        "subject_isolation": 0.12, "composition_rot": 0.10,
        "negative_space": 0.10, "blur_type_bonus": 0.08,
        "expression_proxy": 0.08, "balance": 0.07,
        "aesthetic_clip": 0.08,
    },
    "street": {
        "subject_sharpness": 0.18, "composition_rot": 0.12,
        "leading_lines": 0.12, "subject_isolation": 0.10,
        "exposure_overall": 0.12, "negative_space": 0.08,
        "motion_tolerance": 0.08, "aesthetic_clip": 0.10,
        "balance": 0.05, "symmetry": 0.05,
    },
    "architecture": {
        "symmetry": 0.18, "leading_lines": 0.16,
        "subject_sharpness": 0.15, "exposure_overall": 0.12,
        "composition_rot": 0.10, "balance": 0.10,
        "negative_space": 0.07, "highlight_clip": 0.07,
        "aesthetic_clip": 0.05,
    },
    "macro": {
        "subject_sharpness": 0.25, "sharpness_contrast": 0.15,
        "negative_space": 0.12, "subject_isolation": 0.12,
        "composition_rot": 0.10, "exposure_overall": 0.08,
        "balance": 0.06, "aesthetic_clip": 0.07,
        "color_contrast": 0.05,
    },
    "event": {
        "eye_sharpness": 0.20, "face_exposure": 0.12,
        "expression_proxy": 0.18, "subject_sharpness": 0.15,
        "composition_rot": 0.10, "exposure_overall": 0.10,
        "aesthetic_clip": 0.08, "balance": 0.07,
    },
    "general": {
        "subject_sharpness": 0.20, "exposure_overall": 0.18,
        "composition_rot": 0.15, "subject_isolation": 0.12,
        "aesthetic_clip": 0.10, "negative_space": 0.10,
        "balance": 0.08, "symmetry": 0.07,
    },
}
```

### Sub-Score Mapping

Weight keys in the genre profiles map to raw module outputs plus a few derived values computed in the fusion layer itself:

**Direct mappings (module field → weight key):**

| Weight key | Source |
|---|---|
| `eye_sharpness` | `SharpnessScores.eye_region` |
| `subject_sharpness` | `SharpnessScores.subject` |
| `sharpness_contrast` | `SharpnessScores.sharpness_contrast`, normalized to [0,1] via `min(ratio / 5.0, 1.0)` |
| `composition_rot` | `CompositionScores.rule_of_thirds` |
| `symmetry` | `CompositionScores.symmetry` |
| `leading_lines` | `CompositionScores.leading_lines` |
| `negative_space` | `CompositionScores.negative_space` |
| `subject_isolation` | `CompositionScores.subject_isolation` |
| `balance` | `CompositionScores.balance` |
| `zone_entropy` | `ExposureScores.zone_entropy` |
| `dynamic_range` | `ExposureScores.dynamic_range` |
| `exposure_overall` | `ExposureScores.overall` |
| `face_exposure` | `ExposureScores.face_exposure` (if >= 0, else 0.5 neutral) |
| `aesthetic_clip` | CLIP aesthetic head output (float) |

**Derived scores (computed in fusion from raw sub-scores):**

| Weight key | Computation |
|---|---|
| `front_to_back_sharp` | `min(SharpnessScores.subject, SharpnessScores.background)` — both regions must be sharp for landscape deep-DOF |
| `blur_type_penalty` | `0.0` if blur_type in ("motion_global", "misfocused"), `1.0` otherwise — penalizes technical failures |
| `blur_type_bonus` | `1.0` if blur_type == "bokeh", `0.5` if "sharp", `0.0` otherwise — rewards intentional shallow DOF |
| `motion_tolerance` | `1.0` unless blur_type == "motion_global", then `0.0` — street/event tolerance for subject motion |
| `highlight_clip` | `1.0 - ExposureScores.clipping_highlights` — inverted so lower clipping = higher score |
| `expression_proxy` | If face detected: `1.0` if eyes open, `0.0` if closed. If no face: `0.5` (neutral). Uses YuNet eye-landmark aspect ratio as open/closed heuristic. |
| `behavior_proxy` | `1.0` if blur_type == "motion_subject" (animal in motion = interesting), `0.5` otherwise |
| `color_contrast` | CIE76 DeltaE between mean subject color and mean background color, normalized by `min(deltaE / 50.0, 1.0)` |

### Fusion Logic

```python
def fuse_scores(
    sharpness: SharpnessScores,
    composition: CompositionScores,
    exposure: ExposureScores,
    genre: GenreResult,
    aesthetic: float,
) -> FusionResult:
```

1. **Normalize**: All inputs already in [0,1].
2. **Map to flat dict**: Build from direct mappings + derived scores above.
3. **Soft genre weighting**: Blend weight profiles by genre probability distribution:
   ```python
   effective_weights = sum(genre.distribution[g] * GENRE_WEIGHTS[g] for g in genres)
   ```
4. **Master score**: Dot product of effective weights and sub-score values.
5. **Hard gates** (override to reject):
   - `blur_type == "motion_global"` and `subject_sharpness < 0.2`
   - `blur_type == "misfocused"` and `eye_sharpness < 0.15`
   - Both eyes closed (face detected, eyes_open == False)
6. **Clamp** to [0.0, 1.0].

### Output

```python
@dataclass
class FusionResult:
    master_score: float                # [0.0, 1.0]
    genre: str                         # Top genre tag
    genre_confidence: float            # Router confidence
    sub_scores: dict[str, float]       # All sub-scores for transparency
    hard_reject: bool                  # True if hard gate fired
    hard_reject_reason: str            # e.g. "motion_global_blur" or ""
    star_rating: int                   # 1-5 from master_score
    color_label: int                   # Darktable color label code
```

### Star Rating

```python
stars = max(1, min(5, round(master_score * 5)))
```

### Color Labels

| Label | Meaning |
|---|---|
| RED | Duplicate (existing, unchanged) |
| YELLOW | master_score < 0.3 (weak) |
| NONE | master_score 0.3-0.5 (average) |
| GREEN | master_score 0.5-0.75 (good) |
| BLUE | master_score > 0.75 (excellent) |
| PURPLE | Reserved for user-flagged |

### Reject Flag

Hard gate failures → Darktable reject flag (rating = -1), separate from color labels. `hard_reject_reason` written to XMP metadata.

---

## Module 7: Model Directory Layout

```
models/
  florence2_int8/            # Existing (naming)
  mobileclip_s0_int8/        # Genre + aesthetic embedding
    vision_encoder.onnx
    text_encoder.onnx        # Offline only (precompute prototypes)
  clip_aesthetic_head/       # Tiny MLP
    aesthetic_mlp.onnx
  rmbg14_int8/               # Subject masking
    model.onnx
  yunet/                     # Face detection
    face_detection_yunet.onnx
  yolov8n_int8/              # Object detection
    model.onnx
  genre_prototypes.npy       # Precomputed CLIP text embeddings (~4KB)
```

### Resource Budget

| Model | Disk (INT8) | RSS |
|---|---|---|
| MobileCLIP-S0 vision | ~40MB | ~80MB |
| RMBG-1.4 | ~45MB | ~90MB |
| YuNet | ~1MB | ~5MB |
| YOLOv8n | ~6MB | ~15MB |
| CLIP aesthetic head | ~2MB | ~3MB |
| **Total new** | **~94MB** | **~193MB** |

Combined with Florence-2 (~200MB) + working memory (~200MB): **~600-700MB total RSS**.

### Provisioning

New `scripts/provision_scoring_models.sh` downloads and quantizes each model. Runs once during setup (internet allowed per NFR-2.1).

---

## Database Schema Changes

```sql
ALTER TABLE [folder] ADD COLUMN genre TEXT DEFAULT '';
ALTER TABLE [folder] ADD COLUMN genre_confidence REAL DEFAULT 0.0;
ALTER TABLE [folder] ADD COLUMN master_score REAL DEFAULT 0.0;
ALTER TABLE [folder] ADD COLUMN sub_scores TEXT DEFAULT '';  -- JSON blob
```

Existing columns (sharpness, composition, exposure) retained for backward compatibility but populated with `.overall` values from the new dataclasses.

---

## XMP Metadata Output

All sub-scores written under `photon:` namespace:

```xml
<photon:Genre>wildlife</photon:Genre>
<photon:GenreConfidence>0.87</photon:GenreConfidence>
<photon:MasterScore>0.72</photon:MasterScore>
<photon:EyeSharpness>0.85</photon:EyeSharpness>
<photon:SubjectSharpness>0.78</photon:SubjectSharpness>
<photon:SubjectIsolation>0.64</photon:SubjectIsolation>
<photon:BlurType>bokeh</photon:BlurType>
<photon:CompositionRoT>0.71</photon:CompositionRoT>
<photon:Symmetry>0.32</photon:Symmetry>
<photon:LeadingLines>0.45</photon:LeadingLines>
<photon:NegativeSpace>0.68</photon:NegativeSpace>
<photon:ZoneEntropy>0.82</photon:ZoneEntropy>
<photon:DynamicRange>0.91</photon:DynamicRange>
<photon:ExposureStyle>normal</photon:ExposureStyle>
<photon:FaceExposure>0.88</photon:FaceExposure>
<photon:AestheticScore>0.65</photon:AestheticScore>
```

---

## Backward Compatibility

- `score_sharpness(path)` → returns float (SharpnessScores.overall)
- `score_composition(path)` → returns float (CompositionScores.overall)
- `score_exposure(path)` → returns float (ExposureScores.overall)
- Existing unit tests pass unchanged against convenience wrappers
- DB columns `sharpness`, `composition`, `exposure` still populated
- XMP sidecars gain new fields but retain all existing ones

---

## Out of Scope (Future Work)

- Monocular depth estimation (MiDaS) for depth layering scores
- NIMA rating distribution prediction
- Burst clustering via CLIP embedding cosine similarity
- Adaptive percentile thresholding (top-N% culling)
- User feedback loop / personalization (Phase 2-3)
- Florence-2 "explain my rating" feature
- Per-camera sharpness threshold calibration
