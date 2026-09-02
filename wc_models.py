"""
WildCatcher model registry and classification pipeline (ONNX runtime).

User-added .pt/.pth classifiers are converted to ONNX at import time via the
lazily-imported `wc_convert` module (the only place torch is used). All inference
runs on ONNX Runtime (GPU via DirectML/CoreML/CUDA), so the shipped app does not
load torch at runtime. Classifier architectures (ResNet/EfficientNet, multi-layer
and binary fc1/fc2 heads) are auto-detected during conversion.
"""
import os
import sys
import json
import shutil
import logging

import numpy as np
from PIL import Image as PILImage

from wc_onnx import create_session

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------
MODELS_DIR = "models"
BUILTIN_DETECTOR_PATH = "detector_AI_model.onnx"
CLASSIFICATION_IMG_SIZE = 224
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


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


def _unique_path(dest_dir, filename):
    """Return a non-colliding path inside dest_dir for filename."""
    dest = os.path.join(dest_dir, filename)
    counter = 1
    while os.path.exists(dest):
        base, ext = os.path.splitext(filename)
        dest = os.path.join(dest_dir, f"{base}_{counter}{ext}")
        counter += 1
    return dest


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


def register_model(src_path, name, model_type, manual_class_names=None):
    """
    Add a model to the registry. Classifiers (.pt/.pth) are converted to ONNX
    via wc_convert (lazy torch import). Detectors must be provided as .onnx
    (YOLOv5 .pt conversion is a build-time step — see tools/convert_to_onnx.py).
    Returns the new registry entry or raises on failure.
    """
    if not os.path.isfile(src_path):
        raise FileNotFoundError(f"Model file not found: {src_path}")

    dest_dir = _ensure_models_dir()

    # --- Detector: accept ONNX directly ---
    if model_type == "detector":
        if src_path.lower().endswith((".pt", ".pth")):
            raise ValueError(
                "Detector models must be provided as .onnx. Convert a YOLOv5 .pt "
                "once with tools/convert_to_onnx.py, then add the .onnx file."
            )
        dest = _unique_path(dest_dir, os.path.basename(src_path))
        shutil.copy2(src_path, dest)
        entry = {
            "id": os.path.splitext(os.path.basename(dest))[0],
            "name": name, "type": "detector",
            "filename": os.path.basename(dest),
            "class_names": None, "architecture": "yolov5",
        }
        reg = load_registry()
        reg.append(entry)
        save_registry(reg)
        return entry

    # --- Classifier: probe then convert to ONNX ---
    import wc_convert  # lazy: only loads torch when a model is being added

    if src_path.lower().endswith(".onnx"):
        # Already ONNX: requires class names (no checkpoint to probe).
        class_names = manual_class_names
        if not class_names:
            raise ValueError("Please provide class names for an ONNX classifier.")
        dest = _unique_path(dest_dir, os.path.basename(src_path))
        shutil.copy2(src_path, dest)
        entry = {
            "id": os.path.splitext(os.path.basename(dest))[0],
            "name": name, "type": "classifier",
            "filename": os.path.basename(dest),
            "class_names": class_names, "architecture": None,
            "head_type": "standard", "output_dim": None,
            "num_classes": len(class_names),
        }
        reg = load_registry()
        reg.append(entry)
        save_registry(reg)
        return entry

    info = wc_convert.probe_checkpoint(src_path)
    class_names = info["class_names"]
    num_classes_inferred = info.get("num_classes")

    if not class_names and manual_class_names:
        class_names = manual_class_names
        if num_classes_inferred is not None:
            expected = 2 if num_classes_inferred == 1 else num_classes_inferred
            if len(class_names) != expected:
                raise ValueError(
                    f"Model has {num_classes_inferred} output neuron(s) → expects "
                    f"{expected} class names, but you provided {len(class_names)}."
                )
    if not class_names:
        hint = ""
        if num_classes_inferred is not None:
            expected = 2 if num_classes_inferred == 1 else num_classes_inferred
            hint = f"\nThe model has {num_classes_inferred} output neuron(s) → provide {expected} class names."
        raise ValueError(
            f"Could not detect class names from the checkpoint.{hint}\n"
            f"Please provide class names when adding this model."
        )

    base = os.path.splitext(os.path.basename(src_path))[0]
    onnx_dest = _unique_path(dest_dir, base + ".onnx")
    try:
        meta = wc_convert.convert_classifier_to_onnx(
            src_path, onnx_dest,
            entry={"class_names": class_names, "architecture": info["architecture"],
                   "head_type": info["head_type"]},
        )
    except Exception:
        if os.path.exists(onnx_dest):
            os.remove(onnx_dest)
        raise

    entry = {
        "id": os.path.splitext(os.path.basename(onnx_dest))[0],
        "name": name, "type": "classifier",
        "filename": os.path.basename(onnx_dest),
        "class_names": meta["class_names"],
        "architecture": meta["architecture"],
        "head_type": meta["head_type"],
        "output_dim": meta["output_dim"],
        "num_classes": meta["num_classes"],
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
    _loaded_classifiers.pop(model_id, None)


def update_model_class_names(model_id, class_names):
    """Update class_names for an existing registry entry. Returns True on success."""
    reg = load_registry()
    for entry in reg:
        if entry["id"] == model_id:
            nc = entry.get("output_dim") or entry.get("num_classes")
            if nc is not None:
                expected = 2 if nc == 1 else nc
                if len(class_names) != expected:
                    raise ValueError(
                        f"Model has {nc} output neuron(s) → expects {expected} "
                        f"class names, but you provided {len(class_names)}."
                    )
            entry["class_names"] = class_names
            save_registry(reg)
            _loaded_classifiers.pop(model_id, None)
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
    """Return pseudo-entries for the bundled model(s)."""
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
# Classifier loading + inference (ONNX Runtime)
# ---------------------------------------------------------------------------
_loaded_classifiers = {}  # id -> (session, class_names, head_type, input_name, output_dim)


def _ensure_onnx_classifier(entry):
    """Return the .onnx path for a classifier entry, converting a legacy .pth on
    demand (and updating the registry) if needed."""
    dest_dir = _ensure_models_dir()
    fn = entry["filename"]

    if fn.lower().endswith(".onnx"):
        path = get_model_path(entry)
        if os.path.exists(path):
            return path
        # ONNX referenced but missing — try to find a sibling .pth to rebuild from
        base = os.path.splitext(fn)[0]
        legacy = None
        for ext in (".pth", ".pt"):
            cand = os.path.join(dest_dir, base + ext)
            if os.path.exists(cand):
                legacy = cand
                break
        if legacy is None:
            raise FileNotFoundError(f"Classifier file not found: {path}")
        src, onnx_path = legacy, path
    else:
        # Legacy .pth/.pt entry: convert next to it
        src = os.path.join(dest_dir, fn)
        if not os.path.exists(src):
            raise FileNotFoundError(f"Classifier file not found: {src}")
        onnx_path = os.path.join(dest_dir, os.path.splitext(fn)[0] + ".onnx")

    if not os.path.exists(onnx_path):
        import wc_convert  # lazy
        meta = wc_convert.convert_classifier_to_onnx(src, onnx_path, entry=entry)
        _apply_conversion_to_registry(entry, os.path.basename(onnx_path), meta)
    return onnx_path


def _apply_conversion_to_registry(entry, onnx_filename, meta):
    """Persist post-conversion metadata back to the registry and the live entry."""
    entry["filename"] = onnx_filename
    entry["head_type"] = meta["head_type"]
    entry["output_dim"] = meta["output_dim"]
    entry.setdefault("architecture", meta["architecture"])
    if not entry.get("class_names"):
        entry["class_names"] = meta["class_names"]

    reg = load_registry()
    changed = False
    for e in reg:
        if e["id"] == entry["id"]:
            e.update({
                "filename": onnx_filename,
                "head_type": meta["head_type"],
                "output_dim": meta["output_dim"],
                "architecture": e.get("architecture") or meta["architecture"],
                "class_names": e.get("class_names") or meta["class_names"],
            })
            changed = True
    if changed:
        save_registry(reg)


def unload_classifiers():
    """Drop all cached classifier sessions, freeing their memory.

    Classifiers stay cached in `_loaded_classifiers` for the life of the
    process (normally desirable -- one load per GUI session). A long CLI run
    that walks many folders back-to-back keeps accumulating/holding ONNX
    Runtime sessions in that same cache, which is the "model refresh between
    folders" a heavy-use client asked for to avoid memory growth on
    multi-hour unattended batches (see wc_cli.py). The next process_*_file
    call after this simply reloads on demand via load_classifier()."""
    _loaded_classifiers.clear()


def load_classifier(entry):
    """Load (and cache) an ONNX classifier session.
    Returns (session, class_names, head_type, input_name, output_dim)."""
    mid = entry["id"]
    if mid in _loaded_classifiers:
        return _loaded_classifiers[mid]

    onnx_path = _ensure_onnx_classifier(entry)
    session, provider = create_session(onnx_path, prefer_gpu=True)

    class_names = entry.get("class_names")
    if not class_names:
        raise ValueError(f"Cannot determine class names for model '{entry['name']}'")

    output_dim = entry.get("output_dim")
    if output_dim is None:
        try:
            output_dim = int(session.get_outputs()[0].shape[-1])
        except (TypeError, ValueError):
            output_dim = len(class_names)
    head_type = entry.get("head_type") or "standard"
    input_name = session.get_inputs()[0].name

    result = (session, class_names, head_type, input_name, output_dim)
    _loaded_classifiers[mid] = result
    logging.info(f"Loaded classifier '{entry['name']}' on {provider} "
                 f"(out={output_dim}, head={head_type})")
    return result


def _softmax(x):
    e = np.exp(x - np.max(x))
    return e / e.sum()


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def classify_image(image_path, entry):
    """
    Classify a cropped image using the given classifier entry.
    Handles both multi-class softmax and binary sigmoid outputs.
    Returns (class_name, confidence) in 0.0–1.0.
    """
    session, class_names, head_type, input_name, output_dim = load_classifier(entry)

    with PILImage.open(image_path) as src:
        img = src.convert("RGB").resize(
            (CLASSIFICATION_IMG_SIZE, CLASSIFICATION_IMG_SIZE), PILImage.BILINEAR)
    arr = np.asarray(img, dtype=np.float32) / 255.0
    arr = (arr - IMAGENET_MEAN) / IMAGENET_STD
    arr = np.ascontiguousarray(arr.transpose(2, 0, 1)[None])  # NCHW

    out = session.run(None, {input_name: arr})[0]  # (1, ndim)

    if head_type in ("binary_fc", "binary_sigmoid") or out.shape[1] == 1:
        prob = float(_sigmoid(out[0, 0]))
        if prob >= 0.5:
            idx, conf = 0, prob
        else:
            idx, conf = 1, 1.0 - prob
    else:
        probs = _softmax(out[0])
        idx = int(np.argmax(probs))
        conf = float(probs[idx])

    return class_names[idx], conf


def get_all_class_names():
    """Get class names from the first available classifier (for UI filters)."""
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
