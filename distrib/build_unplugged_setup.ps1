# build_unplugged_setup.ps1 — compile distrib\unplugged.iss into a setup.exe.
#
# Three gates before ISCC runs, because each failure mode here is silent
# otherwise:
#   1. the compiler exists,
#   2. the DeckLink licence page carries real text, not the placeholder,
#   3. every Source path the script names actually exists — an Inno build with a
#      missing Source line fails, but one with a stale filter path ships a filter
#      from wherever it last was, and that is the worse failure.

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

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

# 2. licence gate --------------------------------------------------------------
$lic = Join-Path $here 'decklink_sdk_license.txt'
$text = if (Test-Path $lic) { Get-Content $lic -Raw } else { '' }
if (-not $text -or $text -match 'PLACEHOLDER-REPLACE-WITH') {
    Write-Host "ERROR: distrib\decklink_sdk_license.txt is still the placeholder." -ForegroundColor Red
    Write-Host "       Replace it with the verbatim Blackmagic DeckLink SDK licence from your" -ForegroundColor Red
    Write-Host "       SDK download before building. DeckLinkSource.ax ships behind this page." -ForegroundColor Red
    exit 1
}

# 3. source paths --------------------------------------------------------------
$iss = Get-Content (Join-Path $here 'unplugged.iss') -Raw
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
& $iscc (Join-Path $here 'unplugged.iss')
if ($LASTEXITCODE -ne 0) { Write-Host "ISCC failed: $LASTEXITCODE" -ForegroundColor Red; exit $LASTEXITCODE }
Write-Host "setup built: $here\out" -ForegroundColor Green
