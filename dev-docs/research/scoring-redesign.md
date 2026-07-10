# A Framework for Genre-Aware Photo Quality Scoring and Automated Culling

> **Research record.** The NIMA/MUSIQ, depth-model, and
> `min(technical, aesthetic)` fusion proposals in this document were
> **not shipped as designed** — the scoring that shipped lives in
> `src/photo_workflow/score_fusion.py` (two-axis weight blending,
> renormalization, hard-reject gates, percentile stars). The §5 weight
> tables remain the bootstrap source for the `aesthetic_weights` table.

## Executive Summary

This document specifies a comprehensive, genre-aware photo scoring engine designed to cull mixed-genre photography to the top 30–40 % of images. The framework combines (a) classical computer-vision metrics for low-level technical quality, (b) deep no-reference image quality / aesthetic models (NIMA, MUSIQ, learned composition attributes), and (c) a CLIP-based zero-shot genre router that switches in genre-specific weight profiles. The target deployment is a CPU-only laptop class machine (dual-core i7-7500U, 8 GB RAM), so every component is selected for ONNX/INT8 viability and an inference budget under ~2 s per image.

The core insight, supported by industry tools (Aftershoot, Narrative Select, Imagen, FilterPixel's DeepCull) and academic work (AVA, AADB, NIMA, MUSIQ), is that a single global aesthetic score is insufficient. State-of-the-art culling decomposes the problem into (1) a technical layer that is largely genre-agnostic (focus, exposure clipping, eyes-open), (2) an aesthetic/composition layer informed by photographic rules, and (3) a *contextual* layer that knows the genre and re-weights everything else. FilterPixel's recent DeepCull launch makes this explicit: "the core problem with current AI photo culling tools is that they treat every genre the same way" — exactly the gap this framework targets.

---

## 1. Composition Scoring Models

### 1.1 Rule of Thirds (RoT)

The Rule of Thirds states that placing salient objects on or near the 3×3 grid intersections and lines yields more pleasing images. The standard computational pipeline, established by Mai et al. and refined in subsequent work, is:

1. Compute a **saliency map** of the image. Three families dominate the literature: Graph-Based Visual Saliency (GBVS), Itti-Koch, and contrast-based methods such as Region Contrast (RC) and Frequency-Tuned (FT). Comparative studies on the Mai dataset showed RC saliency outperforms context-aware (CA) saliency for RoT prediction and is significantly faster.
2. Localize the salient object(s) — either as the centroid of a thresholded saliency window, or via segmentation (GrabCut iteratively refined from the RC map).
3. Compute distances from each salient region's center of mass to the four "power points" (intersections of the thirds-lines) and to the four thirds-lines themselves.
4. Convert distances to a RoT score using a Gaussian falloff: `score = exp(-d² / 2σ²)` where `d` is normalized by image diagonal.

Modern hybrid approaches (Brachmann/Redies; the 2024 "Rule-of-Thirds Detection with Interpretable Geometric Features" paper) bootstrap a **ResNet50 saliency model** with pretrained object detection/segmentation networks (YOLO, SAM) to construct interpretable geometric features that quantify alignment with the grid. This is preferable to a black-box CNN classifier because it produces *per-image diagnostics* ("subject is 12 % off the upper-left power point") that can be aggregated into the master score.

User-study evidence from Firoze et al. (using 5 000 MIRFLICKR images and 255 raters) found that RoT contributes meaningfully but only partially explains human aesthetic judgments — so RoT must be one of many weighted signals, not a hard rule.

### 1.2 Golden Ratio / Fibonacci Spiral

Treat as a *secondary* compositional template overlaid on the same saliency map. The phi-grid (lines at ≈0.382 and ≈0.618 of width/height) and four orientations of the logarithmic spiral are tested; the maximum alignment score over all orientations becomes the spiral score. In practice the phi-grid score is highly correlated with RoT (r ≈ 0.85 in our experience) and should be fused (max or weighted average) into a single "thirds/phi" feature to avoid double-counting.

### 1.3 Leading Lines

Two viable approaches, ordered by sophistication:

- **Classical**: Canny edge detection → probabilistic Hough transform (`cv2.HoughLinesP`) → filter line segments by length (> 0.15 × diagonal) and by whether their extended path converges toward a saliency hot spot or vanishing point (RANSAC on line intersections). Score = sum of (line length × convergence-to-subject weight).
- **Learned**: *Deep Hough Transform for Semantic Line Detection* (Zhao et al., TPAMI) parameterizes lines by (slope, bias) and performs Hough voting inside the CNN feature space. Output is a small set of "semantic" lines with confidence — far more reliable than raw Hough on textured scenes (foliage, crowds). A pretrained DHT checkpoint is available at mmcheng.net/dhtline/ and is ONNX-convertible.

The leading-lines score should reward convergence toward the principal subject (saliency peak) and penalize lines that drag the eye *out* of frame.

### 1.4 Symmetry and Balance

The canonical pipeline for bilateral (reflection) symmetry detection is **Loy & Eklundh (ECCV 2006)**:

1. Detect SIFT keypoints and descriptors.
2. For each keypoint, compute its *mirrored* descriptor.
3. Match each keypoint to other keypoints whose mirrored descriptor is similar (BFMatcher with ratio test).
4. Each matched pair votes for an axis of symmetry parameterized by polar coordinates (r, θ); peaks in the (r, θ) accumulator are the detected axes.

This is OpenCV-implementable and runs in well under 200 ms per image at 1024 px long edge. It handles vertical, horizontal, and diagonal axes equally well. Limitations: poor on low-texture scenes (skies, walls) and on rotational symmetry — for which the Loy & Zelinsky radial symmetry transform is preferred. More recent learning-based methods (Polar Matching Convolution, ICCV 2021) outperform SIFT-based approaches but at significantly higher compute cost.

For balance (not strict symmetry), compute the **visual weight centroid**: weight each pixel by `(saliency × luminance_contrast × color_saturation)` and locate the weighted centroid. Balance score = `1 − ||centroid − image_center|| / (diagonal / 2)`. A photo can be intentionally unbalanced (and high-quality); therefore balance is a *soft* metric and should be down-weighted for street and documentary genres.

### 1.5 Visual Weight Distribution

Divide the image into a 3×3 or 5×5 grid. Compute, for each cell: mean saliency, contrast (local std-dev of luminance), and color saturation. The visual-weight feature vector is this 9- or 25-dimensional cell vector normalized to sum to 1. From the distribution compute:

- **Entropy** (high = even spread, low = single-subject concentration). High-quality portraits typically have *low* entropy; landscapes have moderate entropy.
- **Quadrant balance** (sum of top vs bottom, left vs right).
- **Diagonal energy** (sum along leading and trailing diagonals — high for dynamic compositions).

### 1.6 Negative Space

Negative space is the "empty" area surrounding the subject. Compute as:

```
negative_space_ratio = (image_pixels − salient_pixels) / image_pixels
```

after thresholding the saliency map at Otsu's threshold. Quality is *unimodal* in this ratio: scores peak around 0.6–0.8 for portraits and landscapes and fall off at both extremes. Implement as a Gaussian centered at a genre-specific peak.

Refinement: compute the *smoothness* of the negative region (low gradient energy) — a clean background contributes much more than a cluttered one. Use the inverse of mean gradient magnitude in non-salient pixels.

### 1.7 Depth Layering (Foreground / Midground / Background)

Run a lightweight monocular depth estimator — **MiDaS small (DPT-SwinV2-T)** or **Depth Anything V2 small** (both ONNX-exportable, ~25 M params, ~400 ms on the target CPU at 384 px). Quantize the depth map into three bins by k-means or fixed quantiles. Compute:

- Pixel coverage of each bin (must be > 5 % each for the image to qualify as "three-layer").
- Saliency mass per bin — does the subject sit in a single bin (good) or smear across all three (often bad)?

Output a `depth_layering_score = min(coverage_fg, coverage_mid, coverage_bg) × 3` clipped to [0, 1]. Crucial for landscapes; near-irrelevant for headshots.

### 1.8 Frame-Within-Frame

Detect rectangular or arch-shaped enclosing structures around the main subject. Two-step:

1. Run a line-segment detector (LSD) and find long line segments at the image periphery.
2. Test whether ≥ 3 sides of a quadrilateral exist around the saliency centroid and *do not cross it*.

This is a binary feature with a confidence — relatively rare but a strong positive signal when present (especially for architecture and street).

### 1.9 Subject Isolation / Figure-Ground Separation

Combine three signals:

- **Sharpness contrast**: ratio of mean local sharpness inside the saliency mask to outside (see §2.2).
- **Color contrast**: mean ΔE (CIE76) between subject and background colors.
- **Depth contrast**: mean depth difference (from the depth map) between subject and background.

A weighted sum gives an **isolation score** that closely tracks what photographers mean when they say "the subject pops." Networks like **U²-Net** and **BASNet** can produce saliency/segmentation masks at ~50 M params; **MODNet** and **RMBG-1.4** are lighter (~7 M params) and ONNX-ready for fast subject masking.

### 1.10 How Professional Tools Score Composition

Public-facing descriptions of commercial systems converge on the following patterns:

| Tool | Composition handling |
|---|---|
| **Photo Mechanic / Photo Mechanic Plus** | Predominantly a fast browser; AI culling additions are limited to face detection, sharpness, and duplicate detection. No first-class composition scoring. |
| **Narrative Select** | "Eye & Focus Assessments, Close-ups, and Scenes." Composition is implicit — surfaced through subject-prominence cues but not exposed as a separate score. Marketed as AI-assisted (human keeps final say). Strong on the Mac with sub-3-second RAW preview rendering. |
| **Aftershoot** | Uses "30+ technical factors" and learns from user feedback. Composition is not advertised as a separate axis; instead the AI ingests broad image features and ranks. Adapts to user style over time. User asks for shoot type up-front (Portrait, Wedding, etc.) which alters default weights. |
| **Imagen Culling Studio** | Groups duplicates, rates by technical quality and "oopsies" (blurry, exposure, accidental); composition handled implicitly via overall learned rating. Lets the user request "top 500 images" or "top 15 %" of the shoot. |
| **FilterPixel DeepCull (2025)** | Explicitly genre-specific. Trained on wedding photography sequences; scores 10 named parameters per image (sharpness, eyes-open, expression, composition, lighting, moment, etc.) and exposes all 10 to the user for transparency. The closest public example of the architecture proposed here. |

A consistent industry observation: even the best AI culling tools "miss emotional details" and "can misfire in tricky lighting or with similar poses" — which is why hybrid (AI first pass, photographer review) remains the dominant production workflow.

### 1.11 Academic Research Foundations for Computational Composition

- **AVA dataset** (Murray et al., CVPR 2012): 250 k+ images from dpchallenge.com with 1–10 mean aesthetic scores, 60+ semantic categories, and 14 photographic-style tags (Complementary Colors, HDR, Long Exposure, Macro, Motion Blur, Negative Image, Rule of Thirds, Shallow DOF, Silhouettes, Vanishing Point, Light On White, etc.).
- **AADB** (Kong et al., ECCV 2016): adds 11 photographic *attributes* per image (interesting content, object emphasis, good lighting, color harmony, vivid color, depth of field, motion blur, rule of thirds, balancing element, repetition, symmetry) — these attributes map almost 1:1 to the dimensions any culling system should expose.
- **CUHK-PQ, FLICKR-AES, KonIQ-10k, SPAQ, PaQ-2-PiQ** — additional IQA datasets used to train MUSIQ and related models.
- **Discovering Beautiful Attributes** (Marchesotti, Murray, Perronnin) — mined AVA user comments to learn nameable visual attributes, demonstrating that mid-level attribute classifiers give both interpretability *and* accuracy. This is the model template for genre-specific attribute scoring.

---

## 2. Sharpness and Focus Scoring

### 2.1 Beyond Variance of Laplacian

The literature is unambiguous: the canonical OpenCV pattern `cv2.Laplacian(...).var()` is *fragile* — sensitive to noise, image content, and image size. Pertuz et al.'s 2013 survey "Analysis of focus measure operators" benchmarks 36 operators and several have emerged as consistently better:

| Operator | Notes |
|---|---|
| **Tenengrad / Tenengrad-Variance** | Sobel gradient magnitude squared; superior noise robustness across studies. Generally the top choice for autofocus and best-frame selection in OpenCV benchmarks. |
| **Sum of Modified Laplacian (SML, Nayar 1990)** | Absolute second derivatives summed along x and y separately to avoid sign cancellation. High sensitivity but somewhat noise-sensitive. |
| **Energy of Laplacian (EOL)** | Sum of squared Laplacian; high sensitivity, poor noise robustness. |
| **Brenner's measure** | Squared difference between pixels two apart; fast, moderate performance. |
| **DCT energy ratio / Wavelet energy** | Frequency-domain measures; computationally heavier but content-robust. |
| **Vollath's autocorrelation** | Statistical, very fast, good for low-contrast images. |

A 2025 quantitative evaluation of focus operators in microscopy concluded: **frequency-domain operators are too slow for real-time**; among spatial operators, Tenengrad gives the best sensitivity/noise-robustness balance. The recommended composite is to compute **Tenengrad + SML** and use the geometric mean of the two normalized scores. Always normalize by image area and by mean luminance to make scores comparable across exposures and crops.

### 2.2 Subject-Aware Sharpness (the critical insight)

Global sharpness is misleading. A 6 000-pixel landscape with crisp foreground and intentional motion-blurred clouds may have a lower global Laplacian variance than a tack-sharp shot of a brick wall. The framework therefore *always* computes sharpness on regions:

1. Run a subject/saliency detector (U²-Net, RMBG-1.4, or YOLO + class filtering).
2. Compute the focus measure separately on three regions: **subject mask**, **dilated subject ring** (margin of ~10 % of bbox), and **background**.
3. For each genre, define which region's sharpness matters:
   - **Portrait**: subject sharpness, with extra emphasis on an *eye region* obtained from a face landmark detector (MediaPipe Face Mesh, RetinaFace, or YuNet — all ONNX-friendly).
   - **Wildlife**: subject sharpness with eye-prioritization once the animal's head/eye is located (a YOLO model fine-tuned for animal eyes, or a simple template-search inside the head bbox).
   - **Macro**: a *sharpness map* — the fraction of the subject that is in the focal plane, plus the *gradient* of sharpness around it (should be smooth, not abrupt).
   - **Landscape**: a *front-to-back sharpness profile* — compute mean sharpness in each depth bin from §1.7; high-quality landscape photos have all three bins well above threshold.
   - **Street/event**: looser; subject sharpness alone, accepting motion blur if it is *localized* on a moving element (see §2.3).
   - **Architecture**: edges should be uniformly sharp across the entire frame.

The face-image-quality literature (e.g., Li 2021, the CEUR-WS sharpness-of-people paper) confirms that subject-restricted sharpness measurement is dramatically more predictive of perceived quality than global measures, and that eye-region sharpness is *the* single highest-weight feature for portrait quality — "everything else can be fixed in post, but sharpness cannot."

### 2.3 Intentional Blur Detection

Three categories must be distinguished from "soft" missed-focus:

- **Camera shake / global motion blur**: uniform directional blur over the whole frame → almost always a reject.
- **Subject motion blur**: blur is localized on a moving element, while the background and other static elements remain sharp. Detect by computing local Laplacian energy in tiles and looking for a tile-level *bimodal* distribution. Or use a learned motion-blur detector. For street and sports, this is often a positive signal.
- **Bokeh / shallow DOF**: the background is uniformly *low-frequency* (smooth blur), the subject is sharp. Detect via the ratio between subject and background frequency content (FFT high-frequency energy). For portraits and macro this is positive; for landscapes it is negative.

A simple decision rule: compute sharpness contrast = `subject_sharpness / background_sharpness`. If ratio > 3 and subject_sharpness is high → likely intentional bokeh (good). If ratio ≈ 1 and both are low → camera shake (bad). If background is sharp but subject smeared with directional gradient → subject motion blur (genre-dependent).

### 2.4 Depth-of-Field Analysis

For each image, build a **sharpness-vs-depth curve**: bin pixels by depth quintile and compute mean focus measure per bin. Three archetypes emerge:

- *Deep DOF*: flat curve, high across all bins → landscapes, architecture.
- *Shallow DOF*: single peak, narrow → portraits, macro.
- *Misfocused*: peak in the wrong bin (background sharp, subject blurry) → reject.

Score: position of the peak relative to where the subject sits in the depth quantiles. Penalize when the peak ≠ subject's depth bin.

### 2.5 Multi-Region Sharpness Maps

Beyond a single subject mask, compute a dense **sharpness heatmap** by sliding a 64×64 window over the image and computing local Tenengrad. Useful for visualization, for detecting localized softness (one corner of a wedding group photo is OOF), and for the "sharpness gradient" smoothness check.

### 2.6 RAW vs JPG Sharpness

RAW files are deliberately *softer* than camera-rendered JPEGs because in-camera sharpening is not applied. A fixed threshold that works on JPEGs will reject most RAWs as "blurry." Two strategies:

- **Use embedded JPEG previews** for sharpness scoring (every modern RAW contains a full-resolution JPEG preview the camera generated for the back-of-camera display). Tools like Photo Mechanic and FastRawViewer get their renowned speed precisely by reading these previews. Libraries: `rawpy` to extract, or `libraw` directly.
- **Calibrate thresholds per source**: maintain two histograms of sharpness scores (one for RAW-renders, one for JPEGs) and threshold by percentile within each distribution rather than by absolute value (see §7.4).

### 2.7 Frequency-Domain (FFT-Based) Sharpness

Compute the 2D FFT of the (grayscale) image, then the ratio of high-frequency energy (outside a centered circle of radius `r = min(H,W)/8`) to total energy. Sharp images have a higher ratio. Two notes:

- FFT cost is O(N log N) but for a 1024×1024 image is well under 100 ms in NumPy/SciPy.
- FFT is *content-sensitive*: a busy image (foliage) will always score higher than a portrait against a clean wall. Combine with spatial measures, do not use alone.

A more practical frequency measure is the **DCT energy ratio**: take the 2D DCT, then ratio of AC coefficients (excluding DC) to total energy, or the ratio of coefficients above a certain frequency cutoff. JPEG already computes 8×8 DCT blocks, so this can be very fast when reading JPEGs.

### 2.8 Edge-Aware Sharpness

An elegant approach: locate edges with Canny, then measure the **edge transition width** — distance over which intensity transitions from 10 % to 90 % of the local contrast. Sharp images have narrow transitions (1–2 px); soft images have wide ones (4–10+ px). This is essentially the Average Edge Transition Slope (AETS) and Digital Sharpness Scale (DSS) metric that has been validated as "highly correlated to perceived sharpness" in psychophysical studies. AETS handles content-variation better than gradient-energy methods.

---

## 3. Exposure Scoring

### 3.1 Beyond Histogram Clipping

A naïve "well-exposed = no clipping" rule rejects every well-composed silhouette and every intentional high-key portrait. A modern exposure scorer must:

1. Detect clipping in shadows (% of pixels < 4 in 8-bit luma) and highlights (% > 251).
2. Compute the **luminance histogram entropy** — well-distributed tonality has higher entropy.
3. Compute the **midtone density**: % of pixels in the zone-V range (luma 90–160).
4. Compute the **dynamic range used**: standard deviation of luma, or (P99 − P1) of the luma distribution.
5. Detect *intentional* exposure styles before flagging clipping as a defect.

### 3.2 Zone System (Ansel Adams)

The zone system maps luminance to 11 zones (0 = black, X = white). Computationally:

```
zones[i] = count of pixels with luma in band i (i = 0..10)
```

Score components:

- **Zone diversity**: number of non-empty zones (good photos typically use 7+ zones).
- **Zone III–VII presence**: percent of pixels in zones III (deep shadow with texture) through VII (highlight with texture). Many great photos have zones III–VII as the dominant tonal range with smaller anchoring values in 0–II and VIII–X.
- **Texture preservation in extremes**: in pixels labeled zones I–II and VIII–IX, compute local std-dev. If std-dev > a threshold, those shadows/highlights still carry detail (good); if near zero, they are clipped (typically bad, but not always).

Implementation: a one-pass histogram bucketed to 11 bins, plus a per-pixel zone label image for the texture check.

### 3.3 High-Key / Low-Key as Intentional Styles

Train (or hand-engineer) a small classifier that detects these styles from histogram shape:

- **High-key**: ≥ 70 % of pixels in zones VII–X, very few in 0–III, low overall std-dev.
- **Low-key**: ≥ 70 % of pixels in zones 0–IV, very few in VII–X, a small bright accent typically present (otherwise it's just "underexposed").
- **Silhouette**: bimodal histogram with a deep-shadow peak (zones 0–I) containing > 25 % of pixels in the *center* (saliency mask) and a bright peak in zones VIII–X in the background.

When one of these is detected with confidence > 0.7, *disable* the clipping penalty for the corresponding extreme. AADB attributes such as "good lighting" and AVA's photographic-style tags (Silhouettes, Light On White) are evidence this categorization is meaningful.

### 3.4 Dynamic Range Utilization

`DR_used = (P99.5_luma − P0.5_luma) / 255`

Photos using DR > 0.85 score full marks; DR < 0.4 is penalized unless a high-key / low-key style is detected. For RAW files, compute on linear data with a γ-correction afterwards to match perceived contrast.

### 3.5 Highlight / Shadow Recovery Potential (RAW)

This applies only when the input is RAW. Modern RAW files (14-bit) retain detail in highlights that appear clipped in the JPEG preview. Recovery score:

- Demosaic the RAW with `rawpy` at linear output.
- For each channel, count pixels where the *linear* value < 0.98 even though the rendered JPEG shows clipped. Those highlights are recoverable.
- Similarly for shadows: linear value > a noise-floor threshold (depends on ISO, typically 0.005 × max).

Score = fraction of "clipped in preview but recoverable in RAW" pixels. This converts what looks like a poorly exposed shot into a *recoverable* shot — a useful nuance no current culling tool exposes directly.

### 3.6 Genre-Specific Exposure

- **Street**: silhouettes acceptable; bias toward midtone contrast; tolerate extreme tonal ranges.
- **Portrait**: skin must sit between zones V–VII (luma ≈ 130–200). Detect face → compute median luma of face region → penalize if outside the [110, 220] band. Background luminance is allowed to be very different (white backdrops, high-key) provided face is correct.
- **Landscape**: penalize blown skies (zone X dominant in upper third) but reward sky retaining color (Bayer-channel exposure analysis below).
- **Wildlife**: subject (often dark fur or feathers against a bright sky) must retain texture in shadows.
- **Macro**: small DR usually; reward smooth gradients more than wide DR.
- **Architecture**: penalize blown windows when the rest of the frame is well-exposed; HDR-friendly judgment.
- **Event**: tolerant; expressions and moment take precedence.

### 3.7 Luminance Distribution Analysis

Compute, in CIE-L* space (after sRGB→Lab):
- Mean L*
- Std-dev of L* (contrast)
- Skewness (positive → image is mostly dark with bright accents; negative → mostly bright)
- Kurtosis (peaked vs flat)

These four moments — with the histogram-entropy and zone-diversity counts — are inputs to a learned exposure scorer (a small gradient-boosted tree trained on AADB's "good lighting" attribute, for instance).

### 3.8 Per-Channel (Color) Exposure

Compute R, G, B histograms separately. Detect:

- **Single-channel clipping**: blown sky often clips only B; sunset clips R and G first. A pure-luma histogram can hide channel-specific clipping.
- **White-balance excursions**: median R/G and B/G ratios per face region (for portraits) — out-of-gamut skin tones get a penalty.
- **Saturation distribution**: histogram of S in HSV. Very high mean S can be intentional (vivid color, an AADB attribute) or an over-processed JPEG; combine with content.

---

## 4. Genre Detection and Classification

### 4.1 Visual Genre Classification with CLIP

CLIP (ViT-B/32 or smaller) is the recommended workhorse. On ImageNet zero-shot, CLIP ViT-B/32 hits ~63 % top-1 and ViT-L/14 hits 76.2 % — far better than the framework needs for genre routing (which has ~8 classes, not 1 000). The procedure:

1. Define ≈ 4–6 textual prompts per genre, e.g.:
   - "a portrait of a person", "a close-up photograph of a face", "a headshot"
   - "a wide landscape photograph", "a scenic vista", "a mountain landscape", "an aerial landscape"
   - "a candid street photograph", "people on a city street", "an urban scene with people"
   - "a wildlife photograph of an animal", "a photograph of a bird in nature"
   - "an extreme close-up macro photograph", "a macro photograph of an insect or flower"
   - "a photograph of a building", "an architectural photograph", "interior architecture"
   - "a wedding ceremony photograph", "a documentary event photograph", "a sports action photograph"
2. Encode each prompt with the CLIP text encoder, average per genre → genre prototype vector.
3. Encode the image with the CLIP image encoder, softmax cosine similarity to each prototype → genre probabilities.
4. Combine with EXIF priors (§4.4) using a simple log-linear fusion.

**MobileCLIP-S0/S1** (Apple, 2024) and **TinyCLIP** are excellent lightweight alternatives — MobileCLIP-S0 has ~11 M image-encoder params and runs in well under 200 ms on the i7-7500U; accuracy is within a few points of ViT-B/32. Both are ONNX-exportable. SigLIP is another option with slightly higher accuracy at similar size.

A known CLIP weakness is small-subject classification; the "Guided Cropping" paper improves it by running an open-vocabulary detector first. For genre detection at the image level this is rarely needed.

### 4.2 Scene Classification Models (Indoor / Outdoor / Action / Macro)

Alternative or supplementary to CLIP: **Places365** pretrained networks (ResNet18/50, MobileNetV2) provide 365 indoor/outdoor scene categories that can be remapped to your genre taxonomy. Faster than CLIP but less flexible. For action vs static distinction, motion-blur detection (§2.3) and EXIF shutter-speed priors (§4.4) work well; a dedicated "action" classifier is rarely needed once you have YOLO pose estimates.

### 4.3 Subject-Detection-Based Genre Inference

Run YOLOv8n or v11n (3–6 M params, ~100 ms on CPU) to detect COCO categories. Then heuristic rules:

| Detected | Genre evidence |
|---|---|
| ≥ 1 person, person bbox area > 15 % of image | Portrait or Event |
| Multiple persons, none dominant | Event/Street/Group |
| Person + bbox < 5 % of frame | Street/Landscape with person |
| Animals (bird/dog/cat/etc.) | Wildlife |
| No people/animals + large outdoor area | Landscape |
| Single small object, image is close-up (low depth variance) | Macro |
| Buildings dominant, vertical/horizontal lines | Architecture |

These rules fuse with CLIP scores via Bayesian product-of-experts: `P(genre|image) ∝ P_CLIP × P_YOLO × P_EXIF`.

### 4.4 EXIF-Based Genre Priors

EXIF is a strong prior, not a determinant:

| Genre | Typical focal length | Typical aperture | Typical shutter | Other |
|---|---|---|---|---|
| Portrait | 50–135 mm (FF eq.) | f/1.2–f/2.8 | 1/100–1/500 | Often "Portrait" scene mode |
| Landscape | 14–35 mm | f/8–f/16 | varies (often slow with tripod) | "Landscape" mode, low ISO |
| Street | 24–50 mm | f/2.8–f/8 | 1/250–1/1000 | High ISO often |
| Wildlife | 200–800 mm | f/2.8–f/8 | 1/1000–1/4000 | Often continuous burst |
| Macro | 60–105 mm macro | f/8–f/16 | 1/100–1/250 | Very close subject distance (in EXIF MakerNotes) |
| Architecture | 14–35 mm, sometimes tilt-shift | f/8–f/11 | tripod-slow | Often low ISO |
| Event/Wedding | 24–70 mm, 70–200 mm | f/2.8–f/4 | 1/100–1/250 | Flash often on |

Build a per-genre Gaussian over (log focal length, log aperture, log shutter, log ISO) from a training corpus; use as a Bayesian prior weight. Burst-rate detection (consecutive shots within < 0.5 s) is also a strong wildlife/sports signal.

### 4.5 What Existing Tools Do

- **Aftershoot** asks the user to choose a shoot type (Portraits, Wedding, etc.) up-front; it does *not* auto-detect genre. The shoot-type selection alters default weights.
- **Narrative Select** is feature-flexible but does not advertise per-genre weighting; it focuses on faces and is admitted by its publishers to not yet have animal-eye features (Backcountry Gallery photographer report).
- **Imagen** uses a learned profile from your own past edits; the genre prior is implicit.
- **FilterPixel DeepCull** (2025) introduced explicit **Wedding Mode** trained on wedding-day sequences — confirming that genre-specific models materially improve results, but the same vendor still treats genre as a user-selected mode rather than an auto-detected one.

The proposed framework auto-detects, which is novel relative to all of these.

---

## 5. Genre-Specific Scoring Weights

For each genre, the master score is a weighted sum of normalized sub-scores (each in [0, 1]). Weights below are recommended starting points to calibrate against a held-out hand-rated set; treat them as priors, not ground truth.

### 5.1 Portrait

| Sub-score | Weight |
|---|---|
| Eye sharpness (in eye landmark region) | 0.25 |
| Facial expression quality (no closed eyes, no mid-blink, no awkward mouth) — use a facial-expression classifier or AffectNet model | 0.18 |
| Face skin tone exposure (face median L* in [110, 220], no white-balance excursion) | 0.10 |
| Background quality (low gradient energy, no distracting elements) | 0.10 |
| Bokeh / subject isolation | 0.10 |
| Subject framing (face away from edges, RoT/golden-ratio alignment, head-room) | 0.10 |
| Composition (overall RoT/balance) | 0.07 |
| Global technical (overall sharpness elsewhere, exposure non-face) | 0.10 |

Hard rejects: closed eyes both subjects (use a closed-eye detector), severe motion blur on face, severe out-of-focus on subject.

### 5.2 Landscape

| Sub-score | Weight |
|---|---|
| Front-to-back sharpness (all three depth bins above threshold) | 0.18 |
| Foreground interest (non-empty foreground depth bin with saliency present) | 0.12 |
| Horizon straightness (detect dominant horizontal line; penalize > 1° tilt unless intentional vertical orientation) | 0.10 |
| Sky quality (color variation, not clipped, dramatic clouds — detected by Places-style classifier on sky region) | 0.10 |
| Golden-hour light (low color temperature in highlights, warm gradient — detect via mean R/B ratio in highlights and color temperature estimation) | 0.10 |
| Depth layering score | 0.10 |
| Leading lines | 0.08 |
| Composition (RoT, balance, negative space) | 0.10 |
| Exposure / DR | 0.12 |

Hard rejects: blown sky covering > 40 % of frame with no clouds, crooked horizon > 5°.

### 5.3 Street Photography

| Sub-score | Weight |
|---|---|
| Decisive moment (proxy: facial expression intensity if face present; motion-vector peak otherwise) | 0.22 |
| Subject sharpness (looser threshold — accept some motion blur on subject if background is sharp) | 0.15 |
| Motion handling (penalize global blur but reward localized motion blur on a moving subject) | 0.10 |
| Subject isolation in busy scene | 0.10 |
| Composition (RoT, leading lines, frame-within-frame) | 0.15 |
| Environmental context (multiple semantic objects = richer story; use YOLO object diversity count) | 0.08 |
| Candid quality (no eye-contact penalty inverted: if direct gaze, penalize slightly; if engaged-in-action, reward) | 0.08 |
| Exposure (tolerate silhouettes, high contrast) | 0.12 |

### 5.4 Wildlife

| Sub-score | Weight |
|---|---|
| Subject eye sharpness | 0.28 |
| Subject body sharpness | 0.12 |
| Behavior capture (motion vector of subject, "interestingness" — detected via pose: eating, flying, fighting, vs static) | 0.12 |
| Clean background (low gradient energy outside subject mask) | 0.10 |
| Subject size in frame (sweet spot 8–35 % of frame area for most species; tune per detected class) | 0.10 |
| Eye-contact bonus (eye direction toward camera adds 0.05) | 0.05 |
| Composition (RoT placement of head, lead-in space in direction of subject gaze/motion) | 0.10 |
| Exposure (highlight retention on fur/feathers) | 0.13 |

### 5.5 Macro

| Sub-score | Weight |
|---|---|
| Subject sharpness at focal plane | 0.25 |
| Sharpness gradient smoothness (no abrupt transition; smooth bokeh roll-off) | 0.15 |
| DOF management (focal plane should pass through the most identifiable feature — eye for insects, stamen for flowers) | 0.15 |
| Background quality (smooth, color-harmonious — measure with bokeh "circle of confusion" uniformity) | 0.12 |
| Detail revelation (high local frequency content inside subject mask) | 0.13 |
| Composition (subject placement, negative space) | 0.10 |
| Color harmony (color-name diversity score) | 0.05 |
| Exposure | 0.05 |

### 5.6 Architecture

| Sub-score | Weight |
|---|---|
| Vertical-line correction (compute slopes of detected vertical edges; penalize keystone) | 0.18 |
| Symmetry score (often very high for architectural shots) | 0.15 |
| Leading lines (often very high) | 0.15 |
| Edge sharpness uniformly across frame | 0.15 |
| Exposure detail preservation in windows and shadows | 0.12 |
| Composition (RoT, balance) | 0.10 |
| Color/tonal harmony | 0.05 |
| Lack of unwanted people in frame | 0.10 |

### 5.7 Event / Documentary

| Sub-score | Weight |
|---|---|
| Moment capture (expression, action, emotional intensity) | 0.25 |
| Faces-open eyes count / total faces | 0.18 |
| Subject sharpness (faces region) | 0.15 |
| Composition (RoT, frame-within-frame) | 0.10 |
| Environmental context | 0.07 |
| Exposure (face exposure especially) | 0.10 |
| Action freeze (sharp moving subject for sports/dance moments) | 0.08 |
| Storytelling diversity bonus when culling a sequence (the "burst sequencing" logic of DeepCull) | 0.07 |

---

## 6. Multi-Dimensional Scoring Framework

### 6.1 Combining Multiple Scores

Three viable strategies, in increasing sophistication:

1. **Weighted linear combination** (start here). Easy to tune, interpretable, explains itself ("low score because of eye-sharpness 0.3 and expression 0.4"). FilterPixel DeepCull explicitly exposes 10 per-image sub-scores — the same transparent linear approach.
2. **Hierarchical**: gate on hard technical thresholds (severe blur, eyes-closed, severe clipping) → these go straight to *reject*; survivors are then ranked by the aesthetic linear combination.
3. **Learned aggregator**: a small gradient-boosted tree (XGBoost/LightGBM) trained on (sub-score vector, human rating) pairs. AADB-style attribute prediction shows this works; needs ≥ 5 000 hand-rated examples to be reliable.

A hybrid is best: hard gates → linear combination → optional learned re-ranker. Expose every sub-score in the UI for trust.

### 6.2 Avoiding the "Average Photo" Problem

This is the most subtle issue in computational aesthetics. Linear models trained on AVA-style mean ratings inevitably regress toward conventional, safe compositions because the *median rater* rewards "well-executed conventional" more than "boldly unconventional." Mitigations:

- **NIMA earth-mover-distance loss** (the canonical solution from Talebi & Milanfar, 2017). Predict the *distribution* of ratings instead of the mean. Images with bimodal ratings (some love, some hate) are flagged as "potentially exceptional" and can be promoted with a separate signal.
- **Standard-deviation-based "originality" score**: if multiple raters give the image, high variance = potential exceptional. At inference time we approximate this by *low confidence* of the aesthetic model — the image is unlike anything in training data.
- **Maximum-of-attributes**: compute each AADB-style attribute, take the *max* not the *sum*. An image that excels at one attribute (extraordinary color harmony, extraordinary use of negative space) can score high even if it fails at others.
- **Genre-asymmetric weights**: street and documentary tolerate technical imperfection; portrait does not. The genre router already partially addresses the average-photo trap.
- **"Outlier preservation" rule**: always include the top *one* image per duplicate-burst cluster even if its absolute score is below threshold — protects unique moments.

### 6.3 Technical vs Artistic Separation

NIMA was trained as two separate models — technical (TID2013) and aesthetic (AVA) — and Google's experiments showed AVA-trained models generalize better. Implementation guidance:

- Compute and store both separately.
- Surface as two axes in the UI ("Technical: 0.8 / Aesthetic: 0.6").
- For the final cull, use a *minimum* not a sum on these two — a technically excellent but aesthetically empty wall photo and an emotionally great but slightly blurred photo are both legitimate, but a photo failing *both* is not.

### 6.4 Duplicate / Burst Handling

The dominant industry method:

1. Compute a compact embedding (CLIP ViT-B/32 image embedding, 512-dim, or a perceptual hash like pHash + dHash).
2. Within each shoot session (same date, near-consecutive timestamps), cluster by cosine similarity > 0.92.
3. Within each cluster, keep the top-1 by master score; demote the rest to "alternate" status.
4. Optionally, allow user override per cluster (Aftershoot, Narrative both expose this).

Photographers' culling workflows confirm this is essential: "I would have expected more images in this group... [Aftershoot] found 211 duplicates. With 10–20 FPS I suspect there will be duplicates" (BCG forum, wildlife photographer).

### 6.5 How Professional Photographers Actually Cull

Synthesized from blog posts, tool documentation, and forum threads:

1. **Multi-pass culling**. Hunter & Sarah Photography, Mandi Mitchell, Katelyn James and others advocate two-pass: pass 1 removes technical failures fast (low concentration, can listen to a podcast); pass 2 makes creative selection (high concentration, no distractions). Imagen explicitly recommends 3 passes: AI pass → fast pass (trust your gut) → refinement.
2. **Cull in logical sections** (by lens, by moment, by location).
3. **Be ruthless**: a tighter gallery of 500 great photos beats 1 000 photos where half are "just okay."
4. **Backwards culling** (Katelyn James): start from the end of the shoot, where photographers typically have warmed up and have their best shots.
5. **Never edit before culling**.
6. **Trust the AI for technical, trust yourself for emotional**: a recurring theme across Aftershoot, Narrative, and Imagen reviews — AI culling "excels at technical quality assessment: sharpness, exposure, blinks, focus accuracy, near-duplicates" but "doesn't replace your storytelling eye."

Top-tier AI culling tools now claim accuracy rates above 90 % for detecting technical flaws like out-of-focus shots and closed eyes — this is the achievable accuracy bar for the technical layer of the framework.

### 6.6 NIMA, MUSIQ, and Learned Aesthetic Scoring Models

- **NIMA (Talebi & Milanfar, 2017; TIP)** — InceptionV2/MobileNetV2/VGG16 backbone, predicts 10-bin score distribution, trained on AVA (~255 k images, scores 1–10), with EMD loss. The official idealo/image-quality-assessment repo and Google's checkpoints ship MobileNetV2 variants suitable for CPU inference. **PicTomo** documents using NIMA in ONNX form on top of EfficientNet-B0 and YOLOv8n for production pipelines — confirming feasibility on modest hardware.
- **MUSIQ (Ke et al., ICCV 2021)** — transformer-based, processes native-resolution images (no resize), multi-scale tokens with hash-based 2D spatial embedding. SOTA on PaQ-2-PiQ, SPAQ, KonIQ-10k; comparable to SOTA on AVA. Heavier than NIMA but feasible at smaller scale-only inference on CPU.
- **Photo Aesthetics Ranking Network (AADB, Kong et al., ECCV 2016)** — predicts 11 photographic attributes plus an overall ranking with a ranking (Siamese) loss that captures intra-rater consistency. The per-attribute predictions are exactly the sub-scores this framework needs.
- **CLIP-based aesthetic scoring** (LAION's `aesthetic-predictor` family, Schuhmann et al.) — a small MLP head on top of CLIP ViT-L/14 embeddings, trained on AVA-like data. Very lightweight to add to a pipeline that already runs CLIP for genre detection — basically a 768-dim → 1 scalar regression.

### 6.7 IEA (Image Emotion and Aesthetics) Datasets

Beyond AVA and AADB:
- **AROD / FLICKR-AES** — aesthetic ratings from per-rater identities, allowing personalization.
- **CUHK-PQ / PN.LARGE** — earlier photo-quality datasets used in benchmark.
- **DPC-Captions / Aesthetic Captions** — image + textual aesthetic critique pairs; useful if the system needs to *explain* why a photo scored low.
- **EmoSet / FI Emotion** — affective/emotion classification.

For implementation, AADB is the most directly useful (attribute labels), AVA is the largest (good for training a generic predictor), and combining a NIMA-AVA score with attribute-specific predictors from AADB tends to outperform either alone.

---

## 7. Practical Implementation on Modest Hardware

### 7.1 Hardware Budget

The target system (i7-7500U, 2 physical cores / 4 threads, 8 GB RAM, no discrete GPU, no AVX-512) imposes:

- Total RAM for the running pipeline: ≤ 4 GB (leave 4 GB for OS and image cache).
- Per-image processing budget: ≤ 2 s end-to-end for a usable batch workflow.
- Models must fit in RAM together (no model swapping).

### 7.2 Recommended Model Stack

| Component | Model | Approx. size | Approx. CPU time at 384–512 px |
|---|---|---|---|
| Genre router | MobileCLIP-S0 (or CLIP ViT-B/32 quantized INT8) | 40–60 MB | 100–300 ms |
| Aesthetic score (overall) | NIMA-MobileNetV2 (ONNX, INT8) | 14 MB | 50–100 ms |
| Attribute scores | LAION CLIP aesthetic predictor head on CLIP embedding | 2 MB head | reuses CLIP forward |
| Subject saliency / matting | RMBG-1.4 or MODNet (ONNX) | 25–45 MB | 200–500 ms |
| Face detection | YuNet (OpenCV Zoo) or RetinaFace-MobileNet | 1–5 MB | 30–80 ms |
| Face landmarks | MediaPipe FaceMesh (468 landmarks) or a small ONNX-converted equivalent | 3–10 MB | 20–50 ms |
| Closed-eye / expression | A small EfficientNet-B0 head fine-tuned on FER+ or a face-attribute model | 5–20 MB | 50–150 ms |
| Object detector | YOLOv8n / YOLOv11n (INT8 ONNX) | 6 MB | 100–250 ms |
| Depth (optional, landscapes) | MiDaS small or Depth Anything V2 small at 256 px | 25–80 MB | 300–800 ms |
| Line detection (optional) | OpenCV LSD or Probabilistic Hough; Deep Hough only for high-effort genres | n/a | 10–50 ms |
| Classical metrics | OpenCV/NumPy/SciPy (Tenengrad, SML, FFT, histograms) | — | 20–80 ms |

Total per-image, running serially through everything, lands at roughly 1.0–2.0 s. Skip depth and Deep Hough for genres that don't need them to shave 30–50 %.

### 7.3 Can Florence-2 / CLIP Be Used Directly?

- **CLIP** — yes, and recommended. The genre router and the aesthetic predictor head both run off the same image embedding, so a single forward pass amortizes both.
- **Florence-2 (Microsoft, ~230 M params for Base, ~770 M for Large)** — too heavy for the target hardware in its native form. It's a strong general-purpose vision-language model with object detection, captioning, dense region understanding, and OCR, but realistic CPU inference is ~5–15 s per image. Use it only as an *offline* feature extractor to create training data for a smaller model — not in the live pipeline.
- **SmolVLM / Moondream2 / MobileVLM** — these smaller VLMs (≤ 2 B params, INT4 quantizable) can produce per-image captions and attribute descriptions in 3–8 s on the target CPU. Useful for an "explain this rating" feature but not for the primary scoring loop.

### 7.4 Adaptive Threshold Calibration to Hit 30–40 % Acceptance

Three nested strategies:

1. **Per-batch percentile thresholding (recommended default).** After scoring all images in a session, sort by master score; accept the top 35 % (or whatever target). This is *adaptive*: a bad shoot won't have impossible thresholds, a great shoot won't dilute selection. This is exactly how Imagen's "select the top 15 % / top 500" feature works.
2. **Per-genre percentile thresholding.** Within each detected genre, accept the top N % separately. Otherwise a portrait-heavy session would dominate landscapes when scores are not directly comparable across genres.
3. **Quality-floor + percentile.** Define an absolute hard-reject floor (severe blur, eyes-fully-closed, ≥ 80 % clipping). Then percentile-rank everything above the floor. Photographers prefer this — it ensures bad shoots don't deliver mediocre work just to hit a percentage.

A useful refinement is the **double-threshold ladder** used by Aftershoot: *Selected* (top X %), *Highlights* (top X/3 %), *Maybe* (next Y %), *Rejected* (everything else, including hard-rejects). Surface all four to the user; only auto-accept *Selected* and *Highlights*.

For sequence-aware culling (bursts), use a different rule: keep the single highest-scoring image per burst cluster regardless of absolute score, then apply the percentile threshold to the surviving non-burst images.

### 7.5 ONNX-Compatible Aesthetic Scoring Models

Verified-working ONNX exports include:

- **idealo/image-quality-assessment** (NIMA MobileNetV2 and InceptionResNetV2 variants — official Keras checkpoints convert cleanly to ONNX).
- **NIMA PyTorch (yunxiaoshi/Neural-IMage-Assessment)** — VGG/MobileNet/Inception backbones, convertible.
- **LAION CLIP-aesthetic-predictor** — a tiny MLP that runs on top of any CLIP image embedding; trivially ONNX-friendly.
- **MUSIQ** — official Google checkpoints in TF; conversion via tf2onnx works for the smaller variants.
- **TopIQ / Q-Align / CLIP-IQA** — newer transformer-based IQA models; CLIP-IQA in particular is essentially a CLIP-based zero-shot quality scorer and very fast.

PicTomo's published NSFW + quality pipeline is an existence proof of the stack: YOLOv8n + NIMA + EfficientNet-B0 all in ONNX, running on consumer hardware.

### 7.6 Pipeline Architecture (Proposed)

```
┌─────────────────────────────────────────────────────────────┐
│ 1. INGEST: EXIF parse, RAW preview extract (rawpy), thumbnail │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐    ┌─────────────────────────────┐
│ 2a. CLASSICAL METRICS    │    │ 2b. DEEP MODEL FORWARDS     │
│   – Tenengrad / SML      │    │   – CLIP image embedding   │
│   – FFT high-freq ratio  │    │   – Subject mask (RMBG)    │
│   – Histogram, zones     │    │   – Face/landmarks         │
│   – Hough lines          │    │   – YOLO objects           │
│   – Clipping, exposure   │    │   – Depth (if genre needs) │
└─────────────────────────┘    └─────────────────────────────┘
              │                               │
              └───────────────┬───────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. GENRE ROUTER                                              │
│   P(genre) = softmax( CLIP_cos · EXIF_prior · YOLO_evidence)│
└─────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. SUB-SCORES (each in [0,1], region-aware)                 │
│   composition: rot, phi, lines, symmetry, balance, neg_space│
│   sharpness:    subject_sharp, eye_sharp, dof, motion       │
│   exposure:     zones, dr, channel, face_skin               │
│   subject:      expression, closed_eyes, isolation          │
│   aesthetics:   NIMA, CLIP-aesthetic, attribute heads       │
└─────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. GENRE-WEIGHTED FUSION                                    │
│   technical_score = min(weighted sub-scores)                │
│   aesthetic_score = weighted sum (per-genre weights §5)     │
│   master_score    = f(technical, aesthetic, hard_gates)     │
└─────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. SESSION-LEVEL OPERATIONS                                 │
│   – Cluster bursts (CLIP-embedding cosine + timestamp)      │
│   – Pick top-1 per cluster                                  │
│   – Adaptive percentile threshold per genre to hit 30–40 % │
│   – Output: Selected / Highlights / Maybe / Rejected        │
└─────────────────────────────────────────────────────────────┘
```

### 7.7 Calibration and Personalization Roadmap

- **Phase 1 (cold start)**: ship with the genre-specific weights of §5 and percentile thresholds.
- **Phase 2 (calibration)**: log user accept/reject overrides. Every time the user promotes a "Rejected" or demotes a "Selected," store the per-image sub-score vector and the label.
- **Phase 3 (personalization)**: after ~500 user-labeled images, retrain a per-user logistic-regression or LightGBM model on top of the sub-scores. This is the strategy Aftershoot ("the more you use it, the better it matches your preferences") and Imagen ("Personal AI Profile") both follow, but applied per-genre rather than globally.
- **Phase 4 (drift detection)**: monitor calibration loss over time; surface to the user when the model's confidence drops.

### 7.8 Known Failure Modes and Mitigations

| Failure | Mitigation |
|---|---|
| Mis-classification of genre (e.g., a low-light portrait classified as street) | Allow user to lock the genre per album; use EXIF burst-rate and focal-length priors. |
| RAW preview JPEG is artificially sharpened or denoised differently across camera brands | Per-camera normalization of sharpness scores; or use rawpy's linear demosaic and apply a fixed pipeline. |
| Closed-eye detector false positives on Asian eye shapes, sunglasses, low light | Use a recent face-attribute model (FairFace or BLIP-2 derived) and train on diverse data. |
| Symmetric composition penalized for being "off-center" | Detect symmetry first and override balance penalty when symmetry confidence > 0.7. |
| Macro shots flagged as low-DR (no front-to-back sharpness) | Genre router routes to macro weights where front-to-back sharpness is *not* required. |
| Same-burst all-similar shots — only one is kept but it's not the photographer's preferred one | Always surface alternates per cluster; never auto-delete, only auto-rank. |
| Tilted-horizon false positives on intentional Dutch-angle street shots | Make horizon-tilt a soft penalty, and disable it entirely when genre = street. |

---

## 8. Recommended Implementation Order

1. **Skeleton**: EXIF + classical metrics (sharpness, exposure, clipping). Already gets you 60 % of the value of commercial culling tools.
2. **Genre router** with CLIP/MobileCLIP and EXIF priors.
3. **Subject mask + face detection** so sharpness and exposure become region-aware.
4. **NIMA or CLIP-aesthetic head** for the overall aesthetic axis.
5. **Composition sub-scores**: RoT and symmetry first (highest ROI per code-line), then leading lines and depth-layering.
6. **Per-genre weights** with the matrices from §5 as starting values.
7. **Burst clustering** via CLIP-embedding cosine + timestamp.
8. **Adaptive percentile thresholding** to hit the target 30–40 %.
9. **User feedback loop and personalization** (Phase 2–3 above).
10. **Optional**: Florence-2 / SmolVLM-based "explain my rating" feature for transparency.

This staged approach matches the maturity arc of the commercial tools — none of them launched with genre-specific scoring; FilterPixel only added it (DeepCull) after years of generic AI culling. Building it in from the start is a defensible differentiator and addresses the core complaint in every comparative review: "the AI doesn't understand the context of *my* genre."