"""AnalysisPipeline — orchestrates all photo workflow stages."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    source_dir: Path
    output_dir: Path
    darktable_db: Path
    model_dir: Path = Path("models")
    dry_run: bool = False


@dataclass
class PhotoRecord:
    """Shared state passed through each pipeline stage."""
    path: Path
    session_id: str = ""
    is_duplicate: bool = False
    sharpness_score: float = 0.0
    composition_score: float = 0.0
    exposure_score: float = 0.0
    semantic_name: str = ""
    metadata: dict = field(default_factory=dict)


class AnalysisPipeline:
    """Orchestrates ingest → group → dedup → score → name → catalog."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self._setup_logging()

    def _setup_logging(self) -> None:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    def run(self) -> list[PhotoRecord]:
        """Execute the full pipeline and return processed records."""
        from .ingest import ingest_volume
        from .grouping import cluster_sessions
        from .dedup import deduplicate
        from .sharpness import score_sharpness
        from .composition import score_composition
        from .exposure import score_exposure
        from .naming import generate_name
        from .darktable_bridge import sync_to_darktable

        logger.info("Pipeline start: source=%s", self.config.source_dir)

        paths = ingest_volume(self.config.source_dir, self.config.output_dir, dry_run=self.config.dry_run)
        records = [PhotoRecord(path=p) for p in paths]

        records = cluster_sessions(records)
        records = deduplicate(records)

        for record in records:
            if record.is_duplicate:
                continue
            record.sharpness_score = score_sharpness(record.path)
            record.composition_score = score_composition(record.path)
            record.exposure_score = score_exposure(record.path)
            record.semantic_name = generate_name(record.path, model_dir=self.config.model_dir)

        if not self.config.dry_run:
            sync_to_darktable(records, db_path=self.config.darktable_db)

        logger.info("Pipeline complete: %d records processed", len(records))
        return records


def main() -> None:
    import click

    @click.command()
    @click.option("--source", required=True, type=click.Path(exists=True, path_type=Path))
    @click.option("--output", required=True, type=click.Path(path_type=Path))
    @click.option("--db", required=True, type=click.Path(path_type=Path), help="Darktable library.db path")
    @click.option("--dry-run", is_flag=True)
    def cli(source: Path, output: Path, db: Path, dry_run: bool) -> None:
        """Run the PHOTONForge photo analysis pipeline."""
        config = PipelineConfig(
            source_dir=source,
            output_dir=output,
            darktable_db=db,
            dry_run=dry_run,
        )
        pipeline = AnalysisPipeline(config)
        pipeline.run()

    cli()
