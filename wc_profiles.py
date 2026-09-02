"""Named, savable settings profiles ("config templates") for WildCatcher.

Requested by a heavy-use client (Osaka Prefecture Environmental Research
Institute, 2026-08-26): the current "last-used settings restored on startup"
behavior makes it easy to mix up configurations across sites/projects. A
profile bundles the processing-relevant settings (pipeline/model steps,
output columns/formats, frame interval, resume/non-destructive flags) under
a name that can be saved, reloaded, and optionally marked as the default
loaded on startup. Used by both the GUI (Settings panel) and the CLI
(wc_cli.py --profile), per the client's explicit ask.

Profiles are stored as one JSON file per name next to the executable (same
pattern as wc_models._ensure_models_dir), so they survive updates and are
easy for a client to back up or hand-edit.
"""
import os
import sys
import json
import re

PROFILES_DIR = "profiles"
META_FILENAME = "_profiles_meta.json"

# Keys copied into/out of a profile. Deliberately excludes cosmetic,
# per-machine state (language, UI zoom, splitter sizes) -- a profile is
# about *what gets processed and how it's exported*, not window layout.
PROFILE_KEYS = (
    "pipeline_steps",
    "output_fields",
    "output_formats",
    "frame_interval",
    "processing_duration",
    "save_all_frames",
    "resume_processing",
    "non_destructive",
)


def _ensure_profiles_dir():
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.abspath(".")
    path = os.path.join(base, PROFILES_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _sanitize_name(name):
    name = (name or "").strip()
    if not name:
        raise ValueError("Profile name cannot be empty")
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def _profile_path(name):
    return os.path.join(_ensure_profiles_dir(), f"{_sanitize_name(name)}.json")


def _meta_path():
    return os.path.join(_ensure_profiles_dir(), META_FILENAME)


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def list_profiles():
    """Return saved profile names, sorted."""
    d = _ensure_profiles_dir()
    return sorted(
        fn[:-5] for fn in os.listdir(d)
        if fn.endswith(".json") and fn != META_FILENAME
    )


def save_profile(name, settings):
    """Persist the subset of `settings` covered by PROFILE_KEYS under `name`."""
    data = {k: settings[k] for k in PROFILE_KEYS if k in settings}
    _save_json(_profile_path(name), data)


def load_profile(name):
    """Return the saved settings dict for `name`, or None if missing/corrupt."""
    path = _profile_path(name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def delete_profile(name):
    path = _profile_path(name)
    if os.path.exists(path):
        os.remove(path)
    meta = _load_json(_meta_path(), {})
    if meta.get("default") == name:
        meta.pop("default", None)
        _save_json(_meta_path(), meta)


def get_default_profile_name():
    return _load_json(_meta_path(), {}).get("default")


def set_default_profile_name(name):
    """Mark `name` as the profile to auto-load on startup, or clear it (None)."""
    meta = _load_json(_meta_path(), {})
    if name:
        meta["default"] = name
    else:
        meta.pop("default", None)
    _save_json(_meta_path(), meta)
