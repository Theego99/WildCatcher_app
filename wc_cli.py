"""WildCatcher heavy-use CLI: batch runner for multiple folders.

Requested by a client (Osaka Prefecture Environmental Research Institute,
thread 2026-08-26) who runs WildCatcher on many camera-station folders
("調査地域名 / 調査地点名 / 回収年月日") and wants to queue several of them for
unattended sequential processing instead of picking one folder at a time in
the GUI. Three asks, all covered here:

  1. Named config profiles (see wc_profiles.py) -- `--profile NAME` loads a
     profile saved from the GUI or via this CLI's sibling save tooling, so a
     run always uses a known, named configuration instead of "whatever was
     last left in the GUI."
  2. Multiple folders queued for sequential processing, with an optional
     scheduled start time -- `wildcatcher-cli.py folderA folderB --schedule
     "2026-09-01 22:00"`.
  3. The classifier model is reloaded fresh between folders by default
     (`wc_models.unload_classifiers()`) so a long unattended run doesn't
     accumulate cached ONNX sessions in memory across dozens of folders --
     the crash risk the client specifically flagged. Pass
     --no-model-refresh to keep the old behavior (reuse across folders).

Reuses the exact same ProcessingThread the GUI drives (wc_processing.py) so
CLI and GUI runs produce identical output -- this is not a second processing
engine, just a headless driver for the existing one.
"""
import os
import sys
import time
import argparse
from datetime import datetime

# The processing engine logs arrows/checkmarks (e.g. "Output -> ..."); a
# plain Windows console defaults to a legacy codepage that mangles them.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

import wc_models as models_mod
import wc_output
import wc_license
import wc_entitlements
import wc_profiles


def _build_default_settings():
    """Same "first available detector + first available classifier" default
    the GUI falls back to (wc_widgets.ModelPipelineWidget.ensure_default_pipeline)."""
    all_models = models_mod.get_all_models()
    steps = []
    for m in all_models:
        if m["type"] == "detector":
            steps.append({
                "model_id": m["id"],
                "confidence": 0.4,
                "per_class": {
                    "animal": {"include": True, "delete_original": False},
                    "human": {"include": True, "delete_original": False},
                    "empty": {"include": False, "delete_original": False},
                },
            })
            break
    for m in all_models:
        if m["type"] == "classifier":
            steps.append({"model_id": m["id"], "confidence": 0.5})
            break
    return {
        "pipeline_steps": steps,
        "output_fields": list(wc_output.DEFAULT_FIELDS),
        "output_formats": list(wc_output.DEFAULT_FORMATS),
        "frame_interval": 16,
        "processing_duration": 5,
        "save_all_frames": False,
        "resume_processing": True,
        "non_destructive": False,
    }


def _resolve_settings(profile_name):
    settings = _build_default_settings()
    name = profile_name or wc_profiles.get_default_profile_name()
    if name:
        saved = wc_profiles.load_profile(name)
        if saved is None:
            print(f"Profile '{name}' not found. Use --list-profiles to see "
                  "available profiles.", file=sys.stderr)
            sys.exit(1)
        settings.update(saved)
        print(f"Using profile '{name}'.")
    else:
        print("No profile given and no default profile set -- using built-in defaults.")
    return settings


def _resolve_entitlements():
    ok, info = wc_license.verify_license_file()
    if not ok:
        print(f"No valid license found ({info}). Processing cannot start.",
              file=sys.stderr)
        sys.exit(1)
    return wc_entitlements.from_license_info(info)


def _build_config(folder, settings, entitlements, resume_override, non_destructive_override):
    return {
        "input_folder": folder,
        "every_n_frames": settings.get("frame_interval", 16),
        "processing_duration_seconds": settings.get("processing_duration", 5),
        "save_all": settings.get("save_all_frames", False),
        "pipeline_steps": settings.get("pipeline_steps", []),
        "output_fields": settings.get("output_fields"),
        "output_formats": settings.get("output_formats"),
        "entitlements": entitlements.as_config(),
        "resume": settings.get("resume_processing", True) if resume_override is None else resume_override,
        "non_destructive": (settings.get("non_destructive", False)
                             if non_destructive_override is None else non_destructive_override),
    }


def _wait_until(target_dt):
    while True:
        remaining = (target_dt - datetime.now()).total_seconds()
        if remaining <= 0:
            return
        print(f"\rScheduled start at {target_dt:%Y-%m-%d %H:%M} -- "
              f"waiting {int(remaining)}s...", end="", flush=True)
        time.sleep(min(30, remaining))


def _run_folder(folder, config):
    # Imported lazily so --list-profiles / argparse errors don't pay the
    # cost of importing the full PyQt5/ONNX/cv2 processing stack.
    from wc_processing import ProcessingThread

    thread = ProcessingThread(config)
    thread.log_signal.connect(print)
    thread.message_signal.connect(lambda level, text: print(f"[{level.upper()}] {text}"))

    def _on_progress(processed, total):
        pct = int(processed * 100 / total) if total else 0
        print(f"\r  {processed}/{total} ({pct}%)", end="", flush=True)

    thread.progress_signal.connect(_on_progress)
    thread.run()
    print()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="wildcatcher-cli",
        description="Queue one or more folders for unattended, sequential "
                     "WildCatcher processing using a saved settings profile.",
    )
    parser.add_argument("folders", nargs="*",
                         help="Folders to process, in order.")
    parser.add_argument("--queue-file", metavar="PATH",
                         help="Text file with one folder path per line, "
                              "appended after FOLDERS.")
    parser.add_argument("--profile", metavar="NAME",
                         help="Named settings profile to use. Defaults to "
                              "the profile marked as default, if any.")
    parser.add_argument("--list-profiles", action="store_true",
                         help="List saved profiles and exit.")
    parser.add_argument("--schedule", metavar="YYYY-MM-DD HH:MM",
                         help="Wait until this local date/time before starting.")
    parser.add_argument("--no-resume", action="store_true",
                         help="Reprocess files even if a prior run already "
                              "finished them.")
    parser.add_argument("--non-destructive", action="store_true",
                         help="Never rename or delete original files.")
    parser.add_argument("--no-model-refresh", action="store_true",
                         help="Keep classifier models cached in memory "
                              "across folders instead of reloading them "
                              "fresh before each one.")
    args = parser.parse_args(argv)

    if args.list_profiles:
        names = wc_profiles.list_profiles()
        default = wc_profiles.get_default_profile_name()
        if not names:
            print("No saved profiles.")
        for n in names:
            print(f"{n}{'  (default)' if n == default else ''}")
        return 0

    folders = list(args.folders)
    if args.queue_file:
        with open(args.queue_file, "r", encoding="utf-8") as f:
            folders.extend(line.strip() for line in f if line.strip())
    if not folders:
        parser.error("No folders given. Pass one or more folders, or --queue-file.")

    missing = [f for f in folders if not os.path.isdir(f)]
    if missing:
        parser.error("Folder(s) not found: " + ", ".join(missing))

    if args.schedule:
        try:
            target = datetime.strptime(args.schedule, "%Y-%m-%d %H:%M")
        except ValueError:
            parser.error("--schedule must look like 'YYYY-MM-DD HH:MM'")
        _wait_until(target)
        print()

    from PyQt5.QtCore import QCoreApplication
    if QCoreApplication.instance() is None:
        QCoreApplication(sys.argv[:1])

    settings = _resolve_settings(args.profile)
    entitlements = _resolve_entitlements()

    print(f"Queued {len(folders)} folder(s):")
    for f in folders:
        print(f"  - {f}")

    failures = []
    for i, folder in enumerate(folders, 1):
        print(f"\n=== [{i}/{len(folders)}] {folder} ===")
        config = _build_config(
            folder, settings, entitlements,
            resume_override=(False if args.no_resume else None),
            non_destructive_override=(True if args.non_destructive else None),
        )
        try:
            _run_folder(folder, config)
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)
            failures.append(folder)
        if not args.no_model_refresh:
            models_mod.unload_classifiers()

    print(f"\nDone. {len(folders) - len(failures)}/{len(folders)} folder(s) completed.")
    if failures:
        print("Failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
