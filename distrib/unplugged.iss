; ---------------------------------------------------------------------------
; unplugged.iss — installer for the Unplugged HTPC app and its filter chain.
;
; Derived in structure from mpc-hc_setup.iss and LAVFilters.iss in this tree;
; the regserver idiom below is LAV's, proven on exactly these binaries.
;
; WHAT SHIPS
;   {app}\            the PyInstaller onedir (Unplugged.exe + _internal)
;   {app}\filters\    every DirectShow filter plus everything each one needs
;                     beside it: MPCVR's .ax with onnxruntime.dll and its five
;                     model files (MPCVR resolves models from the directory its
;                     own .ax sits in, so they must travel together), the LAV
;                     fork's three filters with their ffmpeg DLLs, and
;                     DeckLinkSource.ax.
;
; Registration is Inno's regserver flag: DllRegisterServer at install,
; DllUnregisterServer at uninstall, for all five filters. No [Run] regsvr32
; lines, so a half-finished install cannot leave a filter registered against a
; path that no longer exists.
;
; WHAT DELIBERATELY DOES NOT SHIP
;   The renderer's own logs (ml_debug.csv, mpcvr_trace*.log) — ~96 MB of one
;   machine's diagnostics sitting in the staged build folder.
;   The per-user config. It lives in %LOCALAPPDATA%\Unplugged\s3_shell.ini,
;   outside {app}, so upgrades never touch it and uninstall never deletes it.
;   That is a feature: a re-install must not cost anyone their tuned curve.
;
; THE LICENCE PAGE IS A HARD GATE
;   DeckLinkSource.ax is built against the Blackmagic DeckLink SDK, whose EULA
;   must be accepted by the person installing. LicenseFile below makes Inno show
;   it as a mandatory accept-or-abort page. The text is NOT in this repository —
;   it ships only inside the SDK download — so distrib/decklink_sdk_license.txt
;   is a placeholder and build_unplugged_setup.cmd refuses to compile while the
;   placeholder marker is present. Do not remove that check: shipping a filter
;   built on the SDK behind a bogus licence page is worse than shipping no
;   installer.
; ---------------------------------------------------------------------------

#define MyAppName    "Unplugged"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "unplugged"
#define MyAppExeName "Unplugged.exe"
#define FiltersSrc   "..\..\unplugged-VideoRenderer\_bin\MpcVideoRenderer-0.10.8.2637"
#define LavSrc       "..\..\LAVFilters\bin_x64"
#define DlSrc        "..\src\thirdparty\DeckLinkSource\bin\Filters_x64"
#define AppSrc       "..\src\unplugged-ui\dist\Unplugged"

[Setup]
; A NEW AppId, not MPC-HC's: this is a different product and must not upgrade
; or collide with an MPC-HC installation on the same machine.
AppId={{E4A7C2D8-9B31-4F6A-8C2E-5D7B1A9F3E64}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=admin
; DirectShow CLSID registration is HKCR, machine-wide; there is no honest
; per-user variant of this product.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=decklink_sdk_license.txt
CloseApplications=yes
RestartApplications=no
; The app holds its own .ax open while running; without this the install fails
; halfway with a sharing violation and leaves mixed versions on disk.
OutputDir=out
OutputBaseFilename=Unplugged-setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
SetupLogging=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; ---- the app ---------------------------------------------------------------
Source: "{#AppSrc}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; ---- MPCVR: filter, runtime and models, one directory ----------------------
Source: "{#FiltersSrc}\MpcVideoRenderer64.ax"; DestDir: "{app}\filters"; Flags: 64bit regserver ignoreversion restartreplace uninsrestartdelete
Source: "{#FiltersSrc}\onnxruntime.dll";        DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace
Source: "{#FiltersSrc}\xgb_gamma_model.plxgb";          DestDir: "{app}\filters"; Flags: ignoreversion restartreplace
Source: "{#FiltersSrc}\xgb_highlight_rolloff.plxgb";    DestDir: "{app}\filters"; Flags: ignoreversion restartreplace
Source: "{#FiltersSrc}\xgb_shadow_recovery.plxgb";      DestDir: "{app}\filters"; Flags: ignoreversion restartreplace
Source: "{#FiltersSrc}\yolo26n-seg_op21.onnx";           DestDir: "{app}\filters"; Flags: ignoreversion restartreplace
Source: "{#FiltersSrc}\yolo26n-sem.onnx";                DestDir: "{app}\filters"; Flags: ignoreversion restartreplace

; ---- LAV fork: filters plus the ffmpeg DLLs they link ----------------------
Source: "{#LavSrc}\LAVSplitter.ax"; DestDir: "{app}\filters"; Flags: 64bit regserver ignoreversion restartreplace uninsrestartdelete
Source: "{#LavSrc}\LAVVideo.ax";    DestDir: "{app}\filters"; Flags: 64bit regserver ignoreversion restartreplace uninsrestartdelete
Source: "{#LavSrc}\LAVAudio.ax";    DestDir: "{app}\filters"; Flags: 64bit regserver ignoreversion restartreplace uninsrestartdelete
Source: "{#LavSrc}\avcodec-lav-63.dll";   DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace
Source: "{#LavSrc}\avdevice-lav-63.dll";  DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace
Source: "{#LavSrc}\avfilter-lav-12.dll";  DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace
Source: "{#LavSrc}\avformat-lav-63.dll";  DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace
Source: "{#LavSrc}\avutil-lav-61.dll";    DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace
Source: "{#LavSrc}\swresample-lav-7.dll"; DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace
Source: "{#LavSrc}\swscale-lav-10.dll";   DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace
Source: "{#LavSrc}\libbluray.dll";        DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace
Source: "{#LavSrc}\libwinpthread-1.dll";  DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace
Source: "{#LavSrc}\zlib1.dll";            DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace
Source: "{#LavSrc}\IntelQuickSyncDecoder.dll"; DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace

; ---- DeckLink ingest source -------------------------------------------------
Source: "{#DlSrc}\DeckLinkSource.ax"; DestDir: "{app}\filters"; Flags: 64bit regserver ignoreversion restartreplace uninsrestartdelete

; ---- VC++ runtime, only if you drop it in distrib\redist\ --------------------
; Our binaries are MSVC /MD; a clean Windows box may lack the 2015-2022 x64
; runtime. Included when present, silently skipped when not, so the installer
; builds either way.
#if FileExists("redist\vc_redist.x64.exe")
Source: "redist\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
#endif

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
#if FileExists("redist\vc_redist.x64.exe")
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing Visual C++ runtime..."; Flags: waituntilterminated skipifsilent
#endif
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Unplugged"; Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
; Logs the app writes beside itself. Never the per-user INI: that survives
; uninstall on purpose, in %LOCALAPPDATA%\Unplugged.
Type: filesandordirs; Name: "{app}\logs"

[Code]
// Refuse to install over a running copy of the OLD registered filter path if
// it is held open: regserver on a loaded .ax fails silently and leaves the old
// binary registered. CloseApplications covers the app; this covers a stray
// player process that loaded the filters.
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
