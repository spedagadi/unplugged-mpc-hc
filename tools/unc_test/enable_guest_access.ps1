#Requires -RunAsAdministrator
<#
    Lab-only: make \\<host>\Movies readable WITHOUT a password (guest logon).

    Scope: the Guest account, NTFS read for BUILTIN\Guests on D:\Movies and the
    SMB firewall rule. The machine keeps the Classic sharing model (ForceGuest is
    NOT touched); a client that presents no credentials falls back to Guest.
    The share itself (already Everyone: Full) and other folders are untouched.

    SECURITY: enables a passwordless account for file sharing. Use on a trusted
    LAN only; -Undo restores the previous state.
#>
[CmdletBinding()]
param(
    [string]$Path = 'D:\Movies',
    [switch]$Undo
)
$ErrorActionPreference = 'Stop'
$log = Join-Path $PSScriptRoot 'enable_guest_access.log'
function Say([string]$t) {
    $line = (Get-Date -Format 'HH:mm:ss') + ' ' + $t
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding utf8
}
$guestsSid = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-546')  # BUILTIN\Guests

try {
    if ($Undo) {
        $acl = Get-Acl $Path
        foreach ($r in @($acl.Access | Where-Object { $_.IdentityReference -eq 'BUILTIN\Guests' })) {
            [void]$acl.RemoveAccessRule($r)
        }
        Set-Acl $Path $acl
        Say "NTFS: removed the Guests ACE from $Path"
        Disable-LocalUser -Name Guest -ErrorAction SilentlyContinue
        Say 'Guest account disabled'
        Restart-Service LanmanServer -Force -ErrorAction SilentlyContinue
        Say 'DONE (undo)'
        return
    }

    # 1. Guest account
    $g = Get-LocalUser -Name Guest -ErrorAction SilentlyContinue
    if (-not $g) { throw 'The Guest account does not exist on this build.' }
    if (-not $g.Enabled) { Enable-LocalUser -Name Guest; Say 'Guest account enabled' }
    else { Say 'Guest account already enabled' }

    # 2. NTFS read for Guests (inherited to existing and new children)
    $acl = Get-Acl $Path
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $guestsSid, 'ReadAndExecute', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
    Set-Acl $Path $acl
    Say "NTFS: granted BUILTIN\Guests ReadAndExecute (OI)(CI) on $Path"

    # 3. SMB inbound firewall for the Public profile
    $off = @(Get-NetFirewallRule -DisplayGroup 'File and Printer Sharing' -ErrorAction SilentlyContinue |
             Where-Object { $_.Direction -eq 'Inbound' -and $_.Enabled -eq 'False' })
    if ($off.Count) { $off | Enable-NetFirewallRule; Say ('firewall: enabled ' + (($off | ForEach-Object Name) -join ', ')) }
    else { Say 'firewall: SMB inbound already enabled' }

    # 5. apply the server-side change now (disconnects current SMB sessions)
    Restart-Service LanmanServer -Force -ErrorAction SilentlyContinue
    Say 'LanmanServer restarted'

    Say ('share check: ' + ((Get-SmbShare -Name Movies | Select-Object -ExpandProperty Path)))
    Say 'DONE'
}
catch {
    Say ('FAILED: ' + $_.Exception.Message)
    exit 1
}