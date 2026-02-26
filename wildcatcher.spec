# -*- mode: python ; coding: utf-8 -*-
import sys
import os

IS_WINDOWS = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'

# Data files — same as your working spec + classification model
datas = [
    ('assets', 'assets'),
    ('yolov5', 'yolov5'),
    ('detector_AI_model.pt', '.'),
    ('prec90rec93f191.pt', '.'),
    ('process_images.py', '.'),
    ('load_detector.py', '.'),
    ('video_player.py', '.'),
]

# VLC only on Windows
if IS_WINDOWS and os.path.isdir('vlc'):
    datas.append(('vlc', 'vlc'))

a = Analysis(
    ['detector_animales_diego.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

if IS_WINDOWS:
    # Single-file EXE (same as your working local build)
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name='WildCatcher',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=['assets\\app_icon.ico'],
    )

elif IS_MAC:
    # One-folder mode for macOS .app bundle
    exe = EXE(
        pyz,
        a.scripts,
        exclude_binaries=True,
        name='WildCatcher',
        debug=False,
        strip=False,
        upx=False,
        console=False,
        icon='assets/app_icon.icns' if os.path.isfile('assets/app_icon.icns') else None,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        name='WildCatcher',
    )

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
