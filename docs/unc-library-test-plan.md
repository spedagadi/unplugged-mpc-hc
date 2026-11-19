# Test plan — media library on a UNC share

Proves UR-0001 (the network library availability bug) and separates it from
UR-0002 (the `0x80040217` graph failure). See [USER-REPORTS.md](USER-REPORTS.md).

## Lab layout

```
NAS PC  \\NASPC\Movies   (a few .mkv/.mp4 files, no spaces required)
   |
   | SMB over the LAN
   |
HTPC    Unplugged 2.2.0 (installed, broken) and 2.3.0 (dev build, fixed)
```

The library root **must be added as a UNC path** (`\\NASPC\Movies`). A mapped
drive (`Z:\`) does not exercise the bug — `PathRoot()` has always appended the
separator for drive letters.

## 1. Create the share on the NAS PC

Run in an elevated PowerShell on the NAS. Replace `Movies` and the account.

```powershell
New-Item -ItemType Directory -Force D:\Shares\Movies | Out-Null
# a password-protected local account is the least surprising in a lab
$u = 'media'; $p = 'Unplugged-Lab-1'
if (-not (Get-LocalUser -Name $u -ErrorAction SilentlyContinue)) {
  New-LocalUser $u -Password (ConvertTo-SecureString $p -AsPlainText -Force) -PasswordNeverExpires
}
New-SmbShare -Name Movies -Path D:\Shares\Movies -FullAccess "$env:COMPUTERNAME\$u"
```

Then on the NAS:

```powershell
Set-NetConnectionProfile -NetworkCategory Private
Enable-NetFirewallRule -DisplayGroup 'File and Printer Sharing'
hostname            # -> NASPC, the name used below
```

Copy a few small `.mkv`/`.mp4` files into `D:\Shares\Movies` (and a folder deep
enough to prove recursion, e.g. `Movies\Test Show\Season 1\`).

## 2. Prove the HTPC can see it

On the HTPC, in a normal (non-elevated) shell — **the same account that runs
Unplugged**:

```powershell
cmdkey /add:\\NASPC\Movies /user:NASPC\media /pass:Unplugged-Lab-1
Get-ChildItem \\NASPC\Movies
```

If this lists the files, the share and credentials are fine and any remaining
failure is Unplugged's.

> If name resolution fails, use the NAS IP (`\\192.168.x.x\Movies`). That is
> still a UNC root and exercises the same code.

## 3. A/B the two builds

Use the same share for both, one at a time.

### 3a. Broken reference — installed 2.2.0

1. Launch the installed app, choose **Media Player**.
2. Library → **Folders...** → paste `\\NASPC\Movies` → OK.
3. Wait for the background scan.

Watch the app log live (installed app writes to LocalAppData because Program
Files is not writable):

```powershell
$log = "$env:LOCALAPPDATA\Unplugged\logs\native_ui_log.txt"
Get-Content $log -Wait -Tail 0 |
  Select-String 'library scan done|availability deep|is now (UN)?available|roots set'
```

**Expected (bug present)**

```
library: roots set to 1 (was 0)
library scan done in ...ms: N new, 0 updated, 0 missing
library: availability deep=1 tiles=0 sec=0/N/0 unavailable=N
library: '\NASPC\Movies\...' is now UNAVAILABLE        (N lines)
library: availability deep=0 ... unavailable=N          (every 5 s)
```

Every poster is banded and Play refuses with
`Storage unavailable: reconnect \\NASPC\Movies`.

### 3b. Fixed — 2.3.0 dev build

1. Close the installed app.
2. Rename the previous log so this run stands alone:
   `Rename-Item C:\code\unplugged-mpc-hc\bin\app\Release\native_ui_log.txt native_ui_log.before.txt`
3. Run `C:\code\unplugged-mpc-hc\bin\app\Release\Unplugged.exe`, Media Player
   mode, library open.
4. The root is already in the shared index; if not, add `\\NASPC\Movies` again.

Watch the dev log beside the exe (the app prefers its own directory):

```powershell
$log = 'C:\code\unplugged-mpc-hc\bin\app\Release\native_ui_log.txt'
Get-Content $log -Wait -Tail 0 |
  Select-String 'library scan done|availability deep|is now (UN)?available'
```

**Expected (fixed)**

```
library scan done in ...ms: N new, ...
library: availability deep=1 tiles=0 sec=0/N/0 unavailable=0
```

No `is now UNAVAILABLE` line. Posters have no band; Play opens the file.

## 4. Recovery — the badge must still work

Run with the **fixed** build and the library window visible (the 5 s refresh
only runs while the library is on screen; the root cache is 4 s).

On the NAS:

```powershell
Stop-SmbShare -Name Movies -Force     # share goes away
# ... observe the HTPC, then
Start-SmbShare -Name Movies
```

**Expected**

- Within ~5 s: `library: '\\NASPC\Movies\...' is now UNAVAILABLE` (N lines) and
  the posters band; `unavailable=N`.
- Clicking a title shows `Storage unavailable: reconnect \\NASPC\Movies\`
  (note the trailing separator — that is the fixed `PathRoot`).
- After `Start-SmbShare`, within ~5 s: `... is now available` (N lines),
  `unavailable=0`, bands clear.

If the HTPC keeps a stale SMB session, `net use \\NASPC\Movies /delete` and
re-run `cmdkey` before the second half.

## 5. UR-0002 — the codec-pack graph, separately

Only if you also want to close the `0x80040217` question. Use a machine where
K-Lite can be installed and removed (the HTPC or a VM).

1. Install K-Lite Codec Pack (default). It writes
   `HKCR\Media Type\Extensions\.mkv` → LAV Splitter Source.
2. With the 2.3.0 build, play a title from `\\NASPC\Movies` with the share up.
3. Read the engine log (`s3engine.log`, beside the exe; per-user
   `%USERPROFILE%\.unplugged\logs\engine.log` is the shell copy):

```powershell
Get-Content 'C:\code\unplugged-mpc-hc\bin\app\Release\s3engine.log' -Tail 200 |
  Select-String 'BuildGraph|File Source \(Async\)|AddSourceFilter|\[FILTER\]|FAILED|open url'
```

**Pass:** `[GRAPH] File Source (Async) Load hr=0x00000000` is present,
`[FILTER] video renderer module=...` is present, playback starts.

**Fail / investigate:** `BuildGraph FAILED hr=0x80040217` **without** the
File Source (Async) line. That means the pinned-source path was not taken (or
the engine binary is not the current tree) — rebuild `s3engine` per the handover
before changing graph code.

## Acceptance

| Check | Pass condition |
| --- | --- |
| 2.2.0 on a UNC root | reproduces: every title UNAVAILABLE (UR-0001) |
| 2.3.0 on a UNC root | zero UNAVAILABLE lines while the share is up |
| Play from the share | opens and plays |
| Share stopped | all titles band within ~5 s, Play refuses with the root |
| Share restored | all titles clear within ~5 s |
| UR-0002 (optional) | AsyncReader line present, playback succeeds with K-Lite |

Record the outcome against UR-0001/UR-0002 in [USER-REPORTS.md](USER-REPORTS.md).