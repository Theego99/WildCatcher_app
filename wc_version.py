"""WildCatcher application metadata + version helpers.

Single source of truth for the app version, publisher and update source.
Edit APP_VERSION here for each release (and the installer/spec read nothing
from here yet, so bump those too — see build.bat / installer.iss).
"""

APP_NAME = "WildCatcher"
APP_VERSION = "2.1.1"
APP_PUBLISHER = "WildCatcher"          # TODO: set to your legal/company name
SUPPORT_EMAIL = "support@wildcatcher.app"  # TODO: set your real support address
APP_WEBSITE = "https://github.com/Theego99/WildCatcher_app"

# Auto-update: the app queries this GitHub repo's latest release. Works with the
# existing GitHub Actions release pipeline (no extra hosting needed).
GITHUB_OWNER = "Theego99"
GITHUB_REPO = "WildCatcher_app"
UPDATE_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"


def version_tuple(v):
    """Parse '2.1.0' or 'v2.1.0-beta' -> (2, 1, 0). Non-numeric parts ignored."""
    v = str(v or "").strip().lstrip("vV")
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
