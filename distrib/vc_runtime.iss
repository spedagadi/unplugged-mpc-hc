// ---------------------------------------------------------------------------
// vc_runtime.iss -- the bundled VC++ 2015-2022 x64 runtime: is it needed?
//
// Included by unplugged.iss (which uses NeedVCRedist as a [Run] Check) and by
// distrib\vc_check_test.iss, which drives it against real directories holding
// real DLLs. One copy of this logic exists on purpose: a decision that is only
// tested in a transcription is a decision tested twice and trusted neither time.
//
// WHY THE RUNTIME IS BUNDLED -- and why this is not about our own code.
// Measured on the shipped payload: s3engine.dll, unplugged_vr.ax, the LAV fork
// and DeckLinkSource.ax name no VCRUNTIME140/MSVCP140 at all -- they link the
// CRT statically -- and the Python/Qt half carries app-local copies inside
// _internal, which load from their own folders and need nothing installed.
//
// One component does need the system runtime: filters\onnxruntime.dll,
// Microsoft's own prebuilt binary, which the renderer loads for the ML grade. It
// imports VCRUNTIME140.dll, VCRUNTIME140_1.dll, MSVCP140.dll and MSVCP140_1.dll,
// none of which sit beside it, so that load resolves them through the exe folder
// and System32. What this installer is therefore guaranteeing is "the ML grade
// can load its inference engine", not "the app can start".
//
// WHY NOT THE REGISTRY. This used to ask
// HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64 for
// Installed/Major/Minor/Bld. On a machine where the redistributable had just been
// uninstalled that key still reported 14.44.35211 while System32 no longer held
// VCRUNTIME140_1.dll: the check said "already installed", skipped, and the ML
// grade stayed broken. A registration left behind by another package is not
// evidence that the loader can resolve a name. The question is put to the files
// now, because files are what the process actually consults.
//
// Safe direction only: skip when EVERY required DLL is present at the bundled
// version or newer. Anything else -- missing, older, unreadable -- runs the
// redist, which installs or upgrades the runtime in place.
// ---------------------------------------------------------------------------

// The version actually sitting in distrib\redist\vc_redist.x64.exe.
// build_unplugged_setup.ps1 parses these three lines and refuses to compile if
// the bundled file disagrees, so the skip threshold cannot drift away from what
// the payload ships.
#define VC_REQ_MAJ 14
#define VC_REQ_MIN 44
#define VC_REQ_BLD 35211

// The names filters\onnxruntime.dll imports are listed in NeedVCRedistAt below,
// one call each. api-ms-win-crt-* is the UCRT and is part of Windows 10/11, so it
// is not asked about. (An earlier draft kept them in one #define to split at
// runtime: ISPP evaluates an unquoted define as an expression and the list came
// through as Pascal. Four calls are cheaper than that trap.)

// True when Dir\Dll exists and reports at least VC_REQ_MAJ.VC_REQ_MIN.VC_REQ_BLD.
function VcDllSatisfied(Dir: String; Dll: String): Boolean;
var
  s: String;
  nums: array[1..3] of Integer;
  i, dot: Integer;
begin
  Result := False;
  if not FileExists(Dir + '\' + Dll) then
  begin
    Log(Dll + ': not present in ' + Dir);
    Exit;
  end;
  s := '';
  if not GetVersionNumbersString(Dir + '\' + Dll, s) then
  begin
    Log(Dll + ': no readable version resource in ' + Dir);
    Exit;
  end;
  // s arrives as '14.44.35211.0'; the first three dotted parts are what matter.
  // StrToIntDef(-1) turns a garbage part into a failed comparison, which chooses
  // "install" -- the harmless direction.
  for i := 1 to 3 do
  begin
    dot := Pos('.', s);
    if dot > 0 then
    begin
      nums[i] := StrToIntDef(Copy(s, 1, dot - 1), -1);
      Delete(s, 1, dot);
    end
    else
    begin
      nums[i] := StrToIntDef(s, -1);
      s := '';
    end;
  end;
  if (nums[1] > {#VC_REQ_MAJ}) or ((nums[1] = {#VC_REQ_MAJ}) and
     ((nums[2] > {#VC_REQ_MIN}) or ((nums[2] = {#VC_REQ_MIN}) and
      (nums[3] >= {#VC_REQ_BLD})))) then
  begin
    Result := True;
    Exit;
  end;
  Log(Dll + ': present but older than required (found ' +
      IntToStr(nums[1]) + '.' + IntToStr(nums[2]) + '.' + IntToStr(nums[3]) +
      ' in ' + Dir + ')');
end;

// Every imported name must be satisfied: one stale file fails the load.
function NeedVCRedistAt(Dir: String): Boolean;
var
  allOk: Boolean;
begin
  allOk := True;
  if not VcDllSatisfied(Dir, 'VCRUNTIME140.dll') then allOk := False;
  if not VcDllSatisfied(Dir, 'VCRUNTIME140_1.dll') then allOk := False;
  if not VcDllSatisfied(Dir, 'MSVCP140.dll') then allOk := False;
  if not VcDllSatisfied(Dir, 'MSVCP140_1.dll') then allOk := False;
  if allOk then
    Log('VC++ runtime DLLs in ' + Dir + ' all satisfy ' +
        '{#VC_REQ_MAJ}.{#VC_REQ_MIN}.{#VC_REQ_BLD} - skipping the bundled redist')
  else
    Log('VC++ runtime incomplete in ' + Dir + ' - installing the bundled redist');
  Result := not allOk;
end;

// The [Run] Check entry point. Inno fixes the signature: a Check function takes
// no parameters.
function NeedVCRedist(): Boolean;
begin
  Result := NeedVCRedistAt(ExpandConstant('{sys}'));
end;
