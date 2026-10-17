# run_vc_check.ps1 -- build and run distrib\vc_check_test.iss, then show the verdicts.
#
# It stages the directories the harness reads, because the check under test asks
# about FILES: a "current" set copied from the Qt binaries, a deliberately
# incomplete copy, and an older copy taken from the app-local DLLs the Python
# bundle carries. Then it compiles, runs the setup with /LOG, prints every CASE
# line, and cleans the staged directories up again.
#
# Nothing here installs or uninstalls a runtime; the harness aborts in
# InitializeSetup. Its only output is the log.

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$t = $env:TEMP

# Sources: the four names the payload's onnxruntime imports.
$names = 'VCRUNTIME140.dll','VCRUNTIME140_1.dll','MSVCP140.dll','MSVCP140_1.dll'
$currentSrc = @(
    'C:\code\unplugged\app\.venv\Lib\site-packages\PyQt6\Qt6\bin',
    'C:\Program Files\Unplugged\_internal\PyQt6\Qt6\bin'
) | Where-Object { Test-Path (Join-Path $_ 'VCRUNTIME140.dll') } | Select-Object -First 1
$oldSrc = 'C:\code\unplugged-mpc-hc\src\unplugged-ui\dist\Unplugged\_internal'

if (-not $currentSrc) { Write-Host "ERROR: no source for the current-version DLLs (PyQt6 Qt6\bin)." -ForegroundColor Red; exit 1 }
if (-not (Test-Path (Join-Path $oldSrc 'VCRUNTIME140.dll'))) {
    Write-Host "ERROR: $oldSrc\VCRUNTIME140.dll not found -- build the app first (the harness" -ForegroundColor Red
    Write-Host "       needs an older real copy, and the app-local one is what exists)." -ForegroundColor Red
    exit 1
}

# vc_ok: all four at the version the installer bundles or newer.
foreach ($d in 'vc_ok','vc_partial','vc_old') { Remove-Item (Join-Path $t $d) -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force (Join-Path $t 'vc_ok') | Out-Null
New-Item -ItemType Directory -Force (Join-Path $t 'vc_partial') | Out-Null
New-Item -ItemType Directory -Force (Join-Path $t 'vc_old') | Out-Null
foreach ($n in $names) { Copy-Item (Join-Path $currentSrc $n) (Join-Path $t "vc_ok\$n") -ErrorAction SilentlyContinue }
$have = (Get-ChildItem (Join-Path $t 'vc_ok') -Filter '*.dll').Name
if (Compare-Object $have $names) {
    Write-Host "ERROR: could not stage all four DLLs from $currentSrc (got: $($have -join ', '))." -ForegroundColor Red
    exit 1
}
Copy-Item (Join-Path $t 'vc_ok\*') (Join-Path $t 'vc_partial')
Remove-Item (Join-Path $t 'vc_partial\VCRUNTIME140_1.dll')   # the exact hole this started with
foreach ($n in 'VCRUNTIME140.dll','VCRUNTIME140_1.dll') { Copy-Item (Join-Path $oldSrc $n) (Join-Path $t "vc_old\$n") }

"staged:"
foreach ($d in 'vc_ok','vc_partial','vc_old') {
    $f = Get-ChildItem (Join-Path $t $d)
    "  {0,-12} {1}" -f $d, (($f | ForEach-Object { $_.Name + '=' + [System.Diagnostics.FileVersionInfo]::GetVersionInfo($_.FullName).FileVersion }) -join '  ')
}

# compile
$iscc = $null
foreach ($p in "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") {
    if (Test-Path $p) { $iscc = $p; break }
}
if (-not $iscc) { Write-Host "ERROR: ISCC.exe not found." -ForegroundColor Red; exit 1 }
$log = Join-Path $t 'vc_check_log.txt'
Remove-Item $log -ErrorAction SilentlyContinue
Set-Location $here
& $iscc vc_check_test.iss | Select-Object -Last 2
if ($LASTEXITCODE -ne 0) { Write-Host "harness did not compile ($LASTEXITCODE)" -ForegroundColor Red; exit $LASTEXITCODE }

# run -- it aborts itself in InitializeSetup, so exit 1 is the expected outcome
Start-Process (Join-Path $here 'out\vc_check_test.exe') `
    -ArgumentList '/VERYSILENT','/NORESTART',"/LOG=$log" -NoNewWindow -Wait

"=== verdicts ==="
Select-String -Path $log -Pattern 'CASE|REAL SYSTEM32|VC\+\+|: not present|: present but older|no readable' |
    ForEach-Object { ($_.Line -replace '^\S+\s+\S+\s+', '') }

$fails = (Select-String -Path $log -Pattern 'CASE .*FAIL' | Measure-Object).Count
$passes = (Select-String -Path $log -Pattern 'CASE .*PASS' | Measure-Object).Count
"=== $passes PASS, $fails FAIL ==="

# clean up
foreach ($d in 'vc_ok','vc_partial','vc_old') { Remove-Item (Join-Path $t $d) -Recurse -Force -ErrorAction SilentlyContinue }
Remove-Item (Join-Path $here 'out\vc_check_test.exe') -Force -ErrorAction SilentlyContinue
exit $(if ($fails -eq 0) { 0 } else { 1 })
