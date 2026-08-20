# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: freeze photo-workflow and photo-cartridge as onedir builds.

Built by scripts/build_portable_cli.sh / .ps1, never invoked with bare
`pyinstaller scripts/photonforge.spec` from an arbitrary venv -- the build
scripts create a throwaway venv, `pip install .` (non-editable) into it, and
run pyinstaller from there, so this spec sees the exact same package a real
install would.

onedir, not onefile: onefile re-extracts its payload to a temp dir on every
invocation, which is fatal here -- the Lua plugin shells out per pipeline
stage, so a one-file build would pay that extraction cost on every single
step.

Two entry points (photo-workflow, photo-cartridge) are collected into ONE
output directory so their large shared dependencies -- onnxruntime, opencv,
tokenizers -- are written once, not duplicated per executable. COLLECT
de-duplicates by destination path, so simply concatenating both Analyses'
binaries/datas into a single COLLECT call is enough; no MERGE() needed, since
MERGE only dedupes pure-Python bytecode, not the multi-hundred-MB binary
libraries that actually dominate the size here. The two PYZ archives (pure
Python bytecode) are left to PyInstaller's own automatic naming
(PYZ-00.pyz/PYZ-01.pyz under --workpath), which is already collision-free --
do NOT pass PYZ(..., name=...) here. Doing so once made PyInstaller write
that file relative to the CURRENT DIRECTORY instead of --workpath, leaking a
stray .pyz into whatever directory the build happened to be invoked from;
caught by running the real build twice from different CWDs and finding the
file survive both --workpath overrides.

Verified against the packages actually pulled in when following imports from
photo_workflow.pipeline/cartridge: --collect-all picked up everything except
photo_workflow's own non-code data file (data/genre_weights.db), which has no
hook of its own and is added explicitly below.
"""

import os

from PyInstaller.utils.hooks import collect_all

block_cipher = None

REPO_ROOT = os.path.dirname(SPECPATH)  # noqa: F821 -- SPECPATH is injected by PyInstaller
SRC = os.path.join(REPO_ROOT, "src")

# Packages whose native extensions / data PyInstaller's import-following alone
# does not reliably find. Matches the plan's Task 6 list; onnxruntime is the
# one most likely to regress silently -- its pybind extension lives several
# packages deep (onnxruntime.capi._pybind_state) and collect_all is what
# actually pulls that .so/.pyd in rather than just the pure-Python wrapper.
COLLECT_ALL_PACKAGES = (
    "onnxruntime",
    "cv2",
    "scipy",
    "tokenizers",
    "rawpy",
    "PIL",
    "imagehash",
    "exifread",
)

datas = [
    # The genre-weight prototype DB shipped as package data (pyproject.toml
    # [tool.setuptools.package-data]). "models/" stays external per the plan
    # -- this is the one small data file that is genuinely part of the code.
    (
        os.path.join(SRC, "photo_workflow", "data", "genre_weights.db"),
        os.path.join("photo_workflow", "data"),
    ),
]
binaries = []
hiddenimports = []
for pkg in COLLECT_ALL_PACKAGES:
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

_common = dict(
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

a_workflow = Analysis(  # noqa: F821
    [os.path.join(REPO_ROOT, "scripts", "portable", "freeze_entry_photo_workflow.py")],
    **_common,
)
a_cartridge = Analysis(  # noqa: F821
    [os.path.join(REPO_ROOT, "scripts", "portable", "freeze_entry_photo_cartridge.py")],
    **_common,
)

pyz_workflow = PYZ(a_workflow.pure, a_workflow.zipped_data, cipher=block_cipher)  # noqa: F821
pyz_cartridge = PYZ(a_cartridge.pure, a_cartridge.zipped_data, cipher=block_cipher)  # noqa: F821

exe_workflow = EXE(  # noqa: F821
    pyz_workflow,
    a_workflow.scripts,
    [],
    exclude_binaries=True,
    name="photo-workflow",
    console=True,
    disable_windowed_traceback=False,
)
exe_cartridge = EXE(  # noqa: F821
    pyz_cartridge,
    a_cartridge.scripts,
    [],
    exclude_binaries=True,
    name="photo-cartridge",
    console=True,
    disable_windowed_traceback=False,
)

# One COLLECT call spanning both executables: this is what makes them land in
# a single output directory sharing one _internal/, which is the flat layout
# runner.lua's portable_exe() probes for (<root>/runtime/<os>/<name>[.exe]
# with no per-app subdirectory).
COLLECT(  # noqa: F821
    exe_workflow,
    a_workflow.binaries,
    a_workflow.zipfiles,
    a_workflow.datas,
    exe_cartridge,
    a_cartridge.binaries,
    a_cartridge.zipfiles,
    a_cartridge.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="photonforge-runtime",
)
