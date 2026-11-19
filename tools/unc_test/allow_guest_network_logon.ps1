#Requires -RunAsAdministrator
<#
    Lab-only: remove BUILTIN\Guests / the Guest account from
    "Deny access to this computer from the network" (SeDenyNetworkLogonRight).

    Without this the SMB server refuses the guest fallback with
    "System error 1385 - the user has not been granted the requested logon type".
    Only that one right is edited; every other entry in the list is preserved.
    -Undo re-adds the SIDs (i.e. restores the Windows default deny).
#>
[CmdletBinding()]
param([switch]$Undo)
$ErrorActionPreference = 'Stop'
$dir = $PSScriptRoot
$inf = Join-Path $dir 'secpol_guest.inf'
$db  = Join-Path $dir 'secpol_guest.sdb'
$log = Join-Path $dir 'allow_guest_network_logon.log'
function Say([string]$t) {
    $line = (Get-Date -Format 'HH:mm:ss') + ' ' + $t
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding utf8
}

$guest = Get-LocalUser -Name Guest
$sids = @($guest.SID.Value, 'S-1-5-32-546') | Select-Object -Unique
# secedit may export the principal by name instead of SID
$names = @($guest.Name, (Get-LocalGroup -SID 'S-1-5-32-546').Name)
function Test-GuestEntry([string]$p) {
    $q = $p -replace '^\*', ''
    if ($sids -contains $q) { return $true }
    foreach ($n in $names) { if ($q -ieq $n) { return $true } }
    return $false
}

secedit /export /cfg $inf /areas USER_RIGHTS | Out-Null
if (-not (Test-Path $inf)) { throw 'secedit export failed' }

$lines = [System.IO.File]::ReadAllLines($inf)          # UTF-16
$found = $false
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -notmatch '^SeDenyNetworkLogonRight\s*=') { continue }
    $found = $true
    $parts = ($lines[$i] -replace '^SeDenyNetworkLogonRight\s*=\s*', '') -split ',' |
             ForEach-Object { $_.Trim() } | Where-Object { $_ }
    $before = $parts.Count
    if ($Undo) {
        foreach ($s in $sids) {
            if ($parts -notcontains ('*' + $s)) { $parts += ('*' + $s) }
        }
        Say ('SeDenyNetworkLogonRight: ' + $before + ' -> ' + $parts.Count + ' (undo)')
    } else {
        $parts = @($parts | Where-Object { -not (Test-GuestEntry $_) })
        Say ('SeDenyNetworkLogonRight: ' + $before + ' -> ' + $parts.Count)
    }
    $lines[$i] = 'SeDenyNetworkLogonRight = ' + ($parts -join ',')
}
if (-not $found) {
    if ($Undo) { Say 'no SeDenyNetworkLogonRight line; nothing to do' }
    else { Say 'no SeDenyNetworkLogonRight line present (default already allows Guests)' }
}
[System.IO.File]::WriteAllLines($inf, $lines, [System.Text.Encoding]::Unicode)

secedit /configure /db $db /cfg $inf /areas USER_RIGHTS /quiet
if ($LASTEXITCODE -ne 0) { throw ('secedit configure failed: ' + $LASTEXITCODE) }
Say 'security policy applied'

# verify by re-export
$chk = Join-Path $dir 'secpol_guest_check.inf'
secedit /export /cfg $chk /areas USER_RIGHTS | Out-Null
$line = [System.IO.File]::ReadAllLines($chk) | Where-Object { $_ -match '^SeDenyNetworkLogonRight' }
Say ('now: ' + $line)
Say 'DONE'