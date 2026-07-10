# Module Block Definition Diagram

The SysML **Block Definition Diagram (BDD)** for `src/photo_workflow/`.
Shows the structural composition: which modules contain / compose
which, and the typed «flow items» (dataclasses from
`scoring_types.py`) that travel between them.

This is the "what's in the box" view. For "what flows through the box,"
see [pipeline-activity.md](pipeline-activity.md).

## Top-level composition

```mermaid
classDiagram
    direction LR

    class AnalysisPipeline {
        +run(src, dst, db_path)
        -orchestrate per-photo
    }

    class IngestSubsystem {
        ingest.py
        volume.py
        cartridge.py
    }

    class GroupingSubsystem {
        grouping.py
        dedup.py
    }

    class ScoringSubsystem {
        sharpness.py
        composition.py
        exposure.py
        subject_context.py
        genre_router.py
        score_fusion.py
        scoring_types.py
    }

    class NamingSubsystem {
        naming.py
    }

    class PersistenceSubsystem {
        darktable_bridge.py
        photondb.py
        raw_loader.py
    }

    class TrainingSubsystem {
        genre_trainer.py
        training_weights_db.py
    }

    class HostSubsystem {
        provision.py
    }

    AnalysisPipeline *-- IngestSubsystem : composes
    AnalysisPipeline *-- GroupingSubsystem : composes
    AnalysisPipeline *-- ScoringSubsystem : composes
    AnalysisPipeline *-- NamingSubsystem : composes
    AnalysisPipeline *-- PersistenceSubsystem : composes
    ScoringSubsystem ..> TrainingSubsystem : reads weights
    IngestSubsystem ..> HostSubsystem : provisions cartridges
```

`*--` is composition (subsystems belong to AnalysisPipeline);
`..>` is dependency (a read-only reference).

## Scoring subsystem — internal block diagram

```mermaid
classDiagram
    direction TB

    class SubjectContext {
        +faces: list[FaceDetection]
        +objects: list[ObjectDetection]
        +primary_subject: str
    }
    class SharpnessScores {
        +overall: float
        +subject_region: float
    }
    class CompositionScores {
        +rule_of_thirds: float
        +symmetry: float
    }
    class ExposureScores {
        +entropy: float
        +zone_distribution: list[float]
    }
    class GenreResult {
        +primary: str
        +secondary: list[str]
        +confidence: float
    }
    class FusionResult {
        +master_score: float
        +technical: float
        +aesthetic: float
        +sub_scores: dict
    }

    class build_subject_context
    class score_sharpness
    class score_composition
    class score_exposure
    class route_genre
    class fuse_scores

    build_subject_context ..> SubjectContext : produces
    score_sharpness ..> SharpnessScores : produces
    score_composition ..> CompositionScores : produces
    score_exposure ..> ExposureScores : produces
    route_genre ..> GenreResult : produces

    SubjectContext --> score_sharpness : informs
    SubjectContext --> score_composition : informs
    SubjectContext --> score_exposure : informs
    SubjectContext --> route_genre : informs

    SharpnessScores --> fuse_scores
    CompositionScores --> fuse_scores
    ExposureScores --> fuse_scores
    GenreResult --> fuse_scores
    fuse_scores ..> FusionResult : produces
```

This is the «definition» layer — every typed dataclass shown here is
the «flow item» on the corresponding arrow in
[pipeline-activity.md](pipeline-activity.md).

## Persistence subsystem

```mermaid
classDiagram
    direction LR

    class darktable_bridge {
        +sync_to_darktable(photo, scores, name)
    }
    class library_db {
        SQLite
        on cartridge
        /mnt/photon_ssd/XXX/darktable/library.db
    }
    class xmp_sidecar {
        per-photo .xmp file
        on cartridge
    }
    class photondb {
        +ensure_table()
        +insert_photo()
        +update_stages()
    }
    class photonforge_db {
        SQLite
        per-cartridge progress tracking
    }
    class raw_loader {
        +load(path)
        rawpy wrapper
    }

    darktable_bridge --> library_db : writes
    darktable_bridge --> xmp_sidecar : writes
    photondb --> photonforge_db : owns
    AnalysisPipeline --> photondb : tracks progress
    AnalysisPipeline --> raw_loader : decodes RAWs
```

## Cartridge subsystem

```mermaid
classDiagram
    direction LR

    class cartridge {
        +manage_cartridge()
    }
    class volume {
        +extract_cartridge_id()
        +get_volume_label()
    }
    class provision {
        +bootstrap_cartridge()
        formats fresh PHOTON-XXX
    }

    cartridge *-- volume
    cartridge ..> provision : on first use
```

## SysML traceability

| Block | Implements | Verified By |
|---|---|---|
| `IngestSubsystem` | FR-1.1 | KPM-1.1, tests/test_ingest.py |
| `GroupingSubsystem` | FR-1.2, FR-1.3 | KPM-1.6, KPM-1.10, tests/test_grouping.py, tests/test_dedup.py |
| `ScoringSubsystem` | FR-1.4, FR-1.5, FR-1.6, FR-1.7.1, FR-1.7.2 | KPM-1.8, tests/test_sharpness.py, tests/test_composition.py, tests/test_exposure.py |
| `NamingSubsystem` | FR-1.7 | KPM-1.2, KPM-1.7, tests/test_naming.py |
| `PersistenceSubsystem` | FR-1.8, NFR-2.3 | tests/test_darktable.py, tests/test_photondb.py |
| `cartridge` subsystem | FR-1.9, FR-1.10, NFR-2.3 | KPM-1.4, tests/test_cartridge.py |

The V&V matrix in `dev-docs/photonforge-architecture.md` §3.4 is the
machine-readable form of this table; this diagram is the «structural»
view of the same evidence.
