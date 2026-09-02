"""
Convert WildCatcher's built-in YOLOv5 detector (.pt) to ONNX.

Exports with DYNAMIC batch/height/width so the runtime can keep using the
original `letterbox(auto=True)` rectangular preprocessing (no speed regression
vs the PyTorch path). Run from the repo root with the project venv:

    venv\\Scripts\\python.exe tools\\convert_to_onnx.py
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# The pickled detector mixes top-level (`models.*`) and package (`yolov5.*`) imports.
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "yolov5"))

import torch  # noqa: E402

DETECTOR_PT = os.path.join(_ROOT, "detector_AI_model.pt")
DETECTOR_ONNX = os.path.join(_ROOT, "detector_AI_model.onnx")
OPSET = 12


def _load_detector(path):
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    for m in ckpt["model"].modules():
        if type(m) is torch.nn.Upsample and not hasattr(m, "recompute_scale_factor"):
            m.recompute_scale_factor = None
    model = ckpt["model"].float().fuse().eval()
    for m in model.modules():
        if type(m).__name__ == "Detect":
            m.export = True       # single (b, N, nc+5) inference output
            m.dynamic = True      # rebuild grid per input shape (dynamic H/W)
            m.inplace = False
    return model


def convert_detector(src=DETECTOR_PT, dst=DETECTOR_ONNX, imgsz=1280):
    model = _load_detector(src)
    dummy = torch.zeros(1, 3, imgsz, imgsz)
    with torch.no_grad():
        out = model(dummy)
    out0 = out[0] if isinstance(out, (tuple, list)) else out
    print(f"[detector] torch output shape: {tuple(out0.shape)}")
    torch.onnx.export(
        model, dummy, dst,
        opset_version=OPSET,
        input_names=["images"], output_names=["output"],
        dynamic_axes={
            "images": {0: "batch", 2: "height", 3: "width"},
            "output": {0: "batch", 1: "anchors"},
        },
        do_constant_folding=True,
    )
    mb = os.path.getsize(dst) / (1024 * 1024)
    print(f"[detector] wrote {dst} ({mb:.1f} MB)")
    return dst


if __name__ == "__main__":
    convert_detector()
