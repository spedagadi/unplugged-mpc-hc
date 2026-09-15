@ECHO OFF
REM start_s3hud.bat - launch the ImGui HTPC shell (single instance).
REM   start_s3hud.bat             defaults to DeckLink Quad HDMI Recorder (1)
REM   start_s3hud.bat "Device N"  capture a specific HDMI input (2)/(3)/(4)
SETLOCAL
SET "NoDefaultCurrentDirectoryInExePath="
PUSHD "%~dp0"

SET "DEV=%~1"
IF "%DEV%"=="" SET "DEV=DeckLink Quad HDMI Recorder (1)"

REM The DeckLink card allows ONE capture owner; drop any stale shell first.
TASKKILL /IM s3_shell.exe /F >nul 2>&1
TASKKILL /IM s3hud.exe /F >nul 2>&1
TIMEOUT /T 1 /NOBREAK >nul

START "" "%~dp0s3hud.exe" --decklink-device "%DEV%"
ECHO s3hud started on "%DEV%"
POPD
ENDLOCAL