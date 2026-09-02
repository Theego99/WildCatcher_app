"""In-app updater: check a manifest, download, verify, install, relaunch.

Design notes
------------
* The update manifest and the artifacts live in a **separate public repo**
  (see wc_version.RELEASES_REPO). The source repo is private, and an
  unauthenticated client cannot read a private repo's releases -- it just gets
  a 404. Shipping a token in the exe is not an option, so the release channel
  is its own public repo containing only version.json + the built archives.
* The primary check is a plain raw.githubusercontent.com fetch of version.json:
  no API rate limit (60/hr/IP anonymous, which a whole office shares behind one
  NAT), no auth, and it carries a sha256 we can verify. The Releases API is
  only a fallback.
* Installing cannot overwrite the files of the running process, so the swap is
  done by a detached PowerShell helper that waits for us to exit first.
  PowerShell rather than a .bat because install paths routinely contain
  Japanese characters and cmd's codepage handling of those is unreliable --
  the same class of bug that bit cv2 in 2.1.1.
"""
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

from PyQt5.QtCore import QThread, pyqtSignal

import wc_version

log = logging.getLogger("update")

_UA = {"User-Agent": f"{wc_version.APP_NAME}/{wc_version.APP_VERSION}"}

# robocopy uses exit codes 0-7 for "copied//nothing to do"; >=8 is a real error.
_ROBOCOPY_OK = 8


def is_frozen():
    return bool(getattr(sys, "frozen", False))


def install_dir():
    """The directory that would be replaced by an update."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _asset_from_release(data):
    """Pull a Windows archive URL out of a GitHub release payload."""
    for a in data.get("assets") or []:
        name = (a.get("name") or "").lower()
        if name.endswith(".zip") and "windows" in name:
            return a.get("browser_download_url"), a.get("size")
    for a in data.get("assets") or []:
        if (a.get("name") or "").lower().endswith(".zip"):
            return a.get("browser_download_url"), a.get("size")
    return None, None


def fetch_latest(timeout=8):
    """Return {'version', 'url', 'sha256', 'size', 'notes', 'page'} or None.

    None means "could not determine" (offline, blocked, malformed) -- callers
    must not treat that as "up to date".
    """
    import requests

    try:
        r = requests.get(wc_version.UPDATE_MANIFEST_URL, timeout=timeout,
                         headers={**_UA, "Cache-Control": "no-cache"})
        if r.status_code == 200:
            m = r.json()
            win = m.get("windows") or {}
            url = win.get("url")
            if url:
                return {
                    "version": str(m.get("version") or ""),
                    "url": url,
                    "sha256": (win.get("sha256") or "").strip().lower(),
                    "size": int(win.get("size") or 0),
                    "notes": m.get("notes") or "",
                    "page": m.get("page") or wc_version.RELEASES_URL,
                }
        log.info("manifest fetch returned %s", r.status_code)
    except Exception as e:
        log.info("manifest fetch failed: %s", e)

    # Fallback: the Releases API on the same public repo.
    try:
        r = requests.get(wc_version.UPDATE_API_URL, timeout=timeout,
                         headers={**_UA, "Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            log.info("releases API returned %s", r.status_code)
            return None
        data = r.json()
        url, size = _asset_from_release(data)
        if not url:
            return None
        return {
            "version": str(data.get("tag_name") or ""),
            "url": url,
            "sha256": "",
            "size": int(size or 0),
            "notes": data.get("body") or "",
            "page": data.get("html_url") or wc_version.RELEASES_URL,
        }
    except Exception as e:
        log.info("releases API fetch failed: %s", e)
        return None


class UpdateCheckThread(QThread):
    """Background check -- never touch the network from the UI thread."""
    update_found = pyqtSignal(dict)   # only when something newer exists
    checked = pyqtSignal(object)      # always: the info dict, or None on failure

    def run(self):
        info = fetch_latest()
        self.checked.emit(info)
        if info and wc_version.is_newer(info.get("version")):
            self.update_found.emit(info)


class UpdateDownloadThread(QThread):
    """Stream the archive to a temp file, verifying sha256 as we go."""
    progress = pyqtSignal(int, int)   # bytes done, bytes total (0 = unknown)
    done = pyqtSignal(str)            # path to the downloaded archive
    failed = pyqtSignal(str)

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        import requests
        path = os.path.join(
            tempfile.gettempdir(),
            f"{wc_version.APP_NAME}-{self.info.get('version') or 'update'}.zip")
        try:
            with requests.get(self.info["url"], stream=True, timeout=30,
                              headers=_UA) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or
                            self.info.get("size") or 0)
                digest = hashlib.sha256()
                seen = 0
                with open(path, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=1024 * 512):
                        if self._cancel:
                            fh.close()
                            _quiet_remove(path)
                            return
                        if not chunk:
                            continue
                        fh.write(chunk)
                        digest.update(chunk)
                        seen += len(chunk)
                        self.progress.emit(seen, total)
            want = (self.info.get("sha256") or "").lower()
            if want and digest.hexdigest() != want:
                _quiet_remove(path)
                self.failed.emit("checksum mismatch")
                return
            self.done.emit(path)
        except Exception as e:
            _quiet_remove(path)
            log.warning("update download failed: %s", e)
            self.failed.emit(str(e))


def _quiet_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _require_writable(path):
    """Raise unless we can actually create a file in `path`.

    os.access(..., W_OK) only reports the read-only attribute on Windows, not
    the ACL -- it says True for an admin-installed C:\\Program Files\\WildCatcher
    that a standard user cannot write. Probing for real lets the caller fall
    back to the manual download before the app quits, instead of the helper
    silently failing after the window is gone.
    """
    probe = os.path.join(path, ".wc_update_probe")
    try:
        with open(probe, "wb") as fh:
            fh.write(b"1")
    except OSError as e:
        raise PermissionError(f"cannot write to {path}: {e}") from e
    finally:
        _quiet_remove(probe)


def _extract(zip_path, staging):
    """Unpack `zip_path` into `staging` and return the dir holding the exe."""
    if os.path.isdir(staging):
        shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(staging)
    exe = f"{wc_version.APP_NAME}.exe"
    if os.path.isfile(os.path.join(staging, exe)):
        return staging
    # Archives commonly wrap everything in a single top-level folder.
    for root, _dirs, files in os.walk(staging):
        if exe in files:
            return root
    raise RuntimeError(f"{exe} not found in the downloaded archive")


_PS_SCRIPT = r"""
param(
  [int]$ProcId,
  [string]$Source,
  [string]$Dest,
  [string]$Exe,
  [string]$LogFile
)
$ErrorActionPreference = 'Continue'
"WildCatcher updater starting $(Get-Date -Format o)" | Out-File -LiteralPath $LogFile -Encoding utf8

# Wait for the app to exit so its files stop being locked.
try { Wait-Process -Id $ProcId -Timeout 120 -ErrorAction Stop } catch {}
Start-Sleep -Milliseconds 800

# /E (not /MIR): merge over the install, never delete extras. The install dir
# also holds models\, profiles\ and license.wcl -- mirroring would wipe them.
# /IS /IT: copy even when robocopy judges a file "same" or "tweaked". Without
# them it skips on a size+timestamp match and the update silently no-ops.
# Its own log file, in Unicode: robocopy writes OEM codepage, PowerShell writes
# UTF-8, and interleaving them in one file mangles non-ASCII paths.
$rc = Start-Process -FilePath robocopy.exe -ArgumentList @(
    "`"$Source`"", "`"$Dest`"", "/E", "/IS", "/IT", "/R:3", "/W:1",
    "/NFL", "/NDL", "/NP", "/UNILOG:`"$LogFile.robocopy.log`""
) -Wait -PassThru -WindowStyle Hidden
"robocopy exit $($rc.ExitCode)" | Out-File -LiteralPath $LogFile -Append -Encoding utf8

if ($rc.ExitCode -lt 8) {
    Start-Process -FilePath $Exe -WorkingDirectory $Dest
} else {
    "update FAILED - install left untouched" | Out-File -LiteralPath $LogFile -Append -Encoding utf8
    Start-Process -FilePath $Exe -WorkingDirectory $Dest
}
Remove-Item -LiteralPath $Source -Recurse -Force -ErrorAction SilentlyContinue
"""


def stage_and_launch(zip_path, target_dir=None):
    """Unpack the update and hand the swap to a detached helper.

    Returns the helper's log path. The caller must quit the app immediately
    afterwards -- the helper is already waiting on this process to exit.
    """
    target_dir = target_dir or install_dir()
    _require_writable(target_dir)

    staging = os.path.join(tempfile.gettempdir(),
                           f"{wc_version.APP_NAME}_update_stage")
    source = _extract(zip_path, staging)

    script = os.path.join(tempfile.gettempdir(),
                          f"{wc_version.APP_NAME}_update.ps1")
    logfile = os.path.join(tempfile.gettempdir(),
                           f"{wc_version.APP_NAME}_update.log")
    # utf-8-sig: PowerShell 5.1 reads a BOM-less UTF-8 .ps1 as ANSI, which
    # mangles any non-ASCII path we pass through it.
    with open(script, "w", encoding="utf-8-sig") as fh:
        fh.write(_PS_SCRIPT)

    exe = os.path.join(target_dir, f"{wc_version.APP_NAME}.exe")
    creationflags = 0
    if os.name == "nt":
        creationflags = (getattr(subprocess, "DETACHED_PROCESS", 0) |
                         getattr(subprocess, "CREATE_NO_WINDOW", 0))
    subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-File", script,
         "-ProcId", str(os.getpid()),
         "-Source", source, "-Dest", target_dir,
         "-Exe", exe, "-LogFile", logfile],
        creationflags=creationflags, close_fds=True)
    log.info("update helper launched; log at %s", logfile)
    return logfile
