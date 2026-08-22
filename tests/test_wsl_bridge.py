"""Tests for WSL bridge automation (running Linux Darktable build on Windows via WSL)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from photo_workflow import wsl_bridge

# ============================================================================
# Test detect_wsl()
# ============================================================================


def test_detect_wsl_when_wsl_exe_not_found(monkeypatch):
    """If wsl.exe is not on PATH, return available=False without raising."""
    monkeypatch.setattr("shutil.which", lambda _: None)
    result = wsl_bridge.detect_wsl()
    assert result.available is False
    assert result.distros == []
    assert result.default_distro is None


def test_detect_wsl_when_subprocess_fails(monkeypatch):
    """If wsl.exe --list --verbose exits non-zero, return available=False."""
    monkeypatch.setattr("shutil.which", lambda _: "/mnt/c/Windows/System32/wsl.exe")

    def mock_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["wsl.exe", "--list", "--verbose"],
            returncode=1,
            stdout=b"",
            stderr=b"WSL error",
        )

    monkeypatch.setattr("subprocess.run", mock_run)
    result = wsl_bridge.detect_wsl()
    assert result.available is False
    assert result.distros == []
    assert result.default_distro is None


def test_detect_wsl_parses_utf16le_output_with_two_wsl2_distros_one_default(monkeypatch):
    """Parse real wsl.exe output (UTF-16LE): detect 2 WSL2 distros, one marked default."""
    monkeypatch.setattr("shutil.which", lambda _: "/mnt/c/Windows/System32/wsl.exe")

    # Real wsl --list --verbose output, encoded as UTF-16LE
    wsl_output = (
        "  NAME                   STATE           VERSION\n"
        "* Ubuntu                 Running         2\n"
        "  Debian                 Stopped         2\n"
    ).encode("utf-16-le")

    def mock_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["wsl.exe", "--list", "--verbose"],
            returncode=0,
            stdout=wsl_output,
            stderr=b"",
        )

    monkeypatch.setattr("subprocess.run", mock_run)
    result = wsl_bridge.detect_wsl()
    assert result.available is True
    assert "Ubuntu" in result.distros
    assert "Debian" in result.distros
    assert result.default_distro == "Ubuntu"


def test_detect_wsl_skips_wsl1_distros(monkeypatch):
    """Only include WSL2 distros (version='2'); skip WSL1."""
    monkeypatch.setattr("shutil.which", lambda _: "/mnt/c/Windows/System32/wsl.exe")

    wsl_output = (
        "  NAME                   STATE           VERSION\n"
        "* Ubuntu                 Running         2\n"
        "  LegacyDebian           Stopped         1\n"
    ).encode("utf-16-le")

    def mock_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["wsl.exe", "--list", "--verbose"],
            returncode=0,
            stdout=wsl_output,
            stderr=b"",
        )

    monkeypatch.setattr("subprocess.run", mock_run)
    result = wsl_bridge.detect_wsl()
    assert result.available is True
    assert result.distros == ["Ubuntu"]
    assert result.default_distro == "Ubuntu"
    assert "LegacyDebian" not in result.distros


def test_detect_wsl_skips_unparseable_lines(monkeypatch):
    """Unparseable lines (malformed, too few columns) are skipped gracefully."""
    monkeypatch.setattr("shutil.which", lambda _: "/mnt/c/Windows/System32/wsl.exe")

    wsl_output = (
        "  NAME                   STATE           VERSION\n"
        "* Ubuntu                 Running         2\n"
        "  BrokenLine\n"
        "  Debian                 Stopped         2\n"
    ).encode("utf-16-le")

    def mock_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["wsl.exe", "--list", "--verbose"],
            returncode=0,
            stdout=wsl_output,
            stderr=b"",
        )

    monkeypatch.setattr("subprocess.run", mock_run)
    result = wsl_bridge.detect_wsl()
    assert "Ubuntu" in result.distros
    assert "Debian" in result.distros
    assert "BrokenLine" not in result.distros


# ============================================================================
# Test windows_path_to_wsl()
# ============================================================================


def test_windows_path_to_wsl_converts_drive_paths():
    """D:\\PhotonCartridge -> /mnt/d/PhotonCartridge."""
    result = wsl_bridge.windows_path_to_wsl(Path("D:\\PhotonCartridge"))
    assert result == "/mnt/d/PhotonCartridge"


def test_windows_path_to_wsl_converts_forward_slash_paths():
    """D:/PhotonCartridge -> /mnt/d/PhotonCartridge."""
    result = wsl_bridge.windows_path_to_wsl(Path("D:/PhotonCartridge"))
    assert result == "/mnt/d/PhotonCartridge"


def test_windows_path_to_wsl_handles_nested_paths():
    """D:/Data/Photos/Shoot1 -> /mnt/d/Data/Photos/Shoot1."""
    result = wsl_bridge.windows_path_to_wsl(Path("D:/Data/Photos/Shoot1"))
    assert result == "/mnt/d/Data/Photos/Shoot1"


def test_windows_path_to_wsl_raises_for_relative_path():
    """Relative paths (no drive letter) raise WslError."""
    with pytest.raises(wsl_bridge.WslError, match="not an absolute Windows path"):
        wsl_bridge.windows_path_to_wsl(Path("relative/path"))


def test_windows_path_to_wsl_handles_uppercase_drive():
    """D:\\PhotonCartridge (uppercase) -> /mnt/d/PhotonCartridge (lowercase)."""
    result = wsl_bridge.windows_path_to_wsl(Path("D:\\PhotonCartridge"))
    assert result == "/mnt/d/PhotonCartridge"


# ============================================================================
# Test _decode_wsl_output()
# ============================================================================


def test_decode_wsl_output_handles_utf16le_with_bom():
    """UTF-16LE with BOM is decoded correctly."""
    text = "Hello, World!"
    raw = text.encode("utf-16-le")
    result = wsl_bridge._decode_wsl_output(raw)
    assert result == text


def test_decode_wsl_output_falls_back_to_utf8():
    """If UTF-16LE produces control chars, fall back to UTF-8."""
    text = "Hello, UTF-8!"
    raw = text.encode("utf-8")
    result = wsl_bridge._decode_wsl_output(raw)
    assert result == text


def test_decode_wsl_output_strips_bom_and_null_bytes():
    """BOM and null bytes are stripped."""
    text = "Hello"
    raw = "\ufeff" + text + "\x00\x00"
    raw_bytes = raw.encode("utf-16-le")
    result = wsl_bridge._decode_wsl_output(raw_bytes)
    assert "\ufeff" not in result
    assert "\x00" not in result
    assert "Hello" in result


# ============================================================================
# Test run_make_portable_linux()
# ============================================================================


def test_run_make_portable_linux_raises_when_wsl_not_available(monkeypatch):
    """Raises WslError with setup guidance if WSL is not installed."""
    monkeypatch.setattr(
        "photo_workflow.wsl_bridge.detect_wsl",
        lambda: wsl_bridge.WslInfo(available=False, distros=[], default_distro=None),
    )
    drive = Path("D:/PhotonCartridge")
    with pytest.raises(wsl_bridge.WslError, match="WSL2 is not installed"):
        wsl_bridge.run_make_portable_linux(drive)


def test_run_make_portable_linux_raises_when_no_distros_registered(monkeypatch):
    """Raises WslError if WSL is installed but no distro is registered."""
    monkeypatch.setattr(
        "photo_workflow.wsl_bridge.detect_wsl",
        lambda: wsl_bridge.WslInfo(available=True, distros=[], default_distro=None),
    )
    drive = Path("D:/PhotonCartridge")
    with pytest.raises(wsl_bridge.WslError, match="no WSL2 distro is registered"):
        wsl_bridge.run_make_portable_linux(drive)


def test_run_make_portable_linux_builds_correct_command(monkeypatch):
    """Command is built correctly with all flags."""
    monkeypatch.setattr(
        "photo_workflow.wsl_bridge.detect_wsl",
        lambda: wsl_bridge.WslInfo(
            available=True, distros=["Ubuntu", "Debian"], default_distro="Ubuntu"
        ),
    )

    captured_cmd = []

    def mock_run(cmd, **kwargs):
        captured_cmd.append(cmd)
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("subprocess.run", mock_run)

    drive = Path("D:/PhotonCartridge")
    manifest = Path("D:/config/portable-manifest.yml")
    cache = Path("D:/cache")

    wsl_bridge.run_make_portable_linux(
        drive,
        distro="Ubuntu",
        cart_id="001",
        manifest=manifest,
        cache_dir=cache,
        offline=True,
    )

    assert len(captured_cmd) == 1
    cmd = captured_cmd[0]
    assert cmd[0] == "wsl.exe"
    assert "-d" in cmd
    assert "Ubuntu" in cmd
    assert "--" in cmd
    assert "python3" in cmd
    assert "-m" in cmd
    assert "photo_workflow.cartridge" in cmd
    assert "make-portable" in cmd
    assert "/mnt/d/PhotonCartridge" in cmd
    assert "--os" in cmd
    assert "linux" in cmd
    assert "--id" in cmd
    assert "001" in cmd
    assert "--manifest" in cmd
    assert "/mnt/d/config/portable-manifest.yml" in cmd
    assert "--cache" in cmd
    assert "/mnt/d/cache" in cmd
    assert "--offline" in cmd


def test_run_make_portable_linux_picks_default_distro_when_not_specified(monkeypatch):
    """Uses info.default_distro if distro param is not given."""
    monkeypatch.setattr(
        "photo_workflow.wsl_bridge.detect_wsl",
        lambda: wsl_bridge.WslInfo(
            available=True, distros=["Ubuntu", "Debian"], default_distro="Ubuntu"
        ),
    )

    captured_cmd = []

    def mock_run(cmd, **kwargs):
        captured_cmd.append(cmd)
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("subprocess.run", mock_run)

    drive = Path("D:/PhotonCartridge")
    wsl_bridge.run_make_portable_linux(drive)  # No distro param

    cmd = captured_cmd[0]
    assert "Ubuntu" in cmd


def test_run_make_portable_linux_picks_first_distro_as_fallback(monkeypatch):
    """Uses info.distros[0] if no default is set."""
    monkeypatch.setattr(
        "photo_workflow.wsl_bridge.detect_wsl",
        lambda: wsl_bridge.WslInfo(
            available=True, distros=["Debian", "Ubuntu"], default_distro=None
        ),
    )

    captured_cmd = []

    def mock_run(cmd, **kwargs):
        captured_cmd.append(cmd)
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("subprocess.run", mock_run)

    drive = Path("D:/PhotonCartridge")
    wsl_bridge.run_make_portable_linux(drive)

    cmd = captured_cmd[0]
    assert "Debian" in cmd


def test_run_make_portable_linux_succeeds_and_calls_progress(monkeypatch):
    """On success (returncode=0), calls progress callback with output."""
    monkeypatch.setattr(
        "photo_workflow.wsl_bridge.detect_wsl",
        lambda: wsl_bridge.WslInfo(
            available=True, distros=["Ubuntu"], default_distro="Ubuntu"
        ),
    )

    def mock_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="Build completed successfully", stderr=""
        )

    monkeypatch.setattr("subprocess.run", mock_run)

    progress_calls = []

    def mock_progress(msg):
        progress_calls.append(msg)

    drive = Path("D:/PhotonCartridge")
    wsl_bridge.run_make_portable_linux(drive, progress=mock_progress)

    assert len(progress_calls) == 1
    assert "Build completed successfully" in progress_calls[0]


def test_run_make_portable_linux_raises_on_module_not_found(monkeypatch):
    """Raises actionable WslError if photo_workflow is not installed in the distro."""
    monkeypatch.setattr(
        "photo_workflow.wsl_bridge.detect_wsl",
        lambda: wsl_bridge.WslInfo(
            available=True, distros=["Ubuntu"], default_distro="Ubuntu"
        ),
    )

    def mock_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="",
            stderr="ModuleNotFoundError: No module named 'photo_workflow'",
        )

    monkeypatch.setattr("subprocess.run", mock_run)

    drive = Path("D:/PhotonCartridge")
    with pytest.raises(wsl_bridge.WslError, match="not installed"):
        wsl_bridge.run_make_portable_linux(drive)

    # Check the error message mentions pip install
    try:
        wsl_bridge.run_make_portable_linux(drive)
    except wsl_bridge.WslError as e:
        assert "pip install" in str(e)


def test_run_make_portable_linux_raises_on_other_failures(monkeypatch):
    """Raises WslError with captured stderr for other failures."""
    monkeypatch.setattr(
        "photo_workflow.wsl_bridge.detect_wsl",
        lambda: wsl_bridge.WslInfo(
            available=True, distros=["Ubuntu"], default_distro="Ubuntu"
        ),
    )

    def mock_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=127,
            stdout="",
            stderr="Command 'python3' not found",
        )

    monkeypatch.setattr("subprocess.run", mock_run)

    drive = Path("D:/PhotonCartridge")
    with pytest.raises(wsl_bridge.WslError, match="Command 'python3' not found"):
        wsl_bridge.run_make_portable_linux(drive)


def test_run_make_portable_linux_without_optional_params(monkeypatch):
    """Works correctly with minimal params (no manifest, cache, offline)."""
    monkeypatch.setattr(
        "photo_workflow.wsl_bridge.detect_wsl",
        lambda: wsl_bridge.WslInfo(
            available=True, distros=["Ubuntu"], default_distro="Ubuntu"
        ),
    )

    captured_cmd = []

    def mock_run(cmd, **kwargs):
        captured_cmd.append(cmd)
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="", stderr=""
        )

    monkeypatch.setattr("subprocess.run", mock_run)

    drive = Path("D:/PhotonCartridge")
    wsl_bridge.run_make_portable_linux(drive)

    cmd = captured_cmd[0]
    # Should not include --id, --manifest, --cache, --offline if not passed
    assert "--id" not in cmd
    assert "--manifest" not in cmd
    assert "--cache" not in cmd
    assert "--offline" not in cmd


# ============================================================================
# Test WslError exception
# ============================================================================


def test_wsl_error_is_a_runtime_error():
    """WslError inherits from RuntimeError."""
    exc = wsl_bridge.WslError("test message")
    assert isinstance(exc, RuntimeError)
    assert str(exc) == "test message"


# ============================================================================
# Test WslInfo dataclass
# ============================================================================


def test_wsl_info_dataclass():
    """WslInfo stores available, distros, and default_distro."""
    info = wsl_bridge.WslInfo(available=True, distros=["Ubuntu"], default_distro="Ubuntu")
    assert info.available is True
    assert info.distros == ["Ubuntu"]
    assert info.default_distro == "Ubuntu"
