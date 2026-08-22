"""WSL bridge for automating Linux Darktable extraction on Windows.

Enables a Windows user running `photo-cartridge make-portable --os win --os linux`
to build the Linux half via WSL, instead of requiring a separate Linux machine.

Since AppImage extraction (--appimage-extract) requires a Linux ELF binary
execution capability, this module transparently shells out to WSL to run the
photo_workflow CLI from inside a WSL distro, building only the Linux half via
that distro's Python.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


class WslError(RuntimeError):
    """Exception raised when WSL detection or invocation fails.

    Messages are actionable and intended for end users, not containing raw
    subprocess tracebacks.
    """


@dataclass
class WslInfo:
    """Detection result from querying WSL availability."""

    available: bool
    distros: list[str]  # WSL2 distros only, not WSL1
    default_distro: str | None  # the distro marked with '*' in wsl --list --verbose


def _decode_wsl_output(raw: bytes) -> str:
    """Decode wsl.exe --list --verbose output, handling UTF-16LE with BOM.

    Windows console output redirected to a pipe comes as UTF-16LE with BOM.
    Falls back to UTF-8 with error replacement if that decoding produces
    mostly control characters (heuristic: >10% of chars have ord(c) < 9).
    """
    try:
        # Try UTF-16LE first (Windows native)
        decoded = raw.decode("utf-16-le")
        # Quick check: if more than 10% of non-whitespace chars are control
        # characters, this didn't decode right — fall back to UTF-8.
        non_ws = [c for c in decoded if not c.isspace()]
        if non_ws:
            ctrl_count = sum(1 for c in non_ws if ord(c) < 9)
            if ctrl_count / len(non_ws) > 0.1:
                # Looks like mojibake; fall back to UTF-8
                decoded = raw.decode("utf-8", errors="replace")
    except (UnicodeDecodeError, AttributeError):
        # Fall back to UTF-8 with error replacement
        decoded = raw.decode("utf-8", errors="replace")

    # Strip BOM and stray null bytes
    decoded = decoded.lstrip("\ufeff")
    decoded = decoded.replace("\x00", "")
    return decoded


def detect_wsl() -> WslInfo:
    """Query WSL availability via `wsl.exe --list --verbose`.

    Returns WslInfo with:
    - available=False if wsl.exe is not on PATH or the subprocess call fails
    - available=True if wsl.exe is found and subprocess succeeds (even if no
      distros are registered)

    Never raises — "not installed" is a normal outcome.

    Parses the output format:
    ```
      NAME                   STATE           VERSION
    * Ubuntu                 Running         2
      Debian                 Stopped         2
    ```

    Only includes WSL2 distros in the returned list (version="2").
    The distro marked with '*' is set as default_distro.
    """
    if shutil.which("wsl.exe") is None:
        return WslInfo(available=False, distros=[], default_distro=None)

    try:
        result = subprocess.run(
            ["wsl.exe", "--list", "--verbose"],
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return WslInfo(available=False, distros=[], default_distro=None)

    if result.returncode != 0:
        return WslInfo(available=False, distros=[], default_distro=None)

    output = _decode_wsl_output(result.stdout)
    lines = output.split("\n")

    distros: list[str] = []
    default_distro: str | None = None

    for line in lines:
        line = line.rstrip()
        if not line.strip():
            continue
        # Skip header line (contains "NAME")
        if "NAME" in line:
            continue

        # Check for default marker
        is_default = line.startswith("*")
        if is_default:
            line = line[1:].lstrip()

        # Parse: first token is distro name, last token is version
        parts = line.split()
        if len(parts) < 2:
            continue  # Skip unparseable lines

        distro_name = parts[0]
        version = parts[-1]

        # Only include WSL2 distros
        if version == "2":
            distros.append(distro_name)
            if is_default:
                default_distro = distro_name

    # available=True means wsl.exe found and subprocess succeeded,
    # even if no distros were found (distros could be empty)
    return WslInfo(
        available=True,
        distros=distros,
        default_distro=default_distro,
    )


def windows_path_to_wsl(path: Path) -> str:
    """Convert a Windows drive path to its WSL mount equivalent.

    Examples:
        D:\\PhotonCartridge -> /mnt/d/PhotonCartridge
        D:/PhotonCartridge -> /mnt/d/PhotonCartridge

    Raises WslError if path has no drive letter (relative path).
    """
    from pathlib import PureWindowsPath

    # Use PureWindowsPath to correctly parse Windows paths even on Unix
    win_path = PureWindowsPath(path)
    if not win_path.drive:
        raise WslError(f"{path} is not an absolute Windows path with a drive letter")

    drive_letter = win_path.drive[0].lower()
    # Convert to posix-style path, then strip the drive to get the remainder
    posix = win_path.as_posix()
    # Drive is like "D:", so find where it ends and take the rest
    # The drive might be followed by "/" or might not be, so we need to handle both
    remainder = posix[len(win_path.drive) :]
    # Ensure remainder starts with /
    if remainder and not remainder.startswith("/"):
        remainder = "/" + remainder
    elif not remainder:
        remainder = "/"
    return f"/mnt/{drive_letter}{remainder}"


def run_make_portable_linux(
    drive: Path,
    *,
    distro: str | None = None,
    cart_id: str | None = None,
    manifest: Path | None = None,
    cache_dir: Path | None = None,
    offline: bool = False,
    progress: Callable[[str], None] | None = None,
) -> None:
    """Build the Linux half of the portable drive via WSL.

    Transparently shells out to wsl.exe running `photo_workflow.cartridge
    make-portable --os linux` inside the named distro. Raises WslError on
    any failure, with actionable messages.

    Args:
        drive: Windows path to the cartridge (converted to /mnt/X/... inside WSL)
        distro: WSL distro name (defaults to auto-detected default)
        cart_id: Cartridge ID (passed to make-portable)
        manifest: Path to config/portable-manifest.yml (passed to make-portable)
        cache_dir: Download cache directory (passed to make-portable)
        offline: Cache-only mode (passed to make-portable)
        progress: Optional callback for displaying command output
    """
    # Step 1: Detect WSL
    info = detect_wsl()
    if not info.available:
        raise WslError(
            "WSL2 is not installed or has no usable distro. "
            "Install WSL2 (`wsl --install` from an elevated PowerShell prompt) "
            "and a Linux distro, then re-run. See docs/portable-drive-setup.md "
            "for the one-time setup this tool needs inside WSL."
        )
    # available=True but no distros registered
    if not info.distros:
        raise WslError(
            "WSL2 is installed but no WSL2 distro is registered. "
            "Install one (e.g. `wsl --install -d Ubuntu`), then re-run."
        )

    # Step 2: Pick the distro
    chosen_distro = distro or info.default_distro or info.distros[0]

    # Step 3: Translate drive path to WSL
    wsl_drive = windows_path_to_wsl(drive)

    # Step 4: Build the command
    cmd = [
        "wsl.exe",
        "-d",
        chosen_distro,
        "--",
        "python3",
        "-m",
        "photo_workflow.cartridge",
        "make-portable",
        wsl_drive,
        "--os",
        "linux",
    ]

    if cart_id is not None:
        cmd.extend(["--id", cart_id])

    if manifest is not None:
        cmd.extend(["--manifest", windows_path_to_wsl(manifest)])

    if cache_dir is not None:
        cmd.extend(["--cache", windows_path_to_wsl(cache_dir)])

    if offline:
        cmd.append("--offline")

    # Step 5: Run it
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)

    if result.returncode == 0:
        # Success
        if progress is not None:
            progress(result.stdout)
        return

    # Step 6: Failure — provide actionable errors
    # result.stderr and result.stdout are strings (text=True)
    output = (result.stderr or result.stdout or "").strip()

    if "No module named" in output or "ModuleNotFoundError" in output:
        raise WslError(
            f"photo_workflow is not installed inside the {chosen_distro} distro's Python. "
            "Inside WSL, navigate to this repository (reachable at /mnt/c/... or wherever "
            "it's checked out) and run:\n\n"
            "    pip install -e .\n\n"
            "or:\n\n"
            "    pip install .\n\n"
            "This is a one-time setup step. After that, re-run this command."
        )

    raise WslError(
        f"wsl.exe command failed (exit {result.returncode}):\n"
        f"\nCommand: {' '.join(cmd)}\n"
        f"\nOutput:\n{output}"
    )
