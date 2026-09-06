@ECHO OFF
SET "NoDefaultCurrentDirectoryInExePath="
CALL "C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\Tools\vsdevcmd.bat" -arch=amd64 -host_arch=amd64 -no_logo >nul
PUSHD "%~dp0"
cl /nologo /EHsc /W3 co_test.cpp /Fe:co_test.exe /link strmiids.lib ole32.lib
ECHO BUILD_EXIT=%ERRORLEVEL%
POPD
