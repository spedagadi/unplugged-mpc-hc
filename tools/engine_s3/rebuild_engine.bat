@ECHO OFF
PUSHD "%~dp0"
SET "NoDefaultCurrentDirectoryInExePath="
CALL "C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\Tools\vsdevcmd.bat" -arch=amd64 -host_arch=amd64 -no_logo >nul
REM "10.0" = latest installed Windows SDK (never pin a specific build)
SET "MPCHC_WINSDK_VER=10.0"
msbuild ..\..\src\mpchc_engine\mpchc_engine.vcxproj /p:Configuration=Release /p:Platform=x64 /p:WindowsTargetPlatformVersion=10.0 /p:ML_MPCVR_INCLUDE=C:\Code\VideoRenderer\Source /nologo /verbosity:minimal
ECHO ENGINE_EXIT=%ERRORLEVEL%
POPD
