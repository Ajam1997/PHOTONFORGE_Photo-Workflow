"""Tests for volume label detection and file naming helpers."""

from __future__ import annotations

from pathlib import Path


from photo_workflow.volume import (
    extract_cartridge_id,
    derive_trip_code,
    format_photo_name,
    get_next_sequence,
)


def test_extract_cartridge_id_standard():
    assert extract_cartridge_id("PHOTONFORGE-003") == "003"


def test_extract_cartridge_id_high_number():
    assert extract_cartridge_id("PHOTONFORGE-042") == "042"


def test_extract_cartridge_id_no_match():
    assert extract_cartridge_id("MYUSB") == "000"


def test_extract_cartridge_id_empty():
    assert extract_cartridge_id("") == "000"


def test_derive_trip_code_standard():
    assert derive_trip_code("ICELAND") == "ICE"


def test_derive_trip_code_mixed_case():
    assert derive_trip_code("My Trip") == "MYT"


def test_derive_trip_code_short():
    assert derive_trip_code("AB") == "ABX"


def test_derive_trip_code_single_char():
    assert derive_trip_code("X") == "XXX"


def test_derive_trip_code_numbers_stripped():
    assert derive_trip_code("2026trip") == "TRI"


def test_format_photo_name():
    assert format_photo_name("003", "ICE", 1, ".ARW") == "P003ICE0000001.ARW"


def test_format_photo_name_large_seq():
    assert format_photo_name("003", "ICE", 9999999, ".ARW") == "P003ICE9999999.ARW"


def test_get_next_sequence_empty_dir(tmp_path: Path):
    assert get_next_sequence(tmp_path, "003", "ICE") == 1


def test_get_next_sequence_existing_files(tmp_path: Path):
    (tmp_path / "P003ICE0000001.ARW").touch()
    (tmp_path / "P003ICE0000002.ARW").touch()
    (tmp_path / "P003ICE0000005.ARW").touch()
    assert get_next_sequence(tmp_path, "003", "ICE") == 6


def test_get_next_sequence_ignores_other_prefixes(tmp_path: Path):
    (tmp_path / "P003ICE0000003.ARW").touch()
    (tmp_path / "P004WED0000010.ARW").touch()
    assert get_next_sequence(tmp_path, "003", "ICE") == 4
