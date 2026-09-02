"""Central file logging + support diagnostics for WildCatcher.

Writes a rotating log to a per-user data dir (survives reinstalls, not inside
the app folder which may be read-only), installs a crash handler, and can bundle
logs + system info into a single zip the client emails you for support.
"""
import os
import sys
import json
import logging
import platform
import zipfile
from logging.handlers import RotatingFileHandler
from datetime import datetime


def app_data_dir():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    d = os.path.join(base, "WildCatcher")
    os.makedirs(d, exist_ok=True)
    return d


def log_dir():
    d = os.path.join(app_data_dir(), "logs")
    os.makedirs(d, exist_ok=True)
    return d


LOG_FILE = os.path.join(log_dir(), "wildcatcher.log")


def setup_logging(level=logging.INFO):
    """Attach a rotating file handler to the root logger (idempotent)."""
    logger = logging.getLogger()
    logger.setLevel(level)
    for h in logger.handlers:
        if isinstance(h, RotatingFileHandler) and getattr(h, "_wc", False):
            return LOG_FILE
    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    handler._wc = True
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
    logging.getLogger("wildcatcher").info("=== logging started ===")
    return LOG_FILE


def system_info(extra=None):
    info = {
        "app": "WildCatcher",
        "time": datetime.now().isoformat(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version.replace("\n", " "),
        "frozen": bool(getattr(sys, "frozen", False)),
        "cwd": os.getcwd(),
    }
    try:
        import wc_version
        info["version"] = wc_version.APP_VERSION
    except Exception:
        pass
    try:
        import onnxruntime as ort
        info["onnxruntime"] = ort.__version__
        info["ort_providers"] = ort.get_available_providers()
    except Exception as e:
        info["onnxruntime_error"] = str(e)
    if extra:
        info.update(extra)
    return info


def save_diagnostics_zip(dest_path, extra=None):
    """Bundle system info + all logs into a zip. Returns dest_path."""
    with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("system_info.json",
                   json.dumps(system_info(extra), indent=2, default=str))
        d = log_dir()
        for f in sorted(os.listdir(d)):
            if f.startswith("wildcatcher.log"):
                try:
                    z.write(os.path.join(d, f), arcname=f"logs/{f}")
                except Exception:
                    pass
    return dest_path


def install_excepthook(on_crash=None):
    """Log uncaught exceptions; optionally call on_crash(type, exc, tb)."""
    prev = sys.excepthook

    def hook(exc_type, exc, tb):
        logging.getLogger("crash").critical(
            "Uncaught exception", exc_info=(exc_type, exc, tb))
        if on_crash is not None:
            try:
                on_crash(exc_type, exc, tb)
            except Exception:
                pass
        prev(exc_type, exc, tb)

    sys.excepthook = hook
