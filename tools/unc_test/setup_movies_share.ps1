#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Lab SMB share for the UNC-library test (UR-0001).

.DESCRIPTION
    Shares the movie library read-only as \\<host>\Movies, enables the SMB
    inbound firewall rule that a Public network profile needs, and optionally
    creates a dedicated local account for the test PC.

    Unplugged only reads from a library, so share access is Read.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\setup_movies_share.ps1

.EXAMPLE
    # also create HTPC\unplugged so the test PC has credentials to use
    powershell -ExecutionPolicy Bypass -File .\setup_movies_share.ps1 -CreateUser

.EXAMPLE
    # undo the share (and the lab user, if -CreateUser was used)
    powershell -ExecutionPolicy Bypass -File .\setup_movies_share.ps1 -CreateUser -Remove
#>
[CmdletBinding()]
param(
    [string]$ShareName = 'Movies',
    [string]$Path      = 'D:\Movies',
    [switch]$CreateUser,
    [string]$UserName  = 'unplugged',
    [string]$Password  = 'Unplugged-Lab-1',
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$Text) { Write-Host "==> $Text" }

if ($Remove) {
    if (Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue) {
        Remove-SmbShare -Name $ShareName -Force
        Write-Step "removed share \\$env:COMPUTERNAME\$ShareName"
    } else {
        Write-Step "share '$ShareName' was not present"
    }
    if ($CreateUser -and (Get-LocalUser -Name $UserName -ErrorAction SilentlyContinue)) {
        Remove-LocalUser -Name $UserName
        Write-Step "removed local user $UserName"
    }
    Write-Host ''
    Write-Host 'The SMB-In firewall rule is left enabled (other file sharing may use it).'
    Write-Host "Disable it with: Disable-NetFirewallRule -DisplayGroup 'File and Printer Sharing'"
    return
}

if (-not (Test-Path -LiteralPath $Path)) { throw "Path not found: $Path" }

# --- 1. share ---------------------------------------------------------------
$existing = Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Path -ne $Path) {
        throw "Share '$ShareName' already exists at '$($existing.Path)'; remove it first or pick another -ShareName."
    }
    Write-Step "share already present: \\$env:COMPUTERNAME\$ShareName -> $Path"
} else {
    New-SmbShare -Name $ShareName -Path $Path -ReadAccess 'Everyone' | Out-Null
    Write-Step "created \\$env:COMPUTERNAME\$ShareName -> $Path (share access: Read)"
}

# --- 2. firewall ------------------------------------------------------------
# The SMB-In rule is profile-scoped (Private, Public). Enable whichever copy is
# off rather than flipping the whole network profile to Private.
$rules = @(Get-NetFirewallRule -DisplayGroup 'File and Printer Sharing' -ErrorAction SilentlyContinue |
           Where-Object { $_.Name -like 'FPS-SMB-In-TCP*' -and $_.Enabled -eq 'False' })
if ($rules.Count -gt 0) {
    $rules | Enable-NetFirewallRule
    Write-Step ("enabled firewall rule(s): " + (($rules | ForEach-Object Name) -join ', '))
} else {
    Write-Step 'SMB-In firewall rule already enabled'
}

# --- 3. optional lab account ------------------------------------------------
if ($CreateUser) {
    if (Get-LocalUser -Name $UserName -ErrorAction SilentlyContinue) {
        Write-Step "local user '$UserName' already exists"
    } else {
        New-LocalUser -Name $UserName `
            -Password (ConvertTo-SecureString $Password -AsPlainText -Force) `
            -PasswordNeverExpires `
            -Description 'Unplugged UNC library test' | Out-Null
        Write-Step "created local user '$UserName' (Users group: read on D:\Movies)"
    }
}

# --- 4. what to type on the test PC -----------------------------------------
$unc = "\\$env:COMPUTERNAME\$ShareName"
$ip  = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
        Select-Object -First 1).IPAddress
$acct = if ($CreateUser) { "$env:COMPUTERNAME\$UserName" } else { "$env:COMPUTERNAME\$env:USERNAME" }
$pass = if ($CreateUser) { $Password } else { '<your Windows password>' }

Write-Host ''
Write-Host 'On the test PC, authenticate once, then check the share:'
Write-Host "    cmdkey /add:$unc /user:$acct /pass:$pass"
Write-Host "    dir $unc"
if ($ip) { Write-Host "    (name resolution fallback: \\$ip\$ShareName)" }
Write-Host ''
Write-Host 'Then in Unplugged: Media Player -> Library -> Folders... -> add'
Write-Host "    $unc"