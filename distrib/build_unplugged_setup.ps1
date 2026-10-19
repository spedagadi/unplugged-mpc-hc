# build_unplugged_setup.ps1 -- compile distrib\unplugged.iss into a setup.exe.
#
# Gates before ISCC runs, because each failure mode here is silent
# otherwise:
#   1.  the compiler exists,
#   1b. the bundled VC++ runtime is present, Microsoft-signed, and the same
#       version the .iss skips on,
#   2.  the DeckLink EULA page carries real text, not the placeholder -- EVERY
#       build, because the application payload itself contains SDK-derived code,
#   2b. the Blackmagic notice travels with it, and is not a stub,
#   2c. the GPL source offer is real, when the build ships LAV,
#   3.  every Source path the script names actually exists -- an Inno build with a
#       missing Source line fails, but one with a stale filter path ships a filter
#       from wherever it last was, and that is the worse failure.

param(
    # Build WITHOUT the LAV fork and DeckLinkSource.ax. This removes the GPL
    # source-offer gate, because that obligation exists for the LAV binaries and
    # a build shipping none of them owes nothing. It does NOT remove the
    # Blackmagic gates: _internal\decklink_monitor.dll is compiled from
    # decklink_monitor.c against the DeckLink SDK headers and is bundled inside
    # the application by PyInstaller, so it is in every payload and its licence
    # page must appear for every install. Use this switch to validate the
    # installer mechanics; do not distribute a skip build as the product -- it
    # has no ingest and no file playback through LAV.
    [switch]$SkipFilters,

    # Uncompressed build that finishes in seconds: for checking the wizard pages,
    # the payload layout and COM registration. Its output is named *-TESTONLY.exe
    # by the .iss, so it cannot be mistaken for the deliverable.
    [switch]$Fast
)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$issVersion = Select-String -Path (Join-Path $here 'unplugged.iss') -Pattern '^#define MyAppVersion "([^"]+)"'
$uiVersion = Select-String -Path (Join-Path $here '..\src\unplugged-ui\src\mpvprocessor\__init__.py') -Pattern '^__version__ = "([^"]+)"'
if (-not $issVersion -or -not $uiVersion -or
    $issVersion.Matches[0].Groups[1].Value -ne $uiVersion.Matches[0].Groups[1].Value) {
    throw 'Installer and UI source versions must match before packaging.'
}
$appExe = Join-Path $here '..\src\unplugged-ui\dist\Unplugged\Unplugged.exe'
if (-not (Test-Path $appExe) -or
    ([System.Diagnostics.FileVersionInfo]::GetVersionInfo($appExe)).ProductVersion -ne $uiVersion.Matches[0].Groups[1].Value) {
    throw 'Packaged Unplugged.exe version does not match the UI source. Rebuild unplugged.spec before packaging.'
}
if ($SkipFilters) {
    Write-Host "NOTE: -SkipFilters -- LAV and DeckLinkSource.ax are OMITTED; only the GPL gate is waived." -ForegroundColor Yellow
    Write-Host "      The Blackmagic gates still apply: the app bundles SDK-derived code" -ForegroundColor Yellow
    Write-Host "      (_internal\decklink_monitor.dll) in every build." -ForegroundColor Yellow
    Write-Host "      The resulting setup.exe is a mechanics test, not a distributable product." -ForegroundColor Yellow
}
if ($Fast) {
    Write-Host "NOTE: -Fast -- no compression, output is named *-TESTONLY.exe. Not for shipping." -ForegroundColor Yellow
}

# 1. compiler -----------------------------------------------------------------
$iscc = $null
foreach ($p in @(
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
    if (Test-Path $p) { $iscc = $p; break }
}
if (-not $iscc) {
    Write-Host "ERROR: Inno Setup 6 not found. Install it (winget install JRSoftware.InnoSetup) and re-run." -ForegroundColor Red
    exit 1
}

# 1b. the VC++ runtime, and only the real one ----------------------------------
# Every binary in this payload is MSVC /MD. On a machine with no 2015-2022 x64
# runtime the app fails at load, before any window or log line exists, so it
# looks like a broken install rather than a missing DLL. The installer therefore
# carries the redist; it is not optional, and it must be the genuine Microsoft
# package.
#
# The version check is not ceremony. unplugged.iss's NeedVCRedist skips the
# bundled redist when the box already reports 14.44.35211 or newer, and the one
# safe direction of that comparison is "installed >= bundled". If someone drops a
# NEWER redist in without updating the constant, the skip stays correct; drop an
# OLDER one and the installer would refuse to upgrade a box that has the newer
# runtime while shipping a payload that needs the newer one. So the two have to
# agree, which is only true if the bundled file is the version the constant names.
$vc = Join-Path $here 'redist\vc_redist.x64.exe'
# The skip threshold is not repeated here; it is read out of the script that uses
# it, so a redist bump is a one-line change in distrib\vc_runtime.iss.
$vcm = Select-String -Path (Join-Path $here 'vc_runtime.iss') -Pattern '^#define\s+VC_REQ_(MAJ|MIN|BLD)\s+(\d+)' -AllMatches
$vcParts = @{}
foreach ($m in $vcm) { $vcParts[$m.Matches[0].Groups[1].Value] = $m.Matches[0].Groups[2].Value }
if (-not $vcParts['MAJ'] -or -not $vcParts['MIN'] -or -not $vcParts['BLD']) {
    Write-Host "ERROR: could not read VC_REQ_MAJ/MIN/BLD from distrib\vc_runtime.iss." -ForegroundColor Red
    exit 1
}
$vcNeed = "$($vcParts['MAJ']).$($vcParts['MIN']).$($vcParts['BLD'])"
if (-not (Test-Path $vc)) {
    Write-Host "ERROR: distrib\redist\vc_redist.x64.exe is missing." -ForegroundColor Red
    Write-Host "       The installer bundles the VC++ 2015-2022 x64 runtime; a build" -ForegroundColor Red
    Write-Host "       without it ships /MD binaries that cannot start on a clean box." -ForegroundColor Red
    Write-Host "       Fetch the official package:" -ForegroundColor Yellow
    Write-Host "         Invoke-WebRequest https://aka.ms/vs/17/release/vc_redist.x64.exe -OutFile distrib\redist\vc_redist.x64.exe" -ForegroundColor Yellow
    Write-Host "       Expected version $vcNeed (read from distrib\vc_runtime.iss). If" -ForegroundColor Yellow
    Write-Host "       Microsoft has moved on, bump VC_REQ_MAJ/MIN/BLD there to match." -ForegroundColor Yellow
    exit 1
}
$sig = Get-AuthenticodeSignature $vc
if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {
    Write-Host "ERROR: distrib\redist\vc_redist.x64.exe is not a valid Microsoft-signed" -ForegroundColor Red
    Write-Host "       binary (status=$($sig.SignerStatus.Status) subject=$($sig.SignerCertificate.Subject))." -ForegroundColor Red
    Write-Host "       Replace it with the official download; do not bundle a repacked runtime." -ForegroundColor Red
    exit 1
}
$vcVer = ([System.Diagnostics.FileVersionInfo]::GetVersionInfo($vc)).FileVersion -replace '\.\d+$',''
if ($vcVer -ne $vcNeed) {
    Write-Host "ERROR: bundled redist is $vcVer but the installer skips on >= $vcNeed." -ForegroundColor Red
    Write-Host "       Set VC_REQ_MAJ/VC_REQ_MIN/VC_REQ_BLD in distrib\vc_runtime.iss to" -ForegroundColor Red
    Write-Host "       the version actually in distrib\redist\, so the skip can never" -ForegroundColor Red
    Write-Host "       protect a machine that is missing what this payload needs." -ForegroundColor Red
    exit 1
}
Write-Host "gate ok: VC++ redist $vcVer, Microsoft-signed, matching the .iss skip threshold" -ForegroundColor DarkGray

# 2. Blackmagic EULA gate -- UNCONDITIONAL ------------------------------------
# This used to be skipped by -SkipFilters, on the reasoning that the obligation
# belonged to DeckLinkSource.ax. That reasoning is wrong and was corrected after
# checking what the application actually bundles: _internal\decklink_monitor.dll
# is gcc-built from decklink_monitor.c against the DeckLink SDK headers and is
# copied into the payload by PyInstaller (unplugged.spec adds it from
# src\unplugged-ui\assets). It therefore ships in EVERY build, and the SDK
# headers grant their rights "subject to" the DeckLink SDK EULA. No switch here
# removes that.
$lic = Join-Path $here 'decklink_sdk_license.txt'
$text = if (Test-Path $lic) { Get-Content $lic -Raw } else { '' }
if (-not $text -or $text -match 'PLACEHOLDER-REPLACE-WITH') {
    Write-Host "ERROR: distrib\decklink_sdk_license.txt is still the placeholder." -ForegroundColor Red
    Write-Host "       Replace it with the verbatim Blackmagic DeckLink SDK EULA" -ForegroundColor Red
    Write-Host "       (https://www.blackmagicdesign.com/EULA/DeckLinkSDK) before building." -ForegroundColor Red
    Write-Host "       This gate is unconditional: the application payload contains" -ForegroundColor Red
    Write-Host "       SDK-derived code (_internal\decklink_monitor.dll) in every build," -ForegroundColor Red
    Write-Host "       so -SkipFilters does not waive it. There is no build of this product" -ForegroundColor Red
    Write-Host "       that is free of the Blackmagic licence page." -ForegroundColor Red
    exit 1
}

# 2b. Blackmagic notice must travel, and must not be a stub -------------------
# The header licence requires the copyright notice AND the entire grant statement
# to accompany all copies and derivative works. A notice that is missing, empty,
# or still carrying a marker is the same violation as a missing EULA page, and
# it is quieter -- nothing about the installer looks wrong when it happens.
$notice = Join-Path $here 'blackmagic_sdk_notice.txt'
$noticeText = if (Test-Path $notice) { Get-Content $notice -Raw } else { '' }
if (-not $noticeText -or $noticeText -match 'PLACEHOLDER|TODO|REPLACE-WITH') {
    Write-Host "ERROR: distrib\blackmagic_sdk_notice.txt is missing or still a placeholder." -ForegroundColor Red
    Write-Host "       It must carry the verbatim Blackmagic header notice and name the" -ForegroundColor Red
    Write-Host "       SDK-derived binaries, in every build. Unconditional, same as gate 2." -ForegroundColor Red
    exit 1
}

# 2c. GPL source offer must be real -------------------------------------------
# Bundling modified LAV Filters makes the corresponding source a condition of
# distribution. An offer that points at a placeholder is not an offer; shipping
# it would be a GPL violation presented as compliance, which is worse than an
# honest absence. This one IS payload-conditional: the obligation exists for the
# LAV binaries, and -SkipFilters ships none.
if (-not $SkipFilters) {
    $offer = Join-Path $here 'licenses\lav_gpl_source_offer.txt'
    $offerText = if (Test-Path $offer) { Get-Content $offer -Raw } else { '' }
    if (-not $offerText -or $offerText -match 'SOURCE_OFFER_URL_PLACEHOLDER') {
        Write-Host "ERROR: licenses\lav_gpl_source_offer.txt still has the placeholder URL." -ForegroundColor Red
        Write-Host "       Put the public location of the modified LAV source there, or remove the" -ForegroundColor Red
        Write-Host "       LAV binaries from the installer. There is no third option under the GPL." -ForegroundColor Red
        Write-Host "       (Or build with -SkipFilters to test mechanics without those binaries.)" -ForegroundColor Red
        exit 1
    }
}

# 3. source paths --------------------------------------------------------------
$iss = Get-Content (Join-Path $here 'unplugged.iss') -Raw

# Keep only the lines the preprocessor would emit for THIS configuration. A
# path inside a region that never compiles is not a missing path, and checking it
# anyway would refuse a -SkipFilters build on a machine with no LAV tree -- the
# machine on which a mechanics test is most useful.
#
# This is a deliberately narrow ISPP: it resolves the SkipFilters condition and
# treats every other conditional (#if FileExists, #ifdef FastTest) as active,
# because those gate on file presence or on build speed, not on which binaries
# ship. Nesting is supported by the stack; an #endif that does not close
# something is an error rather than a shrug, because a mis-tracked region means
# gate 3 is checking a payload that is not the one being built.
$lines = $iss -split "`r?`n"
$kept  = [System.Collections.Generic.List[string]]::new()
$stack = [System.Collections.Generic.Stack[object]]::new()
foreach ($line in $lines) {
    $active = $true
    foreach ($f in $stack) { if (-not $f.active) { $active = $false; break } }
    if ($line -match '^\s*#(ifdef|ifndef)\s+SkipFilters\s*$') {
        $want = ($Matches[1] -eq 'ifdef')
        $stack.Push(@{ skip = $true; active = ([bool]$SkipFilters -eq $want) })
        continue
    }
    if ($line -match '^\s*#(if|ifdef|ifndef)\b') { $stack.Push(@{ skip = $false; active = $true }); }
    elseif ($line -match '^\s*#else\s*$') {
        if ($stack.Count -eq 0) { Write-Host "ERROR: #else with no open conditional in unplugged.iss" -ForegroundColor Red; exit 1 }
        $top = $stack.Pop()
        if ($top.skip) { $top.active = -not $top.active }
        $stack.Push($top)
    }
    elseif ($line -match '^\s*#endif\s*$') {
        if ($stack.Count -eq 0) { Write-Host "ERROR: #endif with no open conditional in unplugged.iss" -ForegroundColor Red; exit 1 }
        [void]$stack.Pop()
        continue
    }
    if ($active) { $kept.Add($line) }
}
if ($stack.Count) {
    Write-Host "ERROR: unplugged.iss ends with an unclosed conditional (depth $($stack.Count))" -ForegroundColor Red
    exit 1
}
$iss = $kept -join "`n"

$missing = @()
# resolve the #define'd roots, then check each literal Source that uses them
$roots = @{}
foreach ($m in [regex]::Matches($iss, '#define\s+(\w+)\s+"([^"]+)"')) {
    $roots[$m.Groups[1].Value] = $m.Groups[2].Value
}
foreach ($m in [regex]::Matches($iss, 'Source:\s*"([^"]+)"')) {
    $raw = $m.Groups[1].Value
    if ($raw -match '^\{#(\w+)\}(.*)$') {
        $base = $roots[$Matches[1]]
        if ($null -eq $base) { $missing += $raw; continue }
        $full = [System.IO.Path]::GetFullPath((Join-Path $here $base) + $Matches[2].Replace('\*', ''))
        if ($Matches[2] -like '*\*') { $full = Split-Path $full -Parent }
        if (-not (Test-Path $full)) { $missing += "$raw  ->  $full" }
    } elseif ($raw -notmatch 'redist') {
        $full = [System.IO.Path]::GetFullPath((Join-Path $here $raw))
        if (-not (Test-Path $full)) { $missing += "$raw  ->  $full" }
    }
}
if ($missing.Count) {
    Write-Host "ERROR: these Source paths do not exist:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "       $_" -ForegroundColor Red }
    exit 1
}

# compile ----------------------------------------------------------------------
$isccArgs = @()
if ($SkipFilters) { $isccArgs += '/DSkipFilters=1' }
if ($Fast) { $isccArgs += '/DFastTest=1' }
$isccArgs += (Join-Path $here 'unplugged.iss')
& $iscc @isccArgs
if ($LASTEXITCODE -ne 0) { Write-Host "ISCC failed: $LASTEXITCODE" -ForegroundColor Red; exit $LASTEXITCODE }
Write-Host "setup built: $here\out" -ForegroundColor Green
if ($SkipFilters) {
    Write-Host "REMINDER: this setup.exe omits LAV and DeckLinkSource. It validates the installer," -ForegroundColor Yellow
    Write-Host "          it is not the product. The full build needs the two licence texts." -ForegroundColor Yellow
}
