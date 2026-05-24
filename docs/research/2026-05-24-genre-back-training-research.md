# Genre Detection Back-Training Research & Design Prompt

## Executive Summary

PHOTONForge's genre-aware scoring system (implemented per 2026-05-21 spec) routes images through hardcoded MobileCLIP text prototypes, EXIF priors, and YOLO object evidence. Current live deployment shows poor genre discrimination: 81% of images tag as "general", with specific genres (architecture 2, macro 5) severely under-represented. Design and prototype a **back-training mechanism** that allows the genre router to adapt to the user's photography library.

## Context & Constraints

### Existing Architecture (Read-Only)
- **Genre Router**: `src/photo_workflow/genre_router.py`
  - Hardcoded 8 genre prototypes (CLIP text embeddings): wildlife, landscape, portrait, street, architecture, macro, event, general
  - Fusion: `P(genre|image) ∝ P_CLIP(genre) * P_EXIF(genre) * P_YOLO(genre)` 
  - Confidence threshold: 0.3 → default to "general"

- **Subject Context**: `src/photo_workflow/subject_context.py`
  - Provides: CLIP image embedding (512-dim, L2-normalized), subject_mask (RMBG), faces (YuNet), detections (YOLOv8n), EXIF
  - Already computed once per image; reused by all scoring modules

- **Hardware Target**: i7-7500U (dual-core), 8GB RAM, CPU-only, no AVX-512
  - Budget: ≤ 1.5s per-image scoring
  - Fine-tuning must run offline or incrementally (not per-session on live pipeline)

- **Database**: SQLite on external SSD; already stores genre + genre_confidence per image (schema from Darktable bridge)

## Research Tasks

### Task 1: Prototype Calibration Strategy

**Question**: How should user-corrected genre labels be converted into updated CLIP prototypes?

**Explore**:
1. **Approach A — Centroid Re-Estimation**
   - Collect all images user corrects to genre G
   - Extract their CLIP embeddings from stored context
   - Compute new prototype_G = mean(embeddings[corrected_to_G])
   - Replace hardcoded prototype; measure P(genre) shift

2. **Approach B — K-Means Clustering**
   - Cluster user-corrected embeddings within each genre (k=2–3 clusters)
   - Use cluster centroids as genre sub-prototypes
   - At inference, compute max cosine similarity over sub-prototypes per genre
   - Richer but more complex; when does additional k help?

3. **Approach C — Prototype Blending**
   - `new_prototype_G = alpha * hardcoded_G + (1 - alpha) * learned_centroid_G`
   - Avoid collapse to small training set; preserve generic knowledge
   - What value of alpha minimizes overfitting while improving accuracy?

4. **Approach D — No User Correction — Auto-Calibration**
   - Use genre-confident images (confidence > 0.8) as pseudo-labeled training data
   - Assume router is correct at high confidence
   - Iteratively refine prototypes on high-confidence subset
   - Risk: systematically biased if hardcoded prototypes already favor certain genres

**Recommendation**: Propose the single most viable approach for Phase 1 with rationale. Include sample size thresholds (e.g., "re-estimate after 50+ corrections per genre") and convergence criteria.

### Task 2: Feature Engineering for Genre Discrimination

**Question**: What additional signals beyond CLIP + EXIF + YOLO help discriminate "general" from specific genres?

**Explore** (based on subject_context.py's existing fields):
1. **Subject-level features**:
   - subject_area_ratio (% of image covered by detected subject)
   - Eyes-closed heuristic from SharpnessScores (face landmarks via YuNet)
   - Face count (multiple faces → event/street, single face → portrait)
   - Animal species detected (cat/dog/bird → wildlife, not just presence)

2. **Composition/sharpness-based**:
   - Eye sharpness vs background sharpness ratio (high ratio → portrait/macro)
   - Subject isolation score (from composition module once available)
   - Blur type (bokeh → portrait/macro, motion_global → event, sharp → landscape/architecture)

3. **EXIF-derived**:
   - Subject distance (macro lenses have MakerNotes encoding; parse if available)
   - Burst rate (high rate → wildlife/sports; low rate → portrait/landscape)
   - Flash use (event/portrait indicator)

4. **Heuristic Rules** (YOLO-based, per research brief §4.3):
   - If animal detected + area > 5% → boost wildlife confidence
   - If multiple persons + none dominant → boost event/street
   - If no persons/animals + outdoor cues → boost landscape/architecture

**Evaluation**: For each feature, describe:
- Computational cost (must fit in remaining 1.5s budget)
- Discrimination power (does it help separate genres?)
- Redundancy with CLIP embedding (is it already learned implicitly?)

**Recommendation**: Prioritize top 3–5 features with highest ROI (discrimination gain per CPU ms). Propose integration point in genre_router.py (e.g., augment CLIP similarity with weighted auxiliary features).

### Task 3: Learned Adapter Design

**Question**: Should Phase 3 use logistic regression, a small tree model, or neural-network fine-tuning?

**Explore**:
1. **Logistic Regression** (per user)
   - Input: (CLIP_embedding, EXIF_prior_vector, 5 auxiliary features)
   - Output: genre class logits
   - Blending: `P_learned = softmax(lr.predict(features))`; fuse with hardcoded via `0.7 * P_hardcoded + 0.3 * P_learned`
   - Pros: interpretable, fast, tiny model (~10 KB)
   - Cons: linear decision boundary may not capture complex interactions

2. **LightGBM / XGBoost**
   - Same input/output shape
   - Pros: non-linear, handles feature interactions, proven on AADB-style attribute scoring
   - Cons: slightly heavier (~100 KB), requires sklearn ecosystem

3. **LoRA Fine-Tuning on CLIP Vision Encoder**
   - Add small adapter layers to frozen MobileCLIP
   - Fine-tune on user-corrected (image, genre) pairs
   - Pros: leverages learned representations; can adapt CLIP semantics
   - Cons: complex; requires ONNX fine-tuning support; breaks offline constraint (need live CLIP forward)

4. **Ensemble**
   - Logistic regression + hardcoded prototypes
   - No additional training; just adaptive weighting

**Recommendation**: Propose ONE approach with implementation roadmap (pseudo-code or pseudocode sketch). Include:
- Training data requirements (how many user corrections before reliable?)
- Inference overhead (milliseconds added to per-image pipeline)
- Drift monitoring (how to detect when model becomes stale?)

### Task 4: Storage & Versioning

**Question**: Where and how should user-calibrated prototypes and learned models be persisted?

**Explore**:
1. **Prototype Storage**:
   - Embed new prototypes in SQLite (genre_prototypes table) as BLOB (numpy float32 arrays)
   - Or persist in models/ directory as .npy files and reload per session?
   - Version prototypes; allow rollback if calibration degrades F1

2. **Learned Model Storage**:
   - Persist logistic regression coefficients in SQLite (3 KB per genre) or as ONNX
   - ONNX conversion: does sklearn2onnx preserve model in a way that's portable?

3. **Versioning & A/B Testing**:
   - Track "prototype version" + "adapter version" per image in Darktable
   - Allow user to compare "v1_hardcoded" vs "v2_user_calibrated" re-scoring
   - Which is the canonical version to trust for final ranking?

**Recommendation**: Propose a schema for `genre_prototypes` and `genre_adapters` tables (or equivalent SQLite structure). Include version tracking and rollback capability.

### Task 5: Feedback Collection & UI Integration

**Question**: How should users provide genre corrections, and how is feedback integrated into retraining?

**Explore**:
1. **Feedback Mechanism**:
   - User manually changes genre tag in Darktable (drop-down: wildlife | landscape | … | correct)
   - Trigger: auto-flag for retraining if confidence was low?
   - Or explicit "retrain" button in UI after each session?

2. **Retraining Cadence**:
   - Real-time: after each user correction?
   - Batch: once per session / once per 100 corrections?
   - Offline: user manually initiates calibration after importing a batch?

3. **UI Signals**:
   - Show genre_confidence as a visual indicator (bar chart? opacity?)
   - Highlight low-confidence images for user review
   - Surface "before/after" re-scoring when prototypes are updated

**Recommendation**: Sketch a workflow diagram (text or ASCII) showing feedback loop: user corrects tag → system logs correction → threshold triggers retraining → genre router updated → images re-scored. Identify which steps are live vs offline.

---

## Deliverables

Provide:
1. **Single Recommended Approach** for each of Tasks 1–5 (choose the most viable option, not all alternatives)
2. **Pseudo-Code Sketches** showing:
   - How to compute new prototypes from corrected labels
   - How to augment genre_router with auxiliary features
   - How to train and blend a learned adapter
3. **Integration Points** in existing modules (genre_router.py, pipeline.py, darktable_bridge.py) where back-training hooks attach
4. **Success Metrics** and validation plan (e.g., "Reduce 'general' tag from 81% to <15% after 500 user corrections on 3,000-image library")
5. **Risk Assessment**: What could go wrong? (overfitting on small user set, CLIP embedding drift, loss of generic knowledge?)

## References

- **Spec**: docs/superpowers/specs/2026-05-21-genre-aware-scoring-design.md (Module 2: Genre Router §4.1–4.4)
- **Research Brief**: docs/research/scoring-redesign.md (Section 4: Genre Detection §4.1, 4.4, 4.5)
- **Implementation Plan**: docs/superpowers/plans/2026-05-21-genre-aware-scoring.md (Task 3: Genre Router)
- **Related Work**:
  - CLIP zero-shot paper (Radford et al., ICML 2021)
  - Aftershoot & Narrative Select personalization (industry references in research brief §6.7)
  - AADB attribute learning (Kong et al., ECCV 2016) — proof that multi-attribute regression with user feedback improves ranking accuracy
