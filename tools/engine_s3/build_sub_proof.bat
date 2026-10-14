@ECHO OFF
REM build_sub_proof.bat - compile the subtitle proof harness. It talks to s3engine.dll
REM through LoadLibrary/GetProcAddress only, so it needs no import library and no MFC.
SETLOCAL
SET "NoDefaultCurrentDirectoryInExePath="
CALL "C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\Tools\vsdevcmd.bat" -arch=amd64 -host_arch=amd64 -no_logo >nul
PUSHD "%~dp0"
cl /nologo /EHsc /std:c++17 /W3 /utf-8 /Ox sub_proof.cpp /link user32.lib gdi32.lib ole32.lib /out:sub_proof.exe
ECHO SUBPROOF_BUILD_EXIT=%ERRORLEVEL%
POPD
ENDLOCAL
