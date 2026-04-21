"""Tests for sidecar_cli subcommands — verifies JSON-lines stdout protocol."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from photo_workflow.sidecar_cli import cli
from photo_workflow.cartridge import Cartridge


def parse_events(output: str) -> list[dict]:
    """Parse newline-delimited JSON from CLI output."""
    events = []
    for line in output.splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def test_cartridge_list_emits_cartridges_event_and_exits_zero() -> None:
    """cartridge-list emits a cartridges event with items and exits 0."""
    mock_cartridges = [
        Cartridge(
            device="/dev/sdb1",
            mount_point=Path("/mnt/photon_ssd/001"),
            label="PHOTON-001",
            size_bytes=500_000_000,
            free_bytes=200_000_000,
        )
    ]
    runner = CliRunner()
    with patch("photo_workflow.sidecar_cli.detect_cartridges", return_value=mock_cartridges):
        result = runner.invoke(cli, ["cartridge-list"])

    assert result.exit_code == 0
    events = parse_events(result.output)
    assert len(events) == 1
    assert events[0]["type"] == "cartridges"
    items = events[0]["items"]
    assert len(items) == 1
    assert items[0]["label"] == "PHOTON-001"
    assert Path(items[0]["mount_point"]) == Path("/mnt/photon_ssd/001")
    assert "free_bytes" in items[0]
    assert "size_bytes" in items[0]


def test_ingest_emits_progress_and_done_events(tmp_path: Path) -> None:
    """ingest streams progress and done events, exits 0."""
    fake_files = [tmp_path / "DSC_0001.ARW", tmp_path / "DSC_0002.ARW"]
    runner = CliRunner()
    with patch("photo_workflow.sidecar_cli.ingest_volume", return_value=fake_files):
        result = runner.invoke(cli, [
            "ingest",
            "--source", str(tmp_path),
            "--output", str(tmp_path),
            "--db", str(tmp_path / "library.db"),
        ])

    assert result.exit_code == 0
    events = parse_events(result.output)
    types = [e["type"] for e in events]
    assert "progress" in types
    assert "done" in types
    done = next(e for e in events if e["type"] == "done")
    assert done["summary"]["total"] == 2
    assert "elapsed_seconds" in done["summary"]


from unittest.mock import call


def test_eject_sd_calls_udisksctl_with_parent_disk(tmp_path: Path) -> None:
    """_eject_sd resolves partition to parent disk and calls udisksctl power-off."""
    from photo_workflow.sidecar_cli import _eject_sd

    fake_mounts = "/dev/mmcblk0p1 /media/alex/SD_CARD vfat rw 0 0\n"
    with patch("photo_workflow.sidecar_cli.Path") as mock_path_cls, \
         patch("photo_workflow.sidecar_cli.subprocess.run") as mock_run:
        mock_path_cls.return_value.read_text.return_value = fake_mounts
        _eject_sd("/media/alex/SD_CARD")

    mock_run.assert_called_once_with(
        ["udisksctl", "power-off", "-b", "/dev/mmcblk0"],
        check=False,
    )


def test_eject_sd_strips_partition_suffix_for_usb(tmp_path: Path) -> None:
    """_eject_sd handles /dev/sda1 → /dev/sda correctly."""
    from photo_workflow.sidecar_cli import _eject_sd

    fake_mounts = "/dev/sda1 /media/alex/CARD vfat rw 0 0\n"
    with patch("photo_workflow.sidecar_cli.Path") as mock_path_cls, \
         patch("photo_workflow.sidecar_cli.subprocess.run") as mock_run:
        mock_path_cls.return_value.read_text.return_value = fake_mounts
        _eject_sd("/media/alex/CARD")

    mock_run.assert_called_once_with(
        ["udisksctl", "power-off", "-b", "/dev/sda"],
        check=False,
    )


def test_eject_sd_is_silent_when_mount_not_found() -> None:
    """_eject_sd does nothing and does not raise if mount point not in /proc/mounts."""
    from photo_workflow.sidecar_cli import _eject_sd

    with patch("photo_workflow.sidecar_cli.Path") as mock_path_cls, \
         patch("photo_workflow.sidecar_cli.subprocess.run") as mock_run:
        mock_path_cls.return_value.read_text.return_value = ""
        _eject_sd("/media/alex/NONEXISTENT")

    mock_run.assert_not_called()


def test_cartridge_reformat_dry_run_emits_reformat_done_without_mkfs(tmp_path: Path) -> None:
    """cartridge-reformat --dry-run emits reformat_done without calling mkfs.ext4, exits 0."""
    runner = CliRunner()
    with patch("photo_workflow.sidecar_cli.subprocess.run") as mock_run:
        result = runner.invoke(cli, [
            "cartridge-reformat",
            "--device", "/dev/sdb",
            "--label", "PHOTON-TEST",
            "--dry-run",
        ])

    assert result.exit_code == 0
    # subprocess.run must NOT have been called (dry-run skips mkfs)
    mock_run.assert_not_called()
    events = parse_events(result.output)
    types = [e["type"] for e in events]
    assert "reformat_done" in types
    done = next(e for e in events if e["type"] == "reformat_done")
    assert done["label"] == "PHOTON-TEST"
