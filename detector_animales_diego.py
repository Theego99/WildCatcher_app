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
import subprocess

# Import onnxruntime BEFORE PyQt5: on Windows the Qt DLLs conflict with
# onnxruntime-directml's DLL initialization unless ORT is loaded first.
import onnxruntime  # noqa: F401

from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import QSettings, Qt, QSize, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QIcon, QFont, QPalette, QColor, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QHBoxLayout, QProgressBar, QWidget,
    QTextEdit, QCheckBox, QSpinBox, QMessageBox,
    QSizePolicy, QDesktopWidget, QScrollArea, QFrame,
    QGraphicsOpacityEffect, QSplitter, QStackedWidget,
)

# WildCatcher modules
from wc_styles import (
    START_BUTTON_STYLE, STOP_BUTTON_STYLE, DARK_MSGBOX_STYLE,
    SIDEBAR_BUTTON_STYLE, BROWSE_BUTTON_STYLE, IMPORT_BUTTON_STYLE,
    PROGRESS_BAR_STYLE, LOG_TEXTEDIT_STYLE, GLOBAL_MESSAGEBOX_STYLE,
    TOOLTIP_STYLE,
)
from wc_translations import LANGUAGES, LANGUAGE_CODES, get_translation
import wc_version
import wc_logging
import wc_entitlements
from wc_entitlements import FEATURE_CLASSIFY, FEATURE_EXPORT_PREMIUM
from wc_license import (
    LICENSE_FILE, verify_license_file, verify_license_key,
    save_license_key, get_device_fingerprint,
)
from wc_models import resource_path
from wc_processing import ProcessingThread
from wc_widgets import (
    FolderDropViewer, ModelPipelineWidget, CollapsibleSection, scale_css_fontsize,
)
from video_player import VideoPlayer
from wc_review import ResultsGallery
import wc_output

# Add yolov5 to path for detector
yolov5_path = os.path.join(os.path.dirname(__file__), "yolov5")
sys.path.insert(0, yolov5_path)


# NOTE: Placeholder agreement — replace with your reviewed legal EULA text.
EULA_TEXT = """{app} — End User License Agreement

By installing or using {app} ("the Software"), you agree to the following terms.

1. LICENSE. {publisher} grants you a non-exclusive, non-transferable license to
   use the Software on the licensed device(s) in accordance with your purchased
   license. The Software is licensed, not sold.

2. RESTRICTIONS. You may not copy (except for backup), redistribute, rent, lease,
   sublicense, reverse engineer, or attempt to bypass the licensing of the
   Software, except to the extent permitted by applicable law.

3. DATA. The Software processes your images and videos locally on your device.
   {publisher} does not collect your media.

4. NO WARRANTY. The Software is provided "AS IS", without warranty of any kind.
   Automated wildlife detection and classification are probabilistic and may
   contain errors; review results before relying on them.

5. LIMITATION OF LIABILITY. To the maximum extent permitted by law, {publisher}
   shall not be liable for any indirect, incidental, or consequential damages
   arising from the use of the Software.

6. TERMINATION. This license terminates automatically if you breach these terms.

Questions: {support}

If you do not agree to these terms, click Decline and do not use the Software.
"""


# =========================================================================
# BACKGROUND UPDATE CHECK
# =========================================================================
class UpdateCheckThread(QThread):
    """Silently query GitHub for a newer release (off the UI thread)."""
    update_found = pyqtSignal(str, str)  # (tag, download_url)

    def run(self):
        try:
            import requests
            r = requests.get(wc_version.UPDATE_API_URL, timeout=8,
                             headers={"Accept": "application/vnd.github+json"})
            if r.status_code == 200:
                data = r.json()
                tag = data.get("tag_name", "")
                if wc_version.is_newer(tag):
                    self.update_found.emit(
                        tag, data.get("html_url") or wc_version.RELEASES_URL)
        except Exception as e:
            logging.getLogger("update").info("startup update check failed: %s", e)


# =========================================================================
# MAIN WINDOW
# =========================================================================
class VideoDetectionApp(QMainWindow):
    # Base application font — UI zoom scales this live.
    BASE_FONT_FAMILY = "Segoe UI Variable"
    BASE_FONT_PT = 10
    MIN_UI_SCALE = 0.8
    MAX_UI_SCALE = 2.2

    def __init__(self):
        super().__init__()
        self.license_valid = False
        self.license_info = {}
        self.entitlements = None
        self.ui_scale = 1.0
        self.setWindowTitle(f"{wc_version.APP_NAME} {wc_version.APP_VERSION}")

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
        if not self.maybe_show_eula():
            sys.exit(0)
        self.check_license_and_prompt()
        if self.entitlements and self.entitlements.active:
            self.maybe_show_onboarding()
        self.setWindowIcon(QtGui.QIcon(resource_path("assets/app_icon.ico")))
        self.select_input_folder_text = "Select Input Folder"
        # Silent, once-a-day update check shortly after launch.
        QTimer.singleShot(2500, self._maybe_check_updates_on_start)

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
        self.app_icon_label.setCursor(Qt.PointingHandCursor)
        self.app_icon_label.setToolTip(
            f"{wc_version.APP_NAME} {wc_version.APP_VERSION} — About")
        # Click the logo to open the About dialog.
        self.app_icon_label.mousePressEvent = lambda _e: self.show_about()
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

        # Live throughput / ETA / current file line.
        self.progress_detail_label = QLabel("")
        self.progress_detail_label.setStyleSheet("color:#9bc472; font-size:12px;")
        self.progress_detail_label.setVisible(False)
        self.main_area_layout.addWidget(self.progress_detail_label)

        # Re-open the crop review gallery for the current folder anytime.
        self.review_button = QPushButton("Review Results")
        self.review_button.setStyleSheet(
            "QPushButton { background:#1E2E4E; color:#6B9FD4; border:1px solid #3C4C6C;"
            " border-radius:4px; padding:5px 12px; font-size:13px; }"
            "QPushButton:hover { background:#2E3E6E; }")
        self.review_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.review_button.clicked.connect(lambda: self.open_results_review())
        self.main_area_layout.addWidget(self.review_button, alignment=Qt.AlignLeft)

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

        self.resume_checkbox = QCheckBox("Skip already-processed files (resume)")
        self.resume_checkbox.setChecked(True)
        self.resume_checkbox.setToolTip("Re-runs skip files already processed.")

        self.nondestructive_checkbox = QCheckBox("Non-destructive (keep original file names)")
        self.nondestructive_checkbox.setToolTip("Never rename or delete originals.")

        # Remove Tags button (uses hardcoded prefixes)
        self.remove_prefixes_button = QPushButton("Remove Tags from All File Names")
        self.remove_prefixes_button.clicked.connect(self.remove_prefixes_from_files)

        # Separator
        self._sep = QFrame()
        self._sep.setFrameShape(QFrame.HLine)
        self._sep.setStyleSheet("color:#333;")

        # Model pipeline widget (handles all model-specific options)
        self.pipeline_widget = ModelPipelineWidget(trans=self.trans, parent=self)

        # Output / Export customization section
        self._sep2 = QFrame()
        self._sep2.setFrameShape(QFrame.HLine)
        self._sep2.setStyleSheet("color:#333;")
        self._output_section = self._build_output_settings_widget()

    def _build_output_settings_widget(self):
        """A panel of checkboxes letting the client pick output formats + columns."""
        trans = self.trans
        container = QWidget()
        # color-only (no pinned font-size) so children inherit the zoomable
        # app font, while still avoiding the 22px settings-panel default.
        container.setStyleSheet("color:#DDD;")
        lay = QVBoxLayout()
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        container.setLayout(lay)

        header = QLabel(trans.get("output_export_header", "Output / Export"))
        header.setStyleSheet("font-size:16px; color:#9bc472; font-weight:bold;")
        self._output_header_label = header
        lay.addWidget(header)

        hint = QLabel(trans.get("output_export_hint",
                                "Click a section below to expand it."))
        hint.setStyleSheet("color:#888; font-size:10px;")
        self._output_hint_label = hint
        lay.addWidget(hint)

        # --- Formats (collapsible; open by default — it's a short list) ---
        self._output_group_sections = {}
        fmt_sec = CollapsibleSection(
            trans.get("output_formats_label", "Output format(s)"), expanded=True)
        self._output_format_section = fmt_sec
        self._format_checks = {}
        for fmt in wc_output.ALL_FORMATS:
            cb = QCheckBox(wc_output.FORMAT_LABELS.get(fmt, fmt))
            cb.setStyleSheet("color:#DDD;")
            cb.setChecked(fmt in wc_output.DEFAULT_FORMATS)
            self._format_checks[fmt] = cb
            fmt_sec.addWidget(cb)
        note = QLabel(trans.get("timelapse_note",
                                "Timelapse .ddb/.tdb is experimental — open it in "
                                "Timelapse to verify."))
        note.setStyleSheet("color:#888; font-size:10px;")
        note.setWordWrap(True)
        fmt_sec.addWidget(note)
        lay.addWidget(fmt_sec)

        # --- Fields: one collapsible per group (all collapsed by default) ---
        fld_label = QLabel(trans.get("output_fields_label", "Columns to include:"))
        fld_label.setStyleSheet("color:#9bc472; font-weight:bold; margin-top:6px;")
        lay.addWidget(fld_label)
        self._field_checks = {}
        groups = wc_output.fields_by_group()
        for g in wc_output.GROUP_ORDER:
            items = groups.get(g) or []
            if not items:
                continue
            sec = CollapsibleSection(
                trans.get("group_" + g, wc_output.GROUP_LABELS.get(g, g)),
                expanded=False)
            for key, header_txt, _i18n in items:
                cb = QCheckBox(header_txt)
                cb.setStyleSheet("color:#DDD;")
                cb.setChecked(key in wc_output.DEFAULT_FIELDS)
                self._field_checks[key] = cb
                sec.addWidget(cb)
            self._output_group_sections[g] = sec
            lay.addWidget(sec)
        return container

    def _get_output_config(self):
        """Read the selected fields (in registry order) and formats from the GUI."""
        if not hasattr(self, "_field_checks"):
            return list(wc_output.DEFAULT_FIELDS), list(wc_output.DEFAULT_FORMATS)
        fields = [k for (k, _h, _g, _i) in wc_output.FIELDS
                  if self._field_checks.get(k) and self._field_checks[k].isChecked()]
        formats = [f for f in wc_output.ALL_FORMATS
                   if self._format_checks.get(f) and self._format_checks[f].isChecked()]
        return (fields or list(wc_output.DEFAULT_FIELDS),
                formats or list(wc_output.DEFAULT_FORMATS))

    def _apply_output_config(self, fields, formats):
        if not hasattr(self, "_field_checks"):
            return
        for k, cb in self._field_checks.items():
            cb.setChecked(k in fields)
        for f, cb in self._format_checks.items():
            cb.setChecked(f in formats)

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
            self.resume_checkbox,
            self.nondestructive_checkbox,
            self.remove_prefixes_button,
            self._sep,
            self._output_section,
            self._sep2,
            self.pipeline_widget,
        ]
        # These widgets carry no style of their own; give them a (zoom-scaled)
        # default so the whole settings panel responds to the text-size control.
        # Explicit set — idempotent across the repeated _init_settings_panel
        # calls (language change / license import).
        default_styled = {
            self.frame_interval_label, self.frame_interval_spinbox,
            self.processing_duration_label, self.processing_duration_spinbox,
            self.save_all_checkbox, self.resume_checkbox,
            self.nondestructive_checkbox, self.remove_prefixes_button,
        }
        self._settings_default_widgets = []
        for w in widgets:
            if w in default_styled:
                self._settings_default_widgets.append(w)
                # Unscaled base — the global rescale walk scales it from here.
                w.setProperty("_wc_orig_ss", "font-size:22px; color:#FFF;")
                w.setStyleSheet("font-size:22px; color:#FFF;")
            self.settings_content_layout.addWidget(w)

        self.settings_content_layout.addStretch()

        # License info
        self._add_license_box()

        # Scale the (re)built panel to the current zoom.
        self._rescale_all_fonts()

    def _add_license_box(self):
        trans = self.trans
        e = self.entitlements
        box = QVBoxLayout()

        if self.license_valid and isinstance(self.license_info, dict):
            licensee = self.license_info.get("licensee") or trans.get("not_activated", "Not Activated")
            exp = self.license_info.get("expiry", "never")
            box.addWidget(QLabel(f"{trans.get('license_label', 'License:')} {licensee}"))
            box.addWidget(QLabel(f"{trans.get('plan_label', 'Plan:')} {e.label if e else '-'}"))
            exp_str = (trans.get("perpetual", "Perpetual") if exp == "never"
                       else f"{trans.get('expires', 'Expires: ')}{exp}")
            box.addWidget(QLabel(exp_str))
            btn_label = trans.get("manage_license", "Manage license")
        elif e and e.is_trial and e.active:
            t = QLabel(f"{trans.get('plan_label', 'Plan:')} {trans.get('trial_label', 'Trial')} "
                       f"— {e.trial_days_left} {trans.get('days_left', 'days left')}")
            t.setStyleSheet("color:#FFB86B; font-weight:bold;")
            box.addWidget(t)
            box.addWidget(QLabel(trans.get(
                "trial_upsell", "Upgrade to Pro for unlimited files & all features.")))
            btn_label = trans.get("upgrade_activate", "Upgrade / Activate")
        else:
            box.addWidget(QLabel(trans.get("not_activated", "Not Activated")))
            btn_label = trans.get("upgrade_activate", "Upgrade / Activate")

        import_btn = QPushButton(btn_label)
        import_btn.setStyleSheet(IMPORT_BUTTON_STYLE)
        import_btn.clicked.connect(self._open_license_manager)
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

        # --- Text size / zoom ---
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#333; margin-top:8px;")
        self.language_content_layout.addWidget(sep)

        zoom_title = QLabel(self.trans.get("text_size_label", "Text size"))
        zoom_title.setStyleSheet("color:#9bc472; font-weight:bold; font-size:15px; margin-top:6px;")
        self.language_content_layout.addWidget(zoom_title)

        zoom_hint = QLabel(self.trans.get(
            "text_size_hint", "Make everything bigger or smaller."))
        zoom_hint.setStyleSheet("color:#888; font-size:11px;")
        self.language_content_layout.addWidget(zoom_hint)

        zrow = QHBoxLayout()
        zrow.setAlignment(Qt.AlignLeft)
        zrow.setSpacing(8)
        z_btn_style = (
            "QPushButton { background:#1E4E1E; color:#9bc472; border:1px solid #3C5C3C;"
            " border-radius:5px; font-size:18px; font-weight:bold; }"
            "QPushButton:hover { background:#2E6E2E; }"
        )
        minus_btn = QPushButton("A−")
        minus_btn.setFixedSize(48, 40)
        minus_btn.setStyleSheet(z_btn_style)
        minus_btn.clicked.connect(lambda: self._zoom_step(-0.1))
        zrow.addWidget(minus_btn)

        self._zoom_value_label = QLabel(f"{int(round(self.ui_scale * 100))}%")
        self._zoom_value_label.setAlignment(Qt.AlignCenter)
        self._zoom_value_label.setFixedWidth(72)
        self._zoom_value_label.setStyleSheet("color:#FFF; font-size:16px; font-weight:bold;")
        zrow.addWidget(self._zoom_value_label)

        plus_btn = QPushButton("A+")
        plus_btn.setFixedSize(48, 40)
        plus_btn.setStyleSheet(z_btn_style)
        plus_btn.clicked.connect(lambda: self._zoom_step(0.1))
        zrow.addWidget(plus_btn)

        reset_btn = QPushButton(self.trans.get("reset_label", "Reset"))
        reset_btn.setFixedHeight(40)
        reset_btn.setStyleSheet(
            "QPushButton { background:#1E4E1E; color:#9bc472; border:1px solid #3C5C3C;"
            " border-radius:5px; font-size:13px; font-weight:bold; padding:0 12px; }"
            "QPushButton:hover { background:#2E6E2E; }"
        )
        reset_btn.clicked.connect(lambda: self.set_ui_scale(1.0))
        zrow.addWidget(reset_btn)

        self.language_content_layout.addLayout(zrow)

        # Scale the (re)built language panel (incl. the 文字サイズ label) to zoom.
        self._rescale_all_fonts()

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------
    def save_settings(self):
        s = self.settings
        s.setValue("frame_interval", self.frame_interval_spinbox.value())
        s.setValue("processing_duration", self.processing_duration_spinbox.value())
        s.setValue("save_all_frames", self.save_all_checkbox.isChecked())
        s.setValue("resume_processing", self.resume_checkbox.isChecked())
        s.setValue("non_destructive", self.nondestructive_checkbox.isChecked())
        s.setValue("language_index", self.current_language_index)
        s.setValue("ui_scale", self.ui_scale)
        # Save pipeline (includes all per-model options)
        s.setValue("pipeline_steps", json.dumps(self.pipeline_widget.get_pipeline_config()))
        # Save output/export customization
        out_fields, out_formats = self._get_output_config()
        s.setValue("output_fields", json.dumps(out_fields))
        s.setValue("output_formats", json.dumps(out_formats))
        # Save splitter sizes
        s.setValue("v_splitter_sizes", self.v_splitter.sizes())

    def load_settings(self):
        s = self.settings
        # UI zoom (apply before other widgets render so layout settles once)
        try:
            self.ui_scale = float(s.value("ui_scale", 1.0))
        except (TypeError, ValueError):
            self.ui_scale = 1.0
        self.ui_scale = min(self.MAX_UI_SCALE, max(self.MIN_UI_SCALE, self.ui_scale))
        self.apply_ui_scale()
        self.frame_interval_spinbox.setValue(int(s.value("frame_interval", 16)))
        self.processing_duration_spinbox.setValue(int(s.value("processing_duration", 5)))
        self.save_all_checkbox.setChecked(s.value("save_all_frames", "false") == "true")
        self.resume_checkbox.setChecked(s.value("resume_processing", "true") == "true")
        self.nondestructive_checkbox.setChecked(s.value("non_destructive", "false") == "true")
        # Restore output/export customization (fall back to back-compat defaults)
        try:
            of = json.loads(s.value("output_fields", "null"))
        except Exception:
            of = None
        try:
            ofm = json.loads(s.value("output_formats", "null"))
        except Exception:
            ofm = None
        self._apply_output_config(of or wc_output.DEFAULT_FIELDS,
                                  ofm or wc_output.DEFAULT_FORMATS)
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
            self.resume_checkbox.setText(trans.get(
                "resume_checkbox", "Skip already-processed files (resume)"))
            self.nondestructive_checkbox.setText(trans.get(
                "nondestructive_checkbox", "Non-destructive (keep original file names)"))
            self.remove_prefixes_button.setText(trans["remove_prefixes_button"])
            self.remove_prefixes_button.setText(trans["remove_prefixes_button"])

        if hasattr(self, "review_button"):
            self.review_button.setText(trans.get("review_results", "Review Results"))
        if hasattr(self, "settings_button"):
            self.settings_button.setToolTip(trans.get("settings_tooltip", "Settings"))
            self.language_button.setToolTip(trans.get("language_tooltip", "Language & text size"))
            self.player_button.setToolTip(trans.get("player_tooltip", "Video player"))
        if hasattr(self, "folder_viewer"):
            self.folder_viewer.set_hint_text(trans.get("drop_hint", "Drag & drop a folder here"))
        if hasattr(self, "_general_header"):
            self._general_header.setText(trans.get("general_settings", "General Settings"))
        if hasattr(self, "pipeline_widget"):
            self.pipeline_widget.update_translations(trans)

    # ------------------------------------------------------------------
    # UI zoom / text size
    # ------------------------------------------------------------------
    def _sfs(self, px):
        """Scaled font size in px for the current zoom."""
        return max(6, round(px * self.ui_scale))

    def apply_ui_scale(self):
        """Apply the current zoom factor to the whole application font AND to
        EVERY widget whose font size is pinned in a stylesheet (the app font
        can't override those)."""
        pt = max(6, round(self.BASE_FONT_PT * self.ui_scale))
        app = QApplication.instance()
        if app is not None:
            app.setFont(QFont(self.BASE_FONT_FAMILY, pt))
        if hasattr(self, "_zoom_value_label") and self._zoom_value_label is not None:
            self._zoom_value_label.setText(f"{int(round(self.ui_scale * 100))}%")
        self._rescale_all_fonts()

    def _rescale_all_fonts(self, root=None):
        """Truly global zoom: walk the whole widget tree and scale every pinned
        `font-size:Npx` from that widget's cached ORIGINAL stylesheet (so it
        never compounds). Covers headers, dialogs, the 文字サイズ label, pipeline
        internals, tree views — everything, not a hand-picked subset."""
        scale = self.ui_scale
        base = root if root is not None else self
        widgets = base.findChildren(QWidget)
        widgets.append(base)
        for w in widgets:
            try:
                orig = w.property("_wc_orig_ss")
                if orig is None:
                    cur = w.styleSheet()
                    if "font-size" not in cur:
                        continue  # inherits the (scalable) app font
                    w.setProperty("_wc_orig_ss", cur)
                    orig = cur
                w.setStyleSheet(scale_css_fontsize(orig, scale))
            except RuntimeError:
                continue  # C++ widget already deleted

    def _apply_style(self, w, css):
        """Set a widget's stylesheet AND refresh its cached original, so widgets
        that change style at runtime (e.g. Start/Stop) still zoom correctly."""
        w.setProperty("_wc_orig_ss", css)
        w.setStyleSheet(scale_css_fontsize(css, self.ui_scale))

    def set_ui_scale(self, scale):
        self.ui_scale = min(self.MAX_UI_SCALE, max(self.MIN_UI_SCALE, round(scale, 2)))
        self.apply_ui_scale()
        self.settings.setValue("ui_scale", self.ui_scale)

    def _zoom_step(self, delta):
        self.set_ui_scale(self.ui_scale + delta)

    # ------------------------------------------------------------------
    # Panel toggling
    # ------------------------------------------------------------------
    def _show_settings_panel(self):
        """Make the settings panel visible in the horizontal splitter."""
        if not self.settings_panel.isVisible():
            self.settings_panel.show()
            # Open at ~50% of the window width (was capped at 450px ≈ 20%).
            total = self.h_splitter.width()
            settings_w = max(self.settings_panel.minimumWidth(), total // 2)
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
        e = self.entitlements
        # Locked (no license and trial expired) => can't run; steer to purchase.
        if e is None or not e.active:
            self._prompt_upgrade(
                self.trans.get("need_license_to_process",
                               "Activate a license (or start a trial) to process."))
            return
        folder = self.input_dir_line_edit.text()
        if not folder or not os.path.isdir(folder):
            self.log("Please select a valid folder to process")
            return

        # --- Entitlement gating: species classification (Pro) ---
        wants_classify = self.pipeline_widget.has_classifier_step()
        if wants_classify and not e.has(FEATURE_CLASSIFY):
            box = QMessageBox(self)
            box.setStyleSheet(DARK_MSGBOX_STYLE)
            box.setWindowTitle(self.trans.get("upgrade_title", "Upgrade required"))
            box.setText(self.trans.get(
                "classify_locked_msg",
                "Species classification is a Pro feature. This run will detect "
                "animals but not name the species.\n\nContinue with detection "
                "only?"))
            box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            if box.exec_() == QMessageBox.No:
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
        self._last_output_dir = os.path.join(folder, "detection_data")
        self.start_button.setText(self.trans.get("stop_button", "Stop"))
        self._apply_style(self.start_button, STOP_BUTTON_STYLE)
        self.progress_bar.setValue(0)

        out_fields, out_formats = self._get_output_config()

        # --- Entitlement gating: premium export formats (Pro) ---
        out_formats, blocked = e.split_formats(out_formats)
        if blocked:
            self.log(f"Premium export formats skipped (Pro feature): {', '.join(blocked)}")
            QMessageBox.information(
                self, self.trans.get("upgrade_title", "Upgrade required"),
                self.trans.get(
                    "formats_locked_msg",
                    "These export formats are Pro-only and were skipped:\n{fmts}\n\n"
                    "CSV, Excel, JSON and SQLite are included in your plan.").format(
                        fmts=", ".join(blocked)))
            if not out_formats:
                out_formats = ["xlsx"]

        config = {
            "input_folder": folder,
            "every_n_frames": self.frame_interval_spinbox.value(),
            "processing_duration_seconds": self.processing_duration_spinbox.value(),
            "save_all": self.save_all_checkbox.isChecked(),
            "pipeline_steps": self.pipeline_widget.get_pipeline_config(),
            "output_fields": out_fields,
            "output_formats": out_formats,
            "entitlements": e.as_config(),
            "resume": self.resume_checkbox.isChecked(),
            "non_destructive": self.nondestructive_checkbox.isChecked(),
        }

        self.progress_detail_label.setVisible(True)
        self.progress_detail_label.setText(self.trans.get("preparing", "Preparing…"))

        self.processing_thread = ProcessingThread(config)
        self.processing_thread.log_signal.connect(self.log)
        self.processing_thread.progress_signal.connect(self.update_progress)
        self.processing_thread.progress_detail_signal.connect(self._on_progress_detail)
        self.processing_thread.message_signal.connect(self._on_processing_message)
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

    @staticmethod
    def _fmt_duration(seconds):
        seconds = int(max(0, seconds))
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def _on_progress_detail(self, d):
        trans = self.trans
        processed, total = d.get("processed", 0), d.get("total", 0)
        rate = d.get("rate", 0.0)
        parts = [f"{processed}/{total}"]
        if rate > 0:
            parts.append(f"{rate:.1f} {trans.get('items_per_sec', 'files/s')}")
            if processed < total:
                parts.append(f"{trans.get('eta_label', 'ETA')} {self._fmt_duration(d.get('eta', 0))}")
        cur = d.get("current") or ""
        line = "  •  ".join(parts)
        if cur:
            line += f"  —  {cur}"
        self.progress_detail_label.setText(line)

    def _on_processing_message(self, level, text):
        """Surface a processing outcome/problem in a dialog (runs on GUI thread
        via Qt's queued cross-thread signal delivery)."""
        box = QMessageBox(self)
        box.setStyleSheet(DARK_MSGBOX_STYLE)
        if level == "error":
            box.setIcon(QMessageBox.Critical)
            box.setWindowTitle(self.trans.get("error_title", "Error"))
        elif level == "warning":
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle(self.trans.get("warning_title", "Warning"))
        else:
            box.setIcon(QMessageBox.Information)
            box.setWindowTitle(self.trans.get("done_title", "Done"))
        box.setText(text)
        box.addButton(QMessageBox.Ok)
        # Offer shortcuts to the results when there's a folder to show.
        out_dir = getattr(self, "_last_output_dir", None)
        open_btn = review_btn = None
        if out_dir and os.path.isdir(out_dir):
            if os.path.exists(os.path.join(out_dir, "crops.json")):
                review_btn = box.addButton(
                    self.trans.get("review_results", "Review results"),
                    QMessageBox.ActionRole)
            open_btn = box.addButton(
                self.trans.get("open_results_folder", "Open results folder"),
                QMessageBox.ActionRole)
        box.exec_()
        clicked = box.clickedButton()
        if open_btn is not None and clicked is open_btn:
            self._open_folder(out_dir)
        elif review_btn is not None and clicked is review_btn:
            self.open_results_review(out_dir)

    def open_results_review(self, folder=None):
        """Open the crop review + label-correction gallery for a run's output."""
        folder = folder or getattr(self, "_last_output_dir", None)
        if not folder:
            inp = self.input_dir_line_edit.text()
            if inp:
                folder = os.path.join(inp, "detection_data")
        if not folder or not os.path.isdir(folder):
            QMessageBox.information(
                self, self.trans.get("review_title", "Review Results"),
                self.trans.get("no_results_yet", "Process a folder first."))
            return
        import wc_models as models_mod
        species = set()
        for e in models_mod.get_all_models():
            for cn in (e.get("class_names") or []):
                species.add(cn)
        dlg = ResultsGallery(folder, sorted(species), trans=self.trans, parent=self)
        self._rescale_all_fonts(root=dlg)
        dlg.exec_()

    def _open_folder(self, path):
        """Open a folder in the OS file browser (Explorer / Finder / xdg)."""
        if not path or not os.path.isdir(path):
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            self.log(f"Could not open folder: {e}")

    def processing_finished(self):
        self.log("Processing complete")
        self._is_processing = False
        self.start_button.setText(self.trans.get("start_button", "Start"))
        self._apply_style(self.start_button, START_BUTTON_STYLE)
        self.start_button.setEnabled(True)
        if hasattr(self, "progress_detail_label"):
            self.progress_detail_label.setText(
                self.trans.get("processing_complete_short", "Processing complete."))

    # ------------------------------------------------------------------
    # License
    # ------------------------------------------------------------------
    def check_license_and_prompt(self):
        valid, info = verify_license_file(LICENSE_FILE)
        self.license_valid = valid
        self.license_info = info if valid else {}
        if valid:
            self.entitlements = wc_entitlements.from_license_info(info)
        else:
            self.entitlements = self._handle_no_license()
        self._apply_entitlements_to_title()
        self._init_settings_panel()

    def _handle_no_license(self):
        """No license file: run the auto free-trial flow (chosen model)."""
        start = self.settings.value("trial_start_date", "")
        if start:
            days = wc_entitlements.trial_days_left(start)
            if days > 0:
                return wc_entitlements.trial_entitlements(days)
            return self._prompt_trial_expired()      # trial used up
        return self._welcome_trial_or_activate()      # first ever run

    def _welcome_trial_or_activate(self):
        trans = self.trans
        box = QMessageBox(self)
        box.setStyleSheet(DARK_MSGBOX_STYLE)
        box.setWindowTitle(trans.get("welcome_title", "Welcome to WildCatcher"))
        box.setText(trans.get(
            "welcome_msg",
            "Start a free {days}-day trial, or activate a license key you "
            "already have.\n\nThe trial includes species classification and all "
            "export formats, with up to {cap} files per run.").format(
                days=wc_entitlements.TRIAL_DAYS,
                cap=wc_entitlements.TIERS["trial"]["max_images"]))
        trial_btn = box.addButton(
            trans.get("start_trial", "Start free trial"), QMessageBox.AcceptRole)
        lic_btn = box.addButton(
            trans.get("activate_button", "Activate license"), QMessageBox.ActionRole)
        box.exec_()
        if box.clickedButton() is lic_btn:
            self.show_license_dialog(error=None)
            v, i = verify_license_file(LICENSE_FILE)
            if v:
                self.license_valid = True
                self.license_info = i
                return wc_entitlements.from_license_info(i)
        # Default / trial chosen: begin the trial now.
        self.settings.setValue("trial_start_date", wc_entitlements.today_iso())
        return wc_entitlements.trial_entitlements(wc_entitlements.TRIAL_DAYS)

    def _prompt_trial_expired(self):
        trans = self.trans
        box = QMessageBox(self)
        box.setStyleSheet(DARK_MSGBOX_STYLE)
        box.setWindowTitle(trans.get("trial_ended_title", "Trial ended"))
        box.setText(trans.get(
            "trial_ended_msg",
            "Your free trial has ended. Activate a license to keep using "
            "WildCatcher."))
        act = box.addButton(trans.get("activate_button", "Activate license"),
                            QMessageBox.AcceptRole)
        box.addButton(trans.get("close_button", "Close"), QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is act:
            self.show_license_dialog(error=None)
            v, i = verify_license_file(LICENSE_FILE)
            if v:
                self.license_valid = True
                self.license_info = i
                return wc_entitlements.from_license_info(i)
        return wc_entitlements.locked_entitlements()

    def _recompute_entitlements(self):
        """Re-read the license/trial state after an activation attempt."""
        valid, info = verify_license_file(LICENSE_FILE)
        self.license_valid = valid
        self.license_info = info if valid else {}
        if valid:
            self.entitlements = wc_entitlements.from_license_info(info)
        else:
            start = self.settings.value("trial_start_date", "")
            days = wc_entitlements.trial_days_left(start) if start else 0
            self.entitlements = (wc_entitlements.trial_entitlements(days)
                                 if days > 0 else wc_entitlements.locked_entitlements())
        self._apply_entitlements_to_title()
        self._init_settings_panel()

    def _open_license_manager(self):
        self.show_license_dialog(error=None)
        QTimer.singleShot(0, self._recompute_entitlements)

    def _prompt_upgrade(self, message):
        trans = self.trans
        box = QMessageBox(self)
        box.setStyleSheet(DARK_MSGBOX_STYLE)
        box.setWindowTitle(trans.get("upgrade_title", "Upgrade required"))
        box.setText(message)
        act = box.addButton(trans.get("activate_button", "Activate license"),
                            QMessageBox.AcceptRole)
        box.addButton(trans.get("close_button", "Close"), QMessageBox.RejectRole)
        box.exec_()
        if box.clickedButton() is act:
            self._open_license_manager()

    def _apply_entitlements_to_title(self):
        base = f"{wc_version.APP_NAME} {wc_version.APP_VERSION}"
        e = self.entitlements
        if e and e.is_trial and e.active:
            base += f"  —  {self.trans.get('trial_label', 'Trial')}: " \
                    f"{e.trial_days_left} {self.trans.get('days_left', 'days left')}"
        elif e and not e.active:
            base += f"  —  {self.trans.get('inactive_label', 'Not activated')}"
        elif e and not self.license_valid:
            pass
        elif e:
            base += f"  —  {e.label}"
        self.setWindowTitle(base)

    def show_license_dialog(self, error=None):
        trans = self.trans
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(trans.get("license_required", "License Required"))
        dlg.setModal(True)
        dlg.setMinimumWidth(460)
        layout = QVBoxLayout()

        lbl = QLabel(trans.get("license_required_dialog", "WildCatcher License Required"))
        lbl.setStyleSheet("font-size:18px; font-weight:bold;")
        layout.addWidget(lbl)

        step1 = QLabel(trans.get(
            "license_step1",
            "1. Send this Device ID to your vendor to get a license key:"))
        step1.setWordWrap(True)
        layout.addWidget(step1)

        fp = get_device_fingerprint()
        fp_row = QHBoxLayout()
        fp_edit = QLineEdit()
        fp_edit.setReadOnly(True)
        fp_edit.setText(fp)
        fp_edit.setStyleSheet("background:#3C3C3C; color:#FFF; font-size:15px;"
                              " padding:6px; font-family:Consolas,monospace;")
        fp_row.addWidget(fp_edit, 1)
        copy_btn = QPushButton(trans.get("copy_button", "Copy"))
        copy_btn.setStyleSheet(IMPORT_BUTTON_STYLE)
        copy_btn.clicked.connect(lambda: self._copy_device_id(fp, copy_btn))
        fp_row.addWidget(copy_btn)
        layout.addLayout(fp_row)

        step2 = QLabel(trans.get(
            "license_step2", "2. Paste the license key you received below:"))
        step2.setWordWrap(True)
        step2.setStyleSheet("margin-top:8px;")
        layout.addWidget(step2)

        key_edit = QTextEdit()
        key_edit.setPlaceholderText("WC-XXXXXX-XXXXXX-…")
        key_edit.setFixedHeight(90)
        key_edit.setStyleSheet("background:#2E2E2E; color:#FFF; font-size:13px;"
                               " font-family:Consolas,monospace;")
        layout.addWidget(key_edit)

        err_lbl = QLabel(error or "")
        err_lbl.setStyleSheet("color:#FF6B6B;")
        err_lbl.setWordWrap(True)
        err_lbl.setVisible(bool(error))
        layout.addWidget(err_lbl)

        activate_btn = QPushButton(trans.get("activate_button", "Activate"))
        activate_btn.setStyleSheet(IMPORT_BUTTON_STYLE)
        activate_btn.clicked.connect(
            lambda: self._activate_license_key(dlg, key_edit.toPlainText(), err_lbl))
        layout.addWidget(activate_btn)

        file_btn = QPushButton(trans.get("import_from_file", "Import from file (.wcl)…"))
        file_btn.setStyleSheet(
            "QPushButton { background:transparent; color:#9bc472; border:none;"
            " text-decoration:underline; font-size:12px; }")
        file_btn.clicked.connect(lambda: self._import_license_file(dlg, err_lbl))
        layout.addWidget(file_btn)

        dlg.setLayout(layout)
        self._rescale_all_fonts(root=dlg)
        return dlg.exec_()

    def _copy_device_id(self, fp, btn):
        QApplication.clipboard().setText(fp)
        btn.setText(self.trans.get("copied_button", "Copied!"))

    def _activate_license_key(self, parent_dialog, key_text, err_lbl):
        trans = self.trans
        key_text = (key_text or "").strip()
        if not key_text:
            err_lbl.setText(trans.get("paste_key_prompt", "Please paste a license key first."))
            err_lbl.setVisible(True)
            return
        valid, info = save_license_key(key_text)
        if valid:
            self.license_valid = True
            self.license_info = info
            self.entitlements = wc_entitlements.from_license_info(info)
            self._apply_entitlements_to_title()
            QMessageBox.information(
                self, trans.get("activate_button", "Activate"),
                trans.get("license_imported_success", "License activated. Thank you!"))
            self._init_settings_panel()
            parent_dialog.accept()
        else:
            err_lbl.setText(str(info))
            err_lbl.setVisible(True)

    def _import_license_file(self, parent_dialog, err_lbl):
        trans = self.trans
        f, _ = QFileDialog.getOpenFileName(
            self, trans.get("select_license", "Select License"),
            "", "License Files (*.wcl);;All Files (*)")
        if not f:
            return
        try:
            v, i = verify_license_file(f)
            if v:
                dest = os.path.join(os.path.dirname(sys.argv[0]), LICENSE_FILE)
                if os.path.abspath(f) != os.path.abspath(dest):
                    shutil.copy(f, dest)
                self.license_valid = True
                self.license_info = i
                self.entitlements = wc_entitlements.from_license_info(i)
                self._apply_entitlements_to_title()
                QMessageBox.information(
                    self, trans.get("import_from_file", "Import"),
                    trans.get("license_imported_success", "License activated. Thank you!"))
                self._init_settings_panel()
                parent_dialog.accept()
            else:
                err_lbl.setText(str(i))
                err_lbl.setVisible(True)
        except Exception as e:
            err_lbl.setText(str(e))
            err_lbl.setVisible(True)

    # ------------------------------------------------------------------
    # Misc actions
    # ------------------------------------------------------------------
    def open_video_player(self):
        if not (self.entitlements and self.entitlements.active):
            self._prompt_upgrade(self.trans.get(
                "license_required_for_video", "License required"))
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

    # ------------------------------------------------------------------
    # About / EULA / Updates / Diagnostics
    # ------------------------------------------------------------------
    def show_about(self):
        trans = self.trans
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(trans.get("about_title", "About WildCatcher"))
        dlg.setModal(True)
        dlg.setMinimumWidth(420)
        lay = QVBoxLayout()

        logo = QLabel()
        logo.setPixmap(QPixmap(resource_path("assets/app_icon.ico")).scaled(
            64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setAlignment(Qt.AlignCenter)
        lay.addWidget(logo)

        title = QLabel(f"{wc_version.APP_NAME}")
        title.setStyleSheet("font-size:22px; font-weight:bold; color:#9bc472;")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)

        ver = QLabel(f"{trans.get('version_label', 'Version')} {wc_version.APP_VERSION}")
        ver.setAlignment(Qt.AlignCenter)
        ver.setStyleSheet("color:#CCC;")
        lay.addWidget(ver)

        meta = QLabel(
            f"© {wc_version.APP_PUBLISHER}<br>"
            f"<a style='color:#9bc472;' href='{wc_version.APP_WEBSITE}'>{wc_version.APP_WEBSITE}</a><br>"
            f"{trans.get('support_label', 'Support:')} {wc_version.SUPPORT_EMAIL}")
        meta.setOpenExternalLinks(True)
        meta.setAlignment(Qt.AlignCenter)
        meta.setStyleSheet("color:#AAA; font-size:12px;")
        lay.addWidget(meta)

        row = QHBoxLayout()
        upd = QPushButton(trans.get("check_updates", "Check for updates"))
        upd.setStyleSheet(IMPORT_BUTTON_STYLE)
        upd.clicked.connect(lambda: self.check_for_updates(manual=True))
        row.addWidget(upd)
        diag = QPushButton(trans.get("save_diagnostics", "Save diagnostics"))
        diag.setStyleSheet(BROWSE_BUTTON_STYLE)
        diag.clicked.connect(self.save_diagnostics)
        row.addWidget(diag)
        lay.addLayout(row)

        close = QPushButton(trans.get("close_button", "Close"))
        close.clicked.connect(dlg.accept)
        lay.addWidget(close)

        dlg.setLayout(lay)
        self._rescale_all_fonts(root=dlg)
        dlg.exec_()

    def check_for_updates(self, manual=False):
        """Check GitHub releases for a newer version. `manual`=user-initiated."""
        trans = self.trans
        title = trans.get("updates_title", "Updates")
        try:
            import requests
            r = requests.get(wc_version.UPDATE_API_URL, timeout=8,
                             headers={"Accept": "application/vnd.github+json"})
            if r.status_code == 404:
                # No published GitHub Release yet (repo uses tags only / private).
                # Nothing newer to offer -> treat as up to date.
                if manual:
                    QMessageBox.information(self, title, trans.get(
                        "up_to_date", "You're on the latest version ({cur}).").format(
                            cur=wc_version.APP_VERSION))
                return
            if r.status_code != 200:
                if manual:
                    QMessageBox.information(self, title, trans.get(
                        "update_check_failed", "Could not check for updates right now."))
                return
            data = r.json()
            tag = data.get("tag_name", "")
            if wc_version.is_newer(tag, wc_version.APP_VERSION):
                box = QMessageBox(self)
                box.setStyleSheet(DARK_MSGBOX_STYLE)
                box.setWindowTitle(trans.get("update_available", "Update available"))
                box.setText(trans.get(
                    "update_available_msg",
                    "A new version ({new}) is available.\nYou have {cur}.").format(
                        new=tag, cur=wc_version.APP_VERSION))
                box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
                dl = box.button(QMessageBox.Ok)
                dl.setText(trans.get("download_button", "Download"))
                if box.exec_() == QMessageBox.Ok:
                    import webbrowser
                    webbrowser.open(data.get("html_url") or wc_version.RELEASES_URL)
            elif manual:
                QMessageBox.information(self, title, trans.get(
                    "up_to_date", "You're on the latest version ({cur}).").format(
                        cur=wc_version.APP_VERSION))
        except Exception as e:
            logging.getLogger("update").info("update check failed: %s", e)
            if manual:
                QMessageBox.information(self, title, trans.get(
                    "update_check_failed", "Could not check for updates right now."))

    def _maybe_check_updates_on_start(self):
        """Silent update check at most once per day (non-blocking)."""
        if self.settings.value("last_update_check", "") == wc_entitlements.today_iso():
            return
        self.settings.setValue("last_update_check", wc_entitlements.today_iso())
        self._update_thread = UpdateCheckThread()
        self._update_thread.update_found.connect(self._on_update_available)
        self._update_thread.start()

    def _on_update_available(self, tag, url):
        trans = self.trans
        box = QMessageBox(self)
        box.setStyleSheet(DARK_MSGBOX_STYLE)
        box.setWindowTitle(trans.get("update_available", "Update available"))
        box.setText(trans.get(
            "update_available_msg",
            "A new version ({new}) is available.\nYou have {cur}.").format(
                new=tag, cur=wc_version.APP_VERSION))
        box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        box.button(QMessageBox.Ok).setText(trans.get("download_button", "Download"))
        if box.exec_() == QMessageBox.Ok:
            import webbrowser
            webbrowser.open(url)

    def save_diagnostics(self):
        trans = self.trans
        default = os.path.join(
            os.path.expanduser("~"),
            f"wildcatcher_diagnostics_{wc_version.APP_VERSION}.zip")
        path, _ = QFileDialog.getSaveFileName(
            self, trans.get("save_diagnostics", "Save diagnostics"),
            default, "Zip Archive (*.zip)")
        if not path:
            return
        try:
            extra = {
                "license_valid": self.license_valid,
                "licensee": self.license_info.get("licensee") if isinstance(self.license_info, dict) else None,
                "device_id": get_device_fingerprint(),
                "language": self.language,
                "ui_scale": self.ui_scale,
            }
            wc_logging.save_diagnostics_zip(path, extra=extra)
            QMessageBox.information(
                self, trans.get("save_diagnostics", "Save diagnostics"),
                trans.get("diagnostics_saved", "Diagnostics saved to:\n{path}").format(path=path))
        except Exception as e:
            QMessageBox.critical(self, trans.get("error_title", "Error"), str(e))

    def maybe_show_eula(self):
        """Show the EULA on first run (or after its version changes). Returns
        True if accepted (or already accepted), False if the user declined."""
        accepted_ver = self.settings.value("eula_accepted_version", "")
        if accepted_ver == wc_version.APP_VERSION:
            return True
        trans = self.trans
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(trans.get("eula_title", "License Agreement"))
        dlg.setModal(True)
        dlg.setMinimumSize(560, 460)
        lay = QVBoxLayout()
        head = QLabel(trans.get("eula_title", "License Agreement"))
        head.setStyleSheet("font-size:18px; font-weight:bold;")
        lay.addWidget(head)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(EULA_TEXT.format(
            app=wc_version.APP_NAME, publisher=wc_version.APP_PUBLISHER,
            support=wc_version.SUPPORT_EMAIL))
        lay.addWidget(text)
        btns = QHBoxLayout()
        decline = QPushButton(trans.get("decline_button", "Decline"))
        decline.clicked.connect(dlg.reject)
        accept = QPushButton(trans.get("accept_button", "I Agree"))
        accept.setStyleSheet(IMPORT_BUTTON_STYLE)
        accept.clicked.connect(dlg.accept)
        btns.addWidget(decline)
        btns.addStretch()
        btns.addWidget(accept)
        lay.addLayout(btns)
        dlg.setLayout(lay)
        self._rescale_all_fonts(root=dlg)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.settings.setValue("eula_accepted_version", wc_version.APP_VERSION)
            return True
        return False

    def maybe_show_onboarding(self):
        """First-run wizard: logo + live language picker + 3 orientation pages."""
        if self.settings.value("onboarding_done_version", "") == wc_version.APP_VERSION:
            return
        page_keys = [("ob1_title", "ob1_body"), ("ob2_title", "ob2_body"),
                     ("ob3_title", "ob3_body")]
        dlg = QtWidgets.QDialog(self)
        dlg.setModal(True)
        dlg.setMinimumSize(560, 430)
        dlg.setWindowIcon(QIcon(resource_path("assets/app_icon.ico")))
        lay = QVBoxLayout(dlg)

        # --- Header: logo + name + language flags ---
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(resource_path("assets/app_icon.ico")).scaled(
            40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        header.addWidget(logo)
        name_lbl = QLabel(wc_version.APP_NAME)
        name_lbl.setStyleSheet("font-size:18px; font-weight:bold; color:#9bc472;")
        header.addWidget(name_lbl)
        header.addStretch()
        for i, code in enumerate(LANGUAGE_CODES):
            fb = QPushButton()
            fb.setIcon(QIcon(resource_path(f"assets/flags/{code}.ico")))
            fb.setIconSize(QSize(26, 26))
            fb.setFixedSize(34, 30)
            fb.setToolTip(LANGUAGES[i])
            fb.setStyleSheet("QPushButton { border:none; }"
                             "QPushButton:hover { background:#9bc472; border-radius:4px; }")
            fb.clicked.connect(lambda _, idx=i: on_lang(idx))
            header.addWidget(fb)
        lay.addLayout(header)

        # --- Pages ---
        stack = QStackedWidget()
        page_labels = []
        for tkey, bkey in page_keys:
            page = QWidget()
            pl = QVBoxLayout(page)
            t = QLabel()
            t.setStyleSheet("font-size:20px; font-weight:bold; color:#9bc472;")
            b = QLabel()
            b.setWordWrap(True)
            b.setStyleSheet("font-size:13px; color:#DDD;")
            pl.addWidget(t)
            pl.addWidget(b)
            pl.addStretch()
            page_labels.append((t, b, tkey, bkey))
            stack.addWidget(page)
        lay.addWidget(stack, 1)

        nav = QHBoxLayout()
        skip = QPushButton()
        step_lbl = QLabel()
        step_lbl.setStyleSheet("color:#888;")
        back = QPushButton()
        nxt = QPushButton()
        nxt.setStyleSheet(IMPORT_BUTTON_STYLE)
        nav.addWidget(skip)
        nav.addWidget(step_lbl)
        nav.addStretch()
        nav.addWidget(back)
        nav.addWidget(nxt)
        lay.addLayout(nav)

        def update_nav():
            i = stack.currentIndex()
            back.setEnabled(i > 0)
            step_lbl.setText(f"{i + 1} / {len(page_keys)}")
            nxt.setText(self.trans.get("finish_button", "Finish")
                        if i == len(page_keys) - 1 else self.trans.get("next_button", "Next"))

        def retranslate():
            tr = self.trans
            dlg.setWindowTitle(tr.get("welcome_title", "Welcome to WildCatcher"))
            for (t, b, tk, bk) in page_labels:
                t.setText(tr.get(tk, ""))
                b.setText(tr.get(bk, ""))
            skip.setText(tr.get("skip_button", "Skip"))
            back.setText(tr.get("back_button", "Back"))
            update_nav()

        def on_lang(idx):
            self.set_language_by_index(idx)
            retranslate()
            self._rescale_all_fonts(root=dlg)

        def go_next():
            i = stack.currentIndex()
            if i == len(page_keys) - 1:
                dlg.accept()
            else:
                stack.setCurrentIndex(i + 1)
                update_nav()

        def go_back():
            i = stack.currentIndex()
            if i > 0:
                stack.setCurrentIndex(i - 1)
                update_nav()

        skip.clicked.connect(dlg.accept)
        nxt.clicked.connect(go_next)
        back.clicked.connect(go_back)
        retranslate()
        self._rescale_all_fonts(root=dlg)
        dlg.exec_()
        self.settings.setValue("onboarding_done_version", wc_version.APP_VERSION)

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
def _make_splash():
    """A lightweight programmatic splash (no asset dependency)."""
    from PyQt5.QtWidgets import QSplashScreen
    from PyQt5.QtGui import QPainter
    pix = QPixmap(460, 260)
    pix.fill(QColor("#0b1c0a"))
    p = QPainter(pix)
    icon = QPixmap(resource_path("assets/app_icon.ico"))
    if not icon.isNull():
        icon = icon.scaled(88, 88, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawPixmap((460 - icon.width()) // 2, 44, icon)
    p.setPen(QColor("#9bc472"))
    p.setFont(QFont("Segoe UI Variable", 26, QFont.Bold))
    p.drawText(pix.rect().adjusted(0, 150, 0, 0), Qt.AlignHCenter | Qt.AlignTop,
               wc_version.APP_NAME)
    p.setPen(QColor("#AAAAAA"))
    p.setFont(QFont("Segoe UI Variable", 11))
    p.drawText(pix.rect().adjusted(0, 200, 0, -18), Qt.AlignHCenter | Qt.AlignTop,
               f"v{wc_version.APP_VERSION}   •   loading…")
    p.end()
    return QSplashScreen(pix)


if __name__ == "__main__":
    wc_logging.setup_logging()

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
    app.setStyleSheet(GLOBAL_MESSAGEBOX_STYLE + TOOLTIP_STYLE)

    # Show a splash while the (heavy) window + models initialize.
    splash = _make_splash()
    splash.show()
    app.processEvents()

    # Surface uncaught crashes in a dialog + write them to the log.
    def _on_crash(exc_type, exc, tb):
        try:
            QMessageBox.critical(
                None, "WildCatcher — Unexpected Error",
                f"{exc_type.__name__}: {exc}\n\n"
                "The error was written to the log. Use About → Save diagnostics "
                "to send it to support.")
        except Exception:
            pass
    wc_logging.install_excepthook(_on_crash)

    window = VideoDetectionApp()
    window.show()
    splash.finish(window)
    sys.exit(app.exec_())
