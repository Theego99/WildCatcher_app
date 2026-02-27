# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

IS_WINDOWS = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'

# ──────────────────────────────────────────────
# Collect ALL torch files (submodules, data, DLLs)
# This is critical — PyInstaller misses many torch
# DLL dependencies without this.
# ──────────────────────────────────────────────
torch_datas, torch_binaries, torch_hiddenimports = collect_all('torch')
tv_datas, tv_binaries, tv_hiddenimports = collect_all('torchvision')

# Data files
datas = torch_datas + tv_datas + [
    ('assets', 'assets'),
    ('yolov5', 'yolov5'),
    ('detector_AI_model.pt', '.'),
    ('prec90rec93f191.pt', '.'),
    ('process_images.py', '.'),
    ('load_detector.py', '.'),
    ('video_player.py', '.'),
]

if IS_WINDOWS and os.path.isdir('vlc'):
    datas.append(('vlc', 'vlc'))

binaries = torch_binaries + tv_binaries

hiddenimports = torch_hiddenimports + tv_hiddenimports

a = Analysis(
    ['detector_animales_diego.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['runtime_hook_torch.py'],   # <-- Fixes DLL loading
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# One-folder mode (required for torch DLLs)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name='WildCatcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                # No UPX — it can corrupt torch DLLs
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/app_icon.ico'] if IS_WINDOWS and os.path.isfile('assets/app_icon.ico') else [],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='WildCatcher',
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name='WildCatcher.app',
        icon='assets/app_icon.icns' if os.path.isfile('assets/app_icon.icns') else None,
        bundle_identifier='com.wildcatcher.app',
        info_plist={
            'CFBundleName': 'WildCatcher',
            'CFBundleDisplayName': 'WildCatcher',
            'CFBundleVersion': '1.0.0',
            'CFBundleShortVersionString': '1.0.0',
            'NSHighResolutionCapable': True,
        },
    )
