@ECHO OFF
REM build_s3hud.bat — build the Dear ImGui HTPC shell (s3hud.exe).
REM Links the proven mpchc_engine.lib + Dear ImGui (header-only) + D3D11.
REM   build_s3hud.bat             defaults to the Quad HDMI Recorder (1)
SETLOCAL
SET "NoDefaultCurrentDirectoryInExePath="
CALL "C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\Tools\vsdevcmd.bat" -arch=amd64 -host_arch=amd64 -no_logo >nul
PUSHD "%~dp0"

SET IMGUI=..\..\src\thirdparty\imgui
cl /nologo /EHsc /std:c++17 /W3 /utf-8 /Ox /DNDEBUG /I"..\..\src\mpchc_engine" /I"..\..\src\thirdparty\DeckLinkSource" /I"%IMGUI%" /I"%IMGUI%\backends" ^
  s3hud.cpp ^
  "%IMGUI%\imgui.cpp" "%IMGUI%\imgui_draw.cpp" "%IMGUI%\imgui_tables.cpp" "%IMGUI%\imgui_widgets.cpp" ^
  "%IMGUI%\backends\imgui_impl_dx11.cpp" ^
  /link "..\..\src\mpchc_engine\bin\lib\Release_x64\mpchc_engine.lib" ^
  strmiids.lib mfuuid.lib mf.lib mfplat.lib ole32.lib oleaut32.lib user32.lib gdi32.lib d3d11.lib dxgi.lib ^
  /out:s3hud.exe
ECHO HUD_BUILD_EXIT=%ERRORLEVEL%
POPD
ENDLOCAL