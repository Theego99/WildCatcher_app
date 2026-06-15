"""WildCatcher ONNX Runtime session + execution-provider utilities.

Replaces the torch device selection in `wc_gpu.py` for the inference path.
Keeps GPU acceleration without bundling the PyTorch CUDA stack:
  Windows : CUDA (if an onnxruntime-gpu build is present) -> DirectML -> CPU
  macOS   : CoreML -> CPU
  Linux   : CUDA -> CPU
"""
import platform

import onnxruntime as ort

# Ordered preference per platform; filtered against what's actually available.
_PREFERRED = {
    "Windows": ["CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"],
    "Darwin": ["CoreMLExecutionProvider", "CPUExecutionProvider"],
    "Linux": ["CUDAExecutionProvider", "CPUExecutionProvider"],
}


def get_onnx_providers(prefer_gpu=True):
    """Return the ORT provider list to use, best-first, filtered to available ones."""
    available = set(ort.get_available_providers())
    pref = _PREFERRED.get(platform.system(), ["CPUExecutionProvider"])
    providers = [p for p in pref if p in available]
    if not prefer_gpu:
        providers = ["CPUExecutionProvider"]
    if "CPUExecutionProvider" not in providers:
        providers.append("CPUExecutionProvider")  # always a safe fallback
    return providers


def create_session(onnx_path, prefer_gpu=True):
    """Create an InferenceSession on the best available provider.

    Returns (session, active_provider). Falls back to CPU if a GPU provider
    fails to initialize (e.g. missing runtime, unsupported op set).
    """
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    providers = get_onnx_providers(prefer_gpu)
    try:
        sess = ort.InferenceSession(onnx_path, sess_options=so, providers=providers)
    except Exception as e:
        print(f"ONNX: GPU provider init failed ({e}); falling back to CPU.")
        sess = ort.InferenceSession(onnx_path, sess_options=so,
                                    providers=["CPUExecutionProvider"])
    return sess, sess.get_providers()[0]


def get_onnx_diagnostics():
    """Return a list of diagnostic strings about the ONNX Runtime environment."""
    lines = []
    lines.append("=" * 50)
    lines.append("ONNX RUNTIME DIAGNOSTICS")
    lines.append("=" * 50)
    lines.append(f"onnxruntime version: {ort.__version__}")
    lines.append(f"Platform: {platform.system()} {platform.machine()}")

    available = ort.get_available_providers()
    lines.append(f"Available providers: {', '.join(available)}")

    providers = get_onnx_providers(prefer_gpu=True)
    selected = providers[0] if providers else "CPUExecutionProvider"
    lines.append(f"Selected provider: {selected}")

    if selected == "CUDAExecutionProvider":
        lines.append("STATUS: Using NVIDIA GPU (CUDA).")
    elif selected == "DmlExecutionProvider":
        lines.append("STATUS: Using GPU via DirectML (any DirectX 12 GPU).")
    elif selected == "CoreMLExecutionProvider":
        lines.append("STATUS: Using Apple GPU/Neural Engine (CoreML).")
    else:
        lines.append("WARNING: No GPU provider available — running on CPU (SLOWER).")
        if platform.system() == "Windows":
            lines.append("FIX: ensure 'onnxruntime-directml' is installed and a "
                         "DirectX 12 GPU/driver is present.")

    lines.append("=" * 50)
    return lines
