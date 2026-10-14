@ECHO OFF
REM build_subtitle_stack.bat -- the third-party chain MPC-HC's internal subtitle
REM engine needs, in dependency order. None of these ship prebuilt in this fork.
REM
REM /p:SolutionDir IS LOAD-BEARING. Every one of these projects links its
REM dependencies from $(SolutionDir)bin\lib\Release_x64 and writes its own output
REM there too. Built standalone, SolutionDir is "*Undefined*", the outputs fall
REM into each project's directory and the next link dies with LNK1181 on a lib
REM that demonstrably exists on disk -- which is exactly how the first attempt
REM failed at harfbuzz.
REM
REM Stops at the first failure: a cascade of nine libraries failing at link four
REM is not diagnosable from one combined log.
SETLOCAL
SET "PATH=C:\msys64\ucrt64\bin;%PATH%"
SET "MSB=C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe"
SET "SD=C:\code\unplugged-mpc-hc\"
SET "TP=C:\code\unplugged-mpc-hc\src\thirdparty"
SET "LOG=C:\code\unplugged-mpc-hc\tools\engine_s3\_subtitle_stack.log"
TYPE NUL > "%LOG%"

CALL :BUILD zlib            "%TP%\zlib\zlib.vcxproj"                      || GOTO :FAIL
CALL :BUILD libiconv        "%TP%\libiconv\libiconv-for-Windows\libiconv.vcxproj" || GOTO :FAIL
CALL :BUILD libfribidi      "%TP%\fribidi\libfribidi.vcxproj"              || GOTO :FAIL
CALL :BUILD libunibreak     "%TP%\libunibreak\libunibreak.vcxproj"         || GOTO :FAIL
CALL :BUILD freetype2       "%TP%\freetype2\freetype2.vcxproj"             || GOTO :FAIL
CALL :BUILD libharfbuzz     "%TP%\harfbuzz\libharfbuzz.vcxproj"            || GOTO :FAIL
CALL :BUILD libass          "%TP%\libass\libass.vcxproj"                   || GOTO :FAIL
CALL :BUILD Subtitles       "C:\code\unplugged-mpc-hc\src\Subtitles\Subtitles.vcxproj" || GOTO :FAIL
CALL :BUILD SubPic          "C:\code\unplugged-mpc-hc\src\SubPic\SubPic.vcxproj"        || GOTO :FAIL
ECHO STACK_ALL_OK
ECHO STACK_ALL_OK >> "%LOG%"
GOTO :EOF

:FAIL
ECHO STACK_STOPPED_SEE_LOG
EXIT /B 1

:BUILD
ECHO. >> "%LOG%"
ECHO ===== %1 >> "%LOG%"
ECHO building %1 ...
"%MSB%" %2 /p:Configuration=Release /p:Platform=x64 /p:SolutionDir=%SD% /m /nologo /v:minimal >> "%LOG%" 2>&1
IF ERRORLEVEL 1 (
    ECHO STACK_FAILED_AT %1 >> "%LOG%"
    EXIT /B 1
)
ECHO STACK_OK %1 >> "%LOG%"
ECHO STACK_OK %1
EXIT /B 0
