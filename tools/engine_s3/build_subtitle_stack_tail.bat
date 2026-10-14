@ECHO OFF
REM Tail of the subtitle stack: libass -> Subtitles -> SubPic, after the iconv fixup.
REM
REM libiconv's Release|x64 configuration produces a 3 KB IMPORT library for iconv.dll,
REM which would make the engine depend on shipping that DLL. ReleaseStatic produces the
REM object code instead; libass asks for the name "libiconv.lib", so the static lib is
REM copied under that name into the shared lib dir. If iconv ever misbehaves at link or
REM run time, this copy is the first thing to look at.
SETLOCAL
SET "PATH=C:\msys64\ucrt64\bin;%PATH%"
SET "MSB=C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe"
SET "SD=C:\code\unplugged-mpc-hc\"
SET "TP=C:\code\unplugged-mpc-hc\src\thirdparty"
SET "LOG=C:\code\unplugged-mpc-hc\tools\engine_s3\_subtitle_stack.log"

ECHO ===== libiconv static >> "%LOG%"
"%MSB%" "%TP%\libiconv\libiconv-for-Windows\libiconv.vcxproj" /p:Configuration=ReleaseStatic /p:Platform=x64 /p:SolutionDir=%SD% /m /nologo /v:minimal >> "%LOG%" 2>&1
IF ERRORLEVEL 1 ( ECHO STACK_FAILED_AT libiconv-static & EXIT /B 1 )
IF NOT EXIST "%SD%output\x64\ReleaseStatic\libiconvStatic.lib" (
    ECHO STACK_FAILED_AT libiconv-static-missing-output & EXIT /B 1
)
IF NOT EXIST "%SD%bin\lib\Release_x64" MKDIR "%SD%bin\lib\Release_x64"
COPY /Y "%SD%output\x64\ReleaseStatic\libiconvStatic.lib" "%SD%bin\lib\Release_x64\libiconv.lib" >NUL
ECHO STACK_OK libiconv-static

CALL :BUILD libass    "%TP%\libass\libass.vcxproj"
CALL :BUILD Subtitles "%SD%src\Subtitles\Subtitles.vcxproj"
CALL :BUILD SubPic    "%SD%src\SubPic\SubPic.vcxproj"
ECHO STACK_TAIL_OK
GOTO :EOF

:BUILD
ECHO. >> "%LOG%"
ECHO ===== %1 >> "%LOG%"
ECHO building %1 ...
"%MSB%" %2 /p:Configuration=Release /p:Platform=x64 /p:SolutionDir=%SD% /m /nologo /v:minimal >> "%LOG%" 2>&1
IF ERRORLEVEL 1 (
    ECHO STACK_FAILED_AT %1 >> "%LOG%"
    ECHO STACK_FAILED_AT %1
    EXIT /B 1
)
ECHO STACK_OK %1 >> "%LOG%"
ECHO STACK_OK %1
EXIT /B 0
