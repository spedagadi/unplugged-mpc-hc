@echo off
rem Build decklink_monitor.dll with MSVC (x64).
rem
rem Usage:
rem   build_monitor.bat [sdk_include_dir]
rem
rem sdk_include_dir must contain DeckLinkAPI.h and DeckLinkAPI_i.c.
rem Default is the LAVFilters tree (kept in sync with the capture path).
rem
rem Why MSVC and not gcc/msys: gcc builds of this DLL have silently produced
rem binaries with a stale/missing export table under the agent sandbox. If you
rem do build with gcc, verify the export list afterwards (see README).
setlocal
set SDKDIR=%~1
if "%SDKDIR%"=="" set SDKDIR=C:\code\LAVFilters\ffmpeg\decklink
if not exist "%SDKDIR%\DeckLinkAPI.h" (
  echo SDK header not found: %SDKDIR%\DeckLinkAPI.h
  exit /b 1
)

set VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat
if not exist "%VCVARS%" (
  echo vcvars64.bat not found: %VCVARS%
  exit /b 1
)

call "%VCVARS%" >nul
cd /d "%~dp0"

cl /nologo /LD /O2 /W3 /D_CRT_SECURE_NO_WARNINGS /I"%SDKDIR%" ^
   decklink_monitor.c "%SDKDIR%\DeckLinkAPI_i.c" ^
   /Fe:decklink_monitor.dll ^
   /link ole32.lib oleaut32.lib uuid.lib
if errorlevel 1 (
  echo BUILD FAILED
  exit /b 1
)

del /q *.obj 2>nul
echo BUILT: %~dp0decklink_monitor.dll
dumpbin /exports decklink_monitor.dll | findstr vf_dl_