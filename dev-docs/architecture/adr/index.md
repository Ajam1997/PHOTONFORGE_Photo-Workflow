# Architecture Decision Records

Short records of non-obvious decisions (Status / Context / Decision /
Consequences, ~20 lines each). New ADRs are numbered sequentially; a
superseded/retired design gets an ADR when the "why" isn't obvious from the
diff (see the docs-impact matrix in
[doc-maintenance-protocol.md](../doc-maintenance-protocol.md)).

| ADR | Title | Status |
|---|---|---|
| [ADR-001](ADR-001-stage6-five-module-split-superseded.md) | Stage-6 five-module scoring split superseded by the `score_fusion.py` monolith | Accepted |
| [ADR-002](ADR-002-taxonomy-evolution-15x11.md) | Genre taxonomy evolution to 15 Subjects × 11 Photo Types | Accepted |
| [ADR-003](ADR-003-udisks2-polling-over-udev.md) | udisks2 auto-mount + polling instead of udev rules | Accepted |
| [ADR-004](ADR-004-darktable-lua-plugin-over-tauri-and-tk.md) | Darktable Lua plugin as the GUI; Tauri chain and Tk manager retired | Accepted |
| [ADR-005](ADR-005-r2-captioner-lfm2.md) | R2 captioner: LFM2-VL-450M grounded; Florence-2 until then; NIMA deleted; no depth model | Accepted (R2) |
| [ADR-006](ADR-006-per-type-weights-vs-scenerecord.md) | Per-Type weight calibration vs R2 SceneRecord per-region scoring | **OPEN** |
