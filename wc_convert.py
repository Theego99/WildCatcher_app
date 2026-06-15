"""
Torch-dependent model conversion for WildCatcher (import-time only).

This module is imported lazily — ONLY when a user adds a .pt/.pth model and it
must be converted to ONNX. The shipped runtime never imports it, so PyTorch can
be a small CPU-only build used purely for this one-shot export.

It owns the checkpoint probing + architecture/head reconstruction that used to
live in wc_models.py (ResNet / EfficientNet, multi-layer and binary fc1/fc2
heads), plus `convert_classifier_to_onnx`.
"""
import os
import logging

import torch
import torch.nn as nn
from torchvision import models

CLASSIFICATION_IMG_SIZE = 224

_ARCH_BUILDERS = {
    "resnet18": "resnet", "resnet34": "resnet", "resnet50": "resnet", "resnet101": "resnet",
    "efficientnet_b0": "efficientnet", "efficientnet_b1": "efficientnet",
    "efficientnet_b2": "efficientnet", "efficientnet_b3": "efficientnet",
    "efficientnet_b4": "efficientnet",
}


def probe_checkpoint(model_path):
    """Probe a checkpoint for class_names, architecture, num_classes, head_type."""
    info = {"class_names": None, "architecture": None, "num_classes": None,
            "format": "unknown", "head_type": "standard"}
    try:
        ckpt = torch.load(model_path, map_location="cpu", weights_only=False)
        sd = ckpt.get("model_state_dict") or ckpt.get("state_dict", {})

        if "architecture" in ckpt:
            info["architecture"] = ckpt["architecture"]
        elif "arch" in ckpt:
            info["architecture"] = ckpt["arch"]
        else:
            keys_str = " ".join(list(sd.keys())[:10] + list(sd.keys())[-10:])
            if "features." in keys_str and ("classifier." in keys_str or "fc1." in keys_str):
                info["architecture"] = "efficientnet_b0"
            elif "fc.weight" in sd or any("layer4" in k for k in sd):
                info["architecture"] = "resnet50"

        has_fc1 = any(k.startswith("fc1.") for k in sd)
        has_fc2 = any(k.startswith("fc2.") for k in sd)
        if has_fc1 and has_fc2:
            info["head_type"] = "binary_fc"

        if "class_names" in ckpt and isinstance(ckpt["class_names"], (list, tuple)):
            info["class_names"] = list(ckpt["class_names"])
            info["format"] = "class_names"
        elif "class_to_idx" in ckpt and isinstance(ckpt["class_to_idx"], dict):
            c2i = ckpt["class_to_idx"]
            info["class_names"] = [n for n, _ in sorted(c2i.items(), key=lambda x: x[1])]
            info["format"] = "class_to_idx"
        elif "idx_to_class" in ckpt and isinstance(ckpt["idx_to_class"], dict):
            i2c = ckpt["idx_to_class"]
            info["class_names"] = [i2c[k] for k in sorted(i2c.keys())]
            info["format"] = "idx_to_class"
        elif "classes" in ckpt and isinstance(ckpt["classes"], (list, tuple)):
            info["class_names"] = list(ckpt["classes"])
            info["format"] = "classes"
        elif "target_class" in ckpt:
            info["class_names"] = [ckpt["target_class"], "rest"]
            info["format"] = "binary_target"
        elif "class_counts" in ckpt and isinstance(ckpt["class_counts"], dict):
            cc = ckpt["class_counts"]
            if "target" in cc and "rest" in cc:
                fname = os.path.splitext(os.path.basename(model_path))[0].lower()
                for pattern in ["binary_", "vs_rest", "vs_all", "_vs_"]:
                    fname = fname.replace(pattern, " ")
                parts = [p.strip() for p in fname.split() if p.strip()]
                info["class_names"] = [(parts[0] if parts else "target"), "rest"]
                info["format"] = "class_counts_inferred"

        if "num_classes" in ckpt:
            info["num_classes"] = ckpt["num_classes"]
        elif info["class_names"]:
            info["num_classes"] = len(info["class_names"])
        else:
            nc = _infer_num_classes_from_sd(sd)
            if nc:
                info["num_classes"] = nc
    except Exception as e:
        logging.warning(f"Failed to probe checkpoint {model_path}: {e}")
    return info


def _infer_num_classes_from_sd(sd):
    candidates = [
        "classifier.4.weight", "classifier.4.bias", "classifier.1.weight", "classifier.1.bias",
        "fc.weight", "fc.bias", "fc2.weight", "fc2.bias",
        "head.weight", "head.bias", "output.weight", "output.bias",
    ]
    cls_weight_keys = sorted(
        [k for k in sd if k.startswith("classifier.") and k.endswith(".weight")],
        key=lambda k: int(k.split(".")[1]) if k.split(".")[1].isdigit() else -1, reverse=True)
    if cls_weight_keys:
        return sd[cls_weight_keys[0]].shape[0]
    for key in candidates:
        if key in sd and key.endswith(".weight"):
            return sd[key].shape[0]
    return None


def _build_resnet(name, num_classes):
    builder = getattr(models, name)
    model = builder(weights=None)
    model.fc = nn.Linear(model.fc.in_features, num_classes)
    return model


def _build_efficientnet(name, num_classes, state_dict=None):
    builder = getattr(models, name, None)
    if builder is None:
        raise ValueError(f"Unknown architecture: {name}")
    model = builder(weights=None)
    if not (hasattr(model, "classifier") and isinstance(model.classifier, nn.Sequential)):
        raise ValueError(f"Cannot modify classifier head for {name}")
    in_features = model.classifier[1].in_features
    remapped_sd = None
    if state_dict is not None:
        has_fc1 = "fc1.weight" in state_dict
        has_fc2 = "fc2.weight" in state_dict
        if has_fc1 and has_fc2:
            hidden_dim = state_dict["fc1.weight"].shape[0]
            output_dim = state_dict["fc2.weight"].shape[0]
            model.classifier = nn.Sequential(
                nn.Linear(in_features, hidden_dim), nn.ReLU(inplace=True),
                nn.Linear(hidden_dim, output_dim))
            remapped_sd = {}
            for k, v in state_dict.items():
                if k == "fc1.weight":
                    remapped_sd["classifier.0.weight"] = v
                elif k == "fc1.bias":
                    remapped_sd["classifier.0.bias"] = v
                elif k == "fc2.weight":
                    remapped_sd["classifier.2.weight"] = v
                elif k == "fc2.bias":
                    remapped_sd["classifier.2.bias"] = v
                else:
                    remapped_sd[k] = v
        else:
            model.classifier = _rebuild_classifier_head(state_dict, in_features, num_classes)
    else:
        model.classifier[1] = nn.Linear(in_features, num_classes)
    return model, remapped_sd


def _rebuild_classifier_head(state_dict, in_features, num_classes):
    cls_keys = [k for k in state_dict if k.startswith("classifier.")]
    if not cls_keys:
        return nn.Sequential(nn.Dropout(p=0.2, inplace=True), nn.Linear(in_features, num_classes))
    idx_keys, max_idx = {}, 0
    for k in cls_keys:
        parts = k.split(".")
        if len(parts) < 3:
            continue
        try:
            idx = int(parts[1])
        except ValueError:
            continue
        idx_keys.setdefault(idx, set()).add(parts[2])
        max_idx = max(max_idx, idx)
    IDX_LINEAR, IDX_BATCHNORM = "linear", "batchnorm"
    idx_type, has_batchnorm = {}, False
    for idx, keys in idx_keys.items():
        if "running_mean" in keys or "running_var" in keys:
            idx_type[idx] = IDX_BATCHNORM
            has_batchnorm = True
        else:
            idx_type[idx] = IDX_LINEAR
    activation_cls = nn.SiLU if has_batchnorm else nn.ReLU
    layers = []
    for idx in range(max_idx + 1):
        if idx in idx_type:
            if idx_type[idx] == IDX_LINEAR:
                w = state_dict[f"classifier.{idx}.weight"]
                layers.append(nn.Linear(w.shape[1], w.shape[0]))
            else:
                rm = state_dict[f"classifier.{idx}.running_mean"]
                layers.append(nn.BatchNorm1d(rm.shape[0]))
        else:
            if idx_type.get(idx - 1) == IDX_LINEAR:
                layers.append(activation_cls())
            else:
                layers.append(nn.Dropout())
    return nn.Sequential(*layers)


def build_classifier_model(sd, class_names, architecture, head_type):
    """Reconstruct an nn.Module from a state_dict. Returns (model, output_dim, head_type)."""
    num_classes = len(class_names)
    arch_lower = (architecture or "resnet50").lower().replace("-", "_")
    family = _ARCH_BUILDERS.get(arch_lower)
    if family is None:
        raise ValueError(f"Unsupported architecture '{architecture}'. "
                         f"Supported: {', '.join(sorted(_ARCH_BUILDERS.keys()))}")
    if family == "resnet":
        model = _build_resnet(arch_lower, num_classes)
        load_sd = sd
    else:
        model, remapped = _build_efficientnet(arch_lower, num_classes, state_dict=sd)
        load_sd = remapped if remapped is not None else sd

    output_dim = None
    if family == "efficientnet" and hasattr(model, "classifier"):
        for layer in reversed(list(model.classifier.children())):
            if isinstance(layer, nn.Linear):
                output_dim = layer.out_features
                break
    elif family == "resnet" and hasattr(model, "fc"):
        output_dim = model.fc.out_features
    if output_dim == 1:
        head_type = "binary_sigmoid"

    model.load_state_dict(load_sd)
    model.eval()
    return model, output_dim, head_type


def convert_classifier_to_onnx(pth_path, onnx_path, entry=None):
    """Convert a classifier .pth/.pt to ONNX. Returns metadata dict for the registry."""
    info = probe_checkpoint(pth_path)
    entry = entry or {}
    class_names = entry.get("class_names") or info["class_names"]
    if not class_names:
        raise ValueError("Cannot determine class names for classifier conversion")
    architecture = entry.get("architecture") or info["architecture"]
    head_type = entry.get("head_type") or info.get("head_type", "standard")

    ckpt = torch.load(pth_path, map_location="cpu", weights_only=False)
    sd = ckpt.get("model_state_dict") or ckpt.get("state_dict")
    if sd is None:
        raise ValueError("No 'model_state_dict' or 'state_dict' found in checkpoint")

    model, output_dim, head_type = build_classifier_model(sd, class_names, architecture, head_type)
    dummy = torch.zeros(1, 3, CLASSIFICATION_IMG_SIZE, CLASSIFICATION_IMG_SIZE)
    with torch.no_grad():
        torch.onnx.export(
            model, dummy, onnx_path, opset_version=12,
            input_names=["input"], output_names=["output"],
            dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
            do_constant_folding=True)
    logging.info(f"Converted classifier -> {onnx_path} "
                 f"(arch={architecture}, out={output_dim}, head={head_type})")
    return {"class_names": class_names, "architecture": architecture,
            "head_type": head_type, "num_classes": len(class_names),
            "output_dim": output_dim}
