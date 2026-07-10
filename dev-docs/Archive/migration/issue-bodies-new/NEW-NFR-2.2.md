**Parent UN:** UN-030

**Specification:** Resource budget for the full scoring pipeline on the i7-7500U target:
- Peak RSS <= 1.5 GB during the score stage (CLIP + YOLO + Florence-2 INT8 all resident)
- Peak CPU <= 80% of available logical cores (leave headroom for the Darktable UI)

**Linked Budget:** NONE (this NFR *is* the resource budget)

**Verified By:**
- (none yet)

**Validated By:**
- (none yet)

_Created in Phase 4 to parent KPM-1.3 (Peak RSS) and KPM-1.9 (CPU Cap), which previously cited a nonexistent NFR-2.2. Constraint defined in CLAUDE.md (NFR-2.2)._
