@ECHO OFF
REM start_vp.bat - launch s3_shell straight into DeckLink VP capture.
REM   start_vp.bat             auto-selects "DeckLink Quad HDMI Recorder (1)"
REM   start_vp.bat "Device N"  capture a specific HDMI input (2)/(3)/(4)

SETLOCAL
SET "NoDefaultCurrentDirectoryInExePath="
PUSHD "%~dp0"

SET "DEV=%~1"
IF "%DEV%"=="" SET "DEV=DeckLink Quad HDMI Recorder (1)"

REM The DeckLink card allows ONE capture owner; drop any stale shell first.
TASKKILL /IM s3_shell.exe /F >nul 2>&1
TIMEOUT /T 1 /NOBREAK >nul

START "" "%~dp0s3_shell.exe" --decklink-device "%DEV%"
ECHO s3_shell VP capture started on "%DEV%"
POPD
ENDLOCAL