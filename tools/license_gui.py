#!/usr/bin/env python3
"""
WildCatcher — vendor license generator (GUI).

For YOU (the vendor), not clients. Paste a client's Device ID, pick a tier and
expiry, click Generate, then copy the key or the ready-to-send email.

Needs vendor_private_key.pem in the repo root (kept secret, never shipped).
Run:  python tools/license_gui.py
"""
import os
import sys
import json
from datetime import datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from PyQt5.QtWidgets import (  # noqa: E402
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QPlainTextEdit, QDateEdit, QCheckBox, QMessageBox,
    QSpinBox,
)
from PyQt5.QtCore import QDate  # noqa: E402

from Crypto.PublicKey import ECC  # noqa: E402
from Crypto.Signature import DSS  # noqa: E402
from Crypto.Hash import SHA256  # noqa: E402

import wc_license  # noqa: E402
import wc_entitlements  # noqa: E402
import wc_version  # noqa: E402

PRIVATE_KEY_FILE = os.path.join(_ROOT, "vendor_private_key.pem")

EMAIL_TEMPLATE = """Subject: Your {app} license

Hello {licensee},

Thank you for choosing {app}. Here is your license key:

{key}

To activate:
  1. Open {app} and click the logo / Settings to open the license dialog.
  2. Paste the key above and click Activate.

This key is tied to the device you provided ({device}); it will not work on a
different computer. {expiry_line}

Best regards,
{publisher}
{support}
"""


class LicenseGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{wc_version.APP_NAME} — License Generator")
        self.setMinimumWidth(560)
        self._key = None
        self._priv = None
        lay = QVBoxLayout(self)

        lay.addWidget(QLabel("Client Device ID (from the app's license dialog):"))
        self.device = QLineEdit()
        self.device.setPlaceholderText("e.g. 1a2b3c4d5e6f7a8b")
        lay.addWidget(self.device)

        lay.addWidget(QLabel("Licensee / company name:"))
        self.licensee = QLineEdit()
        lay.addWidget(self.licensee)

        row = QHBoxLayout()
        row.addWidget(QLabel("Tier:"))
        self.tier = QComboBox()
        self.tier.addItems(["pro", "basic", "trial"])
        row.addWidget(self.tier)
        row.addWidget(QLabel("Max images/run (0 = tier default):"))
        self.maximg = QSpinBox()
        self.maximg.setRange(0, 1_000_000)
        self.maximg.setSpecialValueText("tier default")
        row.addWidget(self.maximg)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        self.perpetual = QCheckBox("Perpetual (never expires)")
        self.perpetual.setChecked(True)
        self.perpetual.stateChanged.connect(
            lambda s: self.expiry.setEnabled(not self.perpetual.isChecked()))
        row2.addWidget(self.perpetual)
        row2.addWidget(QLabel("Expiry:"))
        self.expiry = QDateEdit()
        self.expiry.setCalendarPopup(True)
        self.expiry.setDate(QDate.currentDate().addYears(1))
        self.expiry.setEnabled(False)
        row2.addWidget(self.expiry)
        lay.addLayout(row2)

        gen = QPushButton("Generate license key")
        gen.clicked.connect(self.generate)
        lay.addWidget(gen)

        lay.addWidget(QLabel("License key:"))
        self.key_out = QPlainTextEdit()
        self.key_out.setReadOnly(True)
        self.key_out.setMaximumHeight(90)
        lay.addWidget(self.key_out)

        krow = QHBoxLayout()
        self.copy_key = QPushButton("Copy key")
        self.copy_key.clicked.connect(lambda: self._copy(self.key_out.toPlainText()))
        krow.addWidget(self.copy_key)
        self.copy_email = QPushButton("Copy email")
        self.copy_email.clicked.connect(lambda: self._copy(self.email_out.toPlainText()))
        krow.addWidget(self.copy_email)
        lay.addLayout(krow)

        lay.addWidget(QLabel("Email to client (editable):"))
        self.email_out = QPlainTextEdit()
        lay.addWidget(self.email_out)

        if not os.path.exists(PRIVATE_KEY_FILE):
            QMessageBox.critical(
                self, "Missing key",
                f"{PRIVATE_KEY_FILE} not found.\nRun tools/generate_keypair.py first.")

    def _load_priv(self):
        if self._priv is None:
            with open(PRIVATE_KEY_FILE) as f:
                self._priv = ECC.import_key(f.read())
        return self._priv

    def _copy(self, text):
        QApplication.clipboard().setText(text or "")

    def generate(self):
        device = self.device.text().strip()
        licensee = self.licensee.text().strip()
        if not device or not licensee:
            QMessageBox.warning(self, "Missing info",
                                "Enter both a Device ID and a licensee name.")
            return
        if self.perpetual.isChecked():
            expiry = "never"
        else:
            expiry = self.expiry.date().toString("yyyy-MM-dd")

        payload = {"l": licensee, "d": device, "x": expiry,
                   "i": datetime.utcnow().strftime("%Y-%m-%d"),
                   "v": wc_license._KEY_VERSION, "tr": self.tier.currentText()}
        if self.maximg.value() > 0:
            payload["mx"] = self.maximg.value()
        pb = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        try:
            sig = DSS.new(self._load_priv(), "fips-186-3").sign(SHA256.new(pb))
            key = wc_license.encode_license_key(pb, sig)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
            return

        self.key_out.setPlainText(key)
        expiry_line = ("This is a perpetual license."
                       if expiry == "never" else f"It is valid until {expiry}.")
        self.email_out.setPlainText(EMAIL_TEMPLATE.format(
            app=wc_version.APP_NAME, licensee=licensee, key=key, device=device,
            expiry_line=expiry_line, publisher=wc_version.APP_PUBLISHER,
            support=wc_version.SUPPORT_EMAIL))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = LicenseGUI()
    w.show()
    sys.exit(app.exec_())
