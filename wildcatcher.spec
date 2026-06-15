# -*- mode: python ; coding: utf-8 -*-
"""
WildCatcher v2.0 — PyInstaller spec file
Build command:  pyinstaller wildcatcher.spec
Output:         dist/WildCatcher/WildCatcher.exe
"""
import sys
import os

block_cipher = None

# ---------------------------------------------------------------------------
# Data files to bundle (src, dest_in_bundle)
# ---------------------------------------------------------------------------
added_data = [
    # Built-in YOLOv5 detector (required — the only detector available)
    ('detector_AI_model.pt',           '.'),

    # User models folder (registry + classifier .pth files)
    ('models',                         'models'),

    # UI assets
    ('assets',                         'assets'),

    # VLC runtime (entire folder)
    ('vlc',                            'vlc'),

    # YOLOv5 inference code (bundled as data, loaded via sys.path at runtime)
    ('yolov5',                         'yolov5'),
]

# ---------------------------------------------------------------------------
# Hidden imports PyInstaller can't auto-detect
# ---------------------------------------------------------------------------
hidden_imports = [
    # --- PyQt5 ---
    'PyQt5.sip',

    # --- Torch / Torchvision ---
    'torch',
    'torch.nn',
    'torch.nn.functional',
    'torch.cuda',
    'torch.backends.cudnn',
    'torch.utils.data',
    'torchvision',
    'torchvision.models',
    'torchvision.transforms',
    'torchvision.transforms.functional',
    'torchvision.ops',

    # --- OpenCV ---
    'cv2',

    # --- PIL / Pillow ---
    'PIL',
    'PIL.Image',
    'PIL.ExifTags',
    'PIL.ImageOps',
    'PIL.ImageDraw',

    # --- Crypto (pycryptodome) for license verification ---
    'Crypto',
    'Crypto.PublicKey',
    'Crypto.PublicKey.RSA',
    'Crypto.Signature',
    'Crypto.Signature.pkcs1_15',
    'Crypto.Hash',
    'Crypto.Hash.SHA256',

    # --- VLC Python bindings ---
    'vlc',

    # --- Ultralytics (required by yolov5 code) ---
    'ultralytics',
    'ultralytics.utils',
    'ultralytics.utils.checks',
    'ultralytics.utils.plotting',

    # --- Scientific / data ---
    'numpy',
    'pandas',
    'matplotlib',
    'matplotlib.pyplot',
    'matplotlib.backends.backend_agg',
    'seaborn',
    'scipy',
    'scipy.ndimage',
    'scipy.ndimage.filters',
    'yaml',
    'psutil',
    'tqdm',
    'requests',
    'openpyxl',

    # --- YOLOv5 modules (needed when torch.load unpickles the detector) ---
    # These are imported WITHOUT the "yolov5." prefix because the app
    # adds yolov5/ to sys.path at runtime.
    'models',
    'models.common',
    'models.experimental',
    'models.yolo',
    'utils',
    'utils.augmentations',
    'utils.autoanchor',
    'utils.dataloaders',
    'utils.downloads',
    'utils.general',
    'utils.metrics',
    'utils.plots',
    'utils.torch_utils',
    'utils.activations',
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    ['detector_animales_diego.py'],
    pathex=['.', 'yolov5'],
    binaries=[],
    datas=added_data,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', '_tkinter',
        'xmlrpc',
        'doctest',
        'test',
        'IPython',
        'jupyter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WildCatcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,           # No console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app_icon.ico',
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
