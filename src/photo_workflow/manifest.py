"""JSONL manifest for staged pipeline checkpointing."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ManifestEntry:
    """Per-photo state tracked across pipeline stages."""

    path: str
    exif_timestamp: str | None = None
    session_id: str = ""
    is_duplicate: bool = False
    sharpness: float | None = None
    composition: float | None = None
    exposure: float | None = None
    semantic_name: str | None = None
    error: str | None = None
    stages_completed: list[str] = field(default_factory=lambda: ["scan"])


def _entry_to_json(entry: ManifestEntry) -> str:
    """Serialize a ManifestEntry to a JSON string."""
    return json.dumps(asdict(entry), ensure_ascii=False)


def _entry_from_json(line: str) -> ManifestEntry:
    """Deserialize a JSON string to a ManifestEntry."""
    data = json.loads(line)
    return ManifestEntry(**data)


def save_manifest(entries: list[ManifestEntry], path: Path) -> None:
    """Write entries to a JSONL file using atomic replace."""
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(_entry_to_json(entry) + "\n")
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def load_manifest(path: Path) -> list[ManifestEntry]:
    """Read all entries from a JSONL manifest file."""
    entries: list[ManifestEntry] = []
    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(_entry_from_json(line))
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Manifest line %d: %s", line_num, exc)
    return entries


def checkpoint(entries: list[ManifestEntry], path: Path) -> None:
    """Flush current in-memory entries to disk via atomic replace."""
    save_manifest(entries, path)
