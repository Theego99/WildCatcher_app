"""
Phase 0.5 speed spike: export the built-in detector to ONNX and compare
inference speed of PyTorch-CUDA vs ONNX Runtime DirectML on this machine.

Speed is content-independent, so synthetic frames are used. Run from repo root:
    venv\\Scripts\\python.exe tools\\spike_benchmark.py
"""
import os
import sys
import time

# The pickled detector mixes top-level (`models.*`/`utils.*`) and package
# (`yolov5.*`) imports, so both the repo root and yolov5/ must be importable.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "yolov5"))

import numpy as np
import torch

MODEL_PT = "detector_AI_model.pt"
MODEL_ONNX = "detector_AI_model.onnx"
# Realistic letterbox(auto=True) shape for a 16:9 frame at imgsz=1280: H=768, W=1280
H, W = 768, 1280
WARMUP = 5
ITERS = 30


def load_torch_model(device="cpu"):
    ckpt = torch.load(MODEL_PT, map_location=device, weights_only=False)
    for m in ckpt["model"].modules():
        t = type(m)
        if t is torch.nn.Upsample and not hasattr(m, "recompute_scale_factor"):
            m.recompute_scale_factor = None
    model = ckpt["model"].float().fuse().eval()
    # Put the Detect head into export mode -> single (b, N, nc+5) output tensor
    for m in model.modules():
        if type(m).__name__ == "Detect":
            m.export = True
            m.dynamic = False
            m.inplace = False
    return model


def export_onnx(model):
    model.cpu()
    dummy = torch.zeros(1, 3, IMG, IMG)
    with torch.no_grad():
        out = model(dummy)
    out0 = out[0] if isinstance(out, (tuple, list)) else out
    print(f"[export] torch output shape: {tuple(out0.shape)}")
    torch.onnx.export(
        model, dummy, MODEL_ONNX,
        opset_version=OPSET, input_names=["images"], output_names=["output"],
        do_constant_folding=True,
    )
    print(f"[export] wrote {MODEL_ONNX}")


def bench_torch():
    if not torch.cuda.is_available():
        print("[torch] CUDA not available, skipping")
        return None
    model = load_torch_model("cpu").to("cuda")
    x = torch.zeros(1, 3, H, W, device="cuda")
    with torch.no_grad():
        for _ in range(WARMUP):
            model(x)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(ITERS):
            model(x)
        torch.cuda.synchronize()
        dt = (time.perf_counter() - t0) / ITERS
    del model, x
    torch.cuda.empty_cache()
    print(f"[torch-CUDA]  {dt*1000:7.1f} ms/frame   {1/dt:6.1f} FPS")
    return dt


def bench_onnx(provider):
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess = ort.InferenceSession(MODEL_ONNX, sess_options=so, providers=[provider])
    actual = sess.get_providers()[0]
    x = np.zeros((1, 3, H, W), dtype=np.float32)
    name = sess.get_inputs()[0].name
    for _ in range(WARMUP):
        sess.run(None, {name: x})
    t0 = time.perf_counter()
    for _ in range(ITERS):
        sess.run(None, {name: x})
    dt = (time.perf_counter() - t0) / ITERS
    print(f"[onnx-{actual:<22}] {dt*1000:7.1f} ms/frame   {1/dt:6.1f} FPS")
    return dt


if __name__ == "__main__":
    print("=" * 60)
    print(f"benchmark input: 1x3x{H}x{W}  (realistic letterbox shape)")
    if not os.path.exists(MODEL_ONNX):
        export_onnx(load_torch_model("cpu"))
    print("-" * 60)
    t = bench_torch()
    d = bench_onnx("DmlExecutionProvider")
    c = bench_onnx("CPUExecutionProvider")
    print("-" * 60)
    if t and d:
        ratio = d / t
        print(f"DirectML is {ratio:.2f}x the torch-CUDA time "
              f"({'slower' if ratio > 1 else 'faster'})")
    print("=" * 60)
