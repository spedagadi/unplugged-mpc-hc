@ECHO OFF
SETLOCAL
SET "NoDefaultCurrentDirectoryInExePath="
CALL "C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\Tools\vsdevcmd.bat" -arch=amd64 -host_arch=amd64 -no_logo >nul
PUSHD "%~dp0"
cl /nologo /EHsc /std:c++17 /W4 /utf-8 /I"..\..\src\mpchc_engine" /I"..\..\src\thirdparty\DeckLinkSource" s3_shell.cpp /link "..\..\src\mpchc_engine\bin\lib\Release_x64\mpchc_engine.lib" strmiids.lib mfuuid.lib mf.lib mfplat.lib ole32.lib oleaut32.lib user32.lib gdi32.lib comdlg32.lib comctl32.lib /out:s3_shell.exe
ECHO BUILD_EXIT=%ERRORLEVEL%
POPD
ENDLOCAL