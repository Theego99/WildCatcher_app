"""
WildCatcher model registry and classification pipeline.

Supports user-added .pt/.pth models (both detector and classifier types).
Classifier architectures auto-detected: ResNet50, EfficientNet-B0/B1/B2, etc.
Models are registered in a JSON config file and loaded on demand.
Pipeline steps define ordered model execution with per-step options.
"""
import os
import sys
import json
import shutil
import logging

import torch
import torch.nn as nn
from torchvision import models, transforms
from PIL import Image as PILImage

from wc_gpu import get_best_device

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MODELS_DIR = "models"
BUILTIN_DETECTOR_PATH = "detector_AI_model.pt"
BUILTIN_CLASSIFIER_PATH = "prec90rec93f191.pt"
CLASSIFICATION_IMG_SIZE = 224


def resource_path(relative_path):
    """Resolve path for both dev and PyInstaller."""
    try:
        base = sys._MEIPASS
    except AttributeError:
        base = os.path.abspath(".")
    return os.path.join(base, relative_path)


def _ensure_models_dir():
    """Create the models directory next to the executable if needed."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.abspath(".")
    path = os.path.join(base, MODELS_DIR)
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Registry  (persisted JSON list of model entries)
# ---------------------------------------------------------------------------

def _registry_path():
    return os.path.join(_ensure_models_dir(), "registry.json")


def load_registry():
    """Load the model registry. Returns list of dicts."""
    path = _registry_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_registry(entries):
    """Persist the registry list to disk."""
    path = _registry_path()
    _ensure_models_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def _probe_checkpoint(model_path):
    """
    Probe a checkpoint file to extract metadata without fully loading it.
    Returns dict with: class_names, architecture, num_classes, format, head_type.

    Supported checkpoint formats:
      - ResNet50 built-in:  {class_names: [...], model_state_dict: {...}}
      - EfficientNet multi: {architecture: str, class_to_idx: {...},
                             idx_to_class: {...}, model_state_dict: {...}}
      - Binary classifier:  {architecture: str, target_class: str,
                             class_counts: {"target": N, "rest": M},
                             model_state_dict: {...}}  (fc1/fc2 head)
    """
    info = {
        "class_names": None,
        "architecture": None,
        "num_classes": None,
        "format": "unknown",
        "head_type": "standard",  # "standard" or "binary_fc"
    }
    try:
        ckpt = torch.load(model_path, map_location="cpu", weights_only=False)

        sd = ckpt.get("model_state_dict") or ckpt.get("state_dict", {})

        # --- Detect architecture ---
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

        # --- Detect head type from state_dict ---
        has_fc1 = any(k.startswith("fc1.") for k in sd)
        has_fc2 = any(k.startswith("fc2.") for k in sd)
        if has_fc1 and has_fc2:
            info["head_type"] = "binary_fc"

        # --- Extract class names (try multiple formats) ---
        # 1) direct class_names list
        if "class_names" in ckpt and isinstance(ckpt["class_names"], (list, tuple)):
            info["class_names"] = list(ckpt["class_names"])
            info["format"] = "class_names"

        # 2) class_to_idx dict  {name: int}
        elif "class_to_idx" in ckpt and isinstance(ckpt["class_to_idx"], dict):
            c2i = ckpt["class_to_idx"]
            info["class_names"] = [n for n, _ in sorted(c2i.items(), key=lambda x: x[1])]
            info["format"] = "class_to_idx"

        # 3) idx_to_class dict  {int: name}
        elif "idx_to_class" in ckpt and isinstance(ckpt["idx_to_class"], dict):
            i2c = ckpt["idx_to_class"]
            info["class_names"] = [i2c[k] for k in sorted(i2c.keys())]
            info["format"] = "idx_to_class"

        # 4) classes list
        elif "classes" in ckpt and isinstance(ckpt["classes"], (list, tuple)):
            info["class_names"] = list(ckpt["classes"])
            info["format"] = "classes"

        # 5) Binary classifier: target_class + rest
        elif "target_class" in ckpt:
            target = ckpt["target_class"]
            info["class_names"] = [target, "rest"]
            info["format"] = "binary_target"

        # 6) class_counts dict with "target"/"rest" keys but no target_class
        elif "class_counts" in ckpt and isinstance(ckpt["class_counts"], dict):
            cc = ckpt["class_counts"]
            # Try to infer class names from class_counts keys
            if "target" in cc and "rest" in cc:
                # Use filename to guess target class
                fname = os.path.splitext(os.path.basename(model_path))[0].lower()
                # Try to extract "X" from "binary_X_vs_rest" pattern
                for pattern in ["binary_", "vs_rest", "vs_all", "_vs_"]:
                    fname = fname.replace(pattern, " ")
                parts = [p.strip() for p in fname.split() if p.strip()]
                target_name = parts[0] if parts else "target"
                info["class_names"] = [target_name, "rest"]
                info["format"] = "class_counts_inferred"

        # Num classes
        if "num_classes" in ckpt:
            info["num_classes"] = ckpt["num_classes"]
        elif info["class_names"]:
            info["num_classes"] = len(info["class_names"])
        else:
            # Try to infer from the output layer shape in state_dict
            nc = _infer_num_classes_from_sd(sd)
            if nc:
                info["num_classes"] = nc

    except Exception as e:
        logging.warning(f"Failed to probe checkpoint {model_path}: {e}")

    return info


def _infer_num_classes_from_sd(sd):
    """Try to determine num_classes from the final linear layer in state_dict."""
    # Common output layer key patterns (ordered by specificity)
    candidates = [
        # EfficientNet multi-layer head
        "classifier.4.weight", "classifier.4.bias",
        # EfficientNet simple head
        "classifier.1.weight", "classifier.1.bias",
        # ResNet
        "fc.weight", "fc.bias",
        # Custom heads
        "fc2.weight", "fc2.bias",
        "head.weight", "head.bias",
        "output.weight", "output.bias",
    ]
    # Find the highest-numbered classifier layer (it's the output)
    cls_weight_keys = sorted(
        [k for k in sd if k.startswith("classifier.") and k.endswith(".weight")],
        key=lambda k: int(k.split(".")[1]) if k.split(".")[1].isdigit() else -1,
        reverse=True,
    )
    if cls_weight_keys:
        shape = sd[cls_weight_keys[0]].shape
        return shape[0]  # output dim = num_classes

    # Fallback to known patterns
    for key in candidates:
        if key in sd and key.endswith(".weight"):
            return sd[key].shape[0]

    return None


def register_model(src_path, name, model_type, manual_class_names=None):
    """
    Copy a .pt/.pth file into the models dir and add it to the registry.
    manual_class_names: optional list of class name strings (for models
    that don't embed class info in the checkpoint).
    Returns the new registry entry or raises on failure.
    """
    if not os.path.isfile(src_path):
        raise FileNotFoundError(f"Model file not found: {src_path}")

    dest_dir = _ensure_models_dir()
    filename = os.path.basename(src_path)

    dest = os.path.join(dest_dir, filename)
    counter = 1
    while os.path.exists(dest):
        base, ext = os.path.splitext(filename)
        dest = os.path.join(dest_dir, f"{base}_{counter}{ext}")
        counter += 1

    shutil.copy2(src_path, dest)

    # Probe checkpoint for metadata
    class_names = None
    architecture = None
    head_type = "standard"
    num_classes_inferred = None
    if model_type == "classifier":
        info = _probe_checkpoint(dest)
        class_names = info["class_names"]
        architecture = info["architecture"]
        head_type = info.get("head_type", "standard")
        num_classes_inferred = info.get("num_classes")

        # Use manual class names if auto-detection failed
        if not class_names and manual_class_names:
            class_names = manual_class_names
            # Validate: binary models (1 output) accept 2 labels
            if num_classes_inferred is not None:
                expected = 2 if num_classes_inferred == 1 else num_classes_inferred
                if len(class_names) != expected:
                    os.remove(dest)
                    raise ValueError(
                        f"Model has {num_classes_inferred} output neuron(s) → "
                        f"expects {expected} class names, but you provided "
                        f"{len(class_names)}."
                    )

        if not class_names:
            os.remove(dest)
            hint = ""
            if num_classes_inferred is not None:
                expected = 2 if num_classes_inferred == 1 else num_classes_inferred
                hint = f"\nThe model has {num_classes_inferred} output neuron(s) → provide {expected} class names."
            raise ValueError(
                f"Could not detect class names from the checkpoint.{hint}\n"
                f"Please provide class names when adding this model."
            )

    entry = {
        "id": os.path.splitext(os.path.basename(dest))[0],
        "name": name,
        "type": model_type,
        "filename": os.path.basename(dest),
        "class_names": class_names,
        "architecture": architecture,
        "head_type": head_type,
    }

    reg = load_registry()
    reg.append(entry)
    save_registry(reg)
    return entry


def unregister_model(model_id):
    """Remove a model from the registry and delete its file."""
    reg = load_registry()
    new_reg = []
    for entry in reg:
        if entry["id"] == model_id:
            fpath = os.path.join(_ensure_models_dir(), entry["filename"])
            if os.path.exists(fpath):
                os.remove(fpath)
        else:
            new_reg.append(entry)
    save_registry(new_reg)


def update_model_class_names(model_id, class_names):
    """Update class_names for an existing registry entry. Returns True on success."""
    reg = load_registry()
    for entry in reg:
        if entry["id"] == model_id:
            # Validate against model output layer if possible
            fpath = os.path.join(_ensure_models_dir(), entry["filename"])
            if os.path.exists(fpath):
                info = _probe_checkpoint(fpath)
                nc = info.get("num_classes")
                if nc is not None:
                    # Binary: 1 output neuron accepts exactly 2 labels
                    # Multi-class: N outputs accepts exactly N labels
                    expected = 2 if nc == 1 else nc
                    if len(class_names) != expected:
                        raise ValueError(
                            f"Model has {nc} output neuron(s) → expects "
                            f"{expected} class names, but you provided "
                            f"{len(class_names)}."
                        )
            entry["class_names"] = class_names
            save_registry(reg)
            return True
    return False


def get_model_entry(model_id):
    """Look up a single registry entry by id (user models only)."""
    for e in load_registry():
        if e["id"] == model_id:
            return e
    return None


# ---------------------------------------------------------------------------
# Built-in entries (always available, not in registry file)
# ---------------------------------------------------------------------------
def get_builtin_entries():
    """Return pseudo-entries for the two bundled models."""
    entries = []
    det_path = resource_path(BUILTIN_DETECTOR_PATH)
    if os.path.isfile(det_path):
        entries.append({
            "id": "__builtin_detector__",
            "name": "Built-in Animal Detector",
            "type": "detector",
            "filename": BUILTIN_DETECTOR_PATH,
            "class_names": None,
            "architecture": "yolov5",
            "builtin": True,
        })
    cls_path = resource_path(BUILTIN_CLASSIFIER_PATH)
    if os.path.isfile(cls_path):
        info = _probe_checkpoint(cls_path)
        entries.append({
            "id": "__builtin_classifier__",
            "name": "Built-in Classifier (ResNet50)",
            "type": "classifier",
            "filename": BUILTIN_CLASSIFIER_PATH,
            "class_names": info["class_names"],
            "architecture": "resnet50",
            "builtin": True,
        })
    return entries


def get_all_models():
    """Return builtin + user-registered models."""
    return get_builtin_entries() + load_registry()


def get_model_path(entry):
    """Resolve the full path for a registry entry."""
    if entry.get("builtin"):
        return resource_path(entry["filename"])
    return os.path.join(_ensure_models_dir(), entry["filename"])


# ---------------------------------------------------------------------------
# Multi-architecture classifier loader
# ---------------------------------------------------------------------------
_loaded_classifiers = {}


def _build_resnet(name, num_classes):
    builder = getattr(models, name)
    model = builder(weights=None)
    model.fc = nn.Linear(model.fc.in_features, num_classes)
    return model


def _build_efficientnet(name, num_classes, state_dict=None):
    """
    Build an EfficientNet model, reconstructing the classifier head
    from the state_dict if provided.  Fully dynamic: reads the actual
    layer structure (Linear, BatchNorm1d, Dropout, activations) from
    the classifier.* keys so ANY head architecture loads correctly.

    Handles:
      - Simple head: Dropout + Linear(in→nc)
      - Multi-layer heads of arbitrary depth (Linear, BatchNorm1d,
        Dropout, SiLU/ReLU — any combination and ordering)
      - Binary fc1/fc2 head: fc1(in→hidden) + ReLU + fc2(hidden→1)
        (keys remapped to classifier.* so standard forward() works)

    Returns: (model, modified_state_dict_or_None)
      modified_state_dict is only returned when fc1/fc2 keys were remapped.
    """
    builder = getattr(models, name, None)
    if builder is None:
        raise ValueError(f"Unknown architecture: {name}")
    model = builder(weights=None)

    if not (hasattr(model, "classifier") and isinstance(model.classifier, nn.Sequential)):
        raise ValueError(f"Cannot modify classifier head for {name}")

    in_features = model.classifier[1].in_features  # e.g. 1280
    remapped_sd = None

    if state_dict is not None:
        # Check for fc1/fc2 custom head (binary classifiers)
        has_fc1 = "fc1.weight" in state_dict
        has_fc2 = "fc2.weight" in state_dict

        if has_fc1 and has_fc2:
            # Binary classifier with custom fc1→fc2 head
            hidden_dim = state_dict["fc1.weight"].shape[0]
            output_dim = state_dict["fc2.weight"].shape[0]
            logging.info(
                f"EfficientNet binary fc head detected: "
                f"Linear({in_features}→{hidden_dim}) → ReLU → Linear({hidden_dim}→{output_dim})"
            )
            model.classifier = nn.Sequential(
                nn.Linear(in_features, hidden_dim),
                nn.ReLU(inplace=True),
                nn.Linear(hidden_dim, output_dim),
            )
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
            # --- Dynamic head reconstruction from classifier.* keys ---
            model.classifier = _rebuild_classifier_head(
                state_dict, in_features, num_classes,
            )
    else:
        model.classifier[1] = nn.Linear(in_features, num_classes)

    return model, remapped_sd


def _rebuild_classifier_head(state_dict, in_features, num_classes):
    """
    Dynamically reconstruct an nn.Sequential classifier head by
    inspecting classifier.* keys in the state_dict.

    Layer-type detection:
      - Has running_mean / running_var  →  BatchNorm1d
      - Has weight (2D) without running_mean  →  Linear
      - No parameters + follows a Linear  →  Activation
      - No parameters + otherwise  →  Dropout

    Activation heuristic:
      - SiLU  if any BatchNorm1d is present (modern head convention)
      - ReLU  otherwise (classic head convention)
    """
    # Collect all classifier.N.* keys and determine max index
    cls_keys = [k for k in state_dict if k.startswith("classifier.")]
    if not cls_keys:
        # No classifier keys at all — simple default head
        return nn.Sequential(
            nn.Dropout(p=0.2, inplace=True),
            nn.Linear(in_features, num_classes),
        )

    # Map each index to the set of sub-keys it has
    # e.g. {1: {"weight", "bias"}, 3: {"weight", "bias", "running_mean", ...}}
    idx_keys = {}
    max_idx = 0
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

    # Classify each index that HAS parameters
    IDX_LINEAR = "linear"
    IDX_BATCHNORM = "batchnorm"
    idx_type = {}
    has_batchnorm = False
    for idx, keys in idx_keys.items():
        if "running_mean" in keys or "running_var" in keys:
            idx_type[idx] = IDX_BATCHNORM
            has_batchnorm = True
        else:
            idx_type[idx] = IDX_LINEAR

    # Choose activation based on head complexity
    activation_cls = nn.SiLU if has_batchnorm else nn.ReLU

    # Build layers 0 .. max_idx
    layers = []
    for idx in range(max_idx + 1):
        if idx in idx_type:
            ltype = idx_type[idx]
            if ltype == IDX_LINEAR:
                w = state_dict[f"classifier.{idx}.weight"]
                layers.append(nn.Linear(w.shape[1], w.shape[0]))
            elif ltype == IDX_BATCHNORM:
                rm = state_dict[f"classifier.{idx}.running_mean"]
                layers.append(nn.BatchNorm1d(rm.shape[0]))
        else:
            # Non-parametric layer — infer type from context
            prev_type = idx_type.get(idx - 1)
            if prev_type == IDX_LINEAR:
                # Directly after a Linear → activation
                layers.append(activation_cls())
            else:
                # After BatchNorm / activation / start → Dropout
                layers.append(nn.Dropout())

    head_desc = " → ".join(type(l).__name__ for l in layers)
    logging.info(f"EfficientNet dynamic head reconstructed ({len(layers)} layers): {head_desc}")

    return nn.Sequential(*layers)


_ARCH_BUILDERS = {
    "resnet18":        "resnet",
    "resnet34":        "resnet",
    "resnet50":        "resnet",
    "resnet101":       "resnet",
    "efficientnet_b0": "efficientnet",
    "efficientnet_b1": "efficientnet",
    "efficientnet_b2": "efficientnet",
    "efficientnet_b3": "efficientnet",
    "efficientnet_b4": "efficientnet",
}


def load_classifier(entry):
    """
    Load a classifier model. Supports ResNet and EfficientNet families.
    Auto-detects multi-layer and binary fc1/fc2 heads from checkpoint state_dict.
    Cached after first load. Returns (model, class_names, device, transform, head_type).
    """
    mid = entry["id"]
    if mid in _loaded_classifiers:
        return _loaded_classifiers[mid]

    path = get_model_path(entry)
    device = get_best_device()
    ckpt = torch.load(path, map_location=device, weights_only=False)

    # Determine class names — prefer registry entry (what the UI shows)
    # over probed names (which may differ, e.g. "rest" vs user-set "not")
    info = _probe_checkpoint(path)
    class_names = entry.get("class_names") or info["class_names"]
    if not class_names:
        raise ValueError(f"Cannot determine class names for model '{entry['name']}'")
    num_classes = len(class_names)
    head_type = entry.get("head_type") or info.get("head_type", "standard")

    # Get state_dict
    sd = ckpt.get("model_state_dict") or ckpt.get("state_dict")
    if sd is None:
        raise ValueError(f"No 'model_state_dict' or 'state_dict' found in checkpoint")

    # Determine architecture
    arch = entry.get("architecture") or info["architecture"] or "resnet50"
    arch_lower = arch.lower().replace("-", "_")

    family = _ARCH_BUILDERS.get(arch_lower)
    if family is None:
        raise ValueError(
            f"Unsupported architecture '{arch}'. "
            f"Supported: {', '.join(sorted(_ARCH_BUILDERS.keys()))}"
        )

    # Build model with state_dict awareness for head reconstruction
    if family == "resnet":
        model = _build_resnet(arch_lower, num_classes)
        load_sd = sd
    elif family == "efficientnet":
        model, remapped_sd = _build_efficientnet(arch_lower, num_classes, state_dict=sd)
        load_sd = remapped_sd if remapped_sd is not None else sd
    else:
        raise ValueError(f"Unknown model family: {family}")

    # Auto-detect binary sigmoid head from actual output dimension
    # Check the last linear layer's output size
    actual_output_dim = None
    if family == "efficientnet" and hasattr(model, "classifier"):
        for layer in reversed(list(model.classifier.children())):
            if isinstance(layer, nn.Linear):
                actual_output_dim = layer.out_features
                break
    elif family == "resnet" and hasattr(model, "fc"):
        actual_output_dim = model.fc.out_features

    if actual_output_dim == 1:
        head_type = "binary_sigmoid"
        logging.info(f"Binary sigmoid model detected (1 output neuron, {len(class_names)} class labels)")

    # Load weights
    model.load_state_dict(load_sd)
    try:
        model.to(device)
        model.eval()
        # Force a kernel launch to verify GPU actually works
        if device.type != 'cpu':
            torch.zeros(1, device=device).sum()
    except RuntimeError as e:
        if device.type != 'cpu':
            logging.warning(f"GPU failed for classifier '{entry['name']}': {e}")
            logging.warning("Falling back to CPU — classification will be slower.")
            device = torch.device('cpu')
            model.to(device)
            model.eval()
        else:
            raise

    transform = transforms.Compose([
        transforms.Resize((CLASSIFICATION_IMG_SIZE, CLASSIFICATION_IMG_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])

    result = (model, class_names, device, transform, head_type)
    _loaded_classifiers[mid] = result
    logging.info(
        f"Loaded classifier '{entry['name']}' ({arch}, {num_classes} classes, "
        f"head={head_type}) on {device}"
    )
    return result


def classify_image(image_path, entry):
    """
    Classify a cropped image using the given classifier entry.
    Handles both multi-class softmax and binary sigmoid outputs.
    Returns (class_name, confidence) where confidence is the
    probability assigned to the predicted class (0.0–1.0).
    """
    model, class_names, device, transform, head_type = load_classifier(entry)
    img = PILImage.open(image_path).convert("RGB")
    tensor = transform(img).unsqueeze(0).to(device)
    with torch.no_grad():
        out = model(tensor)

        if head_type in ("binary_fc", "binary_sigmoid") or out.shape[1] == 1:
            # Binary classifier: single sigmoid output
            # class_names[0] = target class (e.g. "deer")
            # class_names[1] = "rest"
            prob = torch.sigmoid(out[0, 0]).item()
            if prob >= 0.5:
                idx, conf = 0, prob
            else:
                idx, conf = 1, 1.0 - prob
        else:
            # Multi-class: softmax
            probs = torch.softmax(out, dim=1)[0]
            idx = torch.argmax(probs).item()
            conf = probs[idx].item()

    return class_names[idx], conf


def get_all_class_names():
    """Get class names from the built-in classifier (for UI filters)."""
    for e in get_builtin_entries():
        if e["type"] == "classifier" and e.get("class_names"):
            return e["class_names"]
    for e in load_registry():
        if e["type"] == "classifier" and e.get("class_names"):
            return e["class_names"]
    return []


# ---------------------------------------------------------------------------
# Pipeline configuration
# ---------------------------------------------------------------------------
DEFAULT_PIPELINE = [
    {
        "model_id": "__builtin_detector__",
        "confidence": 0.4,
        "delete_original": False,
        "include_crop": True,
    },
]


def validate_pipeline(steps):
    """Check that all referenced models exist. Returns list of error strings."""
    all_ids = {e["id"] for e in get_all_models()}
    errors = []
    for i, step in enumerate(steps):
        if step["model_id"] not in all_ids:
            errors.append(f"Step {i+1}: model '{step['model_id']}' not found")
    return errors