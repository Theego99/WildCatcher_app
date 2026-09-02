"""WildCatcher application metadata + version helpers.

Single source of truth for the app version, publisher and update source.
Edit APP_VERSION here for each release (and installer.iss's MyAppVersion,
which does not read from here -- bump both).
"""
import re

APP_NAME = "WildCatcher"
APP_VERSION = "2.1.2"
APP_PUBLISHER = "WildCatcher"          # TODO: set to your legal/company name

# Auto-update: the app queries this GitHub repo's latest release. Works with the
# existing GitHub Actions release pipeline (no extra hosting needed).
GITHUB_OWNER = "Theego99"
GITHUB_REPO = "WildCatcher_app"
UPDATE_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def version_tuple(v):
    """Parse '2.1.0', 'v2.1.0-beta', or a release tag like 'win-v2.1.2' /
    'mac-v2.1.0' -> (2, 1, 0). Non-numeric parts ignored.

    Release tags carry a platform prefix (this repo tags Windows releases
    'win-vX.Y.Z') that a bare .lstrip("vV") does not remove -- that left
    version_tuple("win-v2.1.2") silently parsing to (0, 0, 0), so every
    prefixed tag ever compared as NOT newer than the running app. Skip to
    the first digit instead of assuming the prefix is only "v".
    """
    v = str(v or "").strip()
    m = re.search(r"\d", v)
    v = v[m.start():] if m else ""
    # cut off any pre-release/build suffix (e.g. '-beta', '+build')
    for sep in ("-", "+", " "):
        if sep in v:
            v = v.split(sep, 1)[0]
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer(remote, local=APP_VERSION):
    """True if `remote` version string is strictly newer than `local`."""
    return version_tuple(remote) > version_tuple(local)
