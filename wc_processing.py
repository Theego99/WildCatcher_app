"""
WildCatcher processing engine.

Processing flow:
  1. Detector runs on every image/video → crops saved to detection_data/
  2. Classifier(s) run on each crop → classname_ prefix applied
  3. Per-class options (delete original, include crop) from classifier step config
  4. Detection category filters (include animal/human) from detector step config
  5. detection_data/ folder is always created
"""
import os
import csv
import json
import shutil
import subprocess
import tempfile

import cv2
from PyQt5.QtCore import QThread, pyqtSignal

from process_images import process_images
from load_detector import load_detector
from wc_onnx import get_onnx_diagnostics
from wc_sleep_guard import prevent_sleep, allow_sleep
import wc_models as models_mod
from PIL import Image

resource_path = models_mod.resource_path

# ---------------------------------------------------------------------------
# Supported file extensions  (Issue #2 fix — expanded)
# ---------------------------------------------------------------------------
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff",
    ".webp", ".heic", ".heif", ".gif",
}
VIDEO_EXTENSIONS = {
    ".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv",
    ".mpg", ".mpeg", ".mts", ".m4v", ".3gp", ".asf",
}


def crop_image(image, bbox):
    """Crop an image using a normalized [x, y, w, h] bounding box."""
    h, w = image.shape[:2]
    x_min, y_min, bw, bh = bbox
    x1 = max(0, int(x_min * w))
    y1 = max(0, int(y_min * h))
    x2 = min(w, int((x_min + bw) * w))
    y2 = min(h, int((y_min + bh) * h))
    if x2 <= x1 or y2 <= y1:
        return None  # Degenerate bounding box
    return image[y1:y2, x1:x2]


# ---------------------------------------------------------------------------
# Metadata extraction helpers
# ---------------------------------------------------------------------------
def _extract_image_time(filepath):
    """Extract capture time from image EXIF data."""
    try:
        with Image.open(filepath) as img:
            exif = img.getexif()
            if exif:
                # DateTimeOriginal > DateTimeDigitized > DateTime
                for tag in (36867, 36868, 306):
                    val = exif.get(tag)
                    if val:
                        return str(val)
                # Check EXIF sub-IFD
                ifd = exif.get_ifd(0x8769)
                for tag in (36867, 36868):
                    val = ifd.get(tag)
                    if val:
                        return str(val)
    except Exception:
        pass
    # Fallback: file modification time
    try:
        from datetime import datetime
        mtime = os.path.getmtime(filepath)
        return datetime.fromtimestamp(mtime).strftime("%Y:%m:%d %H:%M:%S")
    except Exception:
        return ""


def _extract_video_time(filepath):
    """Extract creation time from video metadata via ffprobe, fallback to mtime."""
    # Try ffprobe (bundled with many ffmpeg installs)
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", filepath],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            tags = json.loads(result.stdout).get("format", {}).get("tags", {})
            for key in ("creation_time", "Creation Time", "date"):
                val = tags.get(key)
                if val:
                    return str(val)
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    # Fallback: file modification time
    try:
        from datetime import datetime
        mtime = os.path.getmtime(filepath)
        return datetime.fromtimestamp(mtime).strftime("%Y:%m:%d %H:%M:%S")
    except Exception:
        return ""


def _write_excel_report(path, records, total_files, total_empty,
                        total_human, total_animal, species_counts):
    """Write detection report as .xlsx with two sheets."""
    from openpyxl import Workbook

    wb = Workbook()

    # Sheet 1 — per-file details
    ws = wb.active
    ws.title = "File Details"
    ws.append(["ID", "File Name", "Detection", "Species", "Time",
               "Video Length (s)", "Detection Accuracy", "Species Accuracy"])
    for r in records:
        ws.append([
            r["id"], r["file_name"], r["detection"], r["species"],
            r["time"], r["video_length"],
            r["detection_accuracy"], r["species_accuracy"],
        ])

    # Sheet 2 — summary (same data as the old CSV)
    ws2 = wb.create_sheet("Summary")
    ws2.append(["Category", "Count"])
    ws2.append(["Total files", total_files])
    ws2.append(["Empty", total_empty])
    ws2.append(["Human/Vehicle", total_human])
    ws2.append(["Animal", total_animal])
    if species_counts:
        ws2.append([])
        ws2.append(["Species", "Count"])
        for sp in sorted(species_counts):
            ws2.append([sp, species_counts[sp]])

    wb.save(path)


def _filter_detections(detections, confidence, det_per_class):
    """Return detections above threshold matching category filters from per_class."""
    include_animal = det_per_class.get("animal", {}).get("include", True)
    include_human = det_per_class.get("human", {}).get("include", True)
    return [
        d for d in detections
        if d["conf"] > confidence and (
            (d["category"] == "1" and include_animal) or
            (d["category"] != "1" and include_human)
        )
    ]


# Hardcoded prefixes (no user configuration)
PREFIX_ANIMAL = "animal_"
PREFIX_HUMAN = "human_"
PREFIX_EMPTY = "empty_"


# ---------------------------------------------------------------------------
# Classification pipeline runner
# ---------------------------------------------------------------------------
def _classify_and_sort_crop(
    crop_path, crop_name, output_dir, detection,
    classifier_steps, stats, log, original_path=None,
):
    """
    Run all classifier steps on a single crop.
    Returns: (species_name, species_confidence, was_kept)
    """
    if detection["category"] != "1":
        return None, None, True  # Non-animal crops kept as-is

    species = None
    species_conf = None
    final_kept = True

    for step in classifier_steps:
        entry = _resolve_entry(step["model_id"])
        if entry is None or entry["type"] != "classifier":
            continue
        try:
            species, conf = models_mod.classify_image(crop_path, entry)
            species_conf = conf
            stats["species"][species] = stats["species"].get(species, 0) + 1

            # Per-class options (unified: "include", "delete_original", "min_confidence")
            per_class = step.get("per_class", {})
            class_opts = per_class.get(species, {})

            # Check per-class min confidence threshold
            min_conf = class_opts.get("min_confidence", 0.0)
            if min_conf > 0.0 and conf < min_conf:
                log(f"  Low confidence {species}={conf:.2f} < {min_conf:.2f}, skipping classification")
                species = None
                species_conf = None
                continue

            log(f"  → {species} ({conf:.1%})")

            # Delete original source?
            if class_opts.get("delete_original", False):
                if original_path and os.path.exists(original_path):
                    try:
                        os.remove(original_path)
                        log(f"  Deleted original (class={species}): {os.path.basename(original_path)}")
                    except Exception as e:
                        log(f"  Failed to delete original: {e}")

            # Discard this crop?
            if not class_opts.get("include", True):
                if os.path.exists(crop_path):
                    os.remove(crop_path)
                log(f"  Discarded crop (class={species}, excluded by filter)")
                final_kept = False
                return species, species_conf, final_kept

        except Exception as e:
            log(f"  Classification error ({entry.get('name', '?')}): {e}")

    # Rename crop with species prefix
    if species and os.path.exists(crop_path):
        new_name = f"{species}_{crop_name}"
        new_path = os.path.join(output_dir, new_name)
        if os.path.exists(new_path):
            base, ext = os.path.splitext(new_name)
            counter = 1
            while os.path.exists(new_path):
                new_path = os.path.join(output_dir, f"{base}_{counter}{ext}")
                counter += 1
        try:
            os.rename(crop_path, new_path)
            log(f"  Classified: {crop_name} → {os.path.basename(new_path)}")
        except Exception as e:
            log(f"  Rename failed: {e}")

    return species, species_conf, final_kept


def _resolve_entry(model_id):
    """Find model entry by id across builtins and registry."""
    for e in models_mod.get_all_models():
        if e["id"] == model_id:
            return e
    return None


def _safe_write_crop(path, image, log):
    """Write a crop image with error handling. Returns True on success."""
    try:
        if image is None or image.size == 0:
            log(f"  Warning: empty crop, skipping {os.path.basename(path)}")
            return False
        ok = cv2.imwrite(path, image)
        if not ok:
            log(f"  Warning: cv2.imwrite failed for {os.path.basename(path)}")
            return False
        return True
    except Exception as e:
        log(f"  Error writing crop {os.path.basename(path)}: {e}")
        return False


# ---------------------------------------------------------------------------
# Single-file processors
# ---------------------------------------------------------------------------
def process_image_file(
    image_file, detector, det_confidence, det_per_class,
    output_dir, log,
    classifier_steps=None,
):
    """Process one image. Returns stats dict with per-file detail."""
    stats = {"empty": False, "human": 0, "animal": 0, "species": {}}
    fname = os.path.basename(image_file)
    image_time = _extract_image_time(image_file)
    _empty_detail = {"file_name": fname, "detection": "", "species": "",
                     "time": image_time, "video_length": "N/A",
                     "detection_accuracy": "", "species_accuracy": ""}

    image = cv2.imread(image_file)
    if image is None:
        log(f"Could not read: {fname}")
        stats["empty"] = True
        stats["detail"] = _empty_detail
        return stats

    results = process_images(
        im_files=[image_file], detector=detector,
        confidence_threshold=0.0, use_image_queue=False, quiet=True,
    )
    raw_dets = results[0].get("detections", [])
    detections = _filter_detections(raw_dets, det_confidence, det_per_class)

    if not detections:
        stats["empty"] = True
        # Handle "empty" per_class options
        empty_opts = det_per_class.get("empty", {})
        if empty_opts.get("delete_original", False):
            try:
                os.remove(image_file)
                log(f"Deleted (no detections): {fname}")
            except Exception as e:
                log(f"Delete failed: {e}")
        else:
            # Rename with empty_ prefix
            new_name = PREFIX_EMPTY + fname
            new_path = os.path.join(os.path.dirname(image_file), new_name)
            if not os.path.exists(new_path):
                try:
                    os.rename(image_file, new_path)
                except Exception:
                    pass
        stats["detail"] = _empty_detail
        return stats

    animal_confs, human_confs = [], []
    for d in detections:
        if d["category"] == "1":
            stats["animal"] += 1
            animal_confs.append(d["conf"])
        else:
            stats["human"] += 1
            human_confs.append(d["conf"])

    # Save crops + classify BEFORE renaming the original
    classified_species = []
    classified_confs = []  # (species, confidence) pairs for report
    current_file = image_file

    if output_dir is not None:
        base = os.path.splitext(fname)[0]
        crops_saved = 0
        for i, det in enumerate(detections):
            cropped = crop_image(image, det["bbox"])
            crop_name = f"{base}_crop_{i}.jpg"
            crop_path = os.path.join(output_dir, crop_name)

            if not _safe_write_crop(crop_path, cropped, log):
                continue
            crops_saved += 1

            if classifier_steps:
                sp, sp_conf, _ = _classify_and_sort_crop(
                    crop_path, crop_name, output_dir, det,
                    classifier_steps, stats, log,
                    original_path=current_file,
                )
                if sp:
                    classified_species.append(sp)
                    classified_confs.append((sp, sp_conf))

        if crops_saved == 0 and detections:
            log(f"  Warning: {fname} had {len(detections)} detections but 0 crops saved")

    # Compute per-file detail for Excel report
    from collections import Counter
    if len(animal_confs) >= len(human_confs) and animal_confs:
        det_label = "animal"
        best_det_conf = max(animal_confs)
    elif human_confs:
        det_label = "human"
        best_det_conf = max(human_confs)
    else:
        det_label = ""
        best_det_conf = None
    sp_label, sp_acc = "", None
    if classified_confs and det_label == "animal":
        dom = Counter(s for s, _ in classified_confs).most_common(1)[0][0]
        sp_label = dom
        sp_acc = max(c for s, c in classified_confs if s == dom)
    stats["detail"] = {
        "file_name": fname, "detection": det_label,
        "species": sp_label, "time": image_time, "video_length": "N/A",
        "detection_accuracy": round(best_det_conf, 4) if best_det_conf is not None else "",
        "species_accuracy": round(sp_acc, 4) if sp_acc is not None else "",
    }

    # Rename the original file with species or category prefix
    if classified_species:
        from collections import Counter
        dominant = Counter(classified_species).most_common(1)[0][0]
        prefix = f"{dominant}_"
    elif detections[-1]["category"] == "1":
        prefix = PREFIX_ANIMAL
    else:
        prefix = PREFIX_HUMAN

    new_name = prefix + fname
    new_path = os.path.join(os.path.dirname(current_file), new_name)
    if not os.path.exists(new_path):
        try:
            os.rename(current_file, new_path)
        except Exception as e:
            log(f"Rename failed for {fname}: {e}")

    # Handle per-class delete_original for detector categories
    det_category = "animal" if detections[-1]["category"] == "1" else "human"
    cat_opts = det_per_class.get(det_category, {})
    if cat_opts.get("delete_original", False):
        # Delete the renamed file (or original if rename failed)
        target = new_path if os.path.exists(new_path) else current_file
        if os.path.exists(target):
            try:
                os.remove(target)
                log(f"Deleted original ({det_category}): {os.path.basename(target)}")
            except Exception as e:
                log(f"Delete failed: {e}")

    return stats


def process_video_file(
    video_file, detector, det_confidence, det_per_class,
    output_dir, log,
    every_n_frames=16, max_duration=10, save_all=False,
    classifier_steps=None,
):
    """Process one video. Returns stats dict with per-file detail."""
    stats = {"empty": False, "human": 0, "animal": 0, "species": {}}
    fname = os.path.basename(video_file)
    video_time = _extract_video_time(video_file)
    _empty_detail = {"file_name": fname, "detection": "", "species": "",
                     "time": video_time, "video_length": "N/A",
                     "detection_accuracy": "", "species_accuracy": ""}

    cap = cv2.VideoCapture(video_file)
    if not cap.isOpened():
        log(f"Could not open video: {fname}")
        stats["empty"] = True
        stats["detail"] = _empty_detail
        return stats

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30
    total_frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    video_duration = round(total_frame_count / fps, 1) if total_frame_count > 0 else "N/A"
    _empty_detail["video_length"] = video_duration
    max_frames = int(max_duration * fps)
    temp_dir = tempfile.mkdtemp()
    frame_files = []

    try:
        count = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            count += 1
            if count > max_frames:
                break
            if count % every_n_frames == 0:
                fp = os.path.join(temp_dir, f"frame_{count}.jpg")
                cv2.imwrite(fp, frame)
                frame_files.append(fp)
        cap.release()

        if not frame_files:
            stats["empty"] = True
            stats["detail"] = _empty_detail
            return stats

        results = process_images(
            im_files=frame_files, detector=detector,
            confidence_threshold=0.0, use_image_queue=False, quiet=True,
        )

        best_det, best_frame, best_conf = None, None, -1
        frames_with_dets = []

        for i, res in enumerate(results):
            valid = _filter_detections(
                res.get("detections", []), det_confidence, det_per_class,
            )
            if valid:
                frame = cv2.imread(frame_files[i])
                if save_all and output_dir:
                    frames_with_dets.append((frame, valid))
                else:
                    for d in valid:
                        if d["conf"] > best_conf:
                            best_conf = d["conf"]
                            best_det = d
                            best_frame = frame.copy()

        has_dets = bool(frames_with_dets) or best_det is not None
        if not has_dets:
            stats["empty"] = True
            empty_opts = det_per_class.get("empty", {})
            if empty_opts.get("delete_original", False):
                try:
                    os.remove(video_file)
                    log(f"Deleted (no detections): {fname}")
                except Exception as e:
                    log(f"Delete failed: {e}")
            else:
                new_name = PREFIX_EMPTY + fname
                new_path = os.path.join(os.path.dirname(video_file), new_name)
                if not os.path.exists(new_path):
                    try:
                        os.rename(video_file, new_path)
                    except Exception:
                        pass
            stats["detail"] = _empty_detail
            return stats

        all_dets = []
        if save_all and frames_with_dets:
            for _, dets in frames_with_dets:
                all_dets.extend(dets)
        elif best_det:
            all_dets = [best_det]
        animal_confs, human_confs = [], []
        for d in all_dets:
            if d["category"] == "1":
                stats["animal"] += 1
                animal_confs.append(d["conf"])
            else:
                stats["human"] += 1
                human_confs.append(d["conf"])

        # Crops + classify BEFORE renaming original
        current_file = video_file
        classified_species = []
        classified_confs = []  # (species, confidence) pairs for report

        if output_dir is not None:
            base = os.path.splitext(fname)[0]
            crop_idx = 0

            if save_all and frames_with_dets:
                for frame, dets in frames_with_dets:
                    for det in dets:
                        cropped = crop_image(frame, det["bbox"])
                        cn = f"{base}_crop_{crop_idx}.jpg"
                        cp = os.path.join(output_dir, cn)
                        if _safe_write_crop(cp, cropped, log):
                            if classifier_steps:
                                sp, sp_conf, _ = _classify_and_sort_crop(
                                    cp, cn, output_dir, det,
                                    classifier_steps, stats, log,
                                    original_path=current_file,
                                )
                                if sp:
                                    classified_species.append(sp)
                                    classified_confs.append((sp, sp_conf))
                        crop_idx += 1
            elif best_det and best_frame is not None:
                cropped = crop_image(best_frame, best_det["bbox"])
                cn = f"{base}_crop_0.jpg"
                cp = os.path.join(output_dir, cn)
                if _safe_write_crop(cp, cropped, log):
                    if classifier_steps:
                        sp, sp_conf, _ = _classify_and_sort_crop(
                            cp, cn, output_dir, best_det,
                            classifier_steps, stats, log,
                            original_path=current_file,
                        )
                        if sp:
                            classified_species.append(sp)
                            classified_confs.append((sp, sp_conf))

        # Compute per-file detail for Excel report
        from collections import Counter
        if len(animal_confs) >= len(human_confs) and animal_confs:
            det_label = "animal"
            best_det_conf = max(animal_confs)
        elif human_confs:
            det_label = "human"
            best_det_conf = max(human_confs)
        else:
            det_label = ""
            best_det_conf = None
        sp_label, sp_acc = "", None
        if classified_confs and det_label == "animal":
            dom = Counter(s for s, _ in classified_confs).most_common(1)[0][0]
            sp_label = dom
            sp_acc = max(c for s, c in classified_confs if s == dom)
        stats["detail"] = {
            "file_name": fname, "detection": det_label,
            "species": sp_label, "time": video_time,
            "video_length": video_duration,
            "detection_accuracy": round(best_det_conf, 4) if best_det_conf is not None else "",
            "species_accuracy": round(sp_acc, 4) if sp_acc is not None else "",
        }

        # Rename original with species or category prefix
        if classified_species:
            from collections import Counter
            dominant = Counter(classified_species).most_common(1)[0][0]
            prefix = f"{dominant}_"
        elif all_dets[-1]["category"] == "1":
            prefix = PREFIX_ANIMAL
        else:
            prefix = PREFIX_HUMAN

        new_name = prefix + fname
        new_path = os.path.join(os.path.dirname(video_file), new_name)
        if not os.path.exists(new_path):
            try:
                os.rename(current_file, new_path)
                current_file = new_path
                fname = new_name
            except Exception as e:
                log(f"Rename failed for {fname}: {e}")

        # Handle per-class delete_original for detector categories
        det_category = "animal" if all_dets[-1]["category"] == "1" else "human"
        cat_opts = det_per_class.get(det_category, {})
        if cat_opts.get("delete_original", False):
            target = new_path if os.path.exists(new_path) else current_file
            if os.path.exists(target):
                try:
                    os.remove(target)
                    log(f"Deleted original ({det_category}): {os.path.basename(target)}")
                except Exception as e:
                    log(f"Delete failed: {e}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return stats


# ---------------------------------------------------------------------------
# Processing thread
# ---------------------------------------------------------------------------
class ProcessingThread(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished = pyqtSignal()

    def __init__(self, config):
        super().__init__()
        self.cfg = config
        self.total_files = 0
        self.processed_count = 0
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def log(self, msg):
        self.log_signal.emit(msg)

    def run(self):
        prevent_sleep()
        try:
            self._process()
        finally:
            allow_sleep()
            self.finished.emit()

    def _process(self):
        cfg = self.cfg
        try:
            for line in get_onnx_diagnostics():
                self.log(line)

            # Always create detection_data folder
            output_root = os.path.join(cfg["input_folder"], "detection_data")
            os.makedirs(output_root, exist_ok=True)
            self.log(f"Output → {output_root}")

            # Parse pipeline steps
            pipeline = cfg.get("pipeline_steps", [])
            detector_entry = None
            detector_step = None
            classifier_steps = []

            self.log(f"Pipeline: {len(pipeline)} step(s) configured")
            for step in pipeline:
                entry = _resolve_entry(step["model_id"])
                if entry is None:
                    self.log(f"  ⚠ Model '{step['model_id']}' not found, skipping")
                    continue
                self.log(f"  → {entry['name']} [{entry['type']}]")
                if entry["type"] == "detector" and detector_entry is None:
                    detector_entry = entry
                    detector_step = step
                elif entry["type"] == "classifier":
                    classifier_steps.append(step)

            # Extract detector per_class options (unified format)
            if detector_step:
                det_confidence = detector_step.get("confidence", 0.4)
                det_per_class = detector_step.get("per_class", {
                    "animal": {"include": True, "delete_original": False},
                    "human": {"include": True, "delete_original": False},
                    "empty": {"include": False, "delete_original": False},
                })
                # Backward compat: migrate old flags to per_class
                if not det_per_class and detector_step.get("include_animal") is not None:
                    det_per_class = {
                        "animal": {"include": detector_step.get("include_animal", True),
                                   "delete_original": False},
                        "human": {"include": detector_step.get("include_human", True),
                                  "delete_original": False},
                        "empty": {"include": False,
                                  "delete_original": detector_step.get("delete_no_detection", False)},
                    }
            else:
                det_confidence = 0.4
                det_per_class = {
                    "animal": {"include": True, "delete_original": False},
                    "human": {"include": True, "delete_original": False},
                    "empty": {"include": False, "delete_original": False},
                }

            # Warn if no classifier (Issue #4 fix)
            if not classifier_steps:
                self.log("⚠ No classifier in pipeline — detections will NOT be classified.")
                self.log("  Add a classifier step in Settings → Processing Pipeline to classify species.")
            else:
                self.log(f"Classification: {len(classifier_steps)} classifier(s) will run on each detection")

            # Load detector
            if detector_entry:
                det_path = models_mod.get_model_path(detector_entry)
                self.log(f"Loading detector: {detector_entry['name']}")
            else:
                det_path = resource_path(models_mod.BUILTIN_DETECTOR_PATH)
                self.log("Loading built-in animal detector...")

            try:
                detector = load_detector(det_path)
                self.log("Detector loaded successfully.")
            except Exception as e:
                self.log(f"Failed to load detector: {e}")
                return

            # Pre-load classifiers
            for step in classifier_steps:
                entry = _resolve_entry(step["model_id"])
                if entry:
                    self.log(f"Loading classifier: {entry['name']}")
                    try:
                        models_mod.load_classifier(entry)
                        cn = entry.get("class_names") or []
                        self.log(f"  Loaded '{entry['name']}' ({len(cn)} classes)")
                    except Exception as e:
                        self.log(f"  Failed to load classifier '{entry['name']}': {e}")

            # Gather ALL files  (Issue #2 fix — no prefix skipping)
            image_files, video_files = [], []
            skipped_exts = {}
            for root, dirs, files in os.walk(cfg["input_folder"]):
                if "detection_data" in dirs:
                    dirs.remove("detection_data")
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    path = os.path.join(root, f)
                    if ext in IMAGE_EXTENSIONS:
                        image_files.append(path)
                    elif ext in VIDEO_EXTENSIONS:
                        video_files.append(path)
                    elif ext:
                        skipped_exts[ext] = skipped_exts.get(ext, 0) + 1

            self.total_files = len(image_files) + len(video_files)
            self.log(f"Found {len(image_files)} images, {len(video_files)} videos ({self.total_files} total)")
            if skipped_exts:
                skip_summary = ", ".join(f"{ext}:{n}" for ext, n in sorted(skipped_exts.items()))
                self.log(f"  Skipped extensions: {skip_summary}")

            # Analytics
            total_empty, total_human, total_animal = 0, 0, 0
            total_crops_saved = 0
            species_counts = {}
            records = []
            record_id = 0

            def _output_dir(filepath):
                rel = os.path.relpath(os.path.dirname(filepath), cfg["input_folder"])
                d = os.path.join(output_root, rel)
                os.makedirs(d, exist_ok=True)
                return d

            def _accum(fstats):
                nonlocal total_empty, total_human, total_animal, record_id
                if fstats.get("empty"):
                    total_empty += 1
                total_human += fstats.get("human", 0)
                total_animal += fstats.get("animal", 0)
                for sp, cnt in fstats.get("species", {}).items():
                    species_counts[sp] = species_counts.get(sp, 0) + cnt
                detail = fstats.get("detail")
                if detail:
                    record_id += 1
                    detail["id"] = record_id
                    records.append(detail)

            # Process images
            for fpath in image_files:
                if self._stop_requested:
                    self.log("Stopped by user.")
                    break
                fs = process_image_file(
                    fpath, detector, det_confidence, det_per_class,
                    _output_dir(fpath), self.log,
                    classifier_steps=classifier_steps or None,
                )
                _accum(fs)
                self.processed_count += 1
                self.progress_signal.emit(self.processed_count, self.total_files)

            # Process videos
            for fpath in video_files:
                if self._stop_requested:
                    self.log("Stopped by user.")
                    break
                fs = process_video_file(
                    fpath, detector, det_confidence, det_per_class,
                    _output_dir(fpath), self.log,
                    every_n_frames=cfg.get("every_n_frames", 16),
                    max_duration=cfg.get("processing_duration_seconds", 10),
                    save_all=cfg.get("save_all", False),
                    classifier_steps=classifier_steps or None,
                )
                _accum(fs)
                self.processed_count += 1
                self.progress_signal.emit(self.processed_count, self.total_files)

            # Summary log
            self.log(f"--- Results: {total_animal} animals, {total_human} humans/vehicles, {total_empty} empty ---")
            if species_counts:
                self.log("Species counts: " + ", ".join(
                    f"{sp}={cnt}" for sp, cnt in sorted(species_counts.items())
                ))

            # Excel report (two sheets: per-file details + summary)
            if not self._stop_requested:
                xlsx_path = os.path.join(output_root, "detection_report.xlsx")
                try:
                    _write_excel_report(
                        xlsx_path, records, self.total_files,
                        total_empty, total_human, total_animal,
                        species_counts,
                    )
                    self.log(f"Report saved to {xlsx_path}")
                except ImportError:
                    self.log("openpyxl not installed — falling back to CSV report.")
                    csv_path = os.path.join(output_root, "detection_report.csv")
                    with open(csv_path, "w", newline="", encoding="utf-8") as f:
                        w = csv.writer(f)
                        w.writerow(["Category", "Count"])
                        w.writerow(["Total files", self.total_files])
                        w.writerow(["Empty", total_empty])
                        w.writerow(["Human/Vehicle", total_human])
                        w.writerow(["Animal", total_animal])
                        if species_counts:
                            w.writerow([])
                            w.writerow(["Species", "Count"])
                            for sp in sorted(species_counts):
                                w.writerow([sp, species_counts[sp]])
                    self.log(f"Report saved to {csv_path}")
                except Exception as e:
                    self.log(f"Report write failed: {e}")

            self.log("Stopped by user." if self._stop_requested else "Processing completed.")

        except Exception as e:
            import traceback
            self.log(f"Error: {e}")
            self.log(traceback.format_exc())
