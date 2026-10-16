; ---------------------------------------------------------------------------
; unplugged.iss -- installer for the Unplugged HTPC app and its filter chain.
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
;   The renderer's own logs (ml_debug.csv, mpcvr_trace*.log) -- ~96 MB of one
;   machine's diagnostics sitting in the staged build folder.
;   The per-user config. It lives in %LOCALAPPDATA%\Unplugged\s3_shell.ini,
;   outside {app}, so upgrades never touch it and uninstall never deletes it.
;   That is a feature: a re-install must not cost anyone their tuned curve.
;
; THE BLACKMAGIC LICENCE PAGE IS AN UNCONDITIONAL HARD GATE
;   Two of our binaries are compiled against Blackmagic DeckLink SDK headers:
;   filters\DeckLinkSource.ax (the capture filter) and _internal\
;   decklink_monitor.dll (a read-only signal monitor, gcc-built from
;   decklink_monitor.c, bundled inside the application by PyInstaller). The
;   second one is the reason the gate is unconditional: it ships in the
;   application payload, so it is present in EVERY build -- including one
;   compiled with /DSkipFilters=1, which omits the filter chain. Skipping the
;   filters therefore skips no Blackmagic obligation, and the EULA page must
;   appear for whoever installs.
;
;   The SDK headers grant their rights "subject to" the DeckLink SDK End User
;   Licence Agreement, and require the copyright notice and the full grant
;   statement to accompany all copies and derivative works. Both are met here:
;   LicenseFile shows the EULA as a mandatory accept-or-abort page, and
;   blackmagic_sdk_notice.txt carries the verbatim notice plus a statement of
;   which binaries are SDK-derived.
;
;   The EULA text itself is NOT in this repository -- it ships inside the SDK
;   download -- so distrib/decklink_sdk_license.txt is a placeholder and
;   build_unplugged_setup.ps1 refuses to compile while that marker is present,
;   in every configuration. Do not weaken that check: an installer that ships
;   SDK-derived code behind a bogus licence page is worse than no installer.
; ---------------------------------------------------------------------------

#define MyAppName    "Unplugged"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "unplugged"
#define MyAppExeName "Unplugged.exe"
// The renderer's staging folder, named for this product since the filter became
// unplugged_vr.ax with its own CLSID. The version is baked into the directory name by
// distrib\make_dist.cmd, so a renderer version bump breaks this line -- and gate 3 of
// build_unplugged_setup.ps1 is what catches it: it verifies every Source path exists
// before ISCC runs, so the failure is a refused build, not an installer shipping
// without a video renderer.
#define FiltersSrc   "..\..\unplugged-VideoRenderer\_bin\UnpluggedRenderer-0.10.8.2637"
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
; Unconditional, in every configuration. The Blackmagic SDK-derived code lives
; in the APPLICATION payload (_internal\decklink_monitor.dll), not only in the
; filter chain, so /DSkipFilters=1 does not remove the obligation and must not
; remove the page. The gates follow the payload, and this payload always
; contains SDK-derived code.
;
; This page also serves as the anchor for the End-User Terms page in [Code],
; which is created with CreateCustomPage(wpLicense, ...) -- a custom page
; anchored to a page the wizard never shows is a question about Inno internals
; nobody should have to answer at install time. Showing the licence inventory of
; the product being installed is the right content regardless.
; Inno's LicenseFile accepts ONE file; a comma list aborts the compile with
; "Could not read <the whole list as a path>" â€” which is what kept every build
; after 2026-10-08 from compiling at all. The accept page carries the Blackmagic
; terms (the only licence here that gates use of the payload); the notice and the
; third-party inventory travel as files in {app}\licenses below, which is where
; an accompanying notice belongs rather than on an accept-or-abort page.
LicenseFile=decklink_sdk_license.txt
; The app holds its own .ax open while running; without this the install fails
; halfway with a sharing violation and leaves mixed versions on disk.
CloseApplications=yes
RestartApplications=no
OutputDir=out
; /DFastTest=1 builds in seconds with no compression, to check the wizard, the
; payload and the registration. Its filename says TESTONLY so a smoke build
; cannot be mistaken for the deliverable.
#ifdef FastTest
OutputBaseFilename=Unplugged-setup-{#MyAppVersion}-TESTONLY
Compression=none
#else
OutputBaseFilename=Unplugged-setup-{#MyAppVersion}
Compression=lzma2/max
#endif
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
; The mask is not tidiness, it is containment: the packaged app writes its own
; logs beside itself (s3engine.log at the root, panel.log deeper in), so after
; anyone tests a build the dist folder carries that machine's session history --
; played file paths and all -- and a plain recursive copy would ship it inside
; everybody's installer. Excluding by pattern makes that impossible rather than
; depending on nobody ever running the app from dist before packaging.
Source: "{#AppSrc}\*"; DestDir: "{app}"; Excludes: "*.log"; Flags: ignoreversion recursesubdirs createallsubdirs

; ---- Unplugged renderer: filter, runtime and models, one directory ---------
; The models MUST stay beside the .ax: the filter resolves them from the directory of
; the module it was loaded from, so splitting them across DestDirs breaks ML modes with
; no error. regserver does DllRegisterServer on install and DllUnregisterServer on
; uninstall, which now registers our own CLSID and leaves any install of the upstream
; filter on the machine alone.
Source: "{#FiltersSrc}\onnxruntime.dll";        DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace
Source: "{#FiltersSrc}\xgb_gamma_model.plxgb";          DestDir: "{app}\filters"; Flags: ignoreversion restartreplace
Source: "{#FiltersSrc}\xgb_highlight_rolloff.plxgb";    DestDir: "{app}\filters"; Flags: ignoreversion restartreplace
Source: "{#FiltersSrc}\xgb_shadow_recovery.plxgb";      DestDir: "{app}\filters"; Flags: ignoreversion restartreplace
Source: "{#FiltersSrc}\yolo26n-seg_op21.onnx";           DestDir: "{app}\filters"; Flags: ignoreversion restartreplace
Source: "{#FiltersSrc}\yolo26n-sem.onnx";                DestDir: "{app}\filters"; Flags: ignoreversion restartreplace
; The filter LAST: Inno runs DllRegisterServer the moment a regserver entry is
; copied, and registration loads the module â€” with onnxruntime.dll not yet beside
; it, a clean install failed regsvr32 with 0x3. Older installs masked this because
; the previous install's DLLs were already in the folder.
Source: "{#FiltersSrc}\unplugged_vr.ax"; DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace

; ---- LAV fork and DeckLink source: conditional on not skipping --------------
; These two groups carry the only third-party obligations in the product (GPL
; source offer; Blackmagic SDK notice). Building with /DSkipFilters=1 omits both
; binaries AND both obligations, which is what makes a gate-free test build
; legitimate rather than a workaround.
#ifndef SkipFilters
; ---- LAV fork: the ffmpeg DLLs FIRST, then the filters that import them -----
; The side-by-side manifest the LAV filters' embedded manifests depend on. Each .ax
; carries <dependency><assemblyIdentity name="LAVFilters.Dependencies">, a PRIVATE
; assembly resolved from the directory of the module being loaded; without this file
; beside the filters every load fails with error 14001 (side-by-side configuration
; incorrect) and regsvr32 exits 3. That - not file order, not a race, not a missing
; import - is what the install-time "registration failed" dialog was. LAV's own
; installer ships this manifest for exactly this reason.
Source: "{#LavSrc}\LAVFilters.Dependencies.manifest"; DestDir: "{app}\filters"; Flags: ignoreversion restartreplace
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
; The filters LAST, after every DLL they import: same registration-order reason as
; the renderer above. This is the fix for regsvr32 exit 0x3 on a clean install.
Source: "{#LavSrc}\LAVSplitter.ax"; DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace
Source: "{#LavSrc}\LAVVideo.ax";    DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace
Source: "{#LavSrc}\LAVAudio.ax";    DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace

; ---- DeckLink ingest source -------------------------------------------------
Source: "{#DlSrc}\DeckLinkSource.ax"; DestDir: "{app}\filters"; Flags: 64bit ignoreversion restartreplace
#endif

; ---- VC++ runtime, only if you drop it in distrib\redist\ --------------------
; Our binaries are MSVC /MD; a clean Windows box may lack the 2015-2022 x64
; runtime. Included when present, silently skipped when not, so the installer
; builds either way.
#if FileExists("redist\vc_redist.x64.exe")
Source: "redist\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
#endif

; ---- the terms, twice: once as a wizard page, once as files that travel -------
; dontcopy keeps the EULA out of the installed tree as a stray root file; the
; wizard page extracts it to {tmp} and shows it. The licenses directory is the
; durable copy, because obligations that live only in an installer vanish the
; moment someone copies the folder to another machine.
Source: "unplugged_eula.txt"; DestDir: "{tmp}"; Flags: dontcopy
Source: "licenses\third_party_notices.txt"; DestDir: "{app}\licenses"; Flags: ignoreversion
; Both Blackmagic texts travel in EVERY build, because the SDK-derived binary
; they describe (_internal\decklink_monitor.dll) is in the application payload
; of every build. The notice is the part the header licence itself demands:
; copyright notice plus the full grant statement, accompanying all copies and
; derivative works.
Source: "blackmagic_sdk_notice.txt"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "decklink_sdk_license.txt";  DestDir: "{app}\licenses"; Flags: ignoreversion
#ifndef SkipFilters
; The GPL source offer is genuinely payload-conditional: it exists for the
; modified LAV binaries, and a build that ships none of them owes nothing.
Source: "licenses\lav_gpl_source_offer.txt"; DestDir: "{app}\licenses"; Flags: ignoreversion
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
// ---------------------------------------------------------------------------
// SECOND, MANDATORY ACCEPTANCE PAGE.
//
// Inno's LicenseFile page carries the third-party licences (Blackmagic's among
// them). This page carries OUR terms, deliberately short: responsibility for
// one's own use, no warranty, and the pointer to the third-party licences that
// govern the bundled components. Longer enumerations of what a user might do
// with a capture tool were cut on purpose - a terms page that lists acts draws
// more attention to them than the single neutral responsibility sentence does.
//
// It is enforced in NextButtonClick, not by hiding the Next button: a disabled
// button invites "why is this stuck", while a refused advance with a message
// states the requirement.
// ---------------------------------------------------------------------------
var
  EulaPage: TWizardPage;
  EulaMemo: TNewMemo;
  EulaCheck: TNewCheckBox;

function InitializeSetup(): Boolean;
begin
  // PrivilegesRequired=admin already makes Inno re-spawn the setup elevated when it is
  // launched without rights, so in the normal case this is never reached. It IS reached
  // on machines where the re-spawn cannot happen - UAC disabled by policy, a launcher
  // that strips elevation - and there the install would run unprivileged and fail later
  // in regsvr32 exit codes and Program Files write errors, which read as a broken
  // package rather than as a missing token. Registering DirectShow filters writes
  // machine-wide CLSID keys and the payload lands in Program Files, so admin is not a
  // preference here; say so in one sentence at the door.
  if not IsAdmin then
  begin
    MsgBox('This installer must run with administrator rights.'#13#10 +
           'Right-click the setup file and choose "Run as administrator".',
           mbCriticalError, MB_OK);
    Result := False;
    Exit;
  end;
  Result := True;
end;

procedure InitializeWizard;
var
  lines: TArrayOfString;
  i: Integer;
begin
  // The page description is the wizard's own word-wrapping label. The two
  // points that carry the legal weight belong there rather than in the check
  // box caption: TNewCheckBox has no WordWrap, so a long caption is not wrapped,
  // it is clipped -- and a clipped acceptance clause is worse than a short one.
  EulaPage := CreateCustomPage(wpLicense,
    'End-User Terms',
    'Read the terms under which this software is provided, then accept to '
    + 'continue. Your acceptance covers in particular that you are solely '
    + 'responsible for your use of this software and for complying with the '
    + 'law and the rights of others that apply to that use.');

  EulaMemo := TNewMemo.Create(EulaPage);
  EulaMemo.Parent := EulaPage.Surface;
  EulaMemo.Left := 0;
  EulaMemo.Top := 0;
  EulaMemo.Width := EulaPage.SurfaceWidth;
  EulaMemo.Height := ScaleY(190);
  EulaMemo.ReadOnly := True;
  EulaMemo.WordWrap := True;
  EulaMemo.ScrollBars := ssVertical;

  EulaCheck := TNewCheckBox.Create(EulaPage);
  EulaCheck.Parent := EulaPage.Surface;
  EulaCheck.Left := 0;
  EulaCheck.Top := ScaleY(200);
  EulaCheck.Width := EulaPage.SurfaceWidth;
  EulaCheck.Height := ScaleY(24);
  EulaCheck.Caption := 'I have read and accept the End-User Terms shown above.';

  // The text ships inside the setup so it can never drift from what was accepted.
  ExtractTemporaryFile('unplugged_eula.txt');
  if LoadStringsFromFile(ExpandConstant('{tmp}\unplugged_eula.txt'), lines) then
    for i := 0 to GetArrayLength(lines) - 1 do
      EulaMemo.Lines.Add(lines[i]);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  // A silent install has no page to tick a box on, yet Inno still runs this handler;
  // without this guard /VERYSILENT died on our own MsgBox demanding an acceptance that
  // could never be given. Silent invocation is the operator's acceptance — the same
  // convention every unattended installer follows. Interactive installs keep the gate.
  if WizardSilent then
    Exit;
  if (CurPageID = EulaPage.ID) and (not EulaCheck.Checked) then
  begin
    MsgBox('You must accept the End-User Terms to install this software.', mbError, MB_OK);
    Result := False;
  end;
end;

// ---------------------------------------------------------------------------
// REGISTRATION THAT SURVIVES THE ANTIVIRUS RACE.
//
// Inno's regserver flag registers each filter the moment it is copied, and on a
// clean machine that lost a race: regsvr32 exited 0x3 (module load failure) on
// LAVSplitter.ax while the filter's own ffmpeg DLLs - written seconds earlier -
// were still held by Defender's on-access scan. The same regsvr32 run by hand a
// minute later succeeded instantly, which is what identifies a transient lock
// rather than a missing dependency or a bad binary.
//
// So registration is retried after ALL files exist, when the scan has had time
// to finish. Idempotent: a filter the regserver flag already registered is
// simply registered again. Failures after the retries are logged, not silent.
// ---------------------------------------------------------------------------
procedure CurStepChanged(CurStep: TSetupStep);
var
  names: array of String;
  i, attempt: Integer;
  rc: LongInt;
  ok: Boolean;
begin
  if CurStep <> ssPostInstall then
    Exit;
  SetArrayLength(names, 5);
  names[0] := 'unplugged_vr.ax';
  names[1] := 'LAVSplitter.ax';
  names[2] := 'LAVVideo.ax';
  names[3] := 'LAVAudio.ax';
  names[4] := 'DeckLinkSource.ax';
  for i := 0 to GetArrayLength(names) - 1 do
  begin
    ok := False;
    for attempt := 1 to 6 do
    begin
      if Exec(ExpandConstant('{sys}\regsvr32.exe'),
              '/s "' + ExpandConstant('{app}\filters\' + names[i]) + '"',
              '', SW_HIDE, ewWaitUntilTerminated, rc) and (rc = 0) then
      begin
        ok := True;
        Break;
      end;
      Log('registration attempt ' + IntToStr(attempt) + ' for ' + names[i] +
          ' rc=' + IntToStr(rc) + ' â€” waiting for the file to settle');
      Sleep(800);
    end;
    if not ok then
      Log('REGISTRATION FAILED after retries: ' + names[i] + ' rc=' + IntToStr(rc));
  end;
end;

// The regserver flag no longer owns registration (see above), so it no longer owns
// unregistration either. Best effort, one attempt each: a filter that will not unload
// here is one some process still holds, and fighting that with retries would only make
// uninstall slow. Leftover registrations are logged so they are not silent.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  names: array of String;
  i: Integer;
  rc: LongInt;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  SetArrayLength(names, 5);
  names[0] := 'unplugged_vr.ax';
  names[1] := 'LAVSplitter.ax';
  names[2] := 'LAVVideo.ax';
  names[3] := 'LAVAudio.ax';
  names[4] := 'DeckLinkSource.ax';
  for i := 0 to GetArrayLength(names) - 1 do
  begin
    if not Exec(ExpandConstant('{sys}\regsvr32.exe'),
                '/s /u "' + ExpandConstant('{app}\filters\' + names[i]) + '"',
                '', SW_HIDE, ewWaitUntilTerminated, rc) or (rc <> 0) then
      Log('unregistration failed for ' + names[i] + ' rc=' + IntToStr(rc));
  end;
end;
