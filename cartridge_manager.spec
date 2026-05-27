# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PHOTONForge Cartridge Manager.

Build with:
    pyinstaller cartridge_manager.spec

Output: dist/CartridgeManager/CartridgeManager.exe
"""

import sys
from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / 'tools' / 'cartridge_manager' / 'launcher.py')],
    pathex=[
        str(ROOT / 'src'),
        str(ROOT),
    ],
    binaries=[],
    datas=[],
    hiddenimports=[
        # Core app modules
        'tools',
        'tools.cartridge_manager',
        'tools.cartridge_manager.app',
        'tools.cartridge_manager.db_ops',
        'tools.cartridge_manager.file_ops',
        'tools.cartridge_manager.sampler',
        'tools.cartridge_manager.training_io',
        'tools.cartridge_manager.ui_widgets',
        'tools.cartridge_manager.labeler',
        # photo_workflow imports used by labeler
        'photo_workflow',
        'photo_workflow.genre_router',
        'photo_workflow.scoring_types',
        # Image handling
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
        'rawpy',
        'rawpy._rawpy',
        'exifread',
        'numpy',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy modules not needed by the manager
        'onnxruntime',
        'torch',
        'tensorflow',
        'scipy',
        'matplotlib',
        'pandas',
        'IPython',
        'jupyter',
        'notebook',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CartridgeManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window — pure GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CartridgeManager',
)
