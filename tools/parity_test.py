"""
Parity check: ONNX detector path vs the original PyTorch path.

1. Raw output fidelity: same random input -> torch model vs ONNX session.
2. NMS port: torch (yolov5) NMS vs wc_yolo_utils numpy NMS on the same preds.

Dev-time only (needs torch). Run from repo root:
    venv\\Scripts\\python.exe tools\\parity_test.py
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "yolov5"))

import numpy as np
import torch
import onnxruntime as ort

from yolov5.utils.general import non_max_suppression as torch_nms
from wc_yolo_utils import non_max_suppression as np_nms

ONNX = os.path.join(_ROOT, "detector_AI_model.onnx")
PT = os.path.join(_ROOT, "detector_AI_model.pt")
H, W = 768, 1280


def load_torch_model():
    ckpt = torch.load(PT, map_location="cpu", weights_only=False)
    for m in ckpt["model"].modules():
        if type(m) is torch.nn.Upsample and not hasattr(m, "recompute_scale_factor"):
            m.recompute_scale_factor = None
    model = ckpt["model"].float().fuse().eval()
    for m in model.modules():
        if type(m).__name__ == "Detect":
            m.export, m.dynamic, m.inplace = True, True, False
    return model


def main():
    rng = np.random.default_rng(0)
    x = rng.random((1, 3, H, W), dtype=np.float32)

    model = load_torch_model()
    with torch.no_grad():
        t_out = model(torch.from_numpy(x))
    t_pred = (t_out[0] if isinstance(t_out, (tuple, list)) else t_out).numpy()

    sess = ort.InferenceSession(ONNX, providers=["CPUExecutionProvider"])
    o_pred = sess.run(None, {sess.get_inputs()[0].name: x})[0]

    print(f"torch pred shape {t_pred.shape}  onnx pred shape {o_pred.shape}")
    diff = np.abs(t_pred - o_pred)
    print(f"raw output  max|diff|={diff.max():.3e}  mean|diff|={diff.mean():.3e}")

    # NMS parity at a low threshold so some boxes survive random input
    conf = 0.01
    t_boxes = torch_nms(torch.from_numpy(o_pred), conf_thres=conf, iou_thres=0.45)[0].numpy()
    n_boxes = np_nms(o_pred, conf_thres=conf, iou_thres=0.45)[0]
    print(f"NMS @conf={conf}: torch kept {len(t_boxes)}  numpy kept {len(n_boxes)}")
    if len(t_boxes) and len(n_boxes):
        m = min(len(t_boxes), len(n_boxes))
        bd = np.abs(t_boxes[:m, :4] - n_boxes[:m, :4]).max()
        print(f"  top-{m} box coord max|diff|={bd:.3e}")
    print("OK" if diff.max() < 1e-2 else "WARN: large raw diff")


if __name__ == "__main__":
    main()
