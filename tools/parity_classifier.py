"""
Classifier parity: torch reference vs the ONNX runtime path (classify_image).

For each registered classifier, runs the same image through:
  - torch: reconstructed model + torchvision transforms (the OLD path)
  - onnx : wc_models.classify_image (the NEW path; triggers lazy .pth->.onnx)
and compares predicted class + confidence.

Dev-time only (needs torch). Run from repo root:
    venv\\Scripts\\python.exe tools\\parity_classifier.py [image_path]
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)

import numpy as np
import torch
from PIL import Image
from torchvision import transforms

import wc_convert
import wc_models

IMG = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_ROOT, "assets", "app_icon.png")
SIZE = 224
_tf = transforms.Compose([
    transforms.Resize((SIZE, SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


def torch_predict(entry):
    path = os.path.join(_ROOT, "models", entry["filename"])
    # entry filename may already be .onnx after a prior run; find the source .pth
    if path.lower().endswith(".onnx"):
        base = os.path.splitext(path)[0]
        path = base + ".pth" if os.path.exists(base + ".pth") else base + ".pt"
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    sd = ckpt.get("model_state_dict") or ckpt.get("state_dict")
    info = wc_convert.probe_checkpoint(path)
    model, output_dim, head_type = wc_convert.build_classifier_model(
        sd, entry["class_names"], entry.get("architecture") or info["architecture"],
        entry.get("head_type") or info["head_type"])
    img = Image.open(IMG).convert("RGB")
    with torch.no_grad():
        out = model(_tf(img).unsqueeze(0))
    cn = entry["class_names"]
    if head_type in ("binary_fc", "binary_sigmoid") or out.shape[1] == 1:
        prob = torch.sigmoid(out[0, 0]).item()
        return (cn[0], prob) if prob >= 0.5 else (cn[1], 1 - prob)
    probs = torch.softmax(out, dim=1)[0]
    i = int(torch.argmax(probs))
    return cn[i], float(probs[i])


def main():
    print(f"image: {IMG}")
    print("=" * 72)
    for entry in wc_models.load_registry():
        if entry["type"] != "classifier":
            continue
        try:
            t_cls, t_conf = torch_predict(entry)
            o_cls, o_conf = wc_models.classify_image(IMG, entry)
            ok = (t_cls == o_cls) and abs(t_conf - o_conf) < 1e-2
            print(f"[{'OK ' if ok else 'DIFF'}] {entry['name']:<28} "
                  f"torch=({t_cls},{t_conf:.4f})  onnx=({o_cls},{o_conf:.4f})")
        except Exception as e:
            print(f"[ERR] {entry['name']:<28} {e}")
    print("=" * 72)


if __name__ == "__main__":
    main()
