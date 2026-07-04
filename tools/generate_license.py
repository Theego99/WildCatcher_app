#!/usr/bin/env python3
"""
WildCatcher — vendor license key generator.

Mint a device-locked, signed license KEY (a short string) to send to a client.
The client gives you their Device ID (shown in the app's license dialog); you
run this and send back the printed key. They paste it into the app once.

Usage
-----
  python tools/generate_license.py \
      --device-id 1a2b3c4d5e6f7a8b \
      --licensee "Acme Wildlife Co." \
      --expiry 2026-12-31

  # or a duration instead of a fixed date:
  python tools/generate_license.py --device-id XXXX --licensee "Foo" --days 365

  # perpetual (no expiry):
  python tools/generate_license.py --device-id XXXX --licensee "Foo" --expiry never

Requires vendor_private_key.pem (kept secret, never committed) next to the repo
root. Create one with tools/generate_keypair.py if you don't have it yet.
"""
import os
import sys
import json
import argparse
from datetime import datetime, timedelta

# Allow running from anywhere.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from Crypto.PublicKey import ECC          # noqa: E402
from Crypto.Signature import DSS          # noqa: E402
from Crypto.Hash import SHA256            # noqa: E402

import wc_license                          # noqa: E402

PRIVATE_KEY_FILE = os.path.join(_ROOT, "vendor_private_key.pem")


def _load_private_key():
    if not os.path.exists(PRIVATE_KEY_FILE):
        sys.exit(f"ERROR: {PRIVATE_KEY_FILE} not found.\n"
                 "Run tools/generate_keypair.py once to create it, then paste "
                 "the printed public key into wc_license.py.")
    with open(PRIVATE_KEY_FILE, "r") as f:
        return ECC.import_key(f.read())


def _resolve_expiry(args):
    if args.days is not None:
        return (datetime.utcnow() + timedelta(days=args.days)).strftime("%Y-%m-%d")
    if args.expiry:
        if args.expiry.lower() == "never":
            return "never"
        # Validate format early.
        datetime.strptime(args.expiry, "%Y-%m-%d")
        return args.expiry
    return "never"


def main():
    ap = argparse.ArgumentParser(description="Generate a WildCatcher license key.")
    ap.add_argument("--device-id", required=True,
                    help="Client's Device ID (from the app's license dialog).")
    ap.add_argument("--licensee", required=True,
                    help="Client / company name shown in the app.")
    ap.add_argument("--expiry", default="never",
                    help="Expiry date YYYY-MM-DD, or 'never' (default).")
    ap.add_argument("--days", type=int, default=None,
                    help="Days from today until expiry (overrides --expiry).")
    args = ap.parse_args()

    device_id = args.device_id.strip()
    expiry = _resolve_expiry(args)
    issued = datetime.utcnow().strftime("%Y-%m-%d")

    # Compact on-wire payload (short keys keep the key string small).
    payload = {"l": args.licensee.strip(), "d": device_id,
               "x": expiry, "i": issued, "v": wc_license._KEY_VERSION}
    payload_bytes = json.dumps(payload, sort_keys=True,
                               separators=(",", ":")).encode("utf-8")

    key = _load_private_key()
    signature = DSS.new(key, "fips-186-3").sign(SHA256.new(payload_bytes))
    license_key = wc_license.encode_license_key(payload_bytes, signature)

    # Self-check: the embedded public key must accept what we just signed,
    # otherwise the private key doesn't match the app's public key.
    pub = ECC.import_key(wc_license.PUBLIC_KEY_PEM)
    try:
        DSS.new(pub, "fips-186-3").verify(SHA256.new(payload_bytes), signature)
    except ValueError:
        sys.exit("ERROR: vendor_private_key.pem does not match the public key in "
                 "wc_license.py. Regenerate the pair with tools/generate_keypair.py "
                 "and update PUBLIC_KEY_PEM.")

    print("=" * 64)
    print("  WildCatcher license key")
    print("=" * 64)
    print(f"  Licensee : {args.licensee}")
    print(f"  Device   : {device_id}")
    print(f"  Expiry   : {expiry}")
    print(f"  Issued   : {issued}")
    print("-" * 64)
    print(license_key)
    print("=" * 64)
    print("Send the client the line above; they paste it into WildCatcher's")
    print("license dialog. It only works on the device with that Device ID.")


if __name__ == "__main__":
    main()
