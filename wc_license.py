"""WildCatcher licensing.

Device-locked license *keys* (short signed strings), replacing the old
distribute-a-whole-file model. Flow:

  1. The app shows the client a stable Device ID (`get_device_fingerprint`).
  2. The client sends that ID to the vendor.
  3. The vendor runs tools/generate_license.py to mint a signed key that embeds
     the licensee, the device ID, and an expiry (期限).
  4. The client pastes the key into the app once; it is verified offline against
     the embedded ECC public key and saved locally (`license.wcl`).

Security notes:
  * Keys are signed with ECDSA P-256 (PyCryptodome). Only the holder of
    `vendor_private_key.pem` can mint valid keys.
  * The Device ID is derived from the Windows MachineGuid (or the platform's
    equivalent stable machine id) — NOT from the MAC address or a drive's
    volume serial, both of which drift over time and caused the old
    "the ID keeps changing" problem.
"""
import os
import sys
import json
import struct
import hashlib
import base64
import platform
import subprocess
from datetime import datetime

from Crypto.PublicKey import ECC
from Crypto.Signature import DSS
from Crypto.Hash import SHA256

# ---------------------------------------------------------------------------
# Vendor public key (verifies license keys). The matching PRIVATE key lives in
# vendor_private_key.pem on the vendor's machine ONLY and must never ship.
# ---------------------------------------------------------------------------
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE3ggclqkLLN99bWENKbSwYsxbjefh
+TOLDlTtRal4m6wBVrU2bVGrHpizBxPRQqaWmIAD5VTBVewg/+lQzeiGFQ==
-----END PUBLIC KEY-----"""

LICENSE_FILE = "license.wcl"

# Bump if the device-id derivation ever changes (invalidates old keys on purpose)
_FINGERPRINT_SALT = "WildCatcher::device::v2"
_KEY_PREFIX = "WC-"
_KEY_VERSION = 1
_B32_ALPHABET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")

# Hide console windows when shelling out on Windows.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


# ---------------------------------------------------------------------------
# Stable machine identity
# ---------------------------------------------------------------------------
def _windows_machine_guid():
    """The most stable per-install identifier on Windows: HKLM MachineGuid.
    Survives reboots, network changes and drive reformats."""
    try:
        import winreg
        access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Cryptography", 0, access) as k:
            val, _ = winreg.QueryValueEx(k, "MachineGuid")
            return str(val).strip()
    except Exception:
        return ""


def _windows_hw_uuid():
    """Fallback: motherboard/system UUID. Try modern CIM first, then wmic."""
    # PowerShell CIM (works even where wmic has been removed on newer Windows)
    for cmd in (
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_ComputerSystemProduct).UUID"],
        ["wmic", "csproduct", "get", "uuid"],
    ):
        try:
            out = subprocess.check_output(
                cmd, stderr=subprocess.DEVNULL, timeout=12,
                creationflags=_NO_WINDOW,
            ).decode(errors="ignore")
            for line in out.splitlines():
                line = line.strip()
                if line and line.upper() != "UUID":
                    return line
        except Exception:
            continue
    return ""


def _macos_platform_uuid():
    try:
        out = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            stderr=subprocess.DEVNULL, timeout=12,
        ).decode(errors="ignore")
        for line in out.splitlines():
            if "IOPlatformUUID" in line:
                return line.split('"')[-2]
    except Exception:
        pass
    return ""


def _stable_machine_id():
    """Return a stable, OS-appropriate machine identifier (best available)."""
    system = platform.system()
    if system == "Windows":
        return _windows_machine_guid() or _windows_hw_uuid()
    if system == "Darwin":
        return _macos_platform_uuid()
    # Linux / other
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path) as f:
                mid = f.read().strip()
                if mid:
                    return mid
        except Exception:
            continue
    return ""


def get_device_fingerprint():
    """Stable 16-char hardware fingerprint used to lock a license to one PC."""
    raw = _stable_machine_id()
    if not raw:
        # Last-resort: hostname (unstable, but better than crashing). A blank
        # device id would make every key "valid", so never return empty.
        raw = platform.node() or "unknown-device"
    digest = hashlib.sha256((_FINGERPRINT_SALT + raw).encode("utf-8")).hexdigest()
    return digest[:16]


# ---------------------------------------------------------------------------
# Key encoding  (payload + ECDSA signature -> friendly base32 string)
# ---------------------------------------------------------------------------
def _group(s, n=6):
    return "-".join(s[i:i + n] for i in range(0, len(s), n))


def encode_license_key(payload_bytes, signature):
    packet = bytes([_KEY_VERSION]) + struct.pack(">H", len(payload_bytes)) + payload_bytes + signature
    b32 = base64.b32encode(packet).decode("ascii").rstrip("=")
    return _KEY_PREFIX + _group(b32)


def _normalize_key(key_str):
    s = (key_str or "").strip()
    if s.upper().startswith(_KEY_PREFIX):
        s = s[len(_KEY_PREFIX):]
    s = "".join(ch for ch in s.upper() if ch in _B32_ALPHABET)
    s += "=" * ((-len(s)) % 8)
    return s


def decode_license_key(key_str):
    """Return (payload_bytes, signature_bytes). Raises ValueError if malformed."""
    packet = base64.b32decode(_normalize_key(key_str))
    if len(packet) < 3:
        raise ValueError("License key too short.")
    version = packet[0]
    if version != _KEY_VERSION:
        raise ValueError(f"Unsupported license key version ({version}).")
    plen = struct.unpack(">H", packet[1:3])[0]
    payload = packet[3:3 + plen]
    signature = packet[3 + plen:]
    if len(payload) != plen or not signature:
        raise ValueError("Corrupted license key.")
    return payload, signature


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def _expand_payload(p):
    """Map the compact on-wire keys to the friendly dict the app displays."""
    return {
        "licensee": p.get("l", ""),
        "device_id": p.get("d", ""),
        "expiry": p.get("x", "never"),
        "issued": p.get("i", ""),
    }


def verify_license_key(key_str):
    """Verify a pasted license key. Returns (is_valid, info_or_error)."""
    try:
        payload_bytes, signature = decode_license_key(key_str)
    except Exception as e:
        return False, f"Invalid license key format: {e}"

    # Signature
    try:
        pubkey = ECC.import_key(PUBLIC_KEY_PEM)
        DSS.new(pubkey, "fips-186-3").verify(SHA256.new(payload_bytes), signature)
    except Exception:
        return False, "License key is not genuine (signature check failed)."

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as e:
        return False, f"Invalid license payload: {e}"

    info = _expand_payload(payload)

    # Expiry (期限)
    expiry = info.get("expiry", "never")
    if expiry and expiry != "never":
        try:
            if datetime.strptime(expiry, "%Y-%m-%d") < datetime.utcnow():
                return False, f"License expired on {expiry}."
        except ValueError:
            return False, "Invalid expiry date in license."

    # Device lock
    device_id = info.get("device_id")
    if not device_id:
        return False, "License is missing a device ID."
    if device_id != "ANY" and device_id != get_device_fingerprint():
        return False, "This license key is for a different computer."

    return True, info


def save_license_key(key_str, path=None):
    """Verify then persist a key locally. Returns (is_valid, info_or_error)."""
    valid, info = verify_license_key(key_str)
    if not valid:
        return valid, info
    if path is None:
        path = _default_license_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"key": key_str.strip()}, f)
    except Exception as e:
        return False, f"Could not save license: {e}"
    return True, info


def _default_license_path():
    base = os.path.dirname(sys.argv[0]) if sys.argv and sys.argv[0] else os.getcwd()
    return os.path.join(base, LICENSE_FILE)


def verify_license_file(path=None):
    """Verify the saved license. Returns (is_valid, info_or_error).

    Reads the new key format ({"key": "..."}). Old signed-file licenses are no
    longer accepted — clients re-activate with a key (Device IDs changed with
    the stable-fingerprint fix, so old files could not match anyway)."""
    if path is None:
        path = LICENSE_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        # Also try alongside the executable (frozen app CWD differs).
        alt = _default_license_path()
        if alt != path and os.path.exists(alt):
            return verify_license_file(alt)
        return False, "No license found."
    except json.JSONDecodeError as e:
        return False, f"Invalid license file: {e}"
    except Exception as e:
        return False, str(e)

    if isinstance(data, dict) and data.get("key"):
        return verify_license_key(data["key"])
    if isinstance(data, dict) and data.get("payload"):
        return False, ("This is an old-format license. Please activate with your "
                       "new license key.")
    return False, "Unrecognized license file."
