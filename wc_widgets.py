"""
WildCatcher custom widgets.

FolderDropViewer — drag-and-drop folder viewer with mini file explorer.
PipelineStepWidget — context-aware step: detector shows include_human/animal,
                     classifier shows per-class delete/include options.
ModelPipelineWidget — model management + sequential pipeline configuration.
"""
import os

from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeView, QHeaderView, QAbstractItemView, QFileDialog,
    QFrame, QDoubleSpinBox, QCheckBox, QComboBox, QScrollArea,
    QSizePolicy, QMessageBox, QLineEdit,
)
from PyQt5.QtWidgets import QFileSystemModel

import wc_models as models_mod


# =========================================================================
# SCROLL-PROOF COMBO BOX  (Issue #1 fix)
# =========================================================================
class NoScrollComboBox(QComboBox):
    """QComboBox that ignores mouse wheel events to prevent
    accidental model changes while scrolling the settings panel."""

    def wheelEvent(self, event):
        # Eat the event — do not change selection on scroll
        event.ignore()


# =========================================================================
# FOLDER DROP VIEWER
# =========================================================================
class FolderDropViewer(QWidget):
    """Drag-and-drop area that doubles as a mini file explorer."""
    folder_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._current_path = ""
        self._root_path = ""
        self._hint_text = "Drag & drop a folder here"

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)

        self._hint_label = QLabel(self._hint_text)
        self._hint_label.setAlignment(Qt.AlignCenter)
        self._apply_hint_style(False)
        layout.addWidget(self._hint_label)

        self._nav_bar = QWidget()
        nav = QHBoxLayout()
        nav.setContentsMargins(0, 4, 0, 4)
        nav.setSpacing(6)
        self._nav_bar.setLayout(nav)

        btn_style = (
            "QPushButton { font-size:14px; color:#CCC; background:#333;"
            " border:1px solid #555; border-radius:4px; }"
            "QPushButton:hover { background:#444; }"
        )
        self._back_btn = QPushButton("◀")
        self._back_btn.setFixedSize(28, 28)
        self._back_btn.setStyleSheet(btn_style)
        self._back_btn.clicked.connect(self._navigate_up)
        nav.addWidget(self._back_btn)

        self._home_btn = QPushButton("⌂")
        self._home_btn.setFixedSize(28, 28)
        self._home_btn.setStyleSheet(btn_style)
        self._home_btn.clicked.connect(self._navigate_root)
        nav.addWidget(self._home_btn)

        self._path_label = QLabel()
        self._path_label.setStyleSheet("font-size:13px; color:#AAA; padding-left:4px;")
        nav.addWidget(self._path_label, 1)
        layout.addWidget(self._nav_bar)
        self._nav_bar.hide()

        self._tree = QTreeView()
        self._tree.setStyleSheet("""
            QTreeView { background:#1A1A1A; color:#DDD; border:1px solid #333; border-radius:4px; font-size:13px; }
            QTreeView::item { padding:3px 0; }
            QTreeView::item:selected { background:#3C3C3C; color:#FFF; }
            QTreeView::item:hover { background:#2E2E2E; }
            QHeaderView::section { background:#2A2A2A; color:#AAA; border:none; border-right:1px solid #333; padding:4px 8px; font-size:12px; }
        """)
        self._tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._tree.setSortingEnabled(True)
        self._tree.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self._tree)
        self._tree.hide()

        self._fs_model = QFileSystemModel()
        self._fs_model.setReadOnly(True)
        self._tree.setModel(self._fs_model)
        self.setMinimumHeight(100)

    def set_hint_text(self, text):
        self._hint_text = text
        self._hint_label.setText(text)

    def set_folder(self, path):
        if not path or not os.path.isdir(path):
            return
        self._current_path = os.path.normpath(path)
        self._root_path = self._current_path
        self._fs_model.setRootPath(self._current_path)
        self._tree.setRootIndex(self._fs_model.index(self._current_path))
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, self._fs_model.columnCount()):
            if col == 1:
                self._tree.setColumnWidth(col, 80)
            elif col == 3:
                self._tree.setColumnWidth(col, 140)
            else:
                self._tree.setColumnHidden(col, True)
        self._path_label.setText(self._current_path)
        self._hint_label.hide()
        self._nav_bar.show()
        self._tree.show()

    def _navigate_to(self, path):
        self._current_path = os.path.normpath(path)
        self._tree.setRootIndex(self._fs_model.index(self._current_path))
        self._path_label.setText(self._current_path)

    def _navigate_up(self):
        parent = os.path.dirname(self._current_path)
        if parent and parent != self._current_path:
            self._navigate_to(parent)

    def _navigate_root(self):
        if self._root_path:
            self._navigate_to(self._root_path)
            self.folder_selected.emit(self._root_path)

    def _on_double_click(self, index):
        path = self._fs_model.filePath(index)
        if os.path.isdir(path):
            self._navigate_to(path)

    def _apply_hint_style(self, active):
        color = "#9bc472" if active else "#777"
        border_color = "#9bc472" if active else "#555"
        bg = "#1A2A1A" if active else "#1A1A1A"
        self._hint_label.setStyleSheet(
            f"QLabel {{ color:{color}; font-size:15px; font-style:italic;"
            f" border:2px dashed {border_color}; border-radius:8px;"
            f" background:{bg}; padding:20px; }}"
        )

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._apply_hint_style(True)

    def dragLeaveEvent(self, event):
        self._apply_hint_style(False)

    def dropEvent(self, event):
        self._apply_hint_style(False)
        urls = event.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if os.path.isfile(path):
            path = os.path.dirname(path)
        if os.path.isdir(path):
            self.set_folder(path)
            self.folder_selected.emit(path)


# =========================================================================
# PIPELINE STEP WIDGET  (context-aware: detector vs classifier)
# =========================================================================
_CB_STYLE_RED = "color:#FF6B6B; font-size:12px; border:none;"
_CB_STYLE_GREEN = "color:#9bc472; font-size:12px; border:none;"
_CB_STYLE_BLUE = "color:#6B9FD4; font-size:12px; border:none;"
_LBL_STYLE = "color:#AAA; font-size:12px; border:none;"
_SPIN_STYLE = (
    "QDoubleSpinBox { background:#2A2A3A; color:#DDD; border:1px solid #555;"
    " border-radius:3px; font-size:12px; }"
)
_COMBO_STYLE = (
    "QComboBox { background:#2A2A3A; color:#DDD; border:1px solid #555;"
    " border-radius:3px; padding:3px 6px; font-size:13px; }"
)


class PipelineStepWidget(QFrame):
    """
    A single step in the processing pipeline.
    Both detector and classifier use the same per-class grid:
      - Detector classes: animal, human, empty
      - Classifier classes: from model's class_names
    Each class has: Include checkbox + Delete original checkbox
    """
    removed = pyqtSignal(object)

    # Detector pseudo-classes (always these three)
    DETECTOR_CLASSES = ["animal", "human", "empty"]

    def __init__(self, trans=None, parent=None):
        super().__init__(parent)
        self.trans = trans or {}
        self._class_widgets = {}
        self._current_model_type = None
        self._current_model_id = None

        self.setStyleSheet(
            "QFrame#stepFrame { background:#1E1E2E; border:1px solid #3C3C5C;"
            " border-radius:6px; padding:6px; margin:2px 0; }"
        )
        self.setObjectName("stepFrame")

        self._main_layout = QVBoxLayout()
        self._main_layout.setContentsMargins(8, 6, 8, 6)
        self._main_layout.setSpacing(4)
        self.setLayout(self._main_layout)

        # --- Row 1: model selector + remove ---
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        self._model_label = QLabel(self.trans.get("step_model", "Model:"))
        self._model_label.setStyleSheet(_LBL_STYLE)
        row1.addWidget(self._model_label)

        self.model_combo = NoScrollComboBox()
        self.model_combo.setStyleSheet(_COMBO_STYLE)
        self.model_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        row1.addWidget(self.model_combo, 1)

        remove_btn = QPushButton(self.trans.get("remove_step", "✕"))
        remove_btn.setFixedSize(26, 26)
        remove_btn.setStyleSheet(
            "QPushButton { background:#5C2020; color:#FBB; border:none;"
            " border-radius:3px; padding:2px 8px; font-size:12px; }"
            "QPushButton:hover { background:#7C3030; }"
        )
        remove_btn.clicked.connect(lambda: self.removed.emit(self))
        row1.addWidget(remove_btn)
        self._main_layout.addLayout(row1)

        # --- Row 2: confidence (only visible for detector steps) ---
        self._conf_row = QWidget()
        self._conf_row.setStyleSheet("border:none;")
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(8)
        self._conf_row.setLayout(row2)

        self._conf_label = QLabel(self.trans.get("step_confidence", "Confidence:"))
        self._conf_label.setStyleSheet(_LBL_STYLE)
        row2.addWidget(self._conf_label)

        self.confidence_spin = QDoubleSpinBox()
        self.confidence_spin.setRange(0.0, 1.0)
        self.confidence_spin.setSingleStep(0.05)
        self.confidence_spin.setValue(0.4)
        self.confidence_spin.setFixedWidth(70)
        self.confidence_spin.setStyleSheet(_SPIN_STYLE)
        row2.addWidget(self.confidence_spin)
        row2.addStretch()
        self._main_layout.addWidget(self._conf_row)

        # --- Per-class options container (unified for detector + classifier) ---
        self._cls_container = QWidget()
        cls_lay = QVBoxLayout()
        cls_lay.setContentsMargins(4, 4, 4, 4)
        cls_lay.setSpacing(2)
        self._cls_container.setLayout(cls_lay)

        self._cls_header = QLabel(
            self.trans.get("per_class_options", "Per-class options:"))
        self._cls_header.setStyleSheet("color:#AAA; font-size:12px; font-weight:bold; border:none;")
        cls_lay.addWidget(self._cls_header)

        self._cls_options_layout = QVBoxLayout()
        self._cls_options_layout.setContentsMargins(8, 0, 0, 0)
        self._cls_options_layout.setSpacing(1)
        cls_lay.addLayout(self._cls_options_layout)

        # --- "Set class names" row (hidden unless needed) ---
        self._set_classes_row = QWidget()
        self._set_classes_row.setStyleSheet("border:none;")
        scr = QHBoxLayout()
        scr.setContentsMargins(0, 4, 0, 4)
        scr.setSpacing(6)
        self._set_classes_row.setLayout(scr)

        self._class_names_input = QLineEdit()
        self._class_names_input.setPlaceholderText(
            self.trans.get("class_names_placeholder", "e.g. deer, rest"))
        self._class_names_input.setStyleSheet(
            "QLineEdit { background:#2A2A3A; color:#DDD; border:1px solid #555;"
            " border-radius:3px; padding:3px 6px; font-size:12px; }")
        scr.addWidget(self._class_names_input, 1)

        self._set_classes_btn = QPushButton(self.trans.get("set_classes_btn", "Set Classes"))
        self._set_classes_btn.setStyleSheet(
            "QPushButton { background:#1E4E1E; color:#9bc472; border:1px solid #3C5C3C;"
            " border-radius:3px; padding:3px 10px; font-size:12px; }"
            "QPushButton:hover { background:#2E6E2E; }")
        self._set_classes_btn.clicked.connect(self._on_set_class_names)
        scr.addWidget(self._set_classes_btn)

        cls_lay.addWidget(self._set_classes_row)
        self._set_classes_row.hide()

        self._main_layout.addWidget(self._cls_container)
        self._cls_container.hide()

        self.refresh_models()

    def update_translations(self, trans):
        """Update all translatable labels in this step widget."""
        self.trans = trans
        self._model_label.setText(trans.get("step_model", "Model:"))
        self._conf_label.setText(trans.get("step_confidence", "Confidence:"))
        self._cls_header.setText(trans.get("per_class_options", "Per-class options:"))
        self._class_names_input.setPlaceholderText(
            trans.get("class_names_placeholder", "e.g. deer, rest"))
        self._set_classes_btn.setText(trans.get("set_classes_btn", "Set Classes"))
        # Rebuild per-class grid to update Include / Delete / Min conf labels
        if self._class_widgets:
            class_names = list(self._class_widgets.keys())
            self._rebuild_class_options_list(class_names)

    def _on_model_changed(self, index):
        """Swap visible options based on the selected model's type."""
        if index < 0:
            return
        model_id = self.model_combo.itemData(index)
        entry = self._find_entry(model_id)
        if entry is None:
            return

        mtype = entry.get("type", "")
        self._current_model_type = mtype
        self._current_model_id = model_id
        self._cls_container.show()

        # Confidence row: only for detectors (classifiers use per-class min conf)
        if mtype == "detector":
            self._conf_row.show()
        else:
            self._conf_row.hide()

        if mtype == "detector":
            self._rebuild_class_options_list(self.DETECTOR_CLASSES)
            self._set_classes_row.hide()
        elif mtype == "classifier":
            class_names = entry.get("class_names") or []
            if class_names:
                self._rebuild_class_options_list(class_names)
                self._set_classes_row.hide()
            else:
                # No class names — show input to set them
                self._clear_class_grid()
                num_hint = ""
                path = models_mod.get_model_path(entry)
                if os.path.isfile(path):
                    info = models_mod._probe_checkpoint(path)
                    nc = info.get("num_classes")
                    if nc is not None:
                        expected = 2 if nc == 1 else nc
                        num_hint = " " + self.trans.get(
                            "class_names_expected", "({n} class names expected)"
                        ).format(n=expected)
                no_msg = self.trans.get("no_class_info_msg",
                                        "No class information available")
                below_msg = self.trans.get("enter_class_names_below",
                                           "Enter class names below:")
                no_lbl = QLabel(f"{no_msg}{num_hint}.\n{below_msg}")
                no_lbl.setStyleSheet("color:#FF6B6B; font-size:11px; border:none;")
                no_lbl.setWordWrap(True)
                self._cls_options_layout.addWidget(no_lbl)
                self._set_classes_row.show()
        else:
            self._cls_container.hide()

    def _on_set_class_names(self):
        """User manually enters class names for a model without them."""
        text = self._class_names_input.text().strip()
        if not text:
            return
        names = [c.strip() for c in text.split(",") if c.strip()]
        if not names:
            return

        try:
            ok = models_mod.update_model_class_names(self._current_model_id, names)
            if ok:
                # Refresh entry and rebuild grid
                entry = self._find_entry(self._current_model_id)
                if entry:
                    self._rebuild_class_options_list(names)
                    self._set_classes_row.hide()
                    self._class_names_input.clear()
        except ValueError as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", str(e))

    def _clear_class_grid(self):
        """Remove all widgets from the per-class grid."""
        while self._cls_options_layout.count():
            item = self._cls_options_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._class_widgets = {}

    def _rebuild_class_options_list(self, class_names):
        """Build per-class checkboxes + min confidence for a list of class names."""
        old_state = {}
        for cn, ws in self._class_widgets.items():
            old_state[cn] = {
                "delete": ws["delete"].isChecked(),
                "include": ws["include"].isChecked(),
                "min_conf": ws["min_conf"].value() if "min_conf" in ws else 0.0,
            }

        self._clear_class_grid()

        is_classifier = (self._current_model_type == "classifier")

        for cn in class_names:
            row = QWidget()
            row.setStyleSheet("border:none;")
            rl = QHBoxLayout()
            rl.setContentsMargins(0, 1, 0, 1)
            rl.setSpacing(6)
            row.setLayout(rl)

            nl = QLabel(f"{cn}:")
            nl.setFixedWidth(100)
            nl.setStyleSheet("font-size:12px; color:#DDD; border:none;")
            rl.addWidget(nl)

            icb = QCheckBox(self.trans.get("include_short", "Include"))
            icb.setChecked(True)
            icb.setStyleSheet(_CB_STYLE_GREEN)
            rl.addWidget(icb)

            dcb = QCheckBox(self.trans.get("delete_original_short", "Delete orig"))
            dcb.setStyleSheet(_CB_STYLE_RED)
            rl.addWidget(dcb)

            # Per-class min confidence (only for classifier steps)
            mc_spin = QDoubleSpinBox()
            mc_spin.setRange(0.0, 1.0)
            mc_spin.setSingleStep(0.05)
            mc_spin.setValue(0.0)
            mc_spin.setFixedWidth(60)
            mc_spin.setStyleSheet(_SPIN_STYLE)
            if is_classifier:
                mc_lbl = QLabel(self.trans.get("min_confidence_short", "Min conf."))
                mc_lbl.setStyleSheet("font-size:11px; color:#6B9FD4; border:none;")
                rl.addWidget(mc_lbl)
                rl.addWidget(mc_spin)
            else:
                mc_spin.hide()

            rl.addStretch()
            self._cls_options_layout.addWidget(row)

            # Restore old state if available
            if cn in old_state:
                dcb.setChecked(old_state[cn]["delete"])
                icb.setChecked(old_state[cn]["include"])
                mc_spin.setValue(old_state[cn].get("min_conf", 0.0))
            elif cn == "empty":
                # Default for "empty": don't include, do delete
                icb.setChecked(False)
                dcb.setChecked(False)

            self._class_widgets[cn] = {"delete": dcb, "include": icb, "min_conf": mc_spin}

    def _find_entry(self, model_id):
        for e in models_mod.get_all_models():
            if e["id"] == model_id:
                return e
        return None

    def refresh_models(self):
        """Reload available models into the combo box."""
        old_id = None
        if self.model_combo.currentIndex() >= 0:
            old_id = self.model_combo.itemData(self.model_combo.currentIndex())

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for entry in models_mod.get_all_models():
            tag = "[D]" if entry["type"] == "detector" else "[C]"
            label = f"{entry['name']}  {tag}"
            self.model_combo.addItem(label, entry["id"])
        self.model_combo.blockSignals(False)

        if old_id:
            for i in range(self.model_combo.count()):
                if self.model_combo.itemData(i) == old_id:
                    self.model_combo.setCurrentIndex(i)
                    return
        self._on_model_changed(self.model_combo.currentIndex())

    def get_step_config(self):
        """Return the full step config dict — unified per_class for both types."""
        idx = self.model_combo.currentIndex()
        model_id = self.model_combo.itemData(idx) if idx >= 0 else ""

        per_class = {}
        for cn, ws in self._class_widgets.items():
            per_class[cn] = {
                "include": ws["include"].isChecked(),
                "delete_original": ws["delete"].isChecked(),
                "min_confidence": ws["min_conf"].value() if "min_conf" in ws else 0.0,
            }

        return {
            "model_id": model_id,
            "confidence": self.confidence_spin.value(),
            "per_class": per_class,
        }

    def set_step_config(self, cfg):
        """Restore from a config dict."""
        mid = cfg.get("model_id", "")
        for i in range(self.model_combo.count()):
            if self.model_combo.itemData(i) == mid:
                self.model_combo.setCurrentIndex(i)
                break

        self.confidence_spin.setValue(cfg.get("confidence", 0.4))

        # --- Backward-compat: migrate old detector flags to per_class ---
        per_class = cfg.get("per_class", {})
        if not per_class and cfg.get("include_animal") is not None:
            per_class = {
                "animal": {
                    "include": cfg.get("include_animal", True),
                    "delete_original": False,
                },
                "human": {
                    "include": cfg.get("include_human", True),
                    "delete_original": False,
                },
                "empty": {
                    "include": False,
                    "delete_original": cfg.get("delete_no_detection", False),
                },
            }

        # --- Backward-compat: migrate old classifier flags ---
        for cn, opts in per_class.items():
            if "include_crop" in opts and "include" not in opts:
                opts["include"] = opts.pop("include_crop")

        for cn, opts in per_class.items():
            if cn in self._class_widgets:
                self._class_widgets[cn]["include"].setChecked(opts.get("include", True))
                self._class_widgets[cn]["delete"].setChecked(opts.get("delete_original", False))
                if "min_conf" in self._class_widgets[cn]:
                    self._class_widgets[cn]["min_conf"].setValue(
                        opts.get("min_confidence", 0.0))


# =========================================================================
# MODEL PIPELINE WIDGET
# =========================================================================
class ModelPipelineWidget(QWidget):
    """
    Combined widget for:
    1. Model management (add/remove user models)
    2. Pipeline configuration (ordered steps with per-step model-type-aware options)
    """

    def __init__(self, trans=None, parent=None):
        super().__init__(parent)
        self.trans = trans or {}
        self._step_widgets = []

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.setLayout(layout)

        # ---- Model management section ----
        self._sec1_label = QLabel(self.trans.get("models_section", "Model Management"))
        self._sec1_label.setStyleSheet("font-size:16px; color:#9bc472; font-weight:bold;")
        layout.addWidget(self._sec1_label)

        self._model_list_label = QLabel()
        self._model_list_label.setStyleSheet("font-size:13px; color:#AAA;")
        self._model_list_label.setWordWrap(True)
        layout.addWidget(self._model_list_label)

        model_btn_row = QHBoxLayout()
        self._add_model_btn = QPushButton(self.trans.get("add_model", "Add Model"))
        self._add_model_btn.setStyleSheet(
            "QPushButton { background:#1E4E1E; color:#9bc472; border:1px solid #3C5C3C;"
            " border-radius:4px; padding:5px 12px; font-size:13px; }"
            "QPushButton:hover { background:#2E6E2E; }"
        )
        self._add_model_btn.clicked.connect(self._on_add_model)
        model_btn_row.addWidget(self._add_model_btn)

        self._remove_model_btn = QPushButton(self.trans.get("remove_model", "Remove"))
        self._remove_model_btn.setStyleSheet(
            "QPushButton { background:#4E1E1E; color:#FBB; border:1px solid #5C3C3C;"
            " border-radius:4px; padding:5px 12px; font-size:13px; }"
            "QPushButton:hover { background:#6E2E2E; }"
        )
        self._remove_model_btn.clicked.connect(self._on_remove_model)
        model_btn_row.addWidget(self._remove_model_btn)
        model_btn_row.addStretch()
        layout.addLayout(model_btn_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#333;")
        layout.addWidget(sep)

        # ---- Pipeline section ----
        self._sec2_label = QLabel(self.trans.get("pipeline_section", "Processing Pipeline"))
        self._sec2_label.setStyleSheet("font-size:16px; color:#6B9FD4; font-weight:bold;")
        layout.addWidget(self._sec2_label)

        self._steps_scroll = QScrollArea()
        self._steps_scroll.setWidgetResizable(True)
        self._steps_scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")
        self._steps_scroll.setMinimumHeight(80)

        self._steps_container = QWidget()
        self._steps_layout = QVBoxLayout()
        self._steps_layout.setContentsMargins(0, 0, 0, 0)
        self._steps_layout.setSpacing(4)
        self._steps_layout.addStretch()
        self._steps_container.setLayout(self._steps_layout)
        self._steps_scroll.setWidget(self._steps_container)
        layout.addWidget(self._steps_scroll)

        self._add_step_btn = QPushButton(self.trans.get("add_step", "Add Step"))
        self._add_step_btn.setStyleSheet(
            "QPushButton { background:#1E2E4E; color:#6B9FD4; border:1px solid #3C4C6C;"
            " border-radius:4px; padding:5px 12px; font-size:13px; }"
            "QPushButton:hover { background:#2E3E6E; }"
        )
        self._add_step_btn.clicked.connect(self.add_step)
        layout.addWidget(self._add_step_btn)

        self._refresh_model_list()

    def _refresh_model_list(self):
        all_m = models_mod.get_all_models()
        if not all_m:
            self._model_list_label.setText(self.trans.get("no_models", "No models registered"))
            return
        lines = []
        builtin_tag = self.trans.get("builtin_tag", "(built-in)")
        cls_suffix = self.trans.get("classes_suffix", "classes")
        for e in all_m:
            tag = "[D]" if e["type"] == "detector" else "[C]"
            builtin = f" {builtin_tag}" if e.get("builtin") else ""
            arch = f" • {e['architecture']}" if e.get("architecture") else ""
            cls_count = f" • {len(e['class_names'])} {cls_suffix}" if e.get("class_names") else ""
            lines.append(f"  {tag} {e['name']}{builtin}{arch}{cls_count}")
        self._model_list_label.setText("\n".join(lines))

    def _on_add_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.trans.get("select_model_file", "Select Model File"),
            "",
            self.trans.get("model_file_filter",
                           "PyTorch Models (*.pt *.pth);;All Files (*)"),
        )
        if not path:
            return

        from PyQt5.QtWidgets import QInputDialog
        types = [
            self.trans.get("classifier", "Classifier"),
            self.trans.get("detector", "Detector"),
        ]
        choice, ok = QInputDialog.getItem(
            self, self.trans.get("model_type", "Type:"),
            self.trans.get("model_type", "Model type:"), types, 0, False,
        )
        if not ok:
            return
        model_type = "classifier" if choice == types[0] else "detector"

        name = os.path.splitext(os.path.basename(path))[0]
        name, ok = QInputDialog.getText(
            self, self.trans.get("model_name", "Name:"),
            self.trans.get("model_name", "Model name:"),
            text=name,
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        def _format_details(entry):
            details = self.trans.get("registered_msg", "Registered: {name}").format(name=name)
            if entry.get("architecture"):
                details += "\n" + self.trans.get(
                    "architecture_msg", "Architecture: {arch}"
                ).format(arch=entry["architecture"])
            if entry.get("class_names"):
                details += "\n" + self.trans.get(
                    "classes_msg", "Classes ({n}): {names}"
                ).format(n=len(entry["class_names"]),
                         names=", ".join(entry["class_names"]))
            return details

        err_title = self.trans.get("error_title", "Error")

        try:
            entry = models_mod.register_model(path, name, model_type)
            QMessageBox.information(
                self, self.trans.get("model_added", "Model Added"),
                _format_details(entry))
            self._refresh_model_list()
            for sw in self._step_widgets:
                sw.refresh_models()
        except ValueError as e:
            err_msg = str(e)
            if "class names" in err_msg.lower():
                from PyQt5.QtWidgets import QInputDialog
                hint = ""
                if "output classes" in err_msg:
                    hint = "\n" + err_msg.split("\n")[0]
                text, ok = QInputDialog.getText(
                    self,
                    self.trans.get("enter_class_names_title", "Enter Class Names"),
                    self.trans.get("auto_detect_failed",
                                   "Could not auto-detect class names from the model.")
                    + hint + "\n\n"
                    + self.trans.get("enter_class_names_prompt",
                                     "Enter class names separated by commas\n"
                                     "(e.g.  deer, rest   or   cat, dog, bird):"),
                )
                if ok and text.strip():
                    manual_names = [c.strip() for c in text.split(",") if c.strip()]
                    if manual_names:
                        try:
                            entry = models_mod.register_model(
                                path, name, model_type,
                                manual_class_names=manual_names,
                            )
                            QMessageBox.information(
                                self, self.trans.get("model_added", "Model Added"),
                                _format_details(entry))
                            self._refresh_model_list()
                            for sw in self._step_widgets:
                                sw.refresh_models()
                        except Exception as e2:
                            QMessageBox.critical(self, err_title, str(e2))
            else:
                QMessageBox.critical(self, err_title, err_msg)
        except Exception as e:
            QMessageBox.critical(self, err_title, str(e))

    def _on_remove_model(self):
        from PyQt5.QtWidgets import QInputDialog
        user_models = models_mod.load_registry()
        if not user_models:
            return
        names = [f"{e['name']} ({e['type']})" for e in user_models]
        choice, ok = QInputDialog.getItem(
            self, self.trans.get("remove_model", "Remove"),
            self.trans.get("model_name", "Name:"), names, 0, False,
        )
        if not ok:
            return
        idx = names.index(choice)
        models_mod.unregister_model(user_models[idx]["id"])
        self._refresh_model_list()
        for sw in self._step_widgets:
            sw.refresh_models()

    def add_step(self, config=None):
        sw = PipelineStepWidget(trans=self.trans, parent=self)
        sw.removed.connect(self._remove_step)
        if config:
            sw.set_step_config(config)
        self._step_widgets.append(sw)
        self._steps_layout.insertWidget(self._steps_layout.count() - 1, sw)

    def _remove_step(self, widget):
        if widget in self._step_widgets:
            self._step_widgets.remove(widget)
            widget.setParent(None)
            widget.deleteLater()

    def get_pipeline_config(self):
        return [sw.get_step_config() for sw in self._step_widgets]

    def set_pipeline_config(self, steps):
        for sw in self._step_widgets[:]:
            self._remove_step(sw)
        for cfg in steps:
            self.add_step(cfg)

    def update_translations(self, trans):
        self.trans = trans
        # Update own labels and buttons
        self._sec1_label.setText(trans.get("models_section", "Model Management"))
        self._sec2_label.setText(trans.get("pipeline_section", "Processing Pipeline"))
        self._add_model_btn.setText(trans.get("add_model", "Add Model"))
        self._remove_model_btn.setText(trans.get("remove_model", "Remove"))
        self._add_step_btn.setText(trans.get("add_step", "Add Step"))
        self._refresh_model_list()
        # Propagate to all pipeline step widgets
        for sw in self._step_widgets:
            sw.update_translations(trans)

    def ensure_default_pipeline(self):
        """If no steps exist, add default steps from whatever models are available."""
        if self._step_widgets:
            return
        all_models = models_mod.get_all_models()
        # Add the first available detector
        for m in all_models:
            if m["type"] == "detector":
                self.add_step({
                    "model_id": m["id"],
                    "confidence": 0.4,
                    "per_class": {
                        "animal": {"include": True, "delete_original": False},
                        "human": {"include": True, "delete_original": False},
                        "empty": {"include": False, "delete_original": False},
                    },
                })
                break
        # Add the first available classifier
        for m in all_models:
            if m["type"] == "classifier":
                self.add_step({
                    "model_id": m["id"],
                    "confidence": 0.5,
                })
                break

    def has_classifier_step(self):
        """Check if at least one classifier step exists in the pipeline."""
        for sw in self._step_widgets:
            cfg = sw.get_step_config()
            entry = sw._find_entry(cfg.get("model_id", ""))
            if entry and entry.get("type") == "classifier":
                return True
        return False
