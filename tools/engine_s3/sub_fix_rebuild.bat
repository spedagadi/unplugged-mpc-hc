@ECHO OFF
REM sub_fix_rebuild.bat - rebuild everything that sees STSStyle.h's layout, deploy the
REM engine dll next to the packaged app, and run the subtitle proof harness.
REM
REM STSStyle.h now includes mpc-hc_config.h itself, because USE_LIBASS adds members to the
REM end of the class. Any TU that took the header without the config compiled a smaller
REM STSStyle, so the trailing CString was never constructed and STSStyle::operator= read a
REM wild pointer (the 0xC0000005 in CreateDefaultStyle). Layout is a link-time-invisible
REM contract, so every library that carries the class has to be rebuilt together.
REM
REM ASCII only: cmd tokenises bats as cp1252, and a non-ASCII dash corrupts the line.
SETLOCAL
SET "MSB=C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe"
SET "SD=C:\code\unplugged-mpc-hc\"
SET "LOG=%SD%tools\engine_s3\_sub_fix.log"
SET "DIST=%SD%src\unplugged-ui\dist\Unplugged\_internal"

ECHO ===== Subtitles > "%LOG%"
"%MSB%" "%SD%src\Subtitles\Subtitles.vcxproj" /p:Configuration=Release /p:Platform=x64 /p:SolutionDir=%SD% /m /nologo /v:minimal >> "%LOG%" 2>&1
IF ERRORLEVEL 1 ( ECHO FAILED_AT Subtitles & EXIT /B 1 )
ECHO STACK_OK Subtitles

ECHO ===== SubPic >> "%LOG%"
"%MSB%" "%SD%src\SubPic\SubPic.vcxproj" /p:Configuration=Release /p:Platform=x64 /p:SolutionDir=%SD% /m /nologo /v:minimal >> "%LOG%" 2>&1
IF ERRORLEVEL 1 ( ECHO FAILED_AT SubPic & EXIT /B 1 )
ECHO STACK_OK SubPic

CALL "%SD%tools\engine_s3\rebuild_engine.bat" > "%LOG%.engine" 2>&1
FINDSTR /C:"ENGINE_EXIT=0" "%LOG%.engine" >NUL
IF ERRORLEVEL 1 ( ECHO FAILED_AT engine & TYPE "%LOG%.engine" & EXIT /B 1 )
ECHO STACK_OK engine

CALL "%SD%tools\s3engine\build_s3engine.bat" > "%LOG%.s3" 2>&1
FINDSTR /C:"S3ENGINE_BUILD_EXIT=0" "%LOG%.s3" >NUL
IF ERRORLEVEL 1 ( ECHO FAILED_AT s3engine & TYPE "%LOG%.s3" & EXIT /B 1 )
ECHO STACK_OK s3engine

COPY /Y "%SD%tools\s3engine\s3engine.dll" "%DIST%\s3engine.dll" >NUL
IF ERRORLEVEL 1 ( ECHO FAILED_AT deploy - dist dll locked (close the app) & EXIT /B 1 )
COPY /Y "%SD%tools\s3engine\s3engine.pdb" "%DIST%\s3engine.pdb" >NUL
ECHO DEPLOY_OK
FOR %%F IN ("%DIST%\s3engine.dll") DO ECHO dist dll %%~zF bytes, %%~tF
EXIT /B 0
