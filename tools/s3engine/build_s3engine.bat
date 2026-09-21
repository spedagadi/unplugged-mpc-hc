@ECHO OFF
REM build_s3engine.bat — build s3engine.dll (C-ABI host for the PyQt client UI).
SETLOCAL
SET "NoDefaultCurrentDirectoryInExePath="
CALL "C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\Tools\vsdevcmd.bat" -arch=amd64 -host_arch=amd64 -no_logo >nul
PUSHD "%~dp0"

cl /nologo /EHsc /std:c++17 /W3 /utf-8 /Ox /DNDEBUG /I"..\..\src\mpchc_engine" /I"..\..\src\thirdparty\DeckLinkSource" s3engine.cpp ^
  /LD /Fe:s3engine.dll /link "..\..\src\mpchc_engine\bin\lib\Release_x64\mpchc_engine.lib" ^
  strmiids.lib mfuuid.lib mf.lib mfplat.lib ole32.lib oleaut32.lib user32.lib gdi32.lib dbghelp.lib
ECHO S3ENGINE_BUILD_EXIT=%ERRORLEVEL%
POPD
ENDLOCAL