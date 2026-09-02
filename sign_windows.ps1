<#
  sign_windows.ps1 — sign WildCatcher binaries/installer if a cert is configured.

  Usage:  powershell -ExecutionPolicy Bypass -File sign_windows.ps1 <file> [<file> ...]

  It is a NO-OP (exit 0) when no signing credentials are present, so unsigned
  builds keep working. Configure ONE of these to enable signing:

  A) Azure Trusted Signing (~$10/mo, recommended cheapest):
       $env:WC_AZURE_METADATA = "C:\path\to\trusted-signing-metadata.json"
       # + install the dlib once:  Install-Module -Name TrustedSigning
       # metadata json fields: Endpoint, CodeSigningAccountName, CertificateProfileName
     See SIGNING.md for the 5-minute setup.

  B) A traditional PFX / token cert:
       $env:WC_SIGN_PFX          = "C:\path\to\cert.pfx"
       $env:WC_SIGN_PFX_PASSWORD = "..."           # optional if token
       $env:WC_SIGN_SUBJECT      = "Your Company"  # OR sign by subject from the store
#>
param([Parameter(ValueFromRemainingArguments = $true)] [string[]] $Files)

$ErrorActionPreference = "Stop"
$TIMESTAMP = "http://timestamp.digicert.com"

function Find-SignTool {
    $c = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $roots = @("${env:ProgramFiles(x86)}\Windows Kits\10\bin", "${env:ProgramFiles}\Windows Kits\10\bin")
    foreach ($r in $roots) {
        if (Test-Path $r) {
            $hit = Get-ChildItem $r -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
                   Where-Object { $_.FullName -match 'x64' } | Select-Object -First 1
            if ($hit) { return $hit.FullName }
        }
    }
    return $null
}

if (-not $Files -or $Files.Count -eq 0) { Write-Host "sign_windows: no files given."; exit 0 }

# --- Azure Trusted Signing path ---
if ($env:WC_AZURE_METADATA -and (Test-Path $env:WC_AZURE_METADATA)) {
    if (-not (Get-Module -ListAvailable -Name TrustedSigning)) {
        Write-Host "sign_windows: TrustedSigning module not installed (Install-Module TrustedSigning). Skipping."
        exit 0
    }
    Import-Module TrustedSigning
    foreach ($f in $Files) {
        Write-Host "Signing (Azure Trusted Signing): $f"
        Invoke-TrustedSigning -MetadataFilePath $env:WC_AZURE_METADATA -Files $f `
            -FileDigest SHA256 -TimestampRfc3161 $TIMESTAMP -TimestampDigest SHA256
    }
    Write-Host "sign_windows: Azure signing complete."
    exit 0
}

# --- PFX / store-subject path ---
$signtool = Find-SignTool
if (-not $signtool) { Write-Host "sign_windows: signtool.exe not found (install the Windows SDK). Skipping."; exit 0 }

$args = @("sign", "/fd", "SHA256", "/tr", $TIMESTAMP, "/td", "SHA256")
if ($env:WC_SIGN_PFX -and (Test-Path $env:WC_SIGN_PFX)) {
    $args += @("/f", $env:WC_SIGN_PFX)
    if ($env:WC_SIGN_PFX_PASSWORD) { $args += @("/p", $env:WC_SIGN_PFX_PASSWORD) }
} elseif ($env:WC_SIGN_SUBJECT) {
    $args += @("/n", $env:WC_SIGN_SUBJECT, "/a")
} else {
    Write-Host "sign_windows: no signing credentials configured -> shipping UNSIGNED (ok for now)."
    exit 0
}

foreach ($f in $Files) {
    Write-Host "Signing: $f"
    & $signtool @args $f
    if ($LASTEXITCODE -ne 0) { Write-Error "signtool failed for $f"; exit 1 }
}
Write-Host "sign_windows: signing complete."
