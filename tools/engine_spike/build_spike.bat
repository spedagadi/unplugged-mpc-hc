@ECHO OFF
REM Build spikes: cleared CWD-search policy + vsdevcmd + cl
SET "NoDefaultCurrentDirectoryInExePath="
CALL "C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\Tools\vsdevcmd.bat" -arch=amd64 -host_arch=amd64 -no_logo >nul
SET "PATH=C:\msys64\ucrt64\bin;%PATH%"
PUSHD "%~dp0"
cl /nologo /EHsc /std:c++17 /W3 /utf-8 -DUNICODE -D_UNICODE engine_spike.cpp /link strmiids.lib ole32.lib oleaut32.lib user32.lib /out:engine_spike.exe
cl /nologo /EHsc /std:c++17 /W3 /utf-8 -DUNICODE -D_UNICODE s1_windowed.cpp /link strmiids.lib ole32.lib oleaut32.lib user32.lib gdi32.lib gdiplus.lib /out:s1_windowed.exe
ECHO BUILD_EXIT=%ERRORLEVEL%
