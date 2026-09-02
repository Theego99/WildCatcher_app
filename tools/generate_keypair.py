#!/usr/bin/env python3
"""
WildCatcher — one-time vendor keypair generator.

Creates the ECDSA P-256 signing keypair used for license keys:
  * writes the SECRET private key to vendor_private_key.pem (gitignored)
  * prints the PUBLIC key PEM to paste into wc_license.PUBLIC_KEY_PEM

Run this ONCE. If you ever regenerate it, every previously issued license key
stops working and must be re-issued. Keep vendor_private_key.pem safe and never
commit or share it.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIVATE_KEY_FILE = os.path.join(_ROOT, "vendor_private_key.pem")

from Crypto.PublicKey import ECC  # noqa: E402


def main():
    if os.path.exists(PRIVATE_KEY_FILE):
        resp = input(f"{PRIVATE_KEY_FILE} already exists. Overwrite? "
                     "This INVALIDATES all issued keys [y/N]: ").strip().lower()
        if resp != "y":
            print("Aborted.")
            return

    key = ECC.generate(curve="P-256")
    with open(PRIVATE_KEY_FILE, "w") as f:
        f.write(key.export_key(format="PEM"))
    try:
        os.chmod(PRIVATE_KEY_FILE, 0o600)
    except Exception:
        pass

    print(f"Private key written to {PRIVATE_KEY_FILE} (keep secret!).\n")
    print("Paste this into wc_license.py as PUBLIC_KEY_PEM:\n")
    print(key.public_key().export_key(format="PEM"))


if __name__ == "__main__":
    main()
