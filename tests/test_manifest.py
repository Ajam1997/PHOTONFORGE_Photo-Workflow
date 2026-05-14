"""Tests for the JSONL manifest module."""

from __future__ import annotations

import json
from pathlib import Path

from photo_workflow.manifest import ManifestEntry, save_manifest, load_manifest


def test_manifest_entry_round_trip(tmp_path: Path) -> None:
    """A ManifestEntry survives serialize -> write -> read -> deserialize."""
    entry = ManifestEntry(
        path=str(tmp_path / "IMG_0001.jpg"),
        exif_timestamp="2026-04-01T10:00:00",
    )
    manifest_path = tmp_path / "manifest.jsonl"
    save_manifest([entry], manifest_path)
    loaded = load_manifest(manifest_path)
    assert len(loaded) == 1
    assert loaded[0].path == entry.path
    assert loaded[0].exif_timestamp == entry.exif_timestamp
    assert loaded[0].stages_completed == ["scan"]


def test_checkpoint_flush(tmp_path: Path) -> None:
    """checkpoint() writes current state without losing data on re-read."""
    from photo_workflow.manifest import checkpoint

    entries = [
        ManifestEntry(path=str(tmp_path / f"IMG_{i:04d}.jpg"))
        for i in range(100)
    ]
    manifest_path = tmp_path / "manifest.jsonl"
    save_manifest(entries, manifest_path)

    entries[50].sharpness = 0.85
    entries[50].stages_completed.append("score")
    checkpoint(entries, manifest_path)

    reloaded = load_manifest(manifest_path)
    assert len(reloaded) == 100
    assert reloaded[50].sharpness == 0.85
    assert "score" in reloaded[50].stages_completed
    assert reloaded[0].sharpness is None


def test_atomic_replace_preserves_old_on_disk(tmp_path: Path) -> None:
    """If the process reads a manifest, the file on disk is valid JSONL at all times."""
    manifest_path = tmp_path / "manifest.jsonl"

    original = [ManifestEntry(path=str(tmp_path / "a.jpg"))]
    save_manifest(original, manifest_path)

    updated = [
        ManifestEntry(path=str(tmp_path / "a.jpg"), sharpness=0.5),
        ManifestEntry(path=str(tmp_path / "b.jpg")),
    ]
    save_manifest(updated, manifest_path)

    reloaded = load_manifest(manifest_path)
    assert len(reloaded) == 2
    assert reloaded[0].sharpness == 0.5

    assert list(tmp_path.glob("*.tmp")) == []
