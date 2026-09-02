# PyInstaller runtime hook — runs BEFORE all package runtime hooks.
#
# Import onnxruntime first so its native DLLs initialize while the DLL search
# path is still clean. PyInstaller's PyQt5 runtime hook adds Qt's bin/ directory
# to the search path; if that happens before onnxruntime loads, Qt's bundled
# DLLs shadow onnxruntime's dependencies and its DLL initialization fails
# ("DLL load failed while importing onnxruntime_pybind11_state"). Loading
# onnxruntime first avoids the conflict (its DLLs stay resident afterwards).
try:
    import onnxruntime  # noqa: F401
except Exception:
    pass
