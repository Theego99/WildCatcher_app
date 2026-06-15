"""
WildCatcher — Wildlife Detection Application
Main entry point and UI controller.
"""
import sys
import os

# Windows VLC DLL setup (must happen before any VLC import)
if sys.platform == "win32":
    vlc_path = os.path.join(os.path.dirname(__file__), "vlc")
    if os.path.isdir(vlc_path):
        os.add_dll_directory(vlc_path)

import ctypes
import json
import logging
import shutil

# Import onnxruntime BEFORE PyQt5: on Windows the Qt DLLs conflict with
# onnxruntime-directml's DLL initialization unless ORT is loaded first.
import onnxruntime  # noqa: F401

from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import QSettings, Qt, QSize
from PyQt5.QtGui import QIcon, QFont, QPalette, QColor, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QHBoxLayout, QProgressBar, QWidget,
    QTextEdit, QCheckBox, QSpinBox, QMessageBox,
    QSizePolicy, QDesktopWidget, QScrollArea, QFrame,
    QGraphicsOpacityEffect, QSplitter,
)

# WildCatcher modules
from wc_styles import (
    START_BUTTON_STYLE, STOP_BUTTON_STYLE, DARK_MSGBOX_STYLE,
    SIDEBAR_BUTTON_STYLE, BROWSE_BUTTON_STYLE, IMPORT_BUTTON_STYLE,
    PROGRESS_BAR_STYLE, LOG_TEXTEDIT_STYLE, GLOBAL_MESSAGEBOX_STYLE,
)
from wc_translations import LANGUAGES, LANGUAGE_CODES, get_translation
from wc_license import LICENSE_FILE, verify_license_file, get_device_fingerprint
from wc_models import resource_path
from wc_processing import ProcessingThread
from wc_widgets import FolderDropViewer, ModelPipelineWidget
from video_player import VideoPlayer

# Add yolov5 to path for detector
yolov5_path = os.path.join(os.path.dirname(__file__), "yolov5")
sys.path.insert(0, yolov5_path)


# =========================================================================
# MAIN WINDOW
# =========================================================================
class VideoDetectionApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.license_valid = False
        self.license_info = {}
        self.setWindowTitle("Wild Catcher")

        screen = QDesktopWidget().availableGeometry()
        self.resize(screen.width() // 2, screen.height() // 2)

        self.settings = QSettings("WildCatcher", "VideoDetectionApp")
        self.current_language_index = 0
        self.language = LANGUAGES[0]
        self.trans = {}
        self.is_settings_visible = False
        self.is_language_options_visible = False
        self.processing_thread = None
        self._is_processing = False

        self._build_ui()
        self.update_language()
        self.check_license_and_prompt()
        self.setWindowIcon(QtGui.QIcon(resource_path("assets/app_icon.ico")))
        self.select_input_folder_text = "Select Input Folder"

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        main_widget = QWidget()
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        # --- Sidebar (fixed width, not in splitter) ---
        self._build_sidebar(main_layout)

        # --- Horizontal splitter: settings panel | main content ---
        self.h_splitter = QSplitter(Qt.Horizontal)
        self.h_splitter.setChildrenCollapsible(True)
        self.h_splitter.setHandleWidth(5)
        self.h_splitter.setStyleSheet(
            "QSplitter::handle { background:#333; }"
            "QSplitter::handle:horizontal { width:5px; }"
            "QSplitter::handle:hover { background:#9bc472; }"
        )
        main_layout.addWidget(self.h_splitter)

        # Settings panel (left side of h_splitter)
        self._build_settings_panel()

        # --- Vertical splitter: upper content | logs ---
        self.v_splitter = QSplitter(Qt.Vertical)
        self.v_splitter.setChildrenCollapsible(False)
        self.v_splitter.setHandleWidth(5)
        self.v_splitter.setStyleSheet(
            "QSplitter::handle { background:#333; }"
            "QSplitter::handle:vertical { height:5px; }"
            "QSplitter::handle:hover { background:#9bc472; }"
        )

        # Upper section: input row, start, progress, folder viewer
        self.main_area = QWidget()
        self.main_area_layout = QVBoxLayout()
        self.main_area_layout.setSpacing(10)
        self.main_area_layout.setContentsMargins(8, 8, 8, 4)
        self.main_area.setLayout(self.main_area_layout)

        self._build_input_row()
        self._build_start_button()
        self._build_progress_bar()
        self._build_folder_viewer()

        self.v_splitter.addWidget(self.main_area)

        # Log area (bottom of v_splitter — always visible, draggable)
        self._build_logs()
        self.v_splitter.addWidget(self._log_container)

        # Set initial proportions: upper gets most space, logs get ~120px
        self.v_splitter.setSizes([600, 120])
        self.v_splitter.setStretchFactor(0, 1)
        self.v_splitter.setStretchFactor(1, 0)

        self.h_splitter.addWidget(self.v_splitter)

        # Initial state: settings panel hidden (collapsed)
        self.h_splitter.setSizes([0, 1000])

        # Finalize
        self.update_language()
        self.setStyleSheet("background-color: #0b1c0a;")
        self._init_settings_widgets()
        self.update_language()
        self._init_settings_panel()
        self._init_language_panel()
        self.load_settings()
        self.settings_content_widget.hide()
        self.language_content_widget.hide()
        self.settings_panel.hide()

    def _build_sidebar(self, parent_layout):
        self.sidebar = QWidget()
        self.sidebar_layout = QVBoxLayout()
        self.sidebar_layout.setSpacing(15)
        self.sidebar_layout.setContentsMargins(0, 10, 0, 10)
        self.sidebar.setLayout(self.sidebar_layout)
        self.sidebar.setFixedWidth(70)
        self.sidebar.setStyleSheet("background-color: #15c4d5;")
        parent_layout.addWidget(self.sidebar)

        self.settings_button = self._sidebar_icon_btn("assets/settings_icon.ico")
        self.settings_button.clicked.connect(self.show_settings)
        self.sidebar_layout.addWidget(self.settings_button)

        self.language_button = self._sidebar_icon_btn("assets/language_icon.ico")
        self.language_button.clicked.connect(self.show_language_options)
        self.sidebar_layout.addWidget(self.language_button)

        self.player_button = self._sidebar_icon_btn("assets/player_icon.ico")
        self.player_button.clicked.connect(self.open_video_player)
        self.sidebar_layout.addWidget(self.player_button)

        self.sidebar_layout.addStretch()

        self.app_icon_label = QLabel()
        pix = QPixmap(resource_path("assets/app_icon.ico")).scaled(
            48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.app_icon_label.setPixmap(pix)
        self.app_icon_label.setAlignment(Qt.AlignCenter)
        opacity = QGraphicsOpacityEffect()
        opacity.setOpacity(0.5)
        self.app_icon_label.setGraphicsEffect(opacity)
        self.sidebar_layout.addWidget(self.app_icon_label)

    def _sidebar_icon_btn(self, icon_rel):
        btn = QPushButton()
        btn.setIcon(QIcon(resource_path(icon_rel)))
        btn.setIconSize(QSize(48, 48))
        btn.setStyleSheet(SIDEBAR_BUTTON_STYLE)
        return btn

    def _build_settings_panel(self):
        self.settings_panel = QWidget()
        self.settings_panel_layout = QVBoxLayout()
        self.settings_panel_layout.setContentsMargins(8, 8, 8, 8)
        self.settings_panel.setLayout(self.settings_panel_layout)
        self.settings_panel.setMinimumWidth(300)
        self.settings_panel.setStyleSheet("background-color: #112424;")
        self.h_splitter.addWidget(self.settings_panel)

        # Settings content
        self.settings_content_widget = QWidget()
        self.settings_content_layout = QVBoxLayout()
        self.settings_content_layout.setAlignment(Qt.AlignTop)
        self.settings_content_widget.setLayout(self.settings_content_layout)

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(self.settings_content_widget)
        settings_scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")
        self.settings_panel_layout.addWidget(settings_scroll)

        # Language content
        self.language_content_widget = QWidget()
        self.language_content_layout = QVBoxLayout()
        self.language_content_layout.setAlignment(Qt.AlignTop)
        self.language_content_widget.setLayout(self.language_content_layout)
        self.settings_panel_layout.addWidget(self.language_content_widget)

        self.settings_content_widget.hide()
        self.language_content_widget.hide()

    def _build_input_row(self):
        row = QHBoxLayout()
        self.input_dir_label = QLabel("Input Folder:")
        self.input_dir_label.setStyleSheet("font-size: 18px; color: #FFFFFF;")
        self.input_dir_line_edit = QLineEdit()
        self.input_dir_line_edit.setStyleSheet(
            "font-size:16px; color:#FFF; background:#2E2E2E; border:none; padding:5px;"
        )
        self.browse_button = QPushButton("Browse")
        self.browse_button.setStyleSheet(BROWSE_BUTTON_STYLE)
        self.browse_button.clicked.connect(self.browse_input_directory)
        self.input_dir_line_edit.editingFinished.connect(self._on_input_dir_edited)
        row.addWidget(self.input_dir_label)
        row.addWidget(self.input_dir_line_edit)
        row.addWidget(self.browse_button)
        self.main_area_layout.addLayout(row)

    def _build_start_button(self):
        self.start_button = QPushButton("Start Processing")
        self.start_button.setStyleSheet(START_BUTTON_STYLE)
        self.start_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.start_button.clicked.connect(self.on_start_stop_clicked)
        self.main_area_layout.addWidget(self.start_button, alignment=Qt.AlignLeft)

    def _build_progress_bar(self):
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v/%m")
        self.progress_bar.setStyleSheet(PROGRESS_BAR_STYLE)
        self.progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.main_area_layout.addWidget(self.progress_bar)

    def _build_folder_viewer(self):
        self.folder_viewer = FolderDropViewer(self)
        self.folder_viewer.folder_selected.connect(self._on_folder_dropped)
        self.main_area_layout.addWidget(self.folder_viewer, 1)

    def _build_logs(self):
        self._log_container = QWidget()
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(8, 2, 8, 4)
        log_layout.setSpacing(2)
        self._log_container.setLayout(log_layout)

        self._log_header = QLabel("Logs")
        self._log_header.setStyleSheet("font-size:13px; color:#888; font-weight:bold;")
        log_layout.addWidget(self._log_header)

        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        self.log_text_edit.setStyleSheet(LOG_TEXTEDIT_STYLE)
        log_layout.addWidget(self.log_text_edit)

    # ------------------------------------------------------------------
    # Settings widgets (created once, re-parented into panel)
    # ------------------------------------------------------------------
    def _init_settings_widgets(self):
        # --- General settings (few remaining global options) ---
        self._general_header = QLabel("General Settings")
        self._general_header.setStyleSheet("font-size:16px; color:#9bc472; font-weight:bold;")

        self.frame_interval_label = QLabel("Frame Interval:")
        self.frame_interval_spinbox = QSpinBox()
        self.frame_interval_spinbox.setRange(1, 1000)

        self.processing_duration_label = QLabel("Process Videos Up To (seconds):")
        self.processing_duration_spinbox = QSpinBox()
        self.processing_duration_spinbox.setRange(1, 3600)

        self.save_all_checkbox = QCheckBox("Save All Frames")

        # Remove Tags button (uses hardcoded prefixes)
        self.remove_prefixes_button = QPushButton("Remove Tags from All File Names")
        self.remove_prefixes_button.clicked.connect(self.remove_prefixes_from_files)

        # Separator
        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.HLine)
        self._sep.setStyleSheet("color:#333;")

        # Model pipeline widget (handles all model-specific options)
        self.pipeline_widget = ModelPipelineWidget(trans=self.trans, parent=self)

    def _init_settings_panel(self):
        """Populate settings panel layout with widgets."""
        # Clear
        while self.settings_content_layout.count():
            item = self.settings_content_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
            elif item.layout():
                sub = item.layout()
                while sub.count():
                    si = sub.takeAt(0)
                    sw = si.widget()
                    if sw:
                        sw.setParent(None)

        widgets = [
            self._general_header,
            self.frame_interval_label, self.frame_interval_spinbox,
            self.processing_duration_label, self.processing_duration_spinbox,
            self.save_all_checkbox,
            self.remove_prefixes_button,
            self._sep,
            self.pipeline_widget,
        ]
        for w in widgets:
            w.setStyleSheet(w.styleSheet() if w.styleSheet() else "font-size:22px; color:#FFF;")
            self.settings_content_layout.addWidget(w)

        self.settings_content_layout.addStretch()

        # License info
        self._add_license_box()

    def _add_license_box(self):
        trans = self.trans
        box = QVBoxLayout()
        if self.license_valid and isinstance(self.license_info, dict):
            licensee = self.license_info.get("licensee", trans.get("not_activated", "Not Activated"))
            exp = self.license_info.get("expiry", "never")
        else:
            licensee = trans.get("not_activated", "Not Activated")
            exp = "never"

        box.addWidget(QLabel(f"{trans.get('license_label', 'License:')} {licensee}"))
        exp_str = trans.get("perpetual", "Perpetual") if exp == "never" else f"{trans.get('expires', 'Expires: ')}{exp}"
        box.addWidget(QLabel(exp_str))
        import_btn = QPushButton(trans.get("import_license", "Import License"))
        import_btn.clicked.connect(lambda: self.show_license_dialog(error=None))
        box.addWidget(import_btn)
        container = QWidget()
        container.setLayout(box)
        self.settings_content_layout.addWidget(container)

    def _init_language_panel(self):
        while self.language_content_layout.count():
            item = self.language_content_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                sub = item.layout()
                while sub.count():
                    si = sub.takeAt(0)
                    sw = si.widget()
                    if sw:
                        sw.deleteLater()

        flag_layout = QHBoxLayout()
        flag_layout.setAlignment(Qt.AlignLeft)
        for i, code in enumerate(LANGUAGE_CODES):
            btn = QPushButton()
            btn.setIcon(QIcon(resource_path(f"assets/flags/{code}.ico")))
            btn.setIconSize(QSize(48, 48))
            btn.setFixedSize(60, 60)
            btn.setStyleSheet(
                "QPushButton { border:none; margin:5px; }"
                "QPushButton:hover { background:#9bc472; border-radius:5px; }"
            )
            btn.clicked.connect(lambda _, idx=i: self.set_language_by_index(idx))
            flag_layout.addWidget(btn)
        self.language_content_layout.addLayout(flag_layout)

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------
    def save_settings(self):
        s = self.settings
        s.setValue("frame_interval", self.frame_interval_spinbox.value())
        s.setValue("processing_duration", self.processing_duration_spinbox.value())
        s.setValue("save_all_frames", self.save_all_checkbox.isChecked())
        s.setValue("language_index", self.current_language_index)
        # Save pipeline (includes all per-model options)
        s.setValue("pipeline_steps", json.dumps(self.pipeline_widget.get_pipeline_config()))
        # Save splitter sizes
        s.setValue("v_splitter_sizes", self.v_splitter.sizes())

    def load_settings(self):
        s = self.settings
        self.frame_interval_spinbox.setValue(int(s.value("frame_interval", 16)))
        self.processing_duration_spinbox.setValue(int(s.value("processing_duration", 5)))
        self.save_all_checkbox.setChecked(s.value("save_all_frames", "false") == "true")
        lang_idx = int(s.value("language_index", 0))
        if 0 <= lang_idx < len(LANGUAGES):
            self.current_language_index = lang_idx
            self.language = LANGUAGES[lang_idx]
            self.update_language()
        # Restore splitter sizes
        v_sizes = s.value("v_splitter_sizes")
        if v_sizes:
            try:
                self.v_splitter.setSizes([int(x) for x in v_sizes])
            except Exception:
                pass
        # Restore pipeline
        pipeline_json = s.value("pipeline_steps", "[]")
        try:
            steps = json.loads(pipeline_json)
            if steps:
                self.pipeline_widget.set_pipeline_config(steps)
                # Migrate old settings: if only detector steps, add built-in classifier
                if not self.pipeline_widget.has_classifier_step():
                    import wc_models as models_mod
                    builtins = models_mod.get_builtin_entries()
                    for b in builtins:
                        if b["type"] == "classifier":
                            self.pipeline_widget.add_step({
                                "model_id": b["id"],
                                "confidence": 0.5,
                            })
                            break
            else:
                self.pipeline_widget.ensure_default_pipeline()
        except Exception:
            self.pipeline_widget.ensure_default_pipeline()

    # ------------------------------------------------------------------
    # Language
    # ------------------------------------------------------------------
    def set_language_by_index(self, index):
        self.current_language_index = index
        self.language = LANGUAGES[index]
        self.update_language()
        if self.is_settings_visible:
            self._init_settings_panel()
            self.update_language()
        elif self.is_language_options_visible:
            self._init_language_panel()

    def update_language(self):
        trans = get_translation(self.language)
        self.trans = trans
        self.input_dir_label.setText(trans["input_dir_label"])
        self.browse_button.setText(trans["browse_button"])
        if not self._is_processing:
            self.start_button.setText(trans["start_button"])
        self.select_input_folder_text = trans["select_input_folder"]

        if hasattr(self, "_log_header"):
            self._log_header.setText(trans.get("logs_label", "Logs"))

        if self.settings_content_layout.count() > 0 and hasattr(self, "frame_interval_label"):
            self.frame_interval_label.setText(trans["frame_interval_label"])
            self.processing_duration_label.setText(trans["processing_duration_label"])
            self.save_all_checkbox.setText(trans["save_all_checkbox"])
            self.remove_prefixes_button.setText(trans["remove_prefixes_button"])
            self.remove_prefixes_button.setText(trans["remove_prefixes_button"])

        if hasattr(self, "folder_viewer"):
            self.folder_viewer.set_hint_text(trans.get("drop_hint", "Drag & drop a folder here"))
        if hasattr(self, "_general_header"):
            self._general_header.setText(trans.get("general_settings", "General Settings"))
        if hasattr(self, "pipeline_widget"):
            self.pipeline_widget.update_translations(trans)

    # ------------------------------------------------------------------
    # Panel toggling
    # ------------------------------------------------------------------
    def _show_settings_panel(self):
        """Make the settings panel visible in the horizontal splitter."""
        if not self.settings_panel.isVisible():
            self.settings_panel.show()
            # Give settings ~400px, rest to main content
            total = self.h_splitter.width()
            settings_w = min(450, total // 3)
            self.h_splitter.setSizes([settings_w, total - settings_w])

    def _hide_settings_panel(self):
        """Collapse the settings panel."""
        self.settings_panel.hide()

    def show_settings(self):
        if self.is_settings_visible:
            self.settings_content_widget.hide()
            self._hide_settings_panel()
            self.is_settings_visible = False
        else:
            self.language_content_widget.hide()
            self.settings_content_widget.show()
            self._show_settings_panel()
            self.is_settings_visible = True
            self.is_language_options_visible = False
            self.update_language()

    def show_language_options(self):
        if self.is_language_options_visible:
            self.language_content_widget.hide()
            self._hide_settings_panel()
            self.is_language_options_visible = False
        else:
            self.settings_content_widget.hide()
            self.language_content_widget.show()
            self._show_settings_panel()
            self.is_language_options_visible = True
            self.is_settings_visible = False

    # ------------------------------------------------------------------
    # Folder handling
    # ------------------------------------------------------------------
    def browse_input_directory(self):
        d = QFileDialog.getExistingDirectory(self, self.select_input_folder_text, "")
        if d:
            self.input_dir_line_edit.setText(d)
            self.folder_viewer.set_folder(d)

    def _on_folder_dropped(self, path):
        self.input_dir_line_edit.setText(path)

    def _on_input_dir_edited(self):
        p = self.input_dir_line_edit.text().strip()
        if p and os.path.isdir(p):
            self.folder_viewer.set_folder(p)

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------
    def on_start_stop_clicked(self):
        if self._is_processing:
            self.request_stop_processing()
        else:
            self.start_processing()

    def start_processing(self):
        if not self.license_valid:
            QMessageBox.critical(self, self.trans["license_required"], self.trans["no_valid_license"])
            return
        folder = self.input_dir_line_edit.text()
        if not folder or not os.path.isdir(folder):
            self.log("Please select a valid folder to process")
            return

        # Warn if no classifier step in pipeline
        if not self.pipeline_widget.has_classifier_step():
            msg = QMessageBox(self)
            msg.setWindowTitle("No Classifier")
            msg.setText(
                "No classifier model is in the pipeline.\n"
                "Detections will be saved but NOT classified by species.\n\n"
                "Add a classifier step in Settings → Processing Pipeline\n"
                "to automatically classify each detection.\n\n"
                "Continue without classification?"
            )
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setStyleSheet(DARK_MSGBOX_STYLE)
            if msg.exec_() == QMessageBox.No:
                return

        self._is_processing = True
        self.start_button.setText(self.trans.get("stop_button", "Stop"))
        self.start_button.setStyleSheet(STOP_BUTTON_STYLE)
        self.progress_bar.setValue(0)

        config = {
            "input_folder": folder,
            "every_n_frames": self.frame_interval_spinbox.value(),
            "processing_duration_seconds": self.processing_duration_spinbox.value(),
            "save_all": self.save_all_checkbox.isChecked(),
            "pipeline_steps": self.pipeline_widget.get_pipeline_config(),
        }

        self.processing_thread = ProcessingThread(config)
        self.processing_thread.log_signal.connect(self.log)
        self.processing_thread.progress_signal.connect(self.update_progress)
        self.processing_thread.finished.connect(self.processing_finished)
        self.processing_thread.start()

    def request_stop_processing(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self.trans.get("stop_confirm_title", "Confirm Stop"))
        msg_box.setText(self.trans.get("stop_confirm_msg", "Are you sure you want to stop?"))
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.setStyleSheet(DARK_MSGBOX_STYLE)
        if msg_box.exec_() == QMessageBox.Yes and self.processing_thread:
            self.processing_thread.request_stop()
            self.log("Stop requested. Waiting for current file...")

    def log(self, message):
        self.log_text_edit.append(message)

    def update_progress(self, processed, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(processed)
        self.progress_bar.setFormat(f"{processed}/{total}")

    def processing_finished(self):
        self.log("Processing complete")
        self._is_processing = False
        self.start_button.setText(self.trans.get("start_button", "Start"))
        self.start_button.setStyleSheet(START_BUTTON_STYLE)
        self.start_button.setEnabled(True)

    # ------------------------------------------------------------------
    # License
    # ------------------------------------------------------------------
    def check_license_and_prompt(self):
        valid, info = verify_license_file(LICENSE_FILE)
        self.license_valid = valid
        self.license_info = info if valid else {}
        if not valid:
            result = self.show_license_dialog(error=str(info))
            if result != QtWidgets.QDialog.Accepted:
                v, i = verify_license_file(LICENSE_FILE)
                self.license_valid = v
                self.license_info = i if v else {}
                if not v:
                    sys.exit(0)
        self._init_settings_panel()

    def show_license_dialog(self, error=None):
        trans = self.trans
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(trans.get("license_required", "License Required"))
        dlg.setModal(True)
        dlg.setMinimumWidth(400)
        layout = QVBoxLayout()
        lbl = QLabel(trans.get("license_required_dialog", "WildCatcher License Required"))
        lbl.setStyleSheet("font-size:18px; font-weight:bold;")
        layout.addWidget(lbl)
        if error:
            el = QLabel(error)
            el.setStyleSheet("color:red;")
            layout.addWidget(el)

        fp = get_device_fingerprint()
        fp_row = QHBoxLayout()
        fp_row.addWidget(QLabel("Device ID:"))
        fp_edit = QTextEdit()
        fp_edit.setReadOnly(True)
        fp_edit.setText(fp)
        fp_edit.setFixedHeight(30)
        fp_edit.setStyleSheet("background:#3C3C3C; color:#FFF;")
        fp_row.addWidget(fp_edit)
        layout.addLayout(fp_row)

        btn = QPushButton(trans.get("import_license", "Import License"))
        btn.setStyleSheet(IMPORT_BUTTON_STYLE)
        btn.clicked.connect(lambda: self._import_license(dlg))
        layout.addWidget(btn)
        dlg.setLayout(layout)
        return dlg.exec_()

    def _import_license(self, parent_dialog):
        trans = self.trans
        f, _ = QFileDialog.getOpenFileName(self, "Select License", "", "License Files (*.wcl);;All Files (*)")
        if not f:
            return
        try:
            dest = os.path.join(os.path.dirname(sys.argv[0]), LICENSE_FILE)
            shutil.copy(f, dest)
            v, i = verify_license_file(dest)
            if v:
                self.license_valid = True
                self.license_info = i
                QMessageBox.information(self, trans.get("import_license", "Import"), trans.get("license_imported_success", "Success"))
                self._init_settings_panel()
                parent_dialog.accept()
            else:
                QMessageBox.critical(self, trans.get("import_failed", "Failed"), trans.get("license_not_valid_after_import", "Invalid"))
        except Exception as e:
            QMessageBox.critical(self, trans.get("import_failed", "Failed"), str(e))

    # ------------------------------------------------------------------
    # Misc actions
    # ------------------------------------------------------------------
    def open_video_player(self):
        if not self.license_valid:
            QMessageBox.critical(
                self,
                self.trans.get("invalid_license", "Invalid License"),
                self.trans.get("license_required_for_video", "License required"),
            )
            return
        try:
            lang_code = LANGUAGE_CODES[self.current_language_index]
            self.video_player = VideoPlayer(language_code=lang_code)
            self.video_player.show()
        except Exception as e:
            self.log(f"Video player error: {e}")

    def remove_prefixes_from_files(self):
        folder = self.input_dir_line_edit.text()
        if not folder or not os.path.isdir(folder):
            self.log("Please select a folder first.")
            return
        # Collect all possible prefixes: hardcoded + all known species
        import wc_models as models_mod
        prefixes = ["animal_", "human_", "empty_"]
        for entry in models_mod.get_all_models():
            if entry.get("class_names"):
                for cn in entry["class_names"]:
                    p = f"{cn}_"
                    if p not in prefixes:
                        prefixes.append(p)
        msg = QMessageBox(self)
        msg.setWindowTitle("Confirm Tag Removal")
        msg.setText(f"Remove all WildCatcher tags from files in this folder?\n\nTags: {', '.join(prefixes[:8])}...")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setStyleSheet(DARK_MSGBOX_STYLE)
        if msg.exec_() == QMessageBox.No:
            return
        count = 0
        for root, _, files in os.walk(folder):
            for f in files:
                for pfx in prefixes:
                    if pfx and f.startswith(pfx):
                        old = os.path.join(root, f)
                        new = os.path.join(root, f[len(pfx):])
                        if not os.path.exists(new):
                            try:
                                os.rename(old, new)
                                count += 1
                            except Exception as e:
                                self.log(f"Rename failed: {e}")
                        break  # Only strip one prefix per file
        self.log(f"Removed tags from {count} files.")

    def closeEvent(self, event):
        self.save_settings()
        event.accept()


# =========================================================================
# VLC initialization
# =========================================================================
try:
    if getattr(sys, "frozen", False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    if sys.platform == "win32":
        vlc_path = os.path.join(base_path, "vlc")
        libvlc = os.path.join(vlc_path, "libvlc.dll")
        os.environ["PATH"] = vlc_path + os.pathsep + os.environ["PATH"]
        os.environ["VLC_PLUGIN_PATH"] = os.path.join(vlc_path, "plugins")
        try:
            ctypes.CDLL(libvlc)
        except OSError as e:
            logging.error(f"Failed to load libvlc.dll: {e}")
except Exception as e:
    logging.exception(f"Initialization error: {e}")


# =========================================================================
# Entry point
# =========================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI Variable", 10))

    palette = QPalette()
    dark_colors = {
        QPalette.Window: "#1E1E1E", QPalette.WindowText: "#FFFFFF",
        QPalette.Base: "#1E1E1E", QPalette.AlternateBase: "#2D2D2D",
        QPalette.ToolTipBase: "#1E1E1E", QPalette.ToolTipText: "#FFFFFF",
        QPalette.Text: "#FFFFFF", QPalette.Button: "#3C3C3C",
        QPalette.ButtonText: "#FFFFFF", QPalette.BrightText: "#FFFFFF",
        QPalette.Highlight: "#0078D4", QPalette.HighlightedText: "#FFFFFF",
    }
    for role, color in dark_colors.items():
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(GLOBAL_MESSAGEBOX_STYLE)

    window = VideoDetectionApp()
    window.show()
    sys.exit(app.exec_())
