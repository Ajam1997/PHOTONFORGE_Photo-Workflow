# Research & References

Background research, design investigations, and reference material for PHOTONForge.

## Research Briefs

| Document | Topic | Date |
|:---|:---|:---|
| [PHOTONForge Labeling Quick Reference](photonforge-labeling-quick-reference.md) | **Canonical taxonomy** — the shipped 15 Subjects × 11 Photo Types with labeling guidance | 2026-06 |
| [Photo Tag Taxonomy Research Brief](photo-tag-taxonomy-research-brief.md) | Original two-axis taxonomy research (historical — superseded by the 15×11 quick reference) | 2026-05 |
| [Scoring Redesign](scoring-redesign.md) | Genre-aware image scoring approaches, perceptual quality metrics, IEA40K baseline (research record; §5 weights = bootstrap source) | 2026-05 |
| [Genre Detection Back-Training](2026-05-24-genre-back-training-research.md) | Genre Detection Back-Training | 2026-05 |
| [Backbone Aesthetic Transfer Brief](2026-06-19-backbone-aesthetic-transfer-brief.md) | Aesthetic-head transfer learning on the CLIP backbone | 2026-06 |

---

## Adding New Research

Drop Markdown files into `dev-docs/research/` and add a row to the table above.

Suggested format for a research brief:

```markdown
# [Topic] Research Brief

**Date:** YYYY-MM-DD
**Author:** @handle
**Status:** Draft | Final

## Question
What are we trying to answer?

## Findings
...

## References
- [Title](url)
```
