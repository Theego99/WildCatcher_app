# -*- mode: python ; coding: utf-8 -*-
"""
WildCatcher v2.0 — PyInstaller spec file
Build command:  pyinstaller wildcatcher.spec
Output:         dist/WildCatcher/WildCatcher.exe

Inference uses ONNX Runtime (GPU via DirectML/CoreML/CUDA). PyTorch is bundled
ONLY for one-shot conversion of user-added .pt/.pth models (wc_convert), so
install the CPU-ONLY torch build before packaging to keep the bundle small.
"""
import os

block_cipher = None

# torch / torchvision / onnxruntime are pulled in via hiddenimports below and
# collected by PyInstaller's built-in hooks (hook-torch, hook-onnxruntime, ...).
# We deliberately do NOT collect_all them — that dragged in onnxruntime.quantization
# -> onnx -> onnx.reference, whose import crashes PyInstaller's analysis subprocess.
datas, binaries, hiddenimports = [], [], []

# ---------------------------------------------------------------------------
# Data files to bundle (src, dest_in_bundle)
# ---------------------------------------------------------------------------
# Only bundle paths that exist on this platform (e.g. the Windows-only vlc/ folder)
_candidate_data = [
    ('detector_AI_model.onnx', '.'),   # built-in detector (ONNX), the only detector
    ('models',                 'models'),  # registry + .onnx classifiers
    ('assets',                 'assets'),  # UI assets
    ('vlc',                    'vlc'),      # Windows VLC runtime (absent on macOS)
]
datas += [(src, dst) for src, dst in _candidate_data if os.path.exists(src)]

# ---------------------------------------------------------------------------
# Hidden imports PyInstaller can't auto-detect
# ---------------------------------------------------------------------------
hidden_imports = [
    # --- PyQt5 ---
    'PyQt5.sip',

    # --- ONNX Runtime (inference) ---
    'onnxruntime',

    # --- Conversion module + torch (lazy import lives in wc_convert) ---
    'wc_convert',
    'torch',
    'torch.onnx',
    'torchvision',
    'torchvision.models',
    'onnx',  # required by torch.onnx.export at conversion time

    # --- OpenCV / PIL ---
    'cv2',
    'PIL', 'PIL.Image', 'PIL.ExifTags', 'PIL.ImageOps', 'PIL.ImageDraw',

    # --- Crypto (pycryptodome) for license verification ---
    'Crypto', 'Crypto.PublicKey', 'Crypto.PublicKey.RSA',
    'Crypto.Signature', 'Crypto.Signature.pkcs1_15',
    'Crypto.Hash', 'Crypto.Hash.SHA256',

    # --- VLC Python bindings ---
    'vlc',

    # --- Misc ---
    'numpy',
    'openpyxl',
    'psutil',
    'requests',
]
hiddenimports += hidden_imports

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    ['detector_animales_diego.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    # Loads onnxruntime before the PyQt5 rthook pollutes the DLL search path.
    runtime_hooks=['rthook_onnxruntime.py'],
    excludes=[
        # No longer used at runtime (old yolov5/ultralytics detector path)
        'ultralytics', 'yolov5',
        'matplotlib', 'seaborn', 'pandas', 'scipy',
        'tqdm', 'yaml',
        # onnx: keep core (needed by torch.onnx.export) but drop the heavy /
        # crash-prone bits that aren't needed for export.
        'onnx.reference', 'onnx.backend', 'onnxscript',
        # onnxruntime tooling not needed for inference (these pull in onnx.reference)
        'onnxruntime.quantization', 'onnxruntime.transformers',
        'onnxruntime.tools', 'onnxruntime.training',
        # Standard noise
        'tkinter', '_tkinter', 'xmlrpc', 'doctest', 'test',
        'IPython', 'jupyter',
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
    console=False,
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
