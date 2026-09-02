"""WildCatcher tier / feature entitlements.

One place that defines what each license tier unlocks, so gating is consistent
across the UI and the processing engine. Business config lives in TIERS below —
edit it to change what Basic vs Pro get.

Model (chosen with the owner):
  * trial : auto free trial (no key). Shows off the premium features so people
            upgrade — full classification + premium exports, but volume-capped
            and time-limited (TRIAL_DAYS).
  * basic : paid entry tier. Detection only, standard exports (CSV/Excel/JSON/
            SQLite), volume-capped.
  * pro   : everything — species classification, premium exports (PDF +
            ecosystem formats), unlimited volume.

Already-issued keys have no "tier" field; they default to `pro` (full access)
so upgrading the app never downgrades an existing customer.
"""
from datetime import datetime, date

FEATURE_CLASSIFY = "classify"            # run classifier models (name species)
FEATURE_EXPORT_PREMIUM = "export_premium"  # PDF + ecosystem export formats

# Export formats that require FEATURE_EXPORT_PREMIUM. Everything else
# (csv, xlsx, json, sqlite) is always allowed.
PREMIUM_FORMATS = {"pdf", "megadetector", "wildlife_insights", "timelapse"}

TRIAL_DAYS = 14

TIERS = {
    "trial": {"label": "Trial", "features": [FEATURE_CLASSIFY, FEATURE_EXPORT_PREMIUM], "max_images": 200},
    "basic": {"label": "Basic", "features": [],                                         "max_images": 2000},
    "pro":   {"label": "Pro",   "features": [FEATURE_CLASSIFY, FEATURE_EXPORT_PREMIUM], "max_images": 0},
}
DEFAULT_TIER = "pro"  # licenses without an explicit tier = full access (back-compat)


class Entitlements:
    def __init__(self, tier="pro", features=None, max_images=0, is_trial=False,
                 active=True, expiry="never", licensee="", trial_days_left=None):
        self.tier = tier
        self.features = set(features or [])
        self.max_images = int(max_images or 0)   # 0 = unlimited
        self.is_trial = is_trial
        self.active = active                     # False => nothing may run
        self.expiry = expiry
        self.licensee = licensee
        self.trial_days_left = trial_days_left

    def has(self, feature):
        return feature in self.features

    @property
    def unlimited(self):
        return self.max_images <= 0

    @property
    def label(self):
        return TIERS.get(self.tier, {}).get("label", self.tier.title())

    def split_formats(self, formats):
        """Return (allowed, blocked) format lists for this tier."""
        if self.has(FEATURE_EXPORT_PREMIUM):
            return list(formats), []
        allowed = [f for f in formats if f not in PREMIUM_FORMATS]
        blocked = [f for f in formats if f in PREMIUM_FORMATS]
        return allowed, blocked

    def as_config(self):
        """Serialisable dict passed to the processing thread."""
        return {"tier": self.tier, "features": sorted(self.features),
                "max_images": self.max_images, "is_trial": self.is_trial,
                "active": self.active}


def from_license_info(info):
    """Build Entitlements from a verified license payload dict."""
    if not isinstance(info, dict):
        info = {}
    tier = (info.get("tier") or DEFAULT_TIER).lower()
    base = TIERS.get(tier, TIERS[DEFAULT_TIER])
    features = info.get("features")
    features = base["features"] if features is None else features
    max_images = info.get("max_images")
    max_images = base["max_images"] if max_images is None else max_images
    return Entitlements(
        tier=tier, features=features, max_images=max_images,
        is_trial=(tier == "trial"), active=True,
        expiry=info.get("expiry", "never"), licensee=info.get("licensee", ""))


def trial_entitlements(days_left):
    base = TIERS["trial"]
    return Entitlements(
        tier="trial", features=base["features"], max_images=base["max_images"],
        is_trial=True, active=days_left > 0, licensee="Trial",
        trial_days_left=days_left)


def locked_entitlements():
    """No license and trial expired: nothing may run until activation."""
    return Entitlements(tier="locked", features=[], max_images=0,
                        is_trial=False, active=False, licensee="")


def from_config(cfg):
    """Rebuild Entitlements from as_config() output (engine side)."""
    if not isinstance(cfg, dict):
        return Entitlements()  # permissive default
    return Entitlements(
        tier=cfg.get("tier", "pro"), features=cfg.get("features", []),
        max_images=cfg.get("max_images", 0), is_trial=cfg.get("is_trial", False),
        active=cfg.get("active", True))


def trial_days_left(start_iso, total_days=TRIAL_DAYS, today=None):
    """Days remaining in a trial that began on start_iso (YYYY-MM-DD)."""
    try:
        start = datetime.strptime(start_iso, "%Y-%m-%d").date()
    except Exception:
        return 0
    today = today or date.today()
    return max(0, total_days - (today - start).days)


def today_iso():
    return date.today().strftime("%Y-%m-%d")
