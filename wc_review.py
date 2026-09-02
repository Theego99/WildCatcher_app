"""In-app results review gallery + label correction.

Reads detection_data/crops.json (written by wc_processing), shows each crop as a
thumbnail with its species, and lets the user fix wrong labels. Saving renames
the crop files, updates crops.json, and logs to corrections.csv.
"""
import os
import json
import csv
from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QImageReader
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QGridLayout, QMessageBox, QFrame,
)

from wc_widgets import NoScrollComboBox

_UNLABELED = "(unlabeled)"
MAX_CELLS = 200  # cap rendered thumbnails; use the filter to narrow further


class _CropCell(QFrame):
    def __init__(self, crop, img_path, species_options, trans):
        super().__init__()
        self.crop = crop
        self.setStyleSheet("QFrame { background:#1E2E1E; border:1px solid #3C5C3C;"
                           " border-radius:6px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        thumb = QLabel()
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setFixedSize(124, 124)
        # Decode scaled (low memory even for big crops / many images).
        reader = QImageReader(img_path)
        reader.setAutoTransform(True)
        sz = reader.size()
        if sz.isValid() and (sz.width() > 124 or sz.height() > 124):
            sz.scale(124, 124, Qt.KeepAspectRatio)
            reader.setScaledSize(sz)
        image = reader.read()
        if not image.isNull():
            thumb.setPixmap(QPixmap.fromImage(image))
        else:
            thumb.setText(trans.get("missing_crop", "(missing)"))
            thumb.setStyleSheet("color:#888;")
        lay.addWidget(thumb, alignment=Qt.AlignCenter)

        self.combo = NoScrollComboBox()
        cur = crop.get("species") or _UNLABELED
        opts = list(species_options)
        if cur not in opts and cur != _UNLABELED:
            opts.insert(0, cur)
        self.combo.addItems([_UNLABELED] + opts)
        self.combo.setCurrentText(cur)
        self.combo.setStyleSheet("QComboBox { background:#2A2A3A; color:#DDD;"
                                 " border:1px solid #555; font-size:12px; padding:2px; }")
        lay.addWidget(self.combo)

        conf = crop.get("species_conf")
        if conf is None:
            conf = crop.get("det_conf")
        cl = QLabel(f"{trans.get('conf_short', 'conf')}: {conf:.0%}"
                    if isinstance(conf, (int, float)) else "")
        cl.setStyleSheet("color:#888; font-size:10px;")
        lay.addWidget(cl)

    @property
    def new_species(self):
        t = self.combo.currentText()
        return None if t == _UNLABELED else t

    @property
    def changed(self):
        return (self.crop.get("species") or None) != self.new_species


class ResultsGallery(QDialog):
    def __init__(self, detection_dir, species_options, trans=None, parent=None):
        super().__init__(parent)
        self.detection_dir = detection_dir
        self.species_options = sorted(set(species_options or []))
        self.trans = trans or {}
        self.setWindowTitle(self.trans.get("review_title", "Review Results"))
        self.setStyleSheet("background:#112424; color:#EEE;")
        self.resize(920, 650)
        self.crops = self._load()
        self.cells = []
        self._build()
        self._render()

    def _load(self):
        try:
            with open(os.path.join(self.detection_dir, "crops.json"), encoding="utf-8") as f:
                return json.load(f).get("crops", [])
        except Exception:
            return []

    def _build(self):
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel(self.trans.get("filter_species", "Species:")))
        self.filter_combo = NoScrollComboBox()
        self.filter_combo.addItems([self.trans.get("all", "All")]
                                   + self.species_options + [_UNLABELED])
        self.filter_combo.currentIndexChanged.connect(self._render)
        bar.addWidget(self.filter_combo)
        bar.addWidget(QLabel(self.trans.get("sort_by", "Sort:")))
        self.sort_combo = NoScrollComboBox()
        self.sort_combo.addItems([
            self.trans.get("sort_conf_low", "Confidence: low first"),
            self.trans.get("sort_conf_high", "Confidence: high first"),
            self.trans.get("sort_file", "File order"),
        ])
        self.sort_combo.currentIndexChanged.connect(self._render)
        bar.addWidget(self.sort_combo)
        bar.addStretch()
        self.count_lbl = QLabel()
        bar.addWidget(self.count_lbl)
        lay.addLayout(bar)

        if not self.crops:
            note = QLabel(self.trans.get(
                "no_crops", "No reviewable detections found in this folder.\n"
                "(Crops are saved during processing.)"))
            note.setStyleSheet("color:#888; padding:20px;")
            note.setAlignment(Qt.AlignCenter)
            lay.addWidget(note, 1)
        else:
            self.scroll = QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setStyleSheet("QScrollArea { border:none; }")
            self.grid_host = QWidget()
            self.grid = QGridLayout(self.grid_host)
            self.grid.setSpacing(8)
            self.scroll.setWidget(self.grid_host)
            lay.addWidget(self.scroll, 1)

        brow = QHBoxLayout()
        brow.addStretch()
        save = QPushButton(self.trans.get("save_corrections", "Save corrections"))
        save.clicked.connect(self._save)
        save.setStyleSheet("QPushButton { background:#1E4E1E; color:#9bc472;"
                           " border:1px solid #3C5C3C; border-radius:5px; padding:6px 14px; }"
                           "QPushButton:hover { background:#2E6E2E; }")
        close = QPushButton(self.trans.get("close_button", "Close"))
        close.clicked.connect(self.accept)
        brow.addWidget(save)
        brow.addWidget(close)
        lay.addLayout(brow)

    @staticmethod
    def _conf(c):
        v = c.get("species_conf")
        if v is None:
            v = c.get("det_conf")
        return v if isinstance(v, (int, float)) else 0.0

    def _filtered(self):
        fsp = self.filter_combo.currentText()
        allt = self.trans.get("all", "All")
        out = [c for c in self.crops
               if fsp == allt or (c.get("species") or _UNLABELED) == fsp]
        mode = self.sort_combo.currentIndex()
        if mode == 0:          # low confidence first -> likely mislabels on top
            out.sort(key=self._conf)
        elif mode == 1:        # high confidence first
            out.sort(key=self._conf, reverse=True)
        # mode 2: file order (as loaded)
        return out

    def _render(self):
        if not self.crops:
            return
        for cell in self.cells:
            cell.setParent(None)
            cell.deleteLater()
        self.cells = []
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        flt = self._filtered()
        shown = flt[:MAX_CELLS]
        cols = 5
        for i, c in enumerate(shown):
            try:
                img = os.path.join(self.detection_dir, c.get("path", c.get("crop", "")))
                cell = _CropCell(c, img, self.species_options, self.trans)
            except Exception:
                continue  # one bad crop must never crash the gallery
            self.cells.append(cell)
            self.grid.addWidget(cell, i // cols, i % cols)
        if len(flt) > MAX_CELLS:
            extra = ("  (" + self.trans.get("showing", "showing") + f" {len(shown)} "
                     + self.trans.get("of", "of") + f" {len(flt)}; "
                     + self.trans.get("narrow_filter", "filter by species to see more") + ")")
        else:
            extra = ""
        self.count_lbl.setText(f"{len(flt)} {self.trans.get('crops_label', 'crops')}{extra}")

    def _save(self):
        changed = [c for c in self.cells if c.changed]
        if not changed:
            QMessageBox.information(self, self.trans.get("review_title", "Review"),
                                    self.trans.get("no_changes", "No changes to save."))
            return
        corr_path = os.path.join(self.detection_dir, "corrections.csv")
        exists = os.path.exists(corr_path)
        n = 0
        with open(corr_path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if not exists:
                w.writerow(["timestamp", "crop", "old_species", "new_species"])
            for cell in changed:
                c = cell.crop
                old = c.get("species")
                new = cell.new_species
                relpath = c.get("path", c.get("crop", ""))
                d, fn = os.path.dirname(relpath), os.path.basename(relpath)
                stem = fn[len(old) + 1:] if old and fn.startswith(old + "_") else fn
                newfn = f"{new}_{stem}" if new else stem
                newrel = (d + "/" + newfn) if d else newfn
                absold = os.path.join(self.detection_dir, relpath)
                absnew = os.path.join(self.detection_dir, newrel)
                try:
                    if os.path.exists(absold) and absold != absnew and not os.path.exists(absnew):
                        os.rename(absold, absnew)
                    c["species"] = new
                    c["crop"] = os.path.basename(newrel)
                    c["path"] = newrel
                    w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                relpath, old or "", new or ""])
                    n += 1
                except Exception:
                    continue
        try:
            with open(os.path.join(self.detection_dir, "crops.json"), "w", encoding="utf-8") as f:
                json.dump({"crops": self.crops}, f, ensure_ascii=False)
        except Exception:
            pass
        QMessageBox.information(
            self, self.trans.get("review_title", "Review"),
            self.trans.get("corrections_saved",
                           "Saved {n} correction(s); crops re-labeled.").format(n=n))
        self._render()
