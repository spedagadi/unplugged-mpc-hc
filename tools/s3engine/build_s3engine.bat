@ECHO OFF
REM build_s3engine.bat — build s3engine.dll (C-ABI host for the PyQt client UI).
SETLOCAL
SET "NoDefaultCurrentDirectoryInExePath="
CALL "C:\Program Files\Microsoft Visual Studio\2022\Professional\Common7\Tools\vsdevcmd.bat" -arch=amd64 -host_arch=amd64 -no_logo >nul
PUSHD "%~dp0"

REM The subtitle stack (MPC-HC's internal engine) rides inside mpchc_engine.lib, and it
REM is not header-only: the subpic queue, the libass/rasterizer decoders and their
REM third-party deps are static libs built by tools\engine_s3\build_subtitle_stack.bat
REM into ..\..\bin\lib\Release_x64. Link them here or the engine's new symbols dangle.
REM WIN32_LEAN_AND_MEAN keeps windows.h from pulling winsock.h, which would collide
REM with the winsock2.h that MFC (via mpchc_engine.lib's headers) requires first.
REM MpcPlayer.h now exposes the subtitle stack (ISubPic.h, ISubtitleHost.h, CCritSec),
REM so every consumer of the engine needs the same header world the engine compiles
REM against: BaseClasses for streams.h, plus the MPC-HC subsystem dirs.
REM /MT is mandatory, not a preference: mpchc_engine.lib is MFC-static on the static
REM CRT (common.props), and MpcPlayer.h now includes afxwin.h for the subtitle stack. A
REM /MD TU that touches MFC asks for uafxcw.lib, which collides symbol-for-symbol with
REM the engine's nafxcw.lib (LNK2005 on CFile::hFileNull & co). Same runtime as the lib
REM or the link cannot be made to work at all.
REM /D_UNICODE /DUNICODE are NOT optional: MpcPlayer.h pulls afxwin.h, and static MFC
REM selects its library by CHARACTER SET - uafxcw for Unicode, nafxcw for ANSI (afx.h,
REM the _AFX_NOFORCE_LIBS block). Every project in the chain is CharacterSet=Unicode;
REM this cl line is the only TU built by hand, and without the defines it asked for
REM nafxcw and collided symbol-for-symbol with the rest (LNK2005, CFile::hFileNull).
REM Keep this file pure ASCII: cmd parses bats as cp1252 and an em dash tokenises it.
cl /nologo /EHsc /std:c++17 /W3 /utf-8 /Ox /MT /DNDEBUG /DWIN32_LEAN_AND_MEAN /D_UNICODE /DUNICODE ^
  /I"..\..\src\mpchc_engine" /I"..\..\src\thirdparty\DeckLinkSource" ^
  /I"..\..\src\thirdparty" /I"..\..\src\thirdparty\BaseClasses" ^
  /I"..\..\src\SubPic" /I"..\..\src\Subtitles" /I"..\..\src\DSUtil" ^
  /I"..\..\src\filters\renderer\VideoRenderers" ^
  s3engine.cpp ^
  /LD /Fe:s3engine.dll /link /DEBUG:FULL "..\..\bin\lib\Release_x64\mpchc_engine.lib" ^
  /LIBPATH:"..\..\bin\lib\Release_x64" /LIBPATH:"..\..\src\thirdparty\BaseClasses\bin\lib\Release_x64" ^
  BaseClasses.lib ^
  SubPic.lib Subtitles.lib DSUtil.lib unrar.lib libass.lib libharfbuzz.lib freetype2.lib libfribidi.lib libunibreak.lib zlib.lib libiconv.lib ^
  strmiids.lib mfuuid.lib mf.lib mfplat.lib ole32.lib oleaut32.lib user32.lib gdi32.lib dbghelp.lib version.lib vfw32.lib wininet.lib
ECHO S3ENGINE_BUILD_EXIT=%ERRORLEVEL%
POPD
ENDLOCAL