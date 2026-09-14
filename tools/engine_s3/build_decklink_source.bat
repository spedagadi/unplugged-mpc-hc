@ECHO OFF
SETLOCAL
SET "NoDefaultCurrentDirectoryInExePath="
CALL "C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\Tools\vsdevcmd.bat" -arch=amd64 -host_arch=amd64 -no_logo >nul
PUSHD "%~dp0"
msbuild ..\..\src\thirdparty\DeckLinkSource\DeckLinkSource.vcxproj /p:Configuration="Release Filter" /p:Platform=x64 /nologo /verbosity:minimal
ECHO BUILD_EXIT=%ERRORLEVEL%
POPD
ENDLOCAL