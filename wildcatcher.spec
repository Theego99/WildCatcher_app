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
import sys

sys.path.insert(0, SPECPATH)  # PyInstaller spec-file global: dir of this file
import wc_version  # single source of truth for the app version

block_cipher = None

# PyInstaller rejects a .ico icon on macOS (wants .icns); use the icon only on Windows.
_app_icon = 'assets/app_icon.ico' if sys.platform == 'win32' else None

# torch / torchvision / onnxruntime are pulled in via hiddenimports below and
# collected by PyInstaller's built-in hooks (hook-torch, hook-onnxruntime, ...).
# We deliberately do NOT collect_all them — that dragged in onnxruntime.quantization
# -> onnx -> onnx.reference, whose import crashes PyInstaller's analysis subprocess.
datas, binaries, hiddenimports = [], [], []

# ---------------------------------------------------------------------------
# Data files to bundle (src, dest_in_bundle)
# ---------------------------------------------------------------------------
# Only bundle paths that exist on this platform (e.g. the Windows-only vlc/ folder).
# NOTE: the user `models/` folder is intentionally NOT bundled — it is read from
# next to the executable at runtime (wc_models._ensure_models_dir) and populated
# by installer.iss / build.bat, so bundling it here would be dead weight.
_candidate_data = [
    ('detector_AI_model.onnx', '.'),   # built-in detector (ONNX), the only detector
    ('assets',                 'assets'),  # UI assets
    ('vlc',                    'vlc'),      # Windows VLC runtime (absent on macOS)
]
datas += [(src, dst) for src, dst in _candidate_data if os.path.exists(src)]

# fpdf2 ships a small data dir (sRGB ICC profile). Not needed for the current
# report, but collect it defensively so PDF export never breaks if fpdf grows a
# hard dependency on it.
try:
    from PyInstaller.utils.hooks import collect_data_files
    datas += collect_data_files('fpdf')
except Exception:
    pass

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
    # v2.1 licensing uses ECC (P-256) + DSS keys; keep RSA for old-file compat.
    'Crypto', 'Crypto.PublicKey', 'Crypto.PublicKey.RSA', 'Crypto.PublicKey.ECC',
    'Crypto.Signature', 'Crypto.Signature.pkcs1_15', 'Crypto.Signature.DSS',
    'Crypto.Hash', 'Crypto.Hash.SHA256',

    # --- App metadata / logging / entitlements (v2.1) ---
    'wc_version', 'wc_logging', 'wc_entitlements',

    # --- VLC Python bindings ---
    'vlc',

    # --- Misc ---
    'numpy',
    'openpyxl',
    'psutil',
    'requests',
    'fpdf',  # PDF report export (fpdf2)
]
hiddenimports += hidden_imports

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
_common_analysis_kwargs = dict(
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

a = Analysis(['detector_animales_diego.py'], **_common_analysis_kwargs)

# Second entry point: the heavy-use CLI (wc_cli.py) a client asked for so they
# can queue multiple folders for unattended processing. Shares the same
# dependency bundle as the GUI via MERGE() so this doesn't duplicate
# onnxruntime/torch/PyQt5 in the installed folder -- the whole point of the
# ONNX migration was to keep the install small.
a_cli = Analysis(['wc_cli.py'], **_common_analysis_kwargs)

MERGE(
    (a, 'detector_animales_diego', 'WildCatcher'),
    (a_cli, 'wc_cli', 'WildCatcher-CLI'),
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
pyz_cli = PYZ(a_cli.pure, a_cli.zipped_data, cipher=block_cipher)

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
    icon=_app_icon,
)

exe_cli = EXE(
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name='WildCatcher-CLI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # CLI tool -- needs a real console for stdout/stdin
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_app_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.zipfiles,
    a_cli.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='WildCatcher',
)

# On macOS, wrap the COLLECT output into a double-clickable .app bundle.
# (Without this, PyInstaller produces a bare Unix executable that Finder
# refuses to launch on double-click.)
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='WildCatcher.app',
        icon=None,  # no .icns shipped; uses the default app icon
        bundle_identifier='com.wildcatcher.app',
        info_plist={
            'NSHighResolutionCapable': True,
            'CFBundleShortVersionString': wc_version.APP_VERSION,
        },
    )
