# Issuing WildCatcher licenses

How to turn a client's **Device ID** into a **license key** you send them.
Keys are device‑locked and carry a tier + expiry. They work **only** on the
machine whose Device ID you used.

## One‑time setup (already done)

- The secret signing key lives at **`vendor_private_key.pem`** in the repo root.
  It is **git‑ignored** — never commit, email, or share it. Anyone with it can
  mint licenses. **Back it up somewhere safe.** If it is ever lost, every issued
  key stops being reproducible and you must re‑issue with a new key pair
  (`python tools/generate_keypair.py`, then paste the printed public key into
  `wc_license.PUBLIC_KEY_PEM`).

## The flow

1. **Client sends you their Device ID.** In WildCatcher they click the logo (or
   Settings → *Upgrade / Activate*) and copy the **Device ID** shown (16 chars,
   e.g. `edeb774924684070`). It never changes for that PC.
2. **You generate a key** (GUI or command line — below).
3. **You send them the key string** (starts with `WC-…`).
4. **Client pastes it** into the same dialog → *Activate*. Done.

---

## Option A — GUI (easiest)

```
python tools/license_gui.py
```

1. Paste the client's **Device ID**.
2. Enter the **licensee / company name** (shown in their app).
3. Pick a **Tier**: `pro`, `basic`, or `trial`.
4. Expiry: leave **Perpetual** ticked, or untick and pick a date.
5. (Optional) set **Max images/run** to override the tier default.
6. Click **Generate license key**.
7. Click **Copy key** (send just the key) or **Copy email** (a ready‑to‑send
   message with activation steps) and email it to the client.

## Option B — Command line

```
python tools/generate_license.py --device-id <THEIR_ID> --licensee "Acme Co." --tier pro --expiry never
```

Common variants:

| Goal | Command tail |
|------|--------------|
| Perpetual Pro | `--tier pro --expiry never` |
| 1‑year Pro | `--tier pro --days 365` |
| Basic, fixed date | `--tier basic --expiry 2026-12-31` |
| 30‑day trial key | `--tier trial --days 30` |
| Custom volume cap | `--tier basic --max-images 5000` |

It prints the key; copy the `WC-…` line to the client.

---

## What the tiers unlock

| | Detection | Species classification | Premium exports* | Volume / run |
|---|:---:|:---:|:---:|:---:|
| **Trial** (auto, no key) | ✅ | ✅ | ✅ | 200 files, 14 days |
| **Basic** | ✅ | ❌ | ❌ | 2000 files |
| **Pro** | ✅ | ✅ | ✅ | Unlimited |

\* Premium exports = PDF report + ecosystem formats (MegaDetector JSON, Wildlife
Insights, Timelapse). CSV / Excel / JSON / SQLite are always available.

Tiers are defined in **`wc_entitlements.py`** (`TIERS`) — edit there to change
what Basic vs Pro include, or the trial length/cap.

## Notes

- Keys with **no tier** (any you issued before tiers existed) default to **Pro**,
  so nobody gets downgraded by an app update.
- A key only validates on the Device ID it was made for. If a client changes
  computers, they send you the **new** Device ID and you issue a new key.
- Clients can also start the **auto free trial** with no key at all — good for
  letting prospects try before they contact you.
