# FR-1.7.1: Multi-Genre Tagging Support

## Problem

Current genre detection assigns a **single genre per image** based on highest confidence. However, many photos legitimately belong to multiple genres:
- Wildlife portrait (wildlife + portrait)
- Street landscape (street + landscape)  
- Architectural landscape (architecture + landscape)
- Event documentation (event + street)

Single-genre labeling:
- Loses semantic information
- Forces artificial genre boundaries
- Limits genre-specific scoring weight fusion (e.g., portraits with landscape backgrounds get penalized for lacking DOF)
- Reduces flexibility for user curation workflows

## Proposed Solution

Support **multi-genre tagging** by storing the top N highest-confidence genres per image:

1. **Router Output** — Change `GenreResult` to return `top_genres: list[tuple[str, float]]` instead of single `genre: str`
   - Keep top 3 genres with confidence > threshold (e.g., 0.2)
   - Or always return top 3 regardless of confidence

2. **Score Fusion** — Blend weights from multiple genres:
   - `effective_weights = sum(confidence[g] * GENRE_WEIGHTS[g] for g in top_genres)`
   - Normalize by sum of confidences
   - Result: master score reflects blend of all detected genres

3. **Database Schema** — Store multiple genres:
   ```sql
   ALTER TABLE [folder] ADD COLUMN genres TEXT DEFAULT '';  -- JSON: [{"genre": "wildlife", "confidence": 0.87}, ...]
   ALTER TABLE [folder] ADD COLUMN primary_genre TEXT DEFAULT '';  -- Fallback for single-genre queries
   ```

4. **Darktable Bridge** — Write multiple genres to XMP:
   ```xml
   <photon:Genres>
     <rdf:Seq>
       <rdf:li>
         <rdf:Description>
           <photon:Genre>wildlife</photon:Genre>
           <photon:Confidence>0.87</photon:Confidence>
         </rdf:Description>
       </rdf:li>
       <rdf:li>
         <rdf:Description>
           <photon:Genre>portrait</photon:Genre>
           <photon:Confidence>0.62</photon:Confidence>
         </rdf:Description>
       </rdf:li>
     </rdf:Seq>
   </photon:Genres>
   ```

5. **UI Visualization** — In Darktable:
   - Show genres as comma-separated tags: `wildlife, portrait, landscape`
   - Show confidence alongside: `wildlife (0.87), portrait (0.62)`
   - Allow user to remove low-confidence genres or reorder priorities

## Modules to Touch

- `src/photo_workflow/scoring_types.py`: Modify `GenreResult` dataclass
- `src/photo_workflow/genre_router.py`: Change `route_genre()` to return top-N; update confidence threshold logic
- `src/photo_workflow/score_fusion.py`: Update `fuse_scores()` to blend weights from multiple genres
- `src/photo_workflow/darktable_bridge.py`: Update XMP template for multi-genre output; update `compute_color_label()` logic if needed
- `src/photo_workflow/photondb.py`: Update schema and `ensure_table()` to support JSON genres field
- `tests/test_genre_router.py`: Add tests for top-N genre output
- `tests/test_score_fusion.py`: Add tests for multi-genre weight fusion

## Implementation Options

### Option A: Top-N with Confidence Floor
```python
def route_genre(ctx, threshold=0.2) -> list[tuple[str, float]]:
    """Return all genres with confidence > threshold, sorted by confidence."""
    distribution = {g: p for g, p in fused.items() if p >= threshold}
    return sorted(distribution.items(), key=lambda x: x[1], reverse=True)
```
- **Pro**: Adaptive (low-confidence genres filtered out)
- **Con**: Unpredictable count per image (0–8 genres)

### Option B: Top-3 Unconditional
```python
def route_genre(ctx, top_k=3) -> list[tuple[str, float]]:
    """Return top K genres by confidence."""
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)[:top_k]
```
- **Pro**: Consistent output; always 3 genres to work with
- **Con**: May include low-confidence genres (e.g., "general" at 0.25 confidence)

### Option C: Hybrid (Top-3 with Floor)
```python
def route_genre(ctx, top_k=3, threshold=0.15) -> list[tuple[str, float]]:
    """Return up to top K genres with confidence > threshold."""
    candidates = {g: p for g, p in fused.items() if p >= threshold}
    return sorted(candidates.items(), key=lambda x: x[1], reverse=True)[:top_k]
```
- **Pro**: Balances consistency and quality
- **Con**: Still variable output

**Recommendation**: Start with **Option C (top-3 with 0.15 floor)**. Provides 1–3 genres per image in most cases.

## Score Fusion Behavior

Current (single genre):
```python
master_score = dot_product(GENRE_WEIGHTS[genre], sub_scores)
```

Multi-genre:
```python
genre_weights = {}
total_confidence = sum(conf for _, conf in top_genres)
for genre, conf in top_genres:
    for key, weight in GENRE_WEIGHTS[genre].items():
        genre_weights[key] = genre_weights.get(key, 0) + (conf / total_confidence) * weight

master_score = dot_product(genre_weights, sub_scores)
```

Result: Master score reflects blend of all genres. E.g., a wildlife portrait scored on 80% wildlife weights + 20% portrait weights.

## Success Criteria

- Images with multiple valid genres now capture all of them
- Master score improves (or stays stable) for multi-genre images
- User manual genre corrections drop for images previously mis-assigned to single genre
- Darktable XMP metadata stores all genres for future re-processing

## Backward Compatibility

- `primary_genre` field preserves single-genre for tools that expect it (fallback to highest-confidence genre)
- `GenreResult.genre` property returns `primary_genre` for existing code
- Database migration: `UPDATE [folder] SET primary_genre = (SELECT json_extract(genres, '$[0].genre'))`

## Links

- **Related Issue**: FR-1.7 Genre Detection Calibration and Back-Training
- **Spec**: docs/superpowers/specs/2026-05-21-genre-aware-scoring-design.md (Module 2: Genre Router)
