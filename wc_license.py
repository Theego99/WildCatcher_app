"""WildCatcher license verification."""
import os
import sys
import json
import hashlib
import uuid
import platform
import base64
from datetime import datetime

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

LICENSE_FILE = "license.wcl"


def get_device_fingerprint():
    """Generate a hardware fingerprint for license locking."""
    info = ""
    try:
        if platform.system() == "Windows":
            import subprocess
            uuid_str = subprocess.check_output("wmic csproduct get uuid").decode().split("\n")[1].strip()
            info += uuid_str
        else:
            info += str(uuid.getnode())
    except Exception:
        info += "unknownuuid"
    try:
        info += hex(uuid.getnode())
    except Exception:
        info += "unknownmac"
    try:
        if platform.system() == "Windows":
            import subprocess
            vol = subprocess.check_output("vol", shell=True).decode()
            info += vol.strip().split()[-1]
        elif os.path.exists("/etc/machine-id"):
            with open("/etc/machine-id") as f:
                info += f.read().strip()
    except Exception:
        info += "unknownvol"
    return hashlib.sha256(info.encode()).hexdigest()[:16]


def verify_license_file(path=None):
    """Verify a license file. Returns (is_valid: bool, info_or_error)."""
    if path is None:
        path = LICENSE_FILE
    try:
        with open(path, "r") as f:
            lic = json.load(f)
        # Signature
        data = json.dumps(lic["payload"], sort_keys=True).encode()
        pubkey = RSA.import_key(PUBLIC_KEY_PEM)
        h = SHA256.new(data)
        sig = base64.b64decode(lic["signature"])
        pkcs1_15.new(pubkey).verify(h, sig)
        # Expiry
        expiry = lic["payload"].get("expiry", "never")
        if expiry != "never":
            if datetime.strptime(expiry, "%Y-%m-%d") < datetime.utcnow():
                return False, "License expired."
        # Device lock
        license_fp = lic["payload"].get("device_id")
        if not license_fp:
            return False, "License not valid for this device: missing device ID."
        if license_fp != "ANY" and license_fp != get_device_fingerprint():
            return False, "License not valid for this device."
        return True, lic["payload"]
    except FileNotFoundError:
        return False, "License file not found."
    except json.JSONDecodeError as e:
        return False, f"Invalid license file format: {e}"
    except Exception as e:
        return False, str(e)
