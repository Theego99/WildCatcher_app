# -*- mode: python ; coding: utf-8 -*-
"""
WildCatcher PyInstaller spec file.
Builds a single-folder distribution for Windows, macOS, or Linux.

Usage:
    pyinstaller wildcatcher.spec

The spec auto-detects the current platform and adjusts accordingly.
"""
import sys
import os
import platform

block_cipher = None
IS_WINDOWS = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'
IS_LINUX = sys.platform.startswith('linux')

# ──────────────────────────────────────────────
# 1. DATA FILES
# ──────────────────────────────────────────────
datas = [
    ('assets', 'assets'),
    ('yolov5', 'yolov5'),
    ('detector_AI_model.pt', '.'),
    ('prec90rec93f191.pt', '.'),
    ('process_images.py', '.'),
    ('load_detector.py', '.'),
    ('video_player.py', '.'),
]

# VLC: Only bundle on Windows (Mac/Linux use system VLC or alternative)
if IS_WINDOWS and os.path.isdir('vlc'):
    datas.append(('vlc', 'vlc'))

# ──────────────────────────────────────────────
# 2. HIDDEN IMPORTS
# ──────────────────────────────────────────────
hiddenimports = [
    # PyTorch
    'torch',
    'torch.nn',
    'torch.nn.functional',
    'torch.utils.data',
    'torchvision',
    'torchvision.models',
    'torchvision.transforms',
    # Image processing
    'PIL',
    'PIL.Image',
    'cv2',
    # PyQt5
    'PyQt5',
    'PyQt5.QtWidgets',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.sip',
    # Cryptography (license system)
    'Crypto',
    'Crypto.PublicKey',
    'Crypto.PublicKey.RSA',
    'Crypto.Signature',
    'Crypto.Signature.pkcs1_15',
    'Crypto.Hash',
    'Crypto.Hash.SHA256',
    # YOLOv5 dependencies
    'yaml',
    'scipy',
    'pandas',
    'requests',
    'tqdm',
    'matplotlib',
    # Standard library
    'csv',
    'json',
    'hashlib',
    'uuid',
    'platform',
    'tempfile',
]

# ──────────────────────────────────────────────
# 3. EXCLUDED MODULES (reduce bundle size)
# ──────────────────────────────────────────────
excludes = [
    'tkinter',
    'unittest',
    'test',
    'xmlrpc',
    'IPython',
    'jupyter',
    'notebook',
    'sphinx',
    'docutils',
    'setuptools',
    'pip',
    'wheel',
    'distutils',
    # Torch modules not needed at runtime
    'torch.distributed',
    'torch.testing',
    'caffe2',
]

# ──────────────────────────────────────────────
# 4. ANALYSIS
# ──────────────────────────────────────────────
a = Analysis(
    ['detector_animales_diego.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ──────────────────────────────────────────────
# 5. EXECUTABLE
# ──────────────────────────────────────────────
exe_kwargs = dict(
    pyz=pyz,
    a_scripts=a.scripts,
    exclude_binaries=True,     # One-folder mode
    name='WildCatcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,             # No console window (GUI app)
)

# App icon (platform-specific format)
if IS_WINDOWS and os.path.isfile('assets/app_icon.ico'):
    exe_kwargs['icon'] = 'assets/app_icon.ico'
elif IS_MAC and os.path.isfile('assets/app_icon.icns'):
    exe_kwargs['icon'] = 'assets/app_icon.icns'

exe = EXE(**exe_kwargs)

# ──────────────────────────────────────────────
# 6. COLLECT (one-folder bundle)
# ──────────────────────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WildCatcher',
)

# ──────────────────────────────────────────────
# 7. macOS APP BUNDLE (optional)
# ──────────────────────────────────────────────
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
