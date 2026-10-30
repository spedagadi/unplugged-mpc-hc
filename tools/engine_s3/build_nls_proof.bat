@ECHO OFF
REM build_nls_proof.bat - compile the bidirectional-NLS proof harness. It talks to
REM s3engine.dll through LoadLibrary/GetProcAddress only, so it needs no import
REM library and no MFC.
SETLOCAL
SET "NoDefaultCurrentDirectoryInExePath="
CALL "C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\Tools\vsdevcmd.bat" -arch=amd64 -host_arch=amd64 -no_logo >nul
PUSHD "%~dp0"
cl /nologo /EHsc /std:c++17 /W3 /utf-8 /Ox nls_proof.cpp /link user32.lib gdi32.lib ole32.lib /out:nls_proof.exe
ECHO NLSPROOF_BUILD_EXIT=%ERRORLEVEL%
POPD
ENDLOCAL