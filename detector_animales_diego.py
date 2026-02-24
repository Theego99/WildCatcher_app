import sys
import os
if sys.platform == 'win32':
    vlc_path = os.path.join(os.path.dirname(__file__), "vlc")
    if os.path.isdir(vlc_path):
        os.add_dll_directory(vlc_path)
import cv2
import csv
import shutil
import tempfile
import ctypes
import logging
import json
import base64
import hashlib
import uuid
import platform
from datetime import datetime

from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import QSettings, QThread, pyqtSignal, Qt, QSize
from PyQt5.QtGui import QIcon, QFont, QPalette, QColor, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QFileDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QProgressBar,
    QWidget,
    QTextEdit,
    QCheckBox,
    QSpinBox,
    QDoubleSpinBox,
    QMessageBox,
    QSizePolicy,
    QDesktopWidget,
    QScrollArea,
    QFrame,
    QComboBox,
    QGraphicsOpacityEffect,
)

from process_images import process_images
from load_detector import load_detector


from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Hash import SHA256

PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA9+GyNMZBmhxZEvP9BZ69
IKRH08yqlJJmvun/4rj1n/VnAf7fiTPvheWAa6jKF2np40N/vupTTeHNLFoVjnAH
V+sWfwfBxNSnrdmQPW6TSaj8Va+HfwyTkaG+FqMEl8I1ZTeR3o3N1Bmtcbbx7kMZ
qkSfLYe4ymUWy1meUrdpVZrEK5EpX/+ZQSYUnARBsVnlmdKwS4uIsg1BUefMaZib
d4Ez7/7yWkLxdzl8fW9+3pnewk9dtYKos5wYLIYfO2PmzKV/GvOTSYOmit2PuekF
4Ey2uF1UPF0Nr9EywEuPu8jySJozIR0sIxoCq/qEjv1GWXzTGflvdvVyuDpHYlqC
+QIDAQAB
-----END PUBLIC KEY-----"""

import torch
import torch.nn as nn
from torchvision import models, transforms

from video_player import VideoPlayer

# ======================
# ANIMAL CLASSIFICATION MODEL
# ======================
CLASSIFICATION_MODEL_PATH = "prec90rec93f191.pt"
CLASSIFICATION_IMG_SIZE = 224

_classification_model = None
_classification_class_names = None
_classification_device = None
_classification_transform = None


def get_classification_class_names(model_path=None):
    """Read class names from model checkpoint without loading the full model."""
    if model_path is None:
        model_path = resource_path(CLASSIFICATION_MODEL_PATH)
    try:
        checkpoint = torch.load(model_path, map_location='cpu', weights_only=False)
        return checkpoint.get('class_names', [])
    except Exception:
        return []


def get_best_device():
    """Select the best available compute device: CUDA > MPS > CPU."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def load_classification_model(model_path=None):
    """Load the animal classification ResNet50 model (singleton)."""
    global _classification_model, _classification_class_names, _classification_device, _classification_transform
    if _classification_model is not None:
        return _classification_model, _classification_class_names
    if model_path is None:
        model_path = resource_path(CLASSIFICATION_MODEL_PATH)
    _classification_device = get_best_device()
    checkpoint = torch.load(model_path, map_location=_classification_device, weights_only=False)
    _classification_class_names = checkpoint['class_names']
    num_classes = len(_classification_class_names)
    model = models.resnet50(weights=None)
    model.fc = nn.Linear(model.fc.in_features, num_classes)
    model.load_state_dict(checkpoint['model_state_dict'])
    model.to(_classification_device)
    model.eval()
    _classification_transform = transforms.Compose([
        transforms.Resize((CLASSIFICATION_IMG_SIZE, CLASSIFICATION_IMG_SIZE)),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    _classification_model = model
    print(f"Classification model loaded on {_classification_device}. Classes: {_classification_class_names}")
    return _classification_model, _classification_class_names


def classify_cropped_image(image_path):
    """Classify a cropped animal image and return the predicted class name."""
    global _classification_model, _classification_class_names, _classification_device, _classification_transform
    if _classification_model is None:
        load_classification_model()
    from PIL import Image as PILImage
    img = PILImage.open(image_path).convert('RGB')
    img_tensor = _classification_transform(img).unsqueeze(0).to(_classification_device)
    with torch.no_grad():
        outputs = _classification_model(img_tensor)
        probabilities = torch.softmax(outputs, dim=1)[0]
        pred_idx = torch.argmax(probabilities).item()
    return _classification_class_names[pred_idx]


# ======================
# GPU / CUDA / MPS DIAGNOSTICS
# ======================
def get_gpu_diagnostics():
    lines = []
    lines.append("=" * 50)
    lines.append("COMPUTE DEVICE DIAGNOSTICS")
    lines.append("=" * 50)
    torch_ver = torch.__version__
    lines.append(f"PyTorch version: {torch_ver}")
    lines.append(f"Platform: {platform.system()} {platform.machine()}")
    is_cpu_build = "+cpu" in torch_ver

    # CUDA check
    lines.append(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        lines.append(f"CUDA version: {torch.version.cuda}")
        gpu_count = torch.cuda.device_count()
        lines.append(f"GPU count: {gpu_count}")
        for i in range(gpu_count):
            name = torch.cuda.get_device_name(i)
            mem = torch.cuda.get_device_properties(i).total_memory / (1024 ** 3)
            lines.append(f"  GPU {i}: {name} ({mem:.1f} GB)")
        lines.append("STATUS: Using NVIDIA GPU (CUDA)")

    # MPS check (Apple Silicon)
    mps_available = False
    try:
        if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            mps_available = True
    except Exception:
        pass
    lines.append(f"MPS (Apple Silicon) available: {mps_available}")
    if mps_available and not torch.cuda.is_available():
        lines.append("STATUS: Using Apple GPU (MPS)")

    # CPU fallback
    if not torch.cuda.is_available() and not mps_available:
        lines.append("WARNING: No GPU acceleration available - running on CPU only.")
        if is_cpu_build:
            lines.append("REASON: PyTorch installed as CPU-ONLY build (version contains '+cpu').")
            lines.append("FIX: Reinstall PyTorch with CUDA support:")
            lines.append("  pip uninstall torch torchvision")
            lines.append("  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121")
        elif platform.system() == "Darwin":
            lines.append("NOTE: On macOS, MPS should be available on Apple Silicon (M1+).")
            lines.append("  If on Intel Mac, CPU-only is expected.")
        else:
            lines.append("Possible causes:")
            lines.append("  1. No NVIDIA GPU in this machine")
            lines.append("  2. NVIDIA drivers not installed (run 'nvidia-smi' to check)")
            lines.append("  3. CUDA toolkit version mismatch with PyTorch")
        lines.append("Processing will work but will be SLOWER without GPU.")

    device = get_best_device()
    lines.append(f"Selected device: {device}")
    lines.append("=" * 50)
    return lines


# Button style constants (Feature 4)
START_BUTTON_STYLE = """
    QPushButton { font-size: 18px; padding: 10px 20px; color: #FFFFFF; background-color: rgba(67, 120, 32, 0.4); border: 2px solid #437820; border-radius: 10px; }
    QPushButton:hover { background-color: rgba(67, 120, 32, 1); }
"""
STOP_BUTTON_STYLE = """
    QPushButton { font-size: 18px; padding: 10px 20px; color: #FFFFFF; background-color: rgba(180, 30, 30, 0.4); border: 2px solid #B41E1E; border-radius: 10px; }
    QPushButton:hover { background-color: rgba(180, 30, 30, 1); }
"""

DARK_MSGBOX_STYLE = """
    QMessageBox { background-color: #1E1E1E; color: #FFFFFF; }
    QLabel { color: #FFFFFF; }
    QPushButton { font-size: 16px; padding: 5px; border-radius: 5px; background-color: #3C3C3C; color: #FFFFFF; }
    QPushButton:hover { background-color: #2E2E2E; }
"""

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


yolov5_path = os.path.join(os.path.dirname(__file__), "yolov5")
sys.path.insert(0, yolov5_path)


processed_videos = 0


# Function to draw detections on an image
def draw_detections_on_image(image, detections, confidence_threshold, output_path):
    """
    Draws detections on the image and saves it to output_path.
    """
    height, width, _ = image.shape

    for detection in detections:
        bbox = detection["bbox"]
        confidence = detection["conf"]
        if confidence > confidence_threshold:
            x_min, y_min, bbox_width, bbox_height = bbox
            x_min_pixel = int(x_min * width)
            y_min_pixel = int(y_min * height)
            x_max_pixel = int((x_min + bbox_width) * width)
            y_max_pixel = int((y_min + bbox_height) * height)

            cv2.rectangle(
                image,
                (x_min_pixel, y_min_pixel),
                (x_max_pixel, y_max_pixel),
                (20, 0, 255),
                2,
            )
            label = f"{confidence:.2f}"
            cv2.putText(
                image,
                label,
                (x_min_pixel, y_min_pixel - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.9,
                (0, 0, 255),
                2,
            )

    cv2.imwrite(output_path, image)
    print(f"Saved detection boxes to {output_path}")

# Function to crop images
def crop_image_with_bbox_image(image, bbox):
    """
    Crops the image based on the bounding box and returns the cropped image.
    """
    height, width, _ = image.shape
    x_min, y_min, bbox_width, bbox_height = bbox

    x_min_pixel = int(x_min * width)
    y_min_pixel = int(y_min * height)
    x_max_pixel = int((x_min + bbox_width) * width)
    y_max_pixel = int((y_min + bbox_height) * height)

    x_min_pixel = max(0, x_min_pixel)
    y_min_pixel = max(0, y_min_pixel)
    x_max_pixel = min(width, x_max_pixel)
    y_max_pixel = min(height, y_max_pixel)

    cropped_image = image[y_min_pixel:y_max_pixel, x_min_pixel:x_max_pixel]
    return cropped_image

def _classify_and_rename_crop(
    cropped_image_path, cropped_image_name, output_base,
    detection, use_animal_classification, animal_filter_config,
    stats, log, original_path=None,
):
    """
    Shared helper: classify an animal crop, apply per-animal filters,
    and rename with species prefix. Returns species name or None.
    """
    if not (use_animal_classification and detection["category"] == "1"):
        return None
    try:
        species = classify_cropped_image(cropped_image_path)
        stats['species'][species] = stats['species'].get(species, 0) + 1
        # Apply per-animal filter config
        if animal_filter_config and species in animal_filter_config:
            cfg = animal_filter_config[species]
            if cfg.get('delete_original', False) and original_path and os.path.exists(original_path):
                try:
                    os.remove(original_path)
                    log(f"Deleted original (species={species}): {original_path}")
                except Exception as e:
                    log(f"Failed to delete original: {str(e)}")
            if not cfg.get('include_crop', True):
                if os.path.exists(cropped_image_path):
                    os.remove(cropped_image_path)
                log(f"Skipped crop for '{species}' (filtered out)")
                return species
        # Rename with species prefix
        new_name = f"{species}_{cropped_image_name}"
        new_path = os.path.join(output_base, new_name)
        if not os.path.exists(new_path):
            os.rename(cropped_image_path, new_path)
            log(f"Classified as '{species}': {cropped_image_name} -> {new_name}")
        else:
            log(f"Classified as '{species}' but {new_name} already exists")
        return species
    except Exception as e:
        log(f"Classification failed for {cropped_image_path}: {str(e)}")
        return None


def process_image_file(
    image_file,
    detector,
    confidence_threshold,
    output_base,
    log,
    include_human,
    include_animal,
    rename_images=False,
    delete_no_detections=False,
    hito_prefix="persona_",
    animal_prefix="animal_",
    use_animal_classification=False,
    animal_filter_config=None,
):
    """
    Process a single image file.
    Returns stats dict: {'empty': bool, 'human': int, 'animal': int, 'species': {name: count}}
    """
    stats = {'empty': False, 'human': 0, 'animal': 0, 'species': {}}
    image_path = image_file
    image_file_name = os.path.basename(image_file)
    log(f"Processing image: {image_path}")

    image = cv2.imread(image_path)
    if image is None:
        log(f"Could not read {image_path}")
        stats['empty'] = True
        return stats

    results = process_images(
        im_files=[image_path],
        detector=detector,
        confidence_threshold=0.0,
        use_image_queue=False,
        quiet=True,
    )

    detections = results[0].get("detections", [])
    valid_detections = [
    d for d in detections
    if d["conf"] > confidence_threshold and (
        (d["category"] == "1" and include_animal) or
        (d["category"] != "1" and include_human)
    )
]


    if not valid_detections:
        log(f"No valid detections in {image_path}")
        stats['empty'] = True
        if delete_no_detections:
            try:
                os.remove(image_path)
                log(f"Deleted image: {image_path}")
            except Exception as e:
                log(f"Failed to delete {image_path}: {str(e)}")
        return stats

    # Count detections by type
    for d in valid_detections:
        if d["category"] == "1":
            stats['animal'] += 1
        else:
            stats['human'] += 1

    # Determine prefix based on detection type
    prefix = ""

    for detection in valid_detections:
        if detection["category"] == "1":
            prefix = animal_prefix
        else:
            prefix = hito_prefix

    # Rename image file if enabled
    if rename_images:
        image_dir = os.path.dirname(image_path)
        new_image_name = prefix + image_file_name
        new_image_path = os.path.join(image_dir, new_image_name)

        if os.path.exists(new_image_path):
            log(f"Cannot rename {image_path}: File {new_image_name} already exists")
        else:
            os.rename(image_path, new_image_path)
            log(f"Renamed image: {image_path} -> {new_image_path}")
            image_file_name = new_image_name  # Update for consistency

    # Save detections only if output_base is not None
    if output_base is not None:
        base_filename = os.path.splitext(image_file_name)[0]
        for i, detection in enumerate(valid_detections):
            cropped_image = crop_image_with_bbox_image(image, detection["bbox"])
            cropped_image_name = f"{base_filename}_crop_{i}.jpg"
            cropped_image_path = os.path.join(output_base, cropped_image_name)
            cv2.imwrite(cropped_image_path, cropped_image)
            log(f"Saved cropped image to {cropped_image_path}")

            result = _classify_and_rename_crop(
                cropped_image_path, cropped_image_name, output_base,
                detection, use_animal_classification, animal_filter_config,
                stats, log, original_path=image_path,
            )
            # If crop was filtered out, the helper already removed it
        log("Image processing complete")
    else:
        log("Detection data saving is disabled.")

    return stats

def process_video_file(
    video_file,
    detector,
    confidence_threshold,
    output_base,
    log,
    include_human,
    include_animal,
    every_n_frames=16,
    max_duration_seconds=10,
    save_all_detections=False,
    rename_videos=False,
    delete_no_detections=False,
    hito_prefix="persona_",
    animal_prefix="animal_",
    use_animal_classification=False,
    animal_filter_config=None,
):
    """
    Process a single video file.
    Returns stats dict.
    """
    stats = {'empty': False, 'human': 0, 'animal': 0, 'species': {}}
    video_path = video_file
    video_file_name = os.path.basename(video_file)
    log(f"Processing video: {video_path}")

    # Load the video
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        log(f"Could not open video {video_path}")
        stats['empty'] = True
        return stats

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    max_frames = int(max_duration_seconds * fps)

    log(
        f"Video FPS: {fps}, Total Frames: {total_frames}, Max Frames to Process: {max_frames}"
    )

    frame_count = 0
    temp_dir = tempfile.mkdtemp()
    frame_files = []
    frame_indices = []

    # Variables to track the highest confidence detection
    best_detection = None
    best_frame = None
    max_confidence = -1  # Initialize with a value lower than any confidence score

    # List to store frames with detections when save_all_detections is True
    frames_with_detections = []

    # Flag to indicate if any detections were found
    detections_found = False

    try:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            frame_count += 1
            if frame_count > max_frames:
                log(
                    f"Reached max duration ({max_duration_seconds} seconds) for {video_path}"
                )
                break

            if frame_count % every_n_frames == 0:
                frame_filename = os.path.join(temp_dir, f"frame_{frame_count}.jpg")
                cv2.imwrite(frame_filename, frame)
                frame_files.append(frame_filename)
                frame_indices.append(frame_count)

        cap.release()

        if not frame_files:
            log(f"No frames extracted from {video_path}")
            stats['empty'] = True
            return stats

        # Process frames using the detector
        results = process_images(
            im_files=frame_files,
            detector=detector,
            confidence_threshold=0.0,
            use_image_queue=False,
            quiet=True,
        )

        for i, result in enumerate(results):
            detections = result.get("detections", [])
            valid_detections = [
                d for d in detections
                if d["conf"] > confidence_threshold and (
                    (d["category"] == "1" and include_animal) or
                    (d["category"] != "1" and include_human)
                )
            ]

            if valid_detections:
                detections_found = (
                    True  # At least one detection over the threshold found
                )
                frame_path = frame_files[i]
                frame = cv2.imread(frame_path)
                prefix = ""
                # Update detection types for renaming
                for detection in valid_detections:
                    if detection["category"] == "1":
                        prefix = animal_prefix
                    else:
                        prefix = hito_prefix

                if save_all_detections and output_base is not None:
                    # Collect frames with detections
                    frames_with_detections.append((frame_path, valid_detections))
                else:
                    # Update max confidence and best detection
                    for detection in valid_detections:
                        if detection["conf"] > max_confidence:
                            max_confidence = detection["conf"]
                            best_detection = detection
                            best_frame = frame.copy()

        if not detections_found:
            log(f"No valid detections in {video_path}")
            stats['empty'] = True
            if delete_no_detections:
                try:
                    os.remove(video_path)
                    log(f"Deleted video: {video_path}")
                except Exception as e:
                    log(f"Failed to delete {video_path}: {str(e)}")
            return stats

        # Count detections by type
        all_valid = []
        if save_all_detections and frames_with_detections:
            for _, dets in frames_with_detections:
                all_valid.extend(dets)
        elif best_detection is not None:
            all_valid = [best_detection]
        for d in all_valid:
            if d["category"] == "1":
                stats['animal'] += 1
            else:
                stats['human'] += 1

        # Rename video file if enabled
        if rename_videos:
            video_dir = os.path.dirname(video_path)
            new_video_name = prefix + video_file_name
            new_video_path = os.path.join(video_dir, new_video_name)

            if os.path.exists(new_video_path):
                log(f"Cannot rename {video_path}: File {new_video_name} already exists")
            else:
                os.rename(video_path, new_video_path)
                log(f"Renamed video: {video_path} -> {new_video_path}")
                video_file_name = new_video_name  # Update for consistency
                video_path = new_video_path  # Update video_path as well

        # Save detections only if output_base is not None
        if output_base is not None:
            # Get base filename without extension
            base_filename = os.path.splitext(video_file_name)[0]
            
            # Track detection count across all frames for unique naming
            total_detection_count = 0
            
            if save_all_detections and frames_with_detections:
                for idx, (frame_path, detections) in enumerate(frames_with_detections):
                    frame = cv2.imread(frame_path)
                    
                    # Save cropped images for each detection
                    for j, detection in enumerate(detections):
                        cropped_image = crop_image_with_bbox_image(
                            frame, detection["bbox"]
                        )
                        # Create crop filename: original_name+crop+{number}
                        cropped_image_name = f"{base_filename}_crop_{total_detection_count}.jpg"
                        cropped_image_path = os.path.join(output_base, cropped_image_name)
                        cv2.imwrite(cropped_image_path, cropped_image)
                        log(f"Saved cropped image to {cropped_image_path}")
                        _classify_and_rename_crop(
                            cropped_image_path, cropped_image_name, output_base,
                            detection, use_animal_classification, animal_filter_config,
                            stats, log, original_path=video_path,
                        )
                        total_detection_count += 1

                log(f"Saved all detections for video {video_file_name} to {output_base}")
            elif best_detection is not None and best_frame is not None:
                # Save best frame cropped image
                cropped_image = crop_image_with_bbox_image(
                    best_frame, best_detection["bbox"]
                )
                cropped_image_name = f"{base_filename}_crop_0.jpg"
                cropped_image_path = os.path.join(output_base, cropped_image_name)
                cv2.imwrite(cropped_image_path, cropped_image)

                log(f"Saved cropped image to {cropped_image_path}")
                _classify_and_rename_crop(
                    cropped_image_path, cropped_image_name, output_base,
                    best_detection, use_animal_classification, animal_filter_config,
                    stats, log, original_path=video_path,
                )
            else:
                log("No frames to save.")
        else:
            log("Detection data saving is disabled.")

        log("Video processing complete")

    finally:
        shutil.rmtree(temp_dir)

    return stats

class ProcessingThread(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)  # Emits (processed_count, total_count)
    finished = pyqtSignal()

    def __init__(
        self,
        input_folder,
        every_n_frames,
        confidence_threshold,
        create_detection_data,
        delete_no_detection,
        processing_duration_seconds,
        save_all_checkbox,
        rename_files_checkbox,
        hito_prefix,
        animal_prefix,
        include_human,
        include_animal,
        use_animal_classification=False,
        animal_filter_config=None,
    ):
        super().__init__()
        self.input_folder = input_folder
        self.every_n_frames = every_n_frames
        self.confidence_threshold = confidence_threshold
        self.create_detection_data = create_detection_data
        self.delete_no_detection = delete_no_detection
        self.processing_duration_seconds = processing_duration_seconds
        self.save_all_checkbox = save_all_checkbox
        self.rename_files_checkbox = rename_files_checkbox
        self.hito_prefix = hito_prefix
        self.animal_prefix = animal_prefix
        self.include_human = include_human
        self.include_animal = include_animal
        self.use_animal_classification = use_animal_classification
        self.animal_filter_config = animal_filter_config or {}
        self.total_files = 0
        self.processed_count = 0
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def log(self, message):
        self.log_signal.emit(message)

    def update_progress(self):
        """
        Emit the progress signal with the current state.
        """
        self.progress_signal.emit(self.processed_count, self.total_files)

    def run(self):
        """
        Entry point for the thread. Calls the main processing function.
        """
        self.log("Thread is running...")
        self.process_data()
        self.finished.emit()

    def process_data(self):
        try:
            self.log("Starting processing...")

            # Feature 3: GPU diagnostics
            for line in get_gpu_diagnostics():
                self.log(line)

            if self.create_detection_data:
                output_root = os.path.join(self.input_folder, "detection_data")
                os.makedirs(output_root, exist_ok=True)
                self.log(f"Output will be saved to {output_root}")
            else:
                output_root = None

            self.log("Loading AI detector model...")
            try:
                detector = load_detector(resource_path("detector_AI_model.pt"))
                self.log("Detector loaded successfully.")
            except Exception as e:
                self.log(f"Failed to load detector: {str(e)}")
                return

            self.log("AI detector model loaded successfully")

            if self.use_animal_classification:
                self.log("Loading animal classification model...")
                try:
                    load_classification_model()
                    self.log("Animal classification model loaded successfully.")
                except Exception as e:
                    self.log(f"Failed to load classification model: {str(e)}")
                    self.use_animal_classification = False

            self.log("Counting files in input folder...")
            image_extensions = [".jpg", ".jpeg", ".png"]
            video_extensions = [".mp4", ".avi", ".mov", ".mkv"]
            prefixes = [p for p in [self.hito_prefix, self.animal_prefix] if p]

            image_files = []
            video_files = []

            for root, dirs, files in os.walk(self.input_folder):
                # Feature 1: skip detection_data folder
                if "detection_data" in dirs:
                    dirs.remove("detection_data")
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in image_extensions:
                        if not any(f.startswith(prefix) for prefix in prefixes):
                            image_files.append(os.path.join(root, f))
                    elif ext in video_extensions:
                        if not any(f.startswith(prefix) for prefix in prefixes):
                            video_files.append(os.path.join(root, f))

            self.total_files = len(image_files) + len(video_files)
            self.log(f"Found {len(image_files)} images and {len(video_files)} videos")

            # Feature 5: analytics counters
            total_empty = 0
            total_human = 0
            total_animal = 0
            species_counts = {}

            self.log("Processing images...")
            for image_file in image_files:
                if self._stop_requested:
                    self.log("Processing stopped by user.")
                    break
                # Feature 1: mirror directory structure
                if output_root is not None:
                    rel_dir = os.path.relpath(os.path.dirname(image_file), self.input_folder)
                    file_output = os.path.join(output_root, rel_dir)
                    os.makedirs(file_output, exist_ok=True)
                else:
                    file_output = None
                self.log(f"Processing image: {image_file}")
                fstats = process_image_file(
                    image_file=image_file, detector=detector,
                    confidence_threshold=self.confidence_threshold,
                    output_base=file_output, log=self.log,
                    rename_images=self.rename_files_checkbox,
                    delete_no_detections=self.delete_no_detection,
                    hito_prefix=self.hito_prefix, animal_prefix=self.animal_prefix,
                    include_human=self.include_human, include_animal=self.include_animal,
                    use_animal_classification=self.use_animal_classification,
                    animal_filter_config=self.animal_filter_config,
                )
                if fstats:
                    if fstats.get('empty'): total_empty += 1
                    total_human += fstats.get('human', 0)
                    total_animal += fstats.get('animal', 0)
                    for sp, cnt in fstats.get('species', {}).items():
                        species_counts[sp] = species_counts.get(sp, 0) + cnt
                self.processed_count += 1
                self.update_progress()

            self.log("Processing videos...")
            for video_file in video_files:
                if self._stop_requested:
                    self.log("Processing stopped by user.")
                    break
                if output_root is not None:
                    rel_dir = os.path.relpath(os.path.dirname(video_file), self.input_folder)
                    file_output = os.path.join(output_root, rel_dir)
                    os.makedirs(file_output, exist_ok=True)
                else:
                    file_output = None
                self.log(f"Processing video: {video_file}")
                fstats = process_video_file(
                    video_file=video_file, detector=detector,
                    confidence_threshold=self.confidence_threshold,
                    output_base=file_output, log=self.log,
                    every_n_frames=self.every_n_frames,
                    max_duration_seconds=self.processing_duration_seconds,
                    save_all_detections=self.save_all_checkbox,
                    rename_videos=self.rename_files_checkbox,
                    delete_no_detections=self.delete_no_detection,
                    hito_prefix=self.hito_prefix, animal_prefix=self.animal_prefix,
                    include_human=self.include_human, include_animal=self.include_animal,
                    use_animal_classification=self.use_animal_classification,
                    animal_filter_config=self.animal_filter_config,
                )
                if fstats:
                    if fstats.get('empty'): total_empty += 1
                    total_human += fstats.get('human', 0)
                    total_animal += fstats.get('animal', 0)
                    for sp, cnt in fstats.get('species', {}).items():
                        species_counts[sp] = species_counts.get(sp, 0) + cnt
                self.processed_count += 1
                self.update_progress()

            # Feature 5: write CSV analytics report
            if output_root is not None and not self._stop_requested:
                csv_path = os.path.join(output_root, "detection_report.csv")
                try:
                    with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
                        writer = csv.writer(csvfile)
                        writer.writerow(["Category", "Count"])
                        writer.writerow(["Total files processed", self.total_files])
                        writer.writerow(["Empty (no detections)", total_empty])
                        writer.writerow(["Human/Vehicle detections", total_human])
                        writer.writerow(["Animal detections (total)", total_animal])
                        if self.use_animal_classification and species_counts:
                            writer.writerow([])
                            writer.writerow(["Animal Species", "Count"])
                            for sp_name in sorted(species_counts.keys()):
                                writer.writerow([sp_name, species_counts[sp_name]])
                    self.log(f"Analytics report saved to {csv_path}")
                except Exception as e:
                    self.log(f"Failed to write CSV: {str(e)}")

            if self._stop_requested:
                self.log("Processing was stopped by user.")
            else:
                self.log("Processing completed successfully.")
        except Exception as e:
            self.log(f"Error during processing: {str(e)}")
        finally:
            self.finished.emit()

LICENSE_FILE = "license.wcl"


def get_device_fingerprint():
    info = ""
    # 1. UUID (works on most systems)
    try:
        if platform.system() == "Windows":
            import subprocess
            cmd = 'wmic csproduct get uuid'
            uuid_str = subprocess.check_output(cmd).decode().split('\n')[1].strip()
            info += uuid_str
        else:
            info += str(uuid.getnode())
    except Exception:
        info += "unknownuuid"
    # 2. MAC
    try:
        info += hex(uuid.getnode())
    except Exception:
        info += "unknownmac"
    # 3. Volume Serial (Windows) or /etc/machine-id (Linux)
    try:
        if platform.system() == "Windows":
            import subprocess
            cmd = 'vol'
            vol = subprocess.check_output(cmd, shell=True).decode()
            volnum = vol.strip().split()[-1]
            info += volnum
        elif os.path.exists("/etc/machine-id"):
            with open("/etc/machine-id") as f:
                info += f.read().strip()
    except Exception:
        info += "unknownvol"
    # Shorten (hash)
    return hashlib.sha256(info.encode()).hexdigest()[:16] # 16 hex chars = 64 bits

def verify_license_file(path):
    print(f"\nDEBUG: verify_license_file called with path: {path}")
    try:
        with open(path, "r") as f:
            lic = json.load(f)
        print(f"DEBUG: License file loaded successfully: {lic}")

        # Signature verification
        data = json.dumps(lic["payload"], sort_keys=True).encode()
        pubkey = RSA.import_key(PUBLIC_KEY_PEM) # Ensure PUBLIC_KEY_PEM is defined globally or passed
        h = SHA256.new(data)
        sig = base64.b64decode(lic["signature"])
        pkcs1_15.new(pubkey).verify(h, sig)
        print("DEBUG: Signature verification successful.")

        # Expiration check
        expiry = lic["payload"].get("expiry", "never")
        if expiry != "never":
            expdate = datetime.strptime(expiry, "%Y-%m-%d")
            if expdate < datetime.utcnow():
                print(f"DEBUG: License expired. Expiry: {expdate}, UTC Now: {datetime.utcnow()}")
                return False, "License expired."
        print("DEBUG: Expiry check passed.")

        # Device lock check
        license_fingerprint = lic["payload"].get("device_id")
        current_fingerprint = get_device_fingerprint()
        print(f"DEBUG: License device_id: '{license_fingerprint}', Current device fingerprint: '{current_fingerprint}'")

        if not license_fingerprint: # Handles cases where device_id is missing or empty
            print("DEBUG: License device_id is missing or empty.")
            return False, "License not valid for this device: missing device ID."
        if license_fingerprint != "ANY" and license_fingerprint != current_fingerprint:
            print("DEBUG: Device mismatch: License is not 'ANY' and does not match current device.")
            return False, "License not valid for this device."
        print("DEBUG: Device lock check passed.")

        print("DEBUG: License verification successful.")
        return True, lic["payload"]
    except FileNotFoundError:
        print(f"DEBUG: License file not found at {path}. Returning False.")
        return False, "License file not found."
    except json.JSONDecodeError as e:
        print(f"DEBUG: JSON decoding error in license file: {e}. Returning False.")
        return False, f"Invalid license file format: {e}"
    except Exception as e:
        print(f"DEBUG: Generic exception during license verification: {type(e).__name__}: {e}. Returning False.")
        return False, str(e)

class VideoDetectionApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.license_valid = False
        self.license_info = {}
        self.setWindowTitle("Wild Catcher")
        self.setGeometry(100, 100, 1200, 800)  # Full-screen optimized

        # --- Prepare screen geometry early (for UI) ---
        screen_geometry = QDesktopWidget().availableGeometry()
        self.resize(screen_geometry.width() // 2, screen_geometry.height() // 2)

        # --- App settings ---
        self.settings = QSettings("WildCatcher", "VideoDetectionApp")

        # --- Language system variables only (no UI yet) ---
        self.languages = ["Japanese", "Spanish", "Chinese", "English", "Korean"]
        self.language_codes = ["jp", "es", "cn", "en", "kr"]
        self.current_language_index = 0  # Default to japanese
        self.language = self.languages[self.current_language_index]
        self.trans = {}  # Will be set in update_language()

        # --- Flags for sidebar panels ---
        self.is_settings_visible = False
        self.is_language_options_visible = False
        self.processing_thread = None
        self._is_processing = False
        self._classification_class_names = get_classification_class_names()

        # --- Now build all widgets/UI (all labels/buttons are created here) ---
        self.initUI()

        # --- Now all widgets exist; set translations ---
        self.update_language()

        # --- Now it's safe to do license logic (UI will use self.trans) ---
        self.check_license_and_prompt()

        # --- Set the app icon (optional: should be AFTER QWidget creation) ---
        icon_path = resource_path("assets/app_icon.ico")
        self.setWindowIcon(QtGui.QIcon(icon_path))

        # --- Initialize file dialog text (can also be localized if you want) ---
        self.select_input_folder_text = "Select Input Folder"

    def save_settings(self):
        # Save spinbox values
        self.settings.setValue("frame_interval", self.frame_interval_spinbox.value())
        self.settings.setValue("confidence_threshold", self.confidence_threshold_spinbox.value())
        self.settings.setValue("processing_duration", self.processing_duration_spinbox.value())

        # Save checkbox states
        self.settings.setValue("create_detection_data", self.create_detection_data_checkbox.isChecked())
        self.settings.setValue("delete_no_detection", self.delete_no_detection_checkbox.isChecked())
        self.settings.setValue("save_all_frames", self.save_all_checkbox.isChecked())
        self.settings.setValue("rename_files", self.rename_files_checkbox.isChecked())
        self.settings.setValue("include_human", self.include_human_checkbox.isChecked())
        self.settings.setValue("include_animal", self.include_animal_checkbox.isChecked())
        self.settings.setValue("use_animal_classification", self.use_animal_classification_checkbox.isChecked())
        for cn, cbs in self._animal_filter_checkboxes.items():
            self.settings.setValue(f"animal_delete_{cn}", cbs['delete'].isChecked())
            self.settings.setValue(f"animal_include_{cn}", cbs['include'].isChecked())

        # Save prefixes
        self.settings.setValue("hito_prefix", self.hito_prefix_line_edit.text())
        self.settings.setValue("animal_prefix", self.animal_prefix_line_edit.text())

        # Save language
        self.settings.setValue("language_index", self.current_language_index)

    def load_settings(self):
        # Load spinbox values
        self.frame_interval_spinbox.setValue(int(self.settings.value("frame_interval", 16)))
        self.confidence_threshold_spinbox.setValue(float(self.settings.value("confidence_threshold", 0.4)))
        self.processing_duration_spinbox.setValue(int(self.settings.value("processing_duration", 5)))

        # Load checkbox states
        self.create_detection_data_checkbox.setChecked(self.settings.value("create_detection_data", "false") == "true")
        self.delete_no_detection_checkbox.setChecked(self.settings.value("delete_no_detection", "false") == "true")
        self.save_all_checkbox.setChecked(self.settings.value("save_all_frames", "false") == "true")
        self.rename_files_checkbox.setChecked(self.settings.value("rename_files", "false") == "true")
        self.include_human_checkbox.setChecked(self.settings.value("include_human", "true") == "true")
        self.include_animal_checkbox.setChecked(self.settings.value("include_animal", "true") == "true")
        self.use_animal_classification_checkbox.setChecked(self.settings.value("use_animal_classification", "false") == "true")
        for cn, cbs in self._animal_filter_checkboxes.items():
            cbs['delete'].setChecked(self.settings.value(f"animal_delete_{cn}", "false") == "true")
            cbs['include'].setChecked(self.settings.value(f"animal_include_{cn}", "true") == "true")

        # Load prefixes
        self.hito_prefix_line_edit.setText(self.settings.value("hito_prefix", "p_"))
        self.animal_prefix_line_edit.setText(self.settings.value("animal_prefix", "a_"))

        # Load language
        language_index = int(self.settings.value("language_index", 0))
        self.set_language_by_index(language_index)

    def initUI(self):
        # Main layout
        main_widget = QWidget()
        main_layout = QHBoxLayout()
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
        # Sidebar (left banner)
        self.sidebar = QWidget()
        self.sidebar_layout = QVBoxLayout()
        self.sidebar_layout.setSpacing(15)  # Increase spacing between icons
        self.sidebar_layout.setContentsMargins(
            0, 10, 0, 10
        )  # Optional: Add margins around the layout
        self.sidebar.setLayout(self.sidebar_layout)
        self.sidebar.setFixedWidth(70)  # Adjusted width
        self.sidebar.setStyleSheet("background-color: #15c4d5;")
        main_layout.addWidget(self.sidebar)

        settings_icon_path = resource_path("assets/settings_icon.ico")
        # Settings and language buttons as icons
        self.settings_button = QPushButton()
        self.settings_button.setIcon(QIcon(settings_icon_path))
        self.settings_button.setIconSize(QSize(48, 48))
        self.settings_button.setStyleSheet(
            """
            QPushButton {
                border: none;
            }
            QPushButton:hover {
                background-color: #9bc472;
                border-radius: 5px;
            }
        """
        )

        self.settings_button.clicked.connect(self.show_settings)
        self.sidebar_layout.addWidget(self.settings_button)

        language_icon_path = resource_path("assets/language_icon.ico")
        self.language_button = QPushButton()
        self.language_button.setIcon(QIcon(language_icon_path))
        self.language_button.setIconSize(QSize(48, 48))
        self.language_button.setStyleSheet(
            """
            QPushButton {
                border: none;
            }
            QPushButton:hover {
                background-color: #9bc472;
                border-radius: 5px;
            }
        """
        )

        self.language_button.clicked.connect(self.show_language_options)
        self.sidebar_layout.addWidget(self.language_button)

        player_icon_path = resource_path("assets/player_icon.ico")
        self.player_button = QPushButton()
        self.player_button.setIcon(QIcon(player_icon_path))
        self.player_button.setIconSize(QSize(48, 48))
        self.player_button.setStyleSheet(
            """
            QPushButton {
                border: none;
            }
            QPushButton:hover {
                background-color: #9bc472;
                border-radius: 5px;
            }
        """
        )
        self.player_button.clicked.connect(self.open_video_player)
        self.sidebar_layout.addWidget(self.player_button)
        # Add stretch to push items to the top
        self.sidebar_layout.addStretch()
        icon_path = resource_path("assets/app_icon.ico")
        # Add the app icon at the bottom
        self.app_icon_label = QLabel()
        app_icon_pixmap = QPixmap(icon_path)
        app_icon_pixmap = app_icon_pixmap.scaled(
            48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.app_icon_label.setPixmap(app_icon_pixmap)
        self.app_icon_label.setAlignment(Qt.AlignCenter)

        # Set opacity to 0.5 (50% transparency)
        opacity_effect = QGraphicsOpacityEffect()
        opacity_effect.setOpacity(0.5)
        self.app_icon_label.setGraphicsEffect(opacity_effect)

        # Add the label to the sidebar layout
        self.sidebar_layout.addWidget(self.app_icon_label)

        # Settings panel (always visible)
        self.settings_panel = QWidget()
        self.settings_panel_layout = QVBoxLayout()
        self.settings_panel.setLayout(self.settings_panel_layout)
        self.settings_panel.setMinimumWidth(400)
        self.settings_panel.setMaximumWidth(600)
        self.settings_panel.setStyleSheet(
            """
            background-color: #112424;  
        """
        )

        main_layout.addWidget(self.settings_panel)

        # Settings content widget
        self.settings_content_widget = QWidget()
        self.settings_content_layout = QVBoxLayout()
        self.settings_content_layout.setAlignment(Qt.AlignTop)
        self.settings_content_widget.setLayout(self.settings_content_layout)
        self.settings_panel_layout.addWidget(self.settings_content_widget)

        # Language content widget (new!)
        self.language_content_widget = QWidget()
        self.language_content_layout = QVBoxLayout()
        self.language_content_layout.setAlignment(Qt.AlignTop)
        self.language_content_widget.setLayout(self.language_content_layout)
        self.settings_panel_layout.addWidget(self.language_content_widget)

        # Initially hide both
        self.settings_content_widget.hide()
        self.language_content_widget.hide()


        # Main area
        self.main_area = QWidget()
        self.main_area_layout = QVBoxLayout()
        self.main_area_layout.setSpacing(10)  # Consistent spacing
        self.main_area.setLayout(self.main_area_layout)
        main_layout.addWidget(self.main_area)

        # Input directory selection
        input_dir_layout = QHBoxLayout()
        self.input_dir_label = QLabel("Input Folder:")
        self.input_dir_label.setStyleSheet("font-size: 18px; color: #FFFFFF;")
        self.input_dir_line_edit = QLineEdit()
        self.input_dir_line_edit.setStyleSheet(
            "font-size: 16px; color: #FFFFFF; background-color: #2E2E2E; border: none; padding: 5px;"
        )
        self.browse_button = QPushButton("Browse")
        self.browse_button.setStyleSheet(
            """
            QPushButton {
                font-size: 16px; 
                color: #FFFFFF; 
                background-color: #FF9800; 
                border: none;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #FB8C00;
            }
        """
        )
        self.browse_button.clicked.connect(self.browse_input_directory)
        input_dir_layout.addWidget(self.input_dir_label)
        input_dir_layout.addWidget(self.input_dir_line_edit)
        input_dir_layout.addWidget(self.browse_button)
        self.main_area_layout.addLayout(input_dir_layout)

        # Start processing button
        self.start_button = QPushButton("Start Processing")
        self.start_button.setStyleSheet(START_BUTTON_STYLE)
        self.start_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.start_button.clicked.connect(self.on_start_stop_clicked)
        self.main_area_layout.addWidget(self.start_button, alignment=Qt.AlignLeft)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v/%m")
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                background-color: #3C3C3C;
                border: none;
                color: #FFFFFF;
                text-align: center;
                height: 30px;
                border-radius: 5px;
            }
            QProgressBar::chunk {
                background-color: #9bc472;
                border-radius: 5px;
            }
        """
        )
        self.progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.main_area_layout.addWidget(self.progress_bar)

        # Add stretch to push previous widgets to the top
        self.main_area_layout.addStretch()

        # Show logs label
        self.show_logs_label = QLabel("<a href='#'>Show Logs</a>")
        self.show_logs_label.setOpenExternalLinks(False)
        self.show_logs_label.linkActivated.connect(self.toggle_logs)
        self.show_logs_label.setStyleSheet("font-size: 18px; color: #FFFFFF;")
        self.main_area_layout.addWidget(self.show_logs_label, alignment=Qt.AlignLeft)

        # Log text edit
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        self.log_text_edit.hide()  # Initially hidden
        self.log_text_edit.setStyleSheet(
            """
            QTextEdit {
                background-color: #1E1E1E;
                color: #FFFFFF;
                border: 1px solid #3C3C3C;
                border-radius: 5px;
                font-size: 14px;
            }
        """
        )
        self.log_text_edit.setFixedHeight(200)  # Set a fixed height
        self.main_area_layout.addWidget(self.log_text_edit)
        
        # Update language to set initial texts
        self.update_language()
        
        # Apply styles
        self.applyStyles()
        # Initialize content
        self.show_empty_settings_panel()
        self.initSettingsWidgets() 
        self.update_language()     
        self.initSettingsPanel()
        self.initLanguagePanel()
        self.load_settings()

        # Initially, hide both content widgets
        self.settings_content_widget.hide()
        self.language_content_widget.hide()

    def applyStyles(self):
        # Set the main window's background color
        self.setStyleSheet("background-color: #0b1c0a;")
        # Additional styling can be applied here

    def show_empty_settings_panel(self):
        self.is_settings_visible = False
        self.is_language_options_visible = False

    def show_settings(self):
        if self.is_settings_visible:
            self.settings_content_widget.hide()
            self.is_settings_visible = False
        else:
            self.language_content_widget.hide()
            self.settings_content_widget.show()
            self.is_settings_visible = True
            self.is_language_options_visible = False
            self.update_language()

    def show_language_options(self):
        if self.is_language_options_visible:
            self.language_content_widget.hide()
            self.is_language_options_visible = False
        else:
            self.settings_content_widget.hide()
            self.language_content_widget.show()
            self.is_language_options_visible = True
            self.is_settings_visible = False

    def clear_layout_item(self, item):
        if item is None:
            return
        if item.widget():
            widget = item.widget()
            widget.setParent(None)
        elif item.layout():
            layout = item.layout()
            while layout.count():
                child_item = layout.takeAt(0)
                self.clear_layout_item(child_item)
            layout.setParent(None)
        else:
            # Handle spacer items if necessary
            pass

    def initSettingsPanel(self):
        # Remove all widgets from the layout but DON'T delete them
        while self.settings_content_layout.count():
            item = self.settings_content_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)  # Just remove from layout, do NOT deleteLater
            elif item.layout():
                # For sublayouts (like the license info box), just remove them safely
                sublayout = item.layout()
                while sublayout.count():
                    subitem = sublayout.takeAt(0)
                    subwidget = subitem.widget()
                    if subwidget:
                        subwidget.setParent(None)
                # Don't call deleteLater() on layouts either

        settings_widgets = [
            self.frame_interval_label,
            self.frame_interval_spinbox,
            self.confidence_threshold_label,
            self.confidence_threshold_spinbox,
            self.processing_duration_label,
            self.processing_duration_spinbox,
            self.create_detection_data_checkbox,
            self.delete_no_detection_checkbox,
            self.save_all_checkbox,
            self.rename_files_checkbox,
            self.include_human_checkbox,
            self.hito_container,
            self.include_animal_checkbox,
            self.animal_container,
            self.use_animal_classification_checkbox,
            self.animal_filter_container,
            self.remove_prefixes_button,
        ]

        for widget in settings_widgets:
            widget.setStyleSheet("font-size: 22px; color: #FFFFFF;")
            self.settings_content_layout.addWidget(widget)

        # Set initial visibility correctly
        self.hito_container.setVisible(self.include_human_checkbox.isChecked())
        self.animal_container.setVisible(self.include_animal_checkbox.isChecked())
        self.animal_filter_container.setVisible(self.use_animal_classification_checkbox.isChecked())

        # License Info at bottom
        license_box = QVBoxLayout()
        trans = self.trans  # Always current language

        if self.license_valid and isinstance(self.license_info, dict):
            licensee = self.license_info.get("licensee", trans["not_activated"])
            exp = self.license_info.get("expiry", "never")
        else:
            licensee = trans["not_activated"]
            exp = "never"

        lic_label = QLabel(f"{trans['license_label']} {licensee}")

        # Localized expiry string
        if exp == "never":
            exp_str = trans["perpetual"]
        elif exp:
            exp_str = f"{trans['expires']}{exp}"
        else:
            exp_str = "" # If expiry is invalid or not present and not 'never'
        exp_label = QLabel(exp_str)

        import_btn = QPushButton(trans["import_license"])
        import_btn.clicked.connect(lambda: self.show_license_dialog(error=None))

        license_box.addWidget(lic_label)
        license_box.addWidget(exp_label)
        license_box.addWidget(import_btn)
        license_widget = QWidget()
        license_widget.setLayout(license_box)
        self.settings_content_layout.addWidget(license_widget)



    def initSettingsWidgets(self):
        # Initialize all widgets exactly once here (moved from initSettingsPanel)
        self.frame_interval_label = QLabel("Frame Interval:")
        self.frame_interval_spinbox = QSpinBox()
        self.frame_interval_spinbox.setRange(1, 1000)

        self.confidence_threshold_label = QLabel("Confidence Threshold:")
        self.confidence_threshold_spinbox = QDoubleSpinBox()
        self.confidence_threshold_spinbox.setRange(0.0, 1.0)
        self.confidence_threshold_spinbox.setSingleStep(0.01)

        self.processing_duration_label = QLabel("Process Videos Up To (seconds):")
        self.processing_duration_spinbox = QSpinBox()
        self.processing_duration_spinbox.setRange(1, 3600)

        self.create_detection_data_checkbox = QCheckBox("Create 'detection_data' Folder")
        self.delete_no_detection_checkbox = QCheckBox("Delete Videos Without Detections")
        self.save_all_checkbox = QCheckBox("Save All Frames")
        self.rename_files_checkbox = QCheckBox("Rename Files with Tags")

        self.include_human_checkbox = QCheckBox(self.trans["include_human_checkbox"])
        self.hito_prefix_label = QLabel("Human/Vehicle Tag:")
        self.hito_prefix_line_edit = QLineEdit()
        self.hito_prefix_line_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.hito_prefix_line_edit.setMinimumWidth(150)
        self.hito_prefix_line_edit.setEnabled(True)

        self.hito_layout = QVBoxLayout()
        self.hito_layout.addWidget(self.hito_prefix_label)
        hito_line_layout = QHBoxLayout()
        hito_line_layout.addWidget(QLabel("　　→ :"))
        hito_line_layout.addWidget(self.hito_prefix_line_edit)
        self.hito_layout.addLayout(hito_line_layout)
        self.hito_container = QWidget()
        self.hito_container.setLayout(self.hito_layout)

        self.include_animal_checkbox = QCheckBox(self.trans["include_animal_checkbox"])
        self.animal_prefix_label = QLabel("Non-Bird Animal Tag:")
        self.animal_prefix_line_edit = QLineEdit()
        self.animal_prefix_line_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.animal_prefix_line_edit.setMinimumWidth(150)
        self.animal_prefix_line_edit.setEnabled(True)

        self.animal_layout = QVBoxLayout()
        self.animal_layout.addWidget(self.animal_prefix_label)
        animal_line_layout = QHBoxLayout()
        animal_line_layout.addWidget(QLabel("　　→ :"))
        animal_line_layout.addWidget(self.animal_prefix_line_edit)
        self.animal_layout.addLayout(animal_line_layout)
        self.animal_container = QWidget()
        self.animal_container.setLayout(self.animal_layout)

        self.use_animal_classification_checkbox = QCheckBox(self.trans.get("use_animal_classification_checkbox", "Use Animal Classification Model"))

        # Feature 2: Per-animal filter config UI
        self.animal_filter_container = QWidget()
        self.animal_filter_layout = QVBoxLayout()
        self.animal_filter_layout.setContentsMargins(20, 5, 5, 5)
        self.animal_filter_container.setLayout(self.animal_filter_layout)
        self._animal_filter_checkboxes = {}
        self._animal_filter_header_label = None
        if self._classification_class_names:
            self._animal_filter_header_label = QLabel(self.trans.get("animal_filter_header", "Per-animal settings:"))
            self._animal_filter_header_label.setStyleSheet("font-size: 16px; color: #AAAAAA; font-weight: bold;")
            self.animal_filter_layout.addWidget(self._animal_filter_header_label)
            for class_name in self._classification_class_names:
                row = QWidget()
                rl = QHBoxLayout()
                rl.setContentsMargins(0, 2, 0, 2)
                row.setLayout(rl)
                nl = QLabel(f"{class_name}:")
                nl.setFixedWidth(120)
                nl.setStyleSheet("font-size: 16px; color: #FFFFFF;")
                dcb = QCheckBox(self.trans.get("delete_original_short", "Delete original"))
                dcb.setStyleSheet("font-size: 14px; color: #FF6B6B;")
                icb = QCheckBox(self.trans.get("include_crop_short", "Include crop"))
                icb.setChecked(True)
                icb.setStyleSheet("font-size: 14px; color: #9bc472;")
                rl.addWidget(nl)
                rl.addWidget(dcb)
                rl.addWidget(icb)
                rl.addStretch()
                self.animal_filter_layout.addWidget(row)
                self._animal_filter_checkboxes[class_name] = {'delete': dcb, 'include': icb}

        self.remove_prefixes_button = QPushButton("Remove Tags from All File Names")
        self.remove_prefixes_button.clicked.connect(self.remove_prefixes_from_files)

        self.include_human_checkbox.toggled.connect(self.hito_container.setVisible)
        self.include_animal_checkbox.toggled.connect(self.animal_container.setVisible)
        self.use_animal_classification_checkbox.toggled.connect(self.animal_filter_container.setVisible)
        
        self.hito_container.setVisible(self.include_human_checkbox.isChecked())
        self.animal_container.setVisible(self.include_animal_checkbox.isChecked())
        self.animal_filter_container.setVisible(self.use_animal_classification_checkbox.isChecked())

    def _get_animal_filter_config(self):
        config = {}
        for class_name, cbs in self._animal_filter_checkboxes.items():
            config[class_name] = {'delete_original': cbs['delete'].isChecked(), 'include_crop': cbs['include'].isChecked()}
        return config

    def check_license_and_prompt(self):
        valid, info = verify_license_file(LICENSE_FILE)
        self.license_valid = valid
        self.license_info = info if valid else {}
        
        if not valid:
            # Show the license dialog and get its result
            dialog_result = self.show_license_dialog(error=str(info))
            # After the dialog closes, check its return result
            if dialog_result == QtWidgets.QDialog.Accepted:
                # self.license_valid and self.license_info should already be updated by import_license.
                pass
            else:
                valid_after_dialog, info_after_dialog = verify_license_file(LICENSE_FILE)
                self.license_valid = valid_after_dialog
                self.license_info = info_after_dialog if valid_after_dialog else {}
                if not valid_after_dialog:
                    sys.exit(0)
        # *** ALWAYS update the UI to reflect the current license state ***
        self.initSettingsPanel()


    def show_license_dialog(self, error="No valid license found."):
        trans = self.trans
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(trans["license_required"])
        dlg.setModal(True)
        dlg.setMinimumWidth(400)
        layout = QVBoxLayout()
        label = QLabel(trans["license_required_dialog"])
        label.setStyleSheet("font-size:18px;font-weight:bold;")
        layout.addWidget(label)
        if error:
            error_label = QLabel(error)
            error_label.setStyleSheet("color:red;")
            layout.addWidget(error_label)

        # Fix 1: Make Device ID selectable using QTextEdit
        fingerprint = get_device_fingerprint()
        fingerprint_label = QLabel("Device ID:")
        self.fingerprint_text_edit = QTextEdit()
        self.fingerprint_text_edit.setReadOnly(True)
        self.fingerprint_text_edit.setText(fingerprint)
        self.fingerprint_text_edit.setFixedHeight(30) # Adjust height as needed
        self.fingerprint_text_edit.setStyleSheet("background-color: #3C3C3C; color: #FFFFFF;") # Ensure visibility
        
        fingerprint_layout = QHBoxLayout()
        fingerprint_layout.addWidget(fingerprint_label)
        fingerprint_layout.addWidget(self.fingerprint_text_edit)
        layout.addLayout(fingerprint_layout)

        # Fix 2: Set button style for readability
        import_btn = QPushButton(trans["import_license"])
        import_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #0078D4; /* Blue background */
                color: #FFFFFF; /* White text */
                font-size: 16px;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #0056b3; /* Darker blue on hover */
            }
            """
        )
        import_btn.clicked.connect(lambda: self.import_license(dlg))
        layout.addWidget(import_btn)
        
        dlg.setLayout(layout)
        return dlg.exec_() # Return the result of the modal dialog

    def import_license(self, parent_dialog):
        trans = self.trans
        file, _ = QFileDialog.getOpenFileName(self, "Select License File", "", "License Files (*.wcl);;All Files (*)")
        if file:
            try:
                dest = os.path.join(os.path.dirname(sys.argv[0]), LICENSE_FILE)
                
                # Use shutil.copy for robustness
                shutil.copy(file, dest)

                # Verify the newly copied license file immediately
                current_valid, current_info = verify_license_file(dest) # Verify the *destination* file

                if current_valid:
                    self.license_valid = current_valid
                    self.license_info = current_info
                    QMessageBox.information(self, trans["import_license"], trans["license_imported_success"])
                    self.initSettingsPanel()  
                    parent_dialog.accept()
                else:
                    # If verification fails immediately after copy, show specific error
                    QMessageBox.critical(self, trans["import_failed"], trans["license_not_valid_after_import"])

            except FileNotFoundError:
                QMessageBox.critical(self, trans["import_failed"], "Source or destination file not found.")
            except PermissionError:
                QMessageBox.critical(self, trans["import_failed"], "Permission denied to copy license file.")
            except Exception as e:
                # Catch any other unexpected errors during copy or initial verification attempt
                QMessageBox.critical(self, trans["import_failed"], f"An unexpected error occurred: {str(e)}")


    def initLanguagePanel(self):
        # Clear the layout to prevent duplicate rows
        while self.language_content_layout.count():
            item = self.language_content_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            elif item.layout():
                # If it is a nested layout, clear it recursively
                sublayout = item.layout()
                while sublayout.count():
                    subitem = sublayout.takeAt(0)
                    subwidget = subitem.widget()
                    if subwidget:
                        subwidget.deleteLater()

        # Language flags layout
        flag_layout = QHBoxLayout()
        flag_layout.setAlignment(Qt.AlignLeft)

        # Create language selection buttons
        for index, lang_code in enumerate(self.language_codes):
            flag_button = QPushButton()
            flag_icon_path = resource_path(f"assets/flags/{lang_code}.ico")
            flag_icon = QIcon(flag_icon_path)
            flag_button.setIcon(flag_icon)
            flag_button.setIconSize(QSize(48, 48))
            flag_button.setFixedSize(60, 60)
            flag_button.setStyleSheet(
                """
                QPushButton {
                    border: none;
                    margin: 5px;
                }
                QPushButton:hover {
                    background-color: #9bc472;
                    border-radius: 5px;
                }
            """
            )
            flag_button.clicked.connect(
                lambda checked, idx=index: self.set_language_by_index(idx)
            )
            flag_layout.addWidget(flag_button)

        self.language_content_layout.addLayout(flag_layout)
    
    def set_language_by_index(self, index):
        self.current_language_index = index
        self.language = self.languages[self.current_language_index]
        self.update_language()
        # Re-initialize the settings panel if it is visible
        if self.is_settings_visible:
            self.initSettingsPanel()
            self.update_language()
        elif self.is_language_options_visible:
            # Re-initialize the language panel
            self.initLanguagePanel()

    def update_language(self):
        # Define translations for each language
        translations = {
            "Japanese": {
                "input_dir_label": "処理対象フォルダー:",
                "browse_button": "参照",
                "start_button": "処理開始",
                "open_external_app_button": "動画再生APPを開く",
                "show_logs_label_show": "<a href='#'>ログを表示</a>",
                "show_logs_label_hide": "<a href='#'>ログを隠す</a>",
                "frame_interval_label": "コマ間隔 (コマ何枚に１枚処理するか):",
                "confidence_threshold_label": "確信度のしきい値:",
                "processing_duration_label": "動画の何秒まで処理:",
                "create_detection_data_checkbox": "'detection_data'フォルダーを作成する",
                "delete_no_detection_checkbox": "認識情報がない動画を削除する",
                "save_all_checkbox": "すべてのフレームを保存",
                "rename_files_checkbox": "タグで動画・画像のファイル名を変更",
                "hito_prefix_label": "　　人・車のタグ:",
                "animal_prefix_label": "　　動物のタグ:",
                "remove_prefixes_button": "すべてのファイル名からタグを消す",
                "select_input_folder": "処理対象フォルダーを選択",
                "include_human_checkbox": "人や車両の検出を含める",
                "include_animal_checkbox": "動物の検出を含める",
                "use_animal_classification_checkbox": "動物分類モデルを使用する",
                "animal_filter_header": "動物別の設定:",
                "delete_original_short": "元ファイル削除",
                "include_crop_short": "切り抜き保存",
                "stop_button": "処理停止",
                "stop_confirm_title": "処理停止確認",
                "stop_confirm_msg": "処理を停止してもよろしいですか？",

                "license_label": "ライセンス:",
                "not_activated": "無効",
                "import_license": "ライセンスを参照",
                "expires": "有効期限: ",
                "perpetual": "無限",
                "license_required": "ライセンスが必要",
                "license_imported_success": "ライセンスファイルが正常にインポートされました。",
                "import_failed": "インポートが失敗しました",
                "license_required_dialog": "WildCatcher ライセンスが必要",
                "no_valid_license": "有効なライセンスが見つかりませんでした",
                "license_not_valid_after_import": "コピーされたライセンスファイルは有効ではありません。",
            },
            "Spanish": {
                "input_dir_label": "Carpeta de entrada:",
                "browse_button": "Examinar",
                "start_button": "Iniciar",
                "open_external_app_button": "Abrir reproductor de videos",
                "show_logs_label_show": "<a href='#'>Mostrar registros</a>",
                "show_logs_label_hide": "<a href='#'>Ocultar registros</a>",
                "frame_interval_label": "Intervalo de frames:",
                "confidence_threshold_label": "Umbral de confianza:",
                "processing_duration_label": "Procesar videos hasta (segundos):",
                "create_detection_data_checkbox": "Crear carpeta 'detection_data'",
                "delete_no_detection_checkbox": "Eliminar videos sin detecciones",
                "save_all_checkbox": "Guardar todos los frames",
                "rename_files_checkbox": "Renombrar archivos con etiquetas",
                "hito_prefix_label": "　　Etiqueta para humanos/vehículos:",
                "animal_prefix_label": "　　Etiqueta para animales:",
                "remove_prefixes_button": "Eliminar etiquetas de nombres de archivos",
                "select_input_folder": "Seleccionar carpeta de entrada",
                "include_human_checkbox": "Incluir detecciones de humanos/vehículos",
                "include_animal_checkbox": "Incluir detecciones de animales",
                "use_animal_classification_checkbox": "Usar modelo de clasificación animal",
                "animal_filter_header": "Configuración por animal:",
                "delete_original_short": "Borrar original",
                "include_crop_short": "Incluir recorte",
                "stop_button": "Detener",
                "stop_confirm_title": "Confirmar detención",
                "stop_confirm_msg": "¿Está seguro de que desea detener?",

                "license_label": "Licencia:",
                "not_activated": "Sin Activar",
                "import_license": "Importar Licencia",
                "expires": "Caduca el: ",
                "perpetual": "Indefinida",
                "license_required": "Licencia no detectada",
                "license_imported_success": "Licencia añadida correctamente.",
                "import_failed": "Error al intentar añadir una licencia",
                "license_required_dialog": "WildCatcher requiere una licencia",
                "no_valid_license": "No se ha encontrado una licencia válida.",
                "license_not_valid_after_import": "La licencia no es válida.",
            },
            "Chinese": {
                "input_dir_label": "输入文件夹:",
                "browse_button": "浏览",
                "start_button": "开始处理",
                "open_external_app_button": "打开视频播放器",
                "show_logs_label_show": "<a href='#'>显示日志</a>",
                "show_logs_label_hide": "<a href='#'>隐藏日志</a>",
                "frame_interval_label": "帧间隔:",
                "confidence_threshold_label": "置信度阈值:",
                "processing_duration_label": "处理视频时长 (秒):",
                "create_detection_data_checkbox": "创建'detection_data'文件夹",
                "delete_no_detection_checkbox": "删除没有检测的文件",
                "save_all_checkbox": "保存所有帧",
                "rename_files_checkbox": "用标签重命名文件",
                "hito_prefix_label": "　　人/车辆标签:",
                "animal_prefix_label": "　　动物标签:",
                "remove_prefixes_button": "从文件名中删除标签",
                "select_input_folder": "选择输入文件夹",
                "include_human_checkbox": "包含人类/车辆检测",
                "include_animal_checkbox": "包含动物检测",
                "use_animal_classification_checkbox": "使用动物分类模型",
                "animal_filter_header": "每种动物设置:",
                "delete_original_short": "删除原件",
                "include_crop_short": "包含裁剪",
                "stop_button": "停止处理",
                "stop_confirm_title": "确认停止",
                "stop_confirm_msg": "确定要停止处理吗？",

                "license_label": "License:",
                "not_activated": "Not Activated",
                "import_license": "Import License",
                "expires": "Expires: ",
                "perpetual": "Perpetual",
                "license_required": "License Required",
                "license_imported_success": "License file imported successfully.",
                "import_failed": "Import Failed",
                "license_required_dialog": "WildCatcher License Required",
                "no_valid_license": "No valid license found.",
                "license_not_valid_after_import": "The copied license file is not valid.",

            },
            "English": {
                "input_dir_label": "Input Folder:",
                "browse_button": "Browse",
                "start_button": "Start",
                "open_external_app_button": "Open Video Player App",
                "show_logs_label_show": "<a href='#'>Show Logs</a>",
                "show_logs_label_hide": "<a href='#'>Hide Logs</a>",
                "frame_interval_label": "Frame Interval:",
                "confidence_threshold_label": "Confidence Threshold:",
                "processing_duration_label": "Process Videos Up To (seconds):",
                "create_detection_data_checkbox": "Create 'detection_data' Folder",
                "delete_no_detection_checkbox": "Delete Videos Without Detections",
                "save_all_checkbox": "Save All Frames",
                "rename_files_checkbox": "Rename Files with Tags",
                "hito_prefix_label": "　　Human/Vehicle Tag:",
                "animal_prefix_label": "　　Animal Tag:",
                "remove_prefixes_button": "Remove Tags from All File Names",
                "select_input_folder": "Select Input Folder",
                "include_human_checkbox": "Include Human/Vehicle Detections",
                "include_animal_checkbox": "Include Animal Detections",
                "use_animal_classification_checkbox": "Use Animal Classification Model",
                "animal_filter_header": "Per-animal settings:",
                "delete_original_short": "Delete original",
                "include_crop_short": "Include crop",
                "stop_button": "Stop",
                "stop_confirm_title": "Confirm Stop",
                "stop_confirm_msg": "Are you sure you want to stop processing?",

                "license_label": "License:",
                "not_activated": "Not Activated",
                "import_license": "Import License",
                "expires": "Expires: ",
                "perpetual": "Perpetual",
                "license_required": "License Required",
                "license_imported_success": "License file imported successfully.",
                "import_failed": "Import Failed",
                "license_required_dialog": "WildCatcher License Required",
                "no_valid_license": "No valid license found.",
                "license_not_valid_after_import": "The copied license file is not valid.",

            },
            "Korean": {
                "input_dir_label": "입력 폴더:",
                "browse_button": "찾아보기",
                "start_button": "처리 시작",
                "open_external_app_button": "비디오 플레이어 앱 열기",
                "show_logs_label_show": "<a href='#'>로그 보기</a>",
                "show_logs_label_hide": "<a href='#'>로그 숨기기</a>",
                "frame_interval_label": "프레임 간격:",
                "confidence_threshold_label": "신뢰도 임계값:",
                "processing_duration_label": "비디오 처리 시간 (초):",
                "create_detection_data_checkbox": "'detection_data' 폴더 생성",
                "delete_no_detection_checkbox": "감지되지 않은 비디오 삭제",
                "save_all_checkbox": "모든 프레임 저장",
                "rename_files_checkbox": "태그로 파일 이름 바꾸기",
                "hito_prefix_label": "　　사람/차량 태그:",
                "animal_prefix_label": "　　동물 태그:",
                "remove_prefixes_button": "모든 파일 이름에서 태그 제거",
                "select_input_folder": "입력 폴더 선택",
                "include_human_checkbox": "사람/차량 감지를 포함",
                "include_animal_checkbox": "동물 감지를 포함",
                "use_animal_classification_checkbox": "동물 분류 모델 사용",
                "animal_filter_header": "동물별 설정:",
                "delete_original_short": "원본 삭제",
                "include_crop_short": "크롭 포함",
                "stop_button": "처리 중지",
                "stop_confirm_title": "중지 확인",
                "stop_confirm_msg": "처리를 중지하시겠습니까?",

                "license_label": "License:",
                "not_activated": "Not Activated",
                "import_license": "Import License",
                "expires": "Expires: ",
                "perpetual": "Perpetual",
                "license_required": "License Required",
                "license_imported_success": "License file imported successfully.",
                "import_failed": "Import Failed",
                "license_required_dialog": "WildCatcher License Required",
                "no_valid_license": "No valid license found.",
                "license_not_valid_after_import": "The copied license file is not valid.",
            },
        }

        # Get the translation dictionary for the current language
        trans = translations.get(
            self.language, translations["English"]
        )  # Default to English
        self.trans = trans

        # Update labels and texts
        self.input_dir_label.setText(trans["input_dir_label"])
        self.browse_button.setText(trans["browse_button"])
        if not self._is_processing:
            self.start_button.setText(trans["start_button"])
        # self.open_external_app_button.setText(trans['open_external_app_button'])
        if self.log_text_edit.isVisible():
            self.show_logs_label.setText(trans["show_logs_label_hide"])
        else:
            self.show_logs_label.setText(trans["show_logs_label_show"])
        self.select_input_folder_text = trans["select_input_folder"]

        # Update settings labels if settings are displayed
        if self.settings_content_layout.count() > 0:
            # Check if settings panel is active
            if hasattr(self, "frame_interval_label"):
                self.frame_interval_label.setText(trans["frame_interval_label"])
                self.confidence_threshold_label.setText(
                    trans["confidence_threshold_label"]
                )
                self.processing_duration_label.setText(
                    trans["processing_duration_label"]
                )
                self.create_detection_data_checkbox.setText(
                    trans["create_detection_data_checkbox"]
                )
                self.delete_no_detection_checkbox.setText(
                    trans["delete_no_detection_checkbox"]
                )
                self.save_all_checkbox.setText(trans["save_all_checkbox"])
                self.rename_files_checkbox.setText(trans["rename_files_checkbox"])
                self.hito_prefix_label.setText(trans["hito_prefix_label"])
                self.animal_prefix_label.setText(trans["animal_prefix_label"])
                self.remove_prefixes_button.setText(trans["remove_prefixes_button"])
                self.include_human_checkbox.setText(trans["include_human_checkbox"])
                self.include_animal_checkbox.setText(trans["include_animal_checkbox"])
                self.use_animal_classification_checkbox.setText(trans.get("use_animal_classification_checkbox", "Use Animal Classification Model"))
                # Update animal filter labels
                if self._animal_filter_header_label is not None:
                    self._animal_filter_header_label.setText(trans.get("animal_filter_header", "Per-animal settings:"))
                for _cn, cbs in self._animal_filter_checkboxes.items():
                    cbs['delete'].setText(trans.get("delete_original_short", "Delete original"))
                    cbs['include'].setText(trans.get("include_crop_short", "Include crop"))


    def toggle_logs(self):
        if self.log_text_edit.isVisible():
            self.log_text_edit.hide()
        else:
            self.log_text_edit.show()
        self.update_language()  # Update the show/hide logs text based on visibility

    def browse_input_directory(self):
        dir_name = QFileDialog.getExistingDirectory(
            self, self.select_input_folder_text, ""
        )
        if dir_name:
            self.input_dir_line_edit.setText(dir_name)

    def on_start_stop_clicked(self):
        if self._is_processing:
            self.request_stop_processing()
        else:
            self.start_processing()

    def start_processing(self):
        if not self.license_valid:
            QMessageBox.critical(self, self.trans["license_required"], self.trans["no_valid_license"])
            return
        # Get parameters from UI
        input_folder = self.input_dir_line_edit.text()
        if not input_folder:
            self.log("Please select a folder to process")
            return
        if not os.path.isdir(input_folder):
            self.log("Selected folder does not exist")
            return

        self.log("Starting processing thread...")

        # Use settings variables
        every_n_frames = self.frame_interval_spinbox.value()
        confidence_threshold = self.confidence_threshold_spinbox.value()
        create_detection_data = self.create_detection_data_checkbox.isChecked()
        delete_no_detection = self.delete_no_detection_checkbox.isChecked()
        processing_duration_seconds = self.processing_duration_spinbox.value()
        save_all_checkbox = self.save_all_checkbox.isChecked()
        rename_files_checkbox = self.rename_files_checkbox.isChecked()

        # Get user-defined prefixes
        hito_prefix = self.hito_prefix_line_edit.text()
        animal_prefix = self.animal_prefix_line_edit.text()

        self._is_processing = True
        self.start_button.setText(self.trans.get("stop_button", "Stop"))
        self.start_button.setStyleSheet(STOP_BUTTON_STYLE)
        self.progress_bar.setValue(0)

        self.processing_thread = ProcessingThread(
            input_folder=input_folder,
            every_n_frames=every_n_frames,
            confidence_threshold=confidence_threshold,
            create_detection_data=create_detection_data,
            delete_no_detection=delete_no_detection,
            processing_duration_seconds=processing_duration_seconds,
            save_all_checkbox=save_all_checkbox,
            rename_files_checkbox=rename_files_checkbox,
            hito_prefix=hito_prefix,
            animal_prefix=animal_prefix,
            include_human=self.include_human_checkbox.isChecked(),
            include_animal=self.include_animal_checkbox.isChecked(),
            use_animal_classification=self.use_animal_classification_checkbox.isChecked(),
            animal_filter_config=self._get_animal_filter_config(),
        )

        # Connect signals
        self.processing_thread.log_signal.connect(self.log)
        self.processing_thread.progress_signal.connect(self.update_progress)
        self.processing_thread.finished.connect(self.processing_finished)

        # Start thread
        self.processing_thread.start()
        self.log("Processing thread started.")

    def request_stop_processing(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.trans.get("stop_confirm_title", "Confirm Stop"))
        msg_box.setText(self.trans.get("stop_confirm_msg", "Are you sure you want to stop processing?"))
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.setStyleSheet(DARK_MSGBOX_STYLE)
        if msg_box.exec_() == QMessageBox.Yes:
            if self.processing_thread is not None:
                self.processing_thread.request_stop()
                self.log("Stop requested. Waiting for current file to finish...")

    def log(self, message):
        self.log_text_edit.append(message)

    def update_progress(self, processed, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(processed)
        self.progress_bar.setFormat(f"{processed}/{total}")
        self.log(f"Progress: {processed}/{total}")

    def processing_finished(self):
        self.log("Processing complete")
        self._is_processing = False
        self.start_button.setText(self.trans.get("start_button", "Start"))
        self.start_button.setStyleSheet(START_BUTTON_STYLE)
        self.start_button.setEnabled(True)

    def open_video_player(self):
        if not self.license_valid:
            QMessageBox.critical(
                self,
                self.trans["invalid_license"],
                self.trans["license_required_for_video"]
            )
            return
        try:
            self.log("Opening embedded video player.")
            # Instantiate and show the video player
            lang_code = self.language_codes[self.current_language_index]
            self.video_player = VideoPlayer(language_code=lang_code)
            self.video_player.show()
        except Exception as e:
            self.log(f"Failed to open video player: {str(e)}")

    def remove_prefixes_from_files(self):
            """
            Removes specified prefixes from file names in the selected folder.
            """
            input_folder = self.input_dir_line_edit.text()
            if not input_folder:
                self.log("Please select a folder first.")
                return
            if not os.path.isdir(input_folder):
                self.log("Selected folder does not exist.")
                return

            # Get user-defined prefixes from settings variables
            hito_prefix = self.hito_prefix_line_edit.text()
            animal_prefix = self.animal_prefix_line_edit.text()
            prefixes = [hito_prefix, animal_prefix]

            # Confirm renaming
            message_box = QMessageBox(self)
            message_box.setWindowTitle("Confirm Prefix Removal")
            message_box.setText(
                f"This will remove the prefixes {prefixes} from file names in the selected folder.\nAre you sure you want to proceed?"
            )
            message_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            message_box.setStyleSheet(DARK_MSGBOX_STYLE)

            reply = message_box.exec_()

            if reply == QMessageBox.No:
                self.log("Prefix removal canceled.")
                return

            # Proceed with renaming
            renamed_files = []
            for root, dirs, files in os.walk(input_folder):
                for file in files:
                    for prefix in prefixes:
                        if file.startswith(prefix):
                            original_file_path = os.path.join(root, file)
                            new_file_name = file[len(prefix) :]  # Remove the prefix
                            new_file_path = os.path.join(root, new_file_name)

                            # Check if a file with the new name already exists
                            if os.path.exists(new_file_path):
                                self.log(
                                    f"Cannot rename {original_file_path} to {new_file_name}: File already exists."
                                )
                                continue

                            try:
                                os.rename(original_file_path, new_file_path)
                                renamed_files.append((original_file_path, new_file_path))
                            except Exception as e:
                                self.log(f"Failed to rename {original_file_path}: {str(e)}")

            self.log(f"Renamed {len(renamed_files)} files by removing prefixes.")
            for original, new in renamed_files:
                self.log(f"Renamed: {original} -> {new}")

    def closeEvent(self, event):
        self.save_settings()
        event.accept()


try:
    # Determine the base path
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
        logging.debug("Running in a bundled executable.")
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
        logging.debug("Running in development mode.")

    # VLC setup (Windows only — Mac/Linux use system VLC or skip)
    if sys.platform == 'win32':
        vlc_path = os.path.join(base_path, "vlc")
        libvlc_dll = os.path.join(vlc_path, "libvlc.dll")
        plugins_path = os.path.join(vlc_path, "plugins")

        os.environ["PATH"] = vlc_path + os.pathsep + os.environ["PATH"]
        os.environ["VLC_PLUGIN_PATH"] = plugins_path

        try:
            ctypes.CDLL(libvlc_dll)
            logging.debug("Successfully loaded libvlc.dll")
        except OSError as e:
            logging.error(f"Failed to load libvlc.dll: {e}")
            sys.exit(1)
    else:
        logging.debug(f"Non-Windows platform ({sys.platform}): skipping bundled VLC init.")

except Exception as e:
    logging.exception("An unexpected error occurred during initialization.")
    sys.exit(1)



if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Apply custom font if desired
    font = QFont("Segoe UI Variable", 10)
    app.setFont(font)

    # Adjust application palette to match Fluent Design
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#1E1E1E"))
    palette.setColor(QPalette.WindowText, QColor("#FFFFFF"))
    palette.setColor(QPalette.Base, QColor("#1E1E1E"))
    palette.setColor(QPalette.AlternateBase, QColor("#2D2D2D"))
    palette.setColor(QPalette.ToolTipBase, QColor("#1E1E1E"))
    palette.setColor(QPalette.ToolTipText, QColor("#FFFFFF"))
    palette.setColor(QPalette.Text, QColor("#FFFFFF"))
    palette.setColor(QPalette.Button, QColor("#3C3C3C"))
    palette.setColor(QPalette.ButtonText, QColor("#FFFFFF"))
    palette.setColor(QPalette.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.Highlight, QColor("#0078D4"))
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    app.setPalette(palette)

    # Global QMessageBox styling to ensure readability
    app.setStyleSheet("""
        QMessageBox {
            background-color: #1E1E1E; /* Dark background */
            color: #FFFFFF; /* White text for the message box itself */
        }
        QMessageBox QLabel {
            color: #FFFFFF; /* White text for labels inside QMessageBox */
        }
        QMessageBox QPushButton {
            background-color: #0078D4; /* Blue background for buttons */
            color: #FFFFFF; /* White text for buttons */
            border-radius: 5px;
            padding: 5px 10px;
        }
        QMessageBox QPushButton:hover {
            background-color: #0056b3;
        }
    """)

    # Create and show the main window
    window = VideoDetectionApp()
    window.show()

    sys.exit(app.exec_())