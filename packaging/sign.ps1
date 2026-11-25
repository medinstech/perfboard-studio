<#
    Sign one file with Medinstech's code-signing certificate, and prove that it took.

        pwsh packaging/sign.ps1 <file>

    The certificate is Certum's. Its private key is held in Certum's cloud and reached through
    SimplySign Desktop, so it is never on this machine and a signature can only be made while
    SimplySign is running and logged in (the phone app's token). That is why Windows signing
    happens on a maintainer's machine at release time and never in CI. When the session has
    lapsed, signtool does not say "log in": it says "No certificates were found that met all
    the given criteria", while the certificate is plainly in the store. Sign a scratch file
    with this script just before a release; it takes seconds and is the one check that means
    anything.

    packaging/sign-release.ps1 calls this for the two executables in the bundle, and the
    installer script calls it through SIGNCMD for the installer and the uninstaller it embeds.

    Every signature is timestamped. The certificate expires; a signature without a timestamp
    dies with it, a timestamped one stays valid for as long as the file exists.

    PERFBOARD_STUDIO_SIGN_THUMBPRINT overrides the certificate, which is how a renewed one is
    tried before its thumbprint is written in below.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Path
)

$ErrorActionPreference = "Stop"

# Medinstech Muhendislik ve Teknoloji A.S., issued by Certum Code Signing 2021 CA, valid
# 2026-08-13 to 2027-08-13. A renewal is a new thumbprint: change it here, and in
# src/perfboard_studio/updates.py, which the update check compares an installer against.
$DefaultThumbprint = "015B943D4A9B839FD8B5051D1CEAAD17E76754D8"
$Thumbprint = if ($env:PERFBOARD_STUDIO_SIGN_THUMBPRINT) { $env:PERFBOARD_STUDIO_SIGN_THUMBPRINT } else { $DefaultThumbprint }

# Certum's RFC 3161 timestamp server, the one its certificates are issued to use.
$TimestampUrl = "http://time.certum.pl"

function Find-SignTool {
    $onPath = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    $found = Get-ChildItem $kits -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.Directory.Name -eq "x64" } |
        Sort-Object { [version]$_.Directory.Parent.Name } -ErrorAction SilentlyContinue |
        Select-Object -Last 1
    if (-not $found) { throw "signtool.exe not found: install the Windows SDK signing tools" }
    return $found.FullName
}

if (-not (Test-Path $Path)) { throw "nothing to sign at $Path" }
$Path = (Resolve-Path $Path).Path

$signtool = Find-SignTool

# The timestamp server is a network call to somebody else's machine, and it does fail now
# and then. The signature itself is not the flaky part.
$signed = $false
foreach ($attempt in 1..3) {
    & $signtool sign /sha1 $Thumbprint /fd sha256 /tr $TimestampUrl /td sha256 `
        /d "Perfboard Studio" /du "https://github.com/medinstech/perfboard-studio" $Path
    if ($LASTEXITCODE -eq 0) { $signed = $true; break }
    Write-Warning "signing attempt $attempt failed (exit $LASTEXITCODE)"
    Start-Sleep -Seconds (5 * $attempt)
}
if (-not $signed) {
    throw "could not sign $Path. Is SimplySign Desktop running and logged in?"
}

# signtool's exit code says it wrote a signature. This says Windows accepts it, chained to a
# trusted root, made with the certificate we meant and timestamped.
$signature = Get-AuthenticodeSignature $Path
if ($signature.Status -ne "Valid") {
    throw "$Path is signed but not valid: $($signature.Status) $($signature.StatusMessage)"
}
if ($signature.SignerCertificate.Thumbprint -ne $Thumbprint) {
    throw "$Path is signed by $($signature.SignerCertificate.Thumbprint), not $Thumbprint"
}
if (-not $signature.TimeStamperCertificate) {
    throw "$Path is signed but not timestamped"
}
Write-Host "signed: $Path"
