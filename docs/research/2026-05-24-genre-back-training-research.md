# Genre Detection Back-Training Research Brief

**Date:** 2026-05-24
**Author:** @architect
**Status:** Final

---

## Question

How should PHOTONForge's genre router adapt to a user's photography library when 81% of images currently classify as "general"? Specifically: what calibration strategy converts user corrections into updated CLIP prototypes, which auxiliary features improve genre discrimination, what learned adapter architecture fits the hardware constraints, and how should persistence, versioning, and feedback collection integrate into the existing pipeline?

---

## Findings

### Task 1: Prototype Calibration Strategy

**Recommended Approach: C -- Prototype Blending with Decay**

The research literature on CLIP few-shot adaptation strongly supports a blended prototype approach over pure centroid re-estimation. Proto-Adapter (Kato et al., 2024) demonstrates that constructing adapter weights from class prototypes -- computed as the mean of few-shot image embeddings -- matches or outperforms more complex cache-based methods like Tip-Adapter, even in extremely low-shot settings (1-4 examples per class). However, pure mean-of-user-corrections (Approach A) risks catastrophic forgetting of the hardcoded zero-shot knowledge when the user correction set is small or biased toward a specific sub-genre.

The CLAP framework (Silva-Rodriguez et al., CVPR 2024) formalizes this intuition: it constrains a learned linear probe to remain close to the zero-shot prototypes per class, explicitly trading off adaptation vs. knowledge retention. FewCLIP (2025) extends this with probabilistic regularization over calibration prototypes, demonstrating that distributional constraints prevent overfitting on limited novel-class data.

The blending formula is:

```
prototype_G = alpha * hardcoded_G + (1 - alpha) * learned_centroid_G
```

Where `alpha` decays as user corrections accumulate:

```python
def compute_alpha(n_corrections: int, decay_rate: float = 0.02) -> float:
    """Blend factor: starts at 1.0 (trust hardcoded), decays toward 0.3."""
    return max(0.3, 1.0 - decay_rate * n_corrections)
```

- At 0 corrections: alpha = 1.0, pure hardcoded prototype
- At 15 corrections: alpha = 0.7, blended
- At 35+ corrections: alpha = 0.3, floor -- never fully abandon hardcoded knowledge

**Sample size thresholds:**
- Re-estimate after 10+ corrections per genre (minimum viable centroid)
- Stable convergence expected at 30-50 corrections per genre
- Confidence monitoring: track inter-session F1 on validation hold-out (10% of corrected labels reserved)

**Convergence criterion:** Stop updating prototype when F1 on held-out corrections stabilizes within +/-0.02 for 3 consecutive re-estimation rounds.

**Why not Approach D (auto-calibration)?** The 81% "general" classification rate means high-confidence predictions are systematically biased toward the dominant class. Auto-calibrating on these would reinforce the existing failure mode. User corrections are the necessary ground-truth signal.

**Pseudo-code:**

```python
def recalibrate_prototypes(
    corrections: list[tuple[np.ndarray, str]],  # (clip_embedding, corrected_genre)
    hardcoded_prototypes: dict[str, np.ndarray],
    min_samples: int = 10
) -> dict[str, np.ndarray]:
    updated = {}
    for genre, proto in hardcoded_prototypes.items():
        genre_embeddings = [emb for emb, g in corrections if g == genre]
        if len(genre_embeddings) < min_samples:
            updated[genre] = proto  # not enough data, keep hardcoded
            continue
        learned_centroid = np.mean(genre_embeddings, axis=0)
        learned_centroid = learned_centroid / np.linalg.norm(learned_centroid)
        alpha = compute_alpha(len(genre_embeddings))
        blended = alpha * proto + (1 - alpha) * learned_centroid
        blended = blended / np.linalg.norm(blended)  # re-normalize
        updated[genre] = blended
    return updated
```

### Task 2: Feature Engineering for Genre Discrimination

**Top 5 features by ROI (discrimination gain per CPU millisecond):**

| Rank | Feature | Cost | Discrimination Power | Redundancy with CLIP |
|:---|:---|:---|:---|:---|
| 1 | Face count (from YuNet, already computed) | ~0 ms (reuse) | High. 0 faces rules out portrait. 3+ faces strong event signal. | Low -- CLIP sees faces but doesn't count them reliably. |
| 2 | Subject area ratio (bbox area / image area, from YOLO) | ~0 ms (reuse) | High. Large subject (>15%) = portrait/macro. Tiny subject (<3%) = landscape/street. | Medium -- CLIP implicitly encodes subject prominence but not as a scalar. |
| 3 | Sharpness contrast ratio (subject Tenengrad / background Tenengrad) | ~20 ms | High. Ratio > 3.0 = intentional bokeh (portrait/macro). Ratio ~ 1.0 = landscape/architecture. | Low -- CLIP does not encode sharpness properties. |
| 4 | EXIF focal length bucket (wide/normal/tele/supertele) | ~0 ms (parse) | Medium-high. Supertele (>200mm) is near-definitive wildlife. Wide (<24mm) strongly favors landscape/architecture. | Low -- CLIP has no EXIF awareness. |
| 5 | Animal class presence (YOLO bird/cat/dog/etc. vs. just "animal") | ~0 ms (reuse YOLO detections) | Medium. Specific animal classes boost wildlife confidence differentially (bird in sky = landscape, bird close-up = wildlife). | Medium -- CLIP detects animals but doesn't subclassify well at small subject sizes. |

**Dropped candidates:**
- Burst rate (requires timestamp parsing across multiple images -- cross-image feature, doesn't fit per-image pipeline)
- Flash detection (only in specific MakerNotes, not universally available, low discrimination for non-event genres)
- Subject distance from MakerNotes (too camera-specific, unreliable across brands)

**Integration point:** Augment the fusion in `genre_router.py` from the current three-way product:

```
P(genre|image) ∝ P_CLIP * P_EXIF * P_YOLO
```

to a five-signal product:

```
P(genre|image) ∝ P_CLIP * P_EXIF * P_YOLO * P_subject_context * P_sharpness_profile
```

Where `P_subject_context` is computed from face_count + subject_area_ratio + animal_class, and `P_sharpness_profile` is computed from the sharpness contrast ratio mapped to a per-genre Gaussian likelihood.

Total additional compute: ~20 ms per image (only the sharpness contrast ratio is new computation; everything else reuses existing subject_context.py outputs).

### Task 3: Learned Adapter Design

**Recommended Approach: Logistic Regression, ONNX-exported**

The research is clear on this point: for few-shot CLIP adaptation with 8 classes and ~50-500 user corrections, logistic regression on top of CLIP embeddings is the academically validated baseline. Linear-probe CLIP (Radford et al., 2021) established that a logistic regression classifier trained on CLIP image features achieves competitive accuracy with far more complex adaptation methods. CLAP (CVPR 2024) showed that constraining the linear probe to stay near zero-shot prototypes prevents overfitting. Proto-Adapter (2024) demonstrated that prototype-based constant-size adapters outperform variable-size cache models.

The logistic regression approach is overwhelmingly preferred for this use case because of inference overhead. ONNX-exported sklearn logistic regression achieves inference in ~0.3 ms per sample (confirmed by ONNX Runtime benchmarks), compared to sklearn's native ~16 ms. The model size is ~10 KB for 8 classes with a 517-dimensional input vector (512 CLIP + 5 auxiliary features). LightGBM would add ~100 KB and marginal accuracy gains that don't justify the added dependency. LoRA fine-tuning on the CLIP vision encoder is categorically ruled out: it requires backpropagation through the frozen encoder, breaks the ONNX inference path, and demands far more corrections than a user will realistically provide.

**Blending at inference:**

```python
def fused_genre_prediction(
    clip_embedding: np.ndarray,
    aux_features: np.ndarray,  # [face_count, subj_area, sharp_ratio, focal_bucket, animal_class]
    prototype_scores: np.ndarray,  # from blended prototypes (Task 1)
    adapter_session: ort.InferenceSession | None,
    blend_weight: float = 0.3
) -> np.ndarray:
    if adapter_session is None:
        return prototype_scores
    features = np.concatenate([clip_embedding, aux_features]).reshape(1, -1).astype(np.float32)
    adapter_probs = adapter_session.run(None, {"X": features})[1]  # predict_proba
    adapter_probs = np.array([adapter_probs[0][g] for g in range(8)])
    return (1 - blend_weight) * prototype_scores + blend_weight * adapter_probs
```

**Training data requirements:**
- Minimum viable: 80 corrections total (10 per genre)
- Reliable: 400+ corrections (50 per genre)
- The adapter is retrained from scratch each calibration round (fast -- <1s for logistic regression on 400 samples)

**Inference overhead:** ~0.3 ms per image (ONNX logistic regression). Negligible against the 1.5s budget.

**Drift monitoring:** After each calibration, compute F1 on 10% held-out corrections. Log F1 per genre to `docs/ValidationReports/genre_calibration_log.md`. Alert user if any genre F1 drops below 0.5 after a recalibration (indicates conflicting corrections or domain shift).

**ONNX export:**

```python
from skl2onnx import to_onnx
from sklearn.linear_model import LogisticRegression

lr = LogisticRegression(max_iter=500, C=1.0)
lr.fit(X_train, y_train)
onx = to_onnx(lr, X_train[:1].astype(np.float32))
with open("genre_adapter.onnx", "wb") as f:
    f.write(onx.SerializeToString())
```

### Task 4: Storage and Versioning

**Recommended Schema:**

Two new tables in the cartridge's SQLite database (alongside library.db, or in a separate `photonforge.db`):

```sql
CREATE TABLE genre_prototypes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL,
    genre TEXT NOT NULL,
    prototype BLOB NOT NULL,         -- numpy float32 array, 512 dims, as bytes
    n_corrections INTEGER DEFAULT 0,
    alpha REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now')),
    is_active INTEGER DEFAULT 1,
    UNIQUE(version, genre)
);

CREATE TABLE genre_corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_path TEXT NOT NULL,
    clip_embedding BLOB NOT NULL,    -- numpy float32 array, 512 dims
    original_genre TEXT NOT NULL,
    corrected_genre TEXT NOT NULL,
    confidence_original REAL,
    corrected_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE genre_adapter (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL,
    model_onnx BLOB NOT NULL,        -- serialized ONNX model (~10 KB)
    n_training_samples INTEGER,
    f1_score REAL,
    created_at TEXT DEFAULT (datetime('now')),
    is_active INTEGER DEFAULT 1
);
```

**Versioning and rollback:**
- Each recalibration increments `version` and sets the new row as `is_active = 1`, previous as `is_active = 0`.
- Rollback: `UPDATE genre_prototypes SET is_active = 1 WHERE version = N; UPDATE genre_prototypes SET is_active = 0 WHERE version > N;` (same for adapter).
- Images store `genre_prototype_version` and `genre_adapter_version` in the Darktable bridge metadata so re-scoring can be traced to a specific model state.

**A/B comparison:** The UI can expose a "Compare versions" mode: re-score a sample batch with v1 (hardcoded) vs. vN (calibrated) and display side-by-side genre distributions. The canonical version for final ranking is always the highest active version.

**Storage location:** `photonforge.db` on the cartridge alongside `library.db`. This keeps calibration portable -- each cartridge can have its own calibration state, or a single "master" calibration can be copied across cartridges.

### Task 5: Feedback Collection and UI Integration

**Recommended Workflow:**

```
USER CORRECTS TAG (Darktable or Tauri UI)
        |
        v
System logs correction to genre_corrections table
        |
        v
Correction count check: >= threshold per genre? (10 minimum)
        |                                    |
        NO                                  YES
        |                                    |
        v                                    v
    Wait for more             BATCH RECALIBRATION (offline)
    corrections               1. Load all corrections from DB
                              2. Extract CLIP embeddings (already stored)
                              3. Compute blended prototypes (Task 1)
                              4. Train logistic regression (Task 3)
                              5. Export to ONNX
                              6. Store new version in genre_prototypes + genre_adapter
                              7. Set is_active = 1
                              |
                              v
                   OPTIONAL RE-SCORE (user-triggered)
                   1. User clicks "Apply updated genre model"
                   2. Pipeline re-runs genre_router on all images
                      with updated prototypes + adapter
                   3. Display before/after comparison
                   4. User confirms or rolls back
```

**Retraining cadence:** Batch, not real-time. Recalibration triggers when the user explicitly requests it OR when accumulated corrections since last calibration exceed a threshold (e.g., 20 new corrections). Never recalibrate during a live ingest pipeline run -- it's an offline operation.

**Feedback mechanism:** Two paths:
1. **Darktable tag correction:** User changes the genre tag in Darktable's keyword panel. The darktable_bridge detects the mismatch on next sync and logs to `genre_corrections`.
2. **Tauri UI dropdown:** Library Browser panel shows genre badge per image. User clicks badge -> dropdown -> selects correct genre. Logged immediately.

**UI signals:**
- Genre confidence rendered as opacity on the genre badge (high confidence = solid, low = faded)
- Images with confidence < 0.4 get a "?" overlay suggesting user review
- After recalibration, a toast notification: "Genre model updated (v3). 247 images re-classified. Review changes?"

### Success Metrics and Validation Plan

**Primary metric:** Reduce "general" tag rate from 81% to <15% after 500 user corrections across a 3,000-image library.

**Per-genre targets:**
- Each of the 7 specific genres should represent >= 5% of classified images (assuming a reasonably diverse library)
- Per-genre F1 on held-out corrections >= 0.7
- Total classification accuracy on user-corrected test set >= 85%

**Validation plan:**
1. Baseline: run current hardcoded router on 500 hand-labeled images. Record per-genre precision/recall/F1.
2. After 100 corrections: recalibrate, re-score same 500 images. Measure improvement.
3. After 300 corrections: recalibrate again. Expect "general" rate < 30%.
4. After 500 corrections: final recalibration. Expect "general" rate < 15%, overall F1 > 0.85.
5. Regression test: ensure no genre that was previously well-classified (e.g., portrait via face detection) degrades.

### Risk Assessment

| Risk | Severity | Mitigation |
|:---|:---|:---|
| Overfitting on small user set -- user only shoots wildlife, calibration collapses other genres | High | Alpha floor at 0.3 preserves hardcoded knowledge. Per-genre minimum sample threshold prevents re-estimation with < 10 examples. |
| CLIP embedding drift across model versions | Medium | Pin MobileCLIP version. If model is updated, invalidate all stored embeddings and re-extract (expensive but rare). |
| User corrections are inconsistent (same image tagged "street" then "event") | Medium | Log all corrections with timestamps. Last-write-wins for prototype computation. Surface conflicting corrections in UI for user resolution. |
| Systematic bias: user's "landscape" definition differs from CLIP's training distribution | Low | Prototype blending naturally adapts to user's semantic boundaries. This is a feature, not a bug. |
| Loss of generic knowledge after many calibrations | Medium | Alpha floor (0.3) ensures hardcoded prototypes always contribute. Rollback capability to v1 (hardcoded) preserved. |
| Genre router improvement masks underlying scoring issues (low scores across all genres) | Low | Genre classification and scoring are architecturally separate. Scoring quality tracked independently via KPM-1.2/1.3. |
| Calibration data stored on cartridge lost if cartridge fails | Low | Export calibration state (genre_corrections + prototypes) as JSON backup during safe_eject. |

---

## References

- [Proto-Adapter: Efficient Training-Free CLIP-Adapter for Few-Shot Image Classification](https://pmc.ncbi.nlm.nih.gov/articles/PMC11175357/) -- Kato et al., Sensors 2024. Prototype-based constant-size adapter outperforms Tip-Adapter.
- [Tip-Adapter: Training-free Adaption of CLIP for Few-shot Classification](https://arxiv.org/pdf/2207.09519) -- Renrui Zhang et al., ECCV 2022. Key-value cache model for CLIP adaptation; baseline for comparison.
- [CLAP: A Closer Look at the Few-Shot Adaptation of Large Vision-Language Models](https://github.com/jusiro/CLAP) -- Silva-Rodriguez et al., CVPR 2024. Constrained linear probing that retains zero-shot prototype knowledge.
- [FewCLIP: Probabilistic Prototype Calibration for Generalized Few-shot Semantic Segmentation](https://arxiv.org/pdf/2506.22979) -- 2025. Distributional regularization prevents overfitting on limited novel-class data.
- [Proto-CLIP: Vision-Language Prototypical Network for Few-Shot Learning](https://irvlutd.github.io/Proto-CLIP/) -- IROS 2024. Joint image/text prototype adaptation.
- [Logits DeConfusion with CLIP for Few-Shot Learning](https://openaccess.thecvf.com/content/CVPR2025/papers/Li_Logits_DeConfusion_with_CLIP_for_Few-Shot_Learning_CVPR_2025_paper.pdf) -- CVPR 2025. Multi-level adapter fusion with inter-class deconfusion.
- [Accelerate Scikit-learn Model Inference with ONNX Runtime](https://opensource.microsoft.com/blog/2020/12/17/accelerate-simplify-scikit-learn-model-inference-onnx-runtime/) -- Microsoft, 2020. Confirms ~50x speedup for sklearn models via ONNX export.
- [sklearn-onnx Documentation](https://onnx.ai/sklearn-onnx/introduction.html) -- ONNX export for LogisticRegression, verified working pipeline.
- [CLIP (Learning Transferable Visual Models From Natural Language Supervision)](https://arxiv.org/abs/2103.00020) -- Radford et al., ICML 2021. Foundation reference for zero-shot classification and linear-probe baselines.
- [AADB: Photo Aesthetics Ranking Network with Attributes and Content Adaptation](https://arxiv.org/abs/1606.01621) -- Kong et al., ECCV 2016. Per-attribute prediction with user feedback improves ranking.
