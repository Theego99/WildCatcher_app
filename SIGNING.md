# Code signing WildCatcher (when you're ready)

The app currently ships **unsigned** (cheapest path). Clients click through a
one-time OS warning — see [CLIENT_INSTALL.md](CLIENT_INSTALL.md). Everything
below is already wired up; enabling signing is just adding credentials — **no
code or build changes**.

## Why sign later
- **Windows:** removes the SmartScreen "unknown publisher" text; the "Windows
  protected your PC" block fades as more clients download.
- **macOS:** removes the "unidentified developer" block entirely (no right-click
  needed).

There is **no free way** to remove these for other people's computers — a
certificate from a trusted authority is required. Cheapest options below.

---

## Windows — Azure Trusted Signing (~$10/month, recommended)

Cheapest real option. Cloud-based, no hardware token.

1. Create an **Azure account** and a **Trusted Signing** resource:
   https://learn.microsoft.com/azure/trusted-signing/quickstart
   - Create a *Trusted Signing Account* and a *Certificate Profile* (Public Trust).
   - Complete **identity validation** (individual or business). This is the part
     that takes a little time.
2. Create an **App Registration** (service principal) with the *Trusted Signing
   Certificate Profile Signer* role on the account.
3. **In CI (GitHub Actions)** — add these repo secrets
   (Settings → Secrets and variables → Actions). The build signs automatically
   once they exist:
   - `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`
   - `AZURE_TS_ENDPOINT`   (e.g. `https://eus.codesigning.azure.net`)
   - `AZURE_TS_ACCOUNT`    (your Trusted Signing account name)
   - `AZURE_TS_PROFILE`    (your certificate profile name)
4. **For local builds** (`build.bat`) — instead, set an env var pointing at a
   metadata json and install the module once:
   ```powershell
   Install-Module -Name TrustedSigning -Scope CurrentUser
   $env:WC_AZURE_METADATA = "C:\path\to\trusted-signing-metadata.json"
   ```
   `sign_windows.ps1` picks it up and signs the exe + installer.

`trusted-signing-metadata.json`:
```json
{ "Endpoint": "https://eus.codesigning.azure.net",
  "CodeSigningAccountName": "your-account",
  "CertificateProfileName": "your-profile" }
```

### Alternative: a traditional PFX / token cert
If you buy an OV/EV cert (comes on a hardware token or cloud HSM), set:
```powershell
$env:WC_SIGN_PFX = "C:\path\to\cert.pfx"; $env:WC_SIGN_PFX_PASSWORD = "..."
# or sign by subject from an installed token:  $env:WC_SIGN_SUBJECT = "Your Company"
```

---

## macOS — Apple Developer ID ($99/year)

The macOS CI currently **ad-hoc signs** (right-click → Open on first launch).
To sign + notarize properly:

1. Join the **Apple Developer Program** ($99/yr) and create a **Developer ID
   Application** certificate; export it as a `.p12`.
2. Add repo secrets: `MACOS_CERT_P12_BASE64`, `MACOS_CERT_PASSWORD`,
   `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD` (app-specific password).
3. Update `.github/workflows/release-macos.yml`: import the cert into a temp
   keychain, `codesign --options runtime --sign "Developer ID Application: …"`,
   then `xcrun notarytool submit … --wait` and `xcrun stapler staple`.
   (Ping me and I'll wire this step when you have the account.)

---

## After enabling
Re-run the build/tag. Verify Windows with:
```powershell
signtool verify /pa /v "installer_output\WildCatcher_v2.1.0_Setup.exe"
```
and macOS with `spctl -a -vv WildCatcher.app` (should say *accepted / Notarized*).
