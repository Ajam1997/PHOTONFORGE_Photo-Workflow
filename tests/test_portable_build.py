"""Portable-drive plan Task 6: freezing photo-workflow + photo-cartridge.

Fast tests here guard the spec's structure and the two build scripts'
mechanics -- the things that are cheap to check on every run and that have
already broken once each (see the comments in scripts/photonforge.spec and
scripts/build_portable_cli.ps1's PS 5.1 note).

The one slow test actually runs a real onedir freeze end to end: fresh venv,
non-editable install, pyinstaller, and a --help smoke test of both frozen
executables. That is the actual acceptance criterion for this task -- a spec
file that merely *parses* proves nothing about whether onnxruntime/cv2/
tokenizers/rawpy actually import inside a frozen build, which is exactly the
risk the portable-drive plan flags as unverified.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "scripts" / "photonforge.spec"
BUILD_SH = REPO / "scripts" / "build_portable_cli.sh"
BUILD_PS1 = REPO / "scripts" / "build_portable_cli.ps1"
ENTRY_WORKFLOW = REPO / "scripts" / "portable" / "freeze_entry_photo_workflow.py"
ENTRY_CARTRIDGE = REPO / "scripts" / "portable" / "freeze_entry_photo_cartridge.py"

# Packages the plan calls out by name (Task 6) as needing --collect-all
# because import-following alone misses their native extensions.
EXPECTED_COLLECT_ALL = {
    "onnxruntime", "cv2", "scipy", "tokenizers", "rawpy", "PIL", "imagehash", "exifread",
}


def test_spec_file_is_valid_python():
    ast.parse(SPEC.read_text(encoding="utf-8"))


def test_spec_collects_all_the_packages_the_plan_names():
    text = SPEC.read_text(encoding="utf-8")
    for pkg in EXPECTED_COLLECT_ALL:
        assert f'"{pkg}"' in text, f"{pkg} missing from COLLECT_ALL_PACKAGES"


def test_spec_is_onedir_not_onefile():
    """onefile re-extracts on every invocation -- fatal for per-step shell-outs."""
    text = SPEC.read_text(encoding="utf-8")
    assert "COLLECT(" in text
    assert "exclude_binaries=True" in text


def test_spec_builds_both_console_scripts():
    text = SPEC.read_text(encoding="utf-8")
    assert 'name="photo-workflow"' in text
    assert 'name="photo-cartridge"' in text


def test_spec_pyz_calls_have_no_explicit_name():
    """Regression guard: PYZ(..., name=...) writes relative to the CURRENT
    DIRECTORY rather than --workpath, leaking a stray .pyz wherever the build
    happened to run from. Caught by running the real build from two different
    CWDs; keep the auto-naming so it cannot come back."""
    tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    pyz_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "PYZ"
    ]
    assert pyz_calls, "expected at least one PYZ(...) call in the spec"
    for call in pyz_calls:
        kwnames = {kw.arg for kw in call.keywords}
        assert "name" not in kwnames, "PYZ(..., name=...) leaks a file to the CWD; remove it"


def test_genre_weights_db_is_bundled_as_data():
    """The one package data file with no PyInstaller hook of its own --
    subject_context.py resolves it relative to __file__, so a frozen build
    that omits it fails at runtime, not at build time."""
    text = SPEC.read_text(encoding="utf-8")
    assert "genre_weights.db" in text


def test_entry_scripts_exist_and_call_the_right_main():
    workflow_src = ENTRY_WORKFLOW.read_text(encoding="utf-8")
    cartridge_src = ENTRY_CARTRIDGE.read_text(encoding="utf-8")
    assert "from photo_workflow.pipeline import main" in workflow_src
    assert "from photo_workflow.cartridge import main" in cartridge_src
    # Both must actually call sys.exit(main()), not just import it.
    assert "sys.exit(main())" in workflow_src
    assert "sys.exit(main())" in cartridge_src


def test_build_scripts_use_a_fresh_non_editable_install():
    """The frozen build must reflect what `pip install .` ships, never an
    editable install pointing back at this checkout's src/ tree -- otherwise
    the frozen exe silently depends on files that will not travel with it."""
    sh = BUILD_SH.read_text(encoding="utf-8")
    ps1 = BUILD_PS1.read_text(encoding="utf-8")
    for text, label in ((sh, "build_portable_cli.sh"), (ps1, "build_portable_cli.ps1")):
        assert "venv" in text.lower(), f"{label}: expected a fresh venv"
        assert "-e" not in text.split("pip install")[1].split("\n")[0], (
            f"{label}: pip install line must not use -e (editable)"
        )
        assert "[build]" in text, f"{label}: expected the pyproject 'build' extra"


def test_bash_build_script_syntax():
    result = subprocess.run(["bash", "-n", str(BUILD_SH)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_bash_build_script_shellcheck_clean():
    result = subprocess.run(["shellcheck", str(BUILD_SH)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_powershell_build_script_registered_in_ascii_guard():
    """build_portable_cli.ps1 must be covered by the same PS 5.1 guard as
    update_install.ps1 (tests/test_powershell_scripts.py) -- that test
    globs scripts/*.ps1, so this just confirms the file lives where the glob
    looks."""
    from tests.test_powershell_scripts import PS_SCRIPTS  # type: ignore[import-not-found]

    assert BUILD_PS1 in PS_SCRIPTS


@pytest.mark.slow
def test_real_freeze_build_end_to_end(tmp_path):
    """The actual acceptance test: freeze both console scripts for real, in a
    throwaway venv, and confirm they run. This is what proves onnxruntime,
    opencv, tokenizers and rawpy's native extensions survive freezing --
    the exact risk the portable-drive plan flags as unverified on Windows.
    Linux-only here; Windows needs a real Windows machine to prove.
    """
    if sys.platform == "win32":
        pytest.skip("build_portable_cli.sh is the Linux build script")

    out_dir = tmp_path / "runtime" / "linux"
    result = subprocess.run(
        ["bash", str(BUILD_SH), str(out_dir)],
        capture_output=True, text=True, timeout=600, check=False,
    )
    assert result.returncode == 0, result.stdout[-4000:] + "\n" + result.stderr[-4000:]

    workflow_exe = out_dir / "photo-workflow"
    cartridge_exe = out_dir / "photo-cartridge"
    assert workflow_exe.exists()
    assert cartridge_exe.exists()
    assert (out_dir / "_internal").is_dir()

    wf = subprocess.run([str(workflow_exe), "--help"], capture_output=True, text=True, check=False)
    assert wf.returncode == 0
    assert "photo-workflow" in wf.stdout

    cart = subprocess.run([str(cartridge_exe), "--help"], capture_output=True, text=True, check=False)
    assert cart.returncode == 0
    assert "photo-cartridge" in cart.stdout

    # Relocatability matters more than usual here: the whole point of a
    # portable drive is that its mount point changes between machines.
    relocated = tmp_path / "relocated"
    shutil.copytree(out_dir, relocated)
    moved = subprocess.run([str(relocated / "photo-workflow"), "--help"],
                           capture_output=True, text=True, cwd=str(tmp_path), check=False)
    assert moved.returncode == 0
