---
name: build-s3-shell
description: Build the DeckLink ingest UI + engine (mpchc_engine.lib and s3_shell.exe) on zion-s3-shell. Use when asked to build the player shell/engine output, rebuild after MpcPlayer.cpp or s3_shell.cpp edits, or fix graph/DeckLink engine compile errors.
---

# Build s3_shell + mpchc_engine (DeckLink ingest UI)

Target artifacts:
- `src\mpchc_engine\bin\lib\Release_x64\mpchc_engine.lib` (the engine: `MpcPlayer.cpp` + `DeckLinkMonitor.cpp`)
- `tools\engine_s3\s3_shell.exe` (the frameless control UI that links the engine lib)

## Critical: don't build the whole player

The repo's root `build.bat` builds the **full mpc-hc player**, which is NOT our
deliverable and pulls a long dependency chain (MSYS bash, mingw libs, Inno Setup,
etc.) that is not needed here. The trail deliverable is just the engine lib + the
shell. Use the two scripts under `tools\engine_s3\` instead.

## Environment prerequisites (fresh box, VS2022 17.14 + MSYS2 UCRT64)

- **git not on PATH** (GitHub Desktop only). Not strictly needed for the bat
  scripts below (they bin git into the build env), but harmless to prepend.
- **`cmd` will not resolve a bare `*.bat` from the CWD** (NoDefaultCurrentDirectoryInExePath
  set in this shell): always invoke scripts by full path:
  `cmd /c "C:\code\unplugged-mpc-hc\tools\engine_s3\..."`

## Engine lib first

```powershell
cmd /c "C:\code\unplugged-mpc-hc\tools\engine_s3\rebuild_engine.bat"
```

`rebuild_engine.bat` internally runs:
```
CALL <VS>\Common7\Tools\vsdevcmd.bat -arch=amd64 -host_arch=amd64 -no_logo
SET "MPCHC_WINSDK_VER=10.0"
msbuild ..\..\src\mpchc_engine\mpchc_engine.vcxproj /p:Configuration=Release /p:Platform=x64 /p:WindowsTargetPlatformVersion=10.0 /p:ML_MPCVR_INCLUDE=<VideoRenderer>\Source /p:LAV_INCLUDE=..\..\src\thirdparty\LAVFilters\src\include
```
- `MPCHC_WINSDK_VER` must be `10.0` (latest installed SDK). Watch out: the default
  in `src\platform.props` was 8.1 and would fail on a box without the 8.1 SDK —
  it's now retargeted to `10.0` at `src\platform.props`.
- `ML_MPCVR_INCLUDE` → the `Source` dir of the VideoRenderer repo (for
  `IVideoRenderer.h` — the engine QIs MPCVR's interface at runtime).
- `LAV_INCLUDE` → `src\thirdparty\LAVFilters\src\include` (bundled LAVFilters
  headers, e.g. `LAVAudioSettings.h`, `FilterInterfaces.h` at repo `include\`).

Expected outcome: `mpchc_engine.lib` with `ENGINE_EXIT=0`. Warnings are fine
(ATL attribute deprecation C4467, wchar→char C4244).

## Then s3_shell

```powershell
cmd /c "C:\code\unplugged-mpc-hc\tools\engine_s3\build_s3_shell.bat"
```

Compiles `tools\engine_s3\s3_shell.cpp` with `cl` against
`src\mpchc_engine\bin\lib\Release_x64\mpchc_engine.lib` + DirectShow/MF/Win32 libs.
Expected: `tools\engine_s3\s3_shell.exe` (~550 KB), `BUILD_EXIT=0`.

## Regression backstop

`MpcPlayer.cpp` (engine) changes affect the IGraphBuilder graph: LAVSplitterSource
`decklink://` → decoder → MPCVR; audio → LAVAudio + MpcAudioRenderer (WASAPI
bitstream). `s3_shell.cpp` is UI-only. After any edit: run engine script → shell
script in that order (s3_shell links the engine lib).

## Runtime wiring (why things must be registered)

`s3_shell.exe` finds filters by CLSID at run time:
- MPCVR: `MpcVideoRenderer64.ax` must be `regsvr32`'d (see the build-mpcvr skill).
- DeckLink LAVSplitter: the **fork** LAVFilters build's `LAVSplitter.ax` must be
  registered (see the build-lavfilters skill), not LAV from the bundled submodule.
- Audio: MpcAudioRenderer has a regsvr32 quirk — pin the `InprocServer32` of
  `{601D2A2B-9CDE-40bd-8650-0485E3522727}` to the .ax path (see
  `docs\DeckLink-Working-Trail.md`).

Diagnostics: `s3_shell_diag.log` beside the exe (`[AUDIO]`, `[DECKLINK]` lines).