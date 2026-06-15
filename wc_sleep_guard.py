"""
WildCatcher sleep prevention.

Prevents the OS from entering sleep/standby while processing is active.
Supports Windows, macOS, and Linux.
"""
import sys
import subprocess
import logging

_caffeinate_proc = None

# Windows constants
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def prevent_sleep():
    """Call at the START of processing to keep the PC awake."""
    global _caffeinate_proc
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED
            )
            logging.info("Sleep prevention: Windows execution state set.")

        elif sys.platform == "darwin":
            # caffeinate -s prevents system sleep; killed when process exits
            _caffeinate_proc = subprocess.Popen(
                ["caffeinate", "-s"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logging.info("Sleep prevention: caffeinate started (macOS).")

        elif sys.platform.startswith("linux"):
            # Try systemd-inhibit (available on most modern distros)
            _caffeinate_proc = subprocess.Popen(
                [
                    "systemd-inhibit",
                    "--what=idle:sleep",
                    "--who=WildCatcher",
                    "--why=Processing camera trap images",
                    "sleep", "infinity",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logging.info("Sleep prevention: systemd-inhibit started (Linux).")

    except Exception as e:
        logging.warning(f"Sleep prevention failed (non-fatal): {e}")


def allow_sleep():
    """Call at the END of processing to restore normal sleep behavior."""
    global _caffeinate_proc
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            logging.info("Sleep prevention: Windows execution state restored.")

        elif _caffeinate_proc is not None:
            _caffeinate_proc.terminate()
            _caffeinate_proc.wait(timeout=5)
            _caffeinate_proc = None
            logging.info("Sleep prevention: caffeinate/systemd-inhibit stopped.")

    except Exception as e:
        logging.warning(f"Sleep restoration failed (non-fatal): {e}")
