# FR-1.7: Genre Detection Calibration and Back-Training

## Problem

Current genre detection produces excessive "general" tags:
- **3,770 images tagged "general"** (81% of library)
- Landscape: 14, Wildlife: 240, Architecture: 2, Macro: 5, Street: 13
- Indicates insufficient discrimination between genres in live classification

## Root Cause

The Genre-Aware Scoring system uses hardcoded MobileCLIP text prototypes ("a photograph of a cat", "a wide landscape photograph") + EXIF priors + YOLO evidence. These generic prototypes are not fine-tuned to actual photography and have no mechanism to adapt based on observed classification errors in the user's library.

## Proposed Solution

Support **genre classifier calibration and back-training** via:

1. **Prototype Fine-Tuning** — Collect user-corrected genre labels, re-estimate CLIP prototypes as centroids of corrected embeddings
2. **Feature Augmentation** — Use subject_area_ratio, eye sharpness, face/animal presence to boost discrimination
3. **Learned Adapter** — Train logistic regression or LightGBM on user feedback; blend with hardcoded prototypes
4. **Versioning** — Track prototype versions; allow rollback if calibration degrades accuracy
5. **UI Integration** — Expose genre_confidence; flag low-confidence images for review; integrate feedback loop

## Modules to Touch

- `src/photo_workflow/genre_router.py`: Add calibration functions, parameter for prototype source
- `src/photo_workflow/score_fusion.py`: Track genre_confidence; flag weak predictions
- `src/photo_workflow/darktable_bridge.py`: New XMP field `photon:GenreUserCorrected`
- `[NEW] src/photo_workflow/genre_trainer.py`: Prototype clustering, adapter training, calibration logic
- `[NEW] tests/test_genre_trainer.py`: Unit tests for calibration logic

## Success Criteria

- Reduce "general" tag count to < 10% of library
- Genre confidence distribution shifts right (more images > 0.6 confidence)
- Back-training produces measurable F1 lift on hold-out test set
- Manual genre override rate drops below 5% after calibration on 500+ images

## Research & Design

Detailed research prompt with 5 key tasks and exploration of design trade-offs:  
→ [docs/research/2026-05-24-genre-back-training-research.md](../research/2026-05-24-genre-back-training-research.md)

## References

- **Spec**: docs/superpowers/specs/2026-05-21-genre-aware-scoring-design.md (Module 2: Genre Router §4.1–4.4)
- **Research Brief**: docs/research/scoring-redesign.md (Section 4: Genre Detection §4.1, 4.4, 4.5)
- **Implementation Plan**: docs/superpowers/plans/2026-05-21-genre-aware-scoring.md (Task 3: Genre Router)
