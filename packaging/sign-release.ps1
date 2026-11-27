<#
    Sign a release's Windows installer, attach it and the checksums to the draft, and publish.

        pwsh packaging/sign-release.ps1 v0.26.0             # sign, attach, check; stays a draft
        pwsh packaging/sign-release.ps1 v0.26.0 -Publish    # ...and then publish it
        pwsh packaging/sign-release.ps1 -DryRun <run id>    # rehearse on a dry run's bundle

    Run from a checkout of the tagged commit, on a machine where SimplySign Desktop is logged
    in (see packaging/sign.ps1 on why that is the only place a signature can be made).

    The tag's release.yml run builds the bundle, smoke-tests it, packs an unsigned installer
    it keeps as an artifact, creates the release as a draft with the notes on it and attaches
    the AppImage and the disk image. It does not attach a Windows installer, the checksums, or
    publish: an unsigned installer on a public release is one the update check of every copy
    from 0.26.0 on refuses to run (src/perfboard_studio/updates.py, FIRST_SIGNED_VERSION).

    This takes it from there:

      1. checks that this checkout is the tag's commit, clean, and says the tag's version;
      2. signs a scratch file, so a lapsed SimplySign session is found in seconds and not
         after a download of several hundred megabytes;
      3. downloads the bundle the tag's run built (the artifact perfboard-studio-windows-bundle)
         and asks its console build what version it is;
      4. signs the two executables in it;
      5. packs the installer from that bundle with this checkout's NSIS script, which signs the
         uninstaller it embeds and then the installer itself through SIGNCMD;
      6. downloads the AppImage and the disk image from the draft and writes SHA256SUMS over
         the three files, in the format and order `sha256sum` wrote it before;
      7. attaches the installer and SHA256SUMS to the draft, downloads both back and checks
         them against what was uploaded, the installer's signature included;
      8. with -Publish, checks the draft holds all four files and makes it public.

    The bundle is CI's, not one built here, so what ships is what the run smoke-tested, built
    with the versions release.yml pins rather than whatever this machine has installed. Only
    the signatures are added here.

    Every step can be run again: an upload replaces the file of the same name.
#>
[CmdletBinding(DefaultParameterSetName = "Release")]
param(
    [Parameter(Mandatory = $true, Position = 0, ParameterSetName = "Release")]
    [string]$Tag,

    [Parameter(ParameterSetName = "Release")]
    [switch]$Publish,

    [Parameter(Mandatory = $true, ParameterSetName = "DryRun")]
    [long]$DryRun
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SignScript = Join-Path $PSScriptRoot "sign.ps1"
$Nsi = Join-Path $PSScriptRoot "perfboard-studio.nsi"
$Repo = "medinstech/perfboard-studio"
$BundleArtifact = "perfboard-studio-windows-bundle"

function Step([string]$Text) { Write-Host "`n== $Text" -ForegroundColor Cyan }

function Invoke-Signing([string]$File) {
    & pwsh -NoProfile -ExecutionPolicy Bypass -File $SignScript $File
    if ($LASTEXITCODE -ne 0) { throw "signing $File failed" }
}

function Assert-Signed([string]$File) {
    $signature = Get-AuthenticodeSignature $File
    if ($signature.Status -ne "Valid") {
        throw "$File is not validly signed: $($signature.Status) $($signature.StatusMessage)"
    }
    if (-not $signature.TimeStamperCertificate) { throw "$File is signed but not timestamped" }
    return $signature.SignerCertificate.Thumbprint
}

# `sha256sum`'s own format, which `sha256sum -c` and the update check both read: the hash in
# lower case, two spaces, the bare name, a line feed.
function Get-SumLine([string]$File) {
    $hash = (Get-FileHash -Algorithm SHA256 $File).Hash.ToLowerInvariant()
    return "$hash  $(Split-Path $File -Leaf)"
}

function Find-MakeNsis {
    $onPath = Get-Command makensis.exe -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $default = Join-Path ${env:ProgramFiles(x86)} "NSIS\makensis.exe"
    if (Test-Path $default) { return $default }
    throw "makensis.exe not found: install NSIS 3.08 or newer"
}

# The version the checkout says, read the way the NSIS script and the spec read it.
$versionLine = Select-String -Path (Join-Path $Root "src\perfboard_studio\version.py") `
    -Pattern '^__version__ = "([^"]+)"' | Select-Object -First 1
if (-not $versionLine) { throw "no __version__ line in version.py" }
$Version = $versionLine.Matches[0].Groups[1].Value

$head = (git -C $Root rev-parse HEAD).Trim()
if (git -C $Root status --porcelain --untracked-files=no) {
    throw "this checkout has uncommitted changes, and the installer is packed from it"
}

Step "What is being signed"
if ($PSCmdlet.ParameterSetName -eq "DryRun") {
    $run = gh run view $DryRun --repo $Repo --json headSha,status,conclusion,event,workflowName |
        ConvertFrom-Json
    if ($run.workflowName -ne "release") { throw "run $DryRun is $($run.workflowName), not release" }
    $RunId = $DryRun
    Write-Host "dry run $RunId of $($run.headSha), version ${Version}: nothing is uploaded"
} else {
    if ($Tag -ne "v$Version") { throw "the tag is $Tag and this checkout says $Version" }
    $tagCommit = (git -C $Root rev-parse "$Tag^{commit}").Trim()
    if ($tagCommit -ne $head) {
        throw "this checkout is at $head and $Tag is ${tagCommit}: check out the tag first"
    }
    $runs = gh run list --repo $Repo --workflow release.yml --event push --branch $Tag `
        --json databaseId,headSha,status,conclusion --limit 5 | ConvertFrom-Json
    $run = $runs | Where-Object { $_.headSha -eq $tagCommit } | Select-Object -First 1
    if (-not $run) { throw "no release.yml run for $Tag yet" }
    $RunId = $run.databaseId
    Write-Host "$Tag at $tagCommit, run $RunId"
}
if ($run.headSha -ne $head) { throw "run $RunId built $($run.headSha), and this checkout is $head" }
if ($run.status -ne "completed" -or $run.conclusion -ne "success") {
    throw "run $RunId is $($run.status) $($run.conclusion): every job has to have passed"
}

$Work = Join-Path ([IO.Path]::GetTempPath()) "perfstudio-sign-$RunId"
if (Test-Path $Work) { Remove-Item -Recurse -Force $Work }
New-Item -ItemType Directory -Force $Work | Out-Null

Step "Is SimplySign logged in"
# A fresh script rather than a copy of a Windows system binary: a System32 exe carries a
# Windows catalog signature (IsOSBinary = True), which Get-AuthenticodeSignature returns
# ahead of the newly embedded signature and makes sign.ps1 reject the thumbprint.
$probe = Join-Path $Work "probe.ps1"
Set-Content -Path $probe -Value "# simplysign probe" -Encoding ascii
Invoke-Signing $probe
Remove-Item $probe

Step "The bundle the run built"
$download = Join-Path $Work "bundle"
gh run download $RunId --repo $Repo --name $BundleArtifact --dir $download
$gui = Get-ChildItem $download -Recurse -Filter "perfboard-studio.exe" | Select-Object -First 1
if (-not $gui) { throw "the artifact has no perfboard-studio.exe" }
$Bundle = $gui.Directory.FullName
$cli = Join-Path $Bundle "perfboard-studio-cli.exe"
$says = (& $cli --version | Out-String).Trim()
Write-Host $says
if ($says -notmatch "Perfboard Studio $([regex]::Escape($Version))\b") {
    throw "the bundle says '$says', and this checkout is $Version"
}

Step "Sign the executables"
foreach ($exe in Get-ChildItem $Bundle -Filter "*.exe") { Invoke-Signing $exe.FullName }

Step "Pack the installer"
# SIGNCMD is run by makensis through the shell, once for the uninstaller and once for the
# installer, and the script ends the build if it does not exit 0.
$releases = Join-Path $Root "releases"
New-Item -ItemType Directory -Force $releases | Out-Null
$SetupName = "PerfboardStudio_v${Version}_Setup.exe"
$Setup = Join-Path $releases $SetupName
if (Test-Path $Setup) { Remove-Item $Setup }
$makensis = Find-MakeNsis
& $makensis /INPUTCHARSET UTF8 "/DBUILD_DIR=$Bundle" `
    "/DSIGNCMD=pwsh -NoProfile -ExecutionPolicy Bypass -File `"$SignScript`"" $Nsi
if ($LASTEXITCODE -ne 0) { throw "makensis failed" }
$thumbprint = Assert-Signed $Setup
Write-Host "$SetupName signed by $thumbprint"

if ($PSCmdlet.ParameterSetName -eq "DryRun") {
    Step "Rehearsed"
    Write-Host "$Setup is signed. Nothing was uploaded: install it, then uninstall it, and the"
    Write-Host "uninstaller's prompt should name Medinstech as well."
    exit 0
}

Step "The checksums"
$assets = Join-Path $Work "assets"
gh release download $Tag --repo $Repo --pattern "*.AppImage" --pattern "*.dmg" --dir $assets
$appImage = @(Get-ChildItem $assets -Filter "*.AppImage")
$dmg = @(Get-ChildItem $assets -Filter "*.dmg")
if ($appImage.Count -ne 1 -or $dmg.Count -ne 1) {
    throw "the draft should hold one AppImage and one disk image; it holds $($appImage.Count) and $($dmg.Count)"
}
$Sums = Join-Path $releases "SHA256SUMS"
$lines = @((Get-SumLine $Setup), (Get-SumLine $appImage[0].FullName), (Get-SumLine $dmg[0].FullName))
[IO.File]::WriteAllText($Sums, (($lines -join "`n") + "`n"), [Text.Encoding]::ASCII)
Get-Content $Sums

Step "Attach them to the draft"
$draft = gh release view $Tag --repo $Repo --json isDraft --jq .isDraft
if ($draft -ne "true") { throw "$Tag is already public: sign before publishing, not after" }
gh release upload $Tag $Setup $Sums --repo $Repo --clobber

Step "Download them back"
$back = Join-Path $Work "back"
gh release download $Tag --repo $Repo --pattern $SetupName --pattern "SHA256SUMS" --dir $back
foreach ($name in @($SetupName, "SHA256SUMS")) {
    $sent = (Get-FileHash -Algorithm SHA256 (Join-Path $releases $name)).Hash
    $got = (Get-FileHash -Algorithm SHA256 (Join-Path $back $name)).Hash
    if ($sent -ne $got) { throw "$name on the release is not the file uploaded" }
}
if ((Assert-Signed (Join-Path $back $SetupName)) -ne $thumbprint) {
    throw "the installer on the release is signed by a different certificate"
}
$setupHash = (Get-FileHash -Algorithm SHA256 $Setup).Hash
Write-Host "the release's installer and SHA256SUMS are the ones made here"
Write-Host "installer SHA-256 (winget InstallerSha256, Scoop hash): $setupHash"

if (-not $Publish) {
    Step "Left as a draft"
    Write-Host "Publish with: pwsh packaging/sign-release.ps1 $Tag -Publish"
    exit 0
}

Step "Publish"
$names = gh release view $Tag --repo $Repo --json assets --jq '.assets[].name'
foreach ($want in @("_Setup.exe", ".AppImage", ".dmg", "SHA256SUMS")) {
    if (-not ($names | Where-Object { $_.EndsWith($want) })) {
        throw "the draft has no $want, so it stays a draft"
    }
}
gh release edit $Tag --repo $Repo --draft=false
if ((gh release view $Tag --repo $Repo --json isDraft --jq .isDraft) -ne "false") {
    throw "the release is still a draft"
}
Write-Host "$Tag is public"
