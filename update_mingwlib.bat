@ECHO OFF
REM (C) 2009-2019 see Authors.txt
REM
REM This file is part of MPC-HC.
REM
REM MPC-HC is free software; you can redistribute it and/or modify
REM it under the terms of the GNU General Public License as published by
REM the Free Software Foundation; either version 3 of the License, or
REM (at your option) any later version.
REM
REM MPC-HC is distributed in the hope that it will be useful,
REM but WITHOUT ANY WARRANTY; without even the implied warranty of
REM MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
REM GNU General Public License for more details.
REM
REM You should have received a copy of the GNU General Public License
REM along with this program.  If not, see <http://www.gnu.org/licenses/>.

SETLOCAL
SET "FILE_DIR=%~dp0"
PUSHD "%FILE_DIR%"

IF EXIST "build.user.bat" CALL "%~dp0build.user.bat"

IF DEFINED MPCHC_MINGW64 GOTO VarOk
ECHO ERROR: Please define MPCHC_MINGW64 environment variable
ENDLOCAL
EXIT /B

:VarOk

FOR /f "tokens=1,2 delims=" %%K IN (
  '%MPCHC_MINGW64%\bin\gcc -dumpversion'
) DO (
  SET "gccver=%%K" & Call :SubGCCVer %%gccver:*Z=%%
)

SET LIBDIR=lib

COPY /V /Y "%MPCHC_MINGW64%\lib\gcc\i686-w64-mingw32\%gccver%\libgcc.a" %LIBDIR%\
COPY /V /Y "%MPCHC_MINGW64%\lib\gcc\x86_64-w64-mingw32\%gccver%\libgcc.a" %LIBDIR%64\

IF EXIST "%MPCHC_MINGW64%\i686-w64-mingw32\lib\libmingwex.a" COPY /V /Y "%MPCHC_MINGW64%\i686-w64-mingw32\lib\libmingwex.a" %LIBDIR%\
IF NOT EXIST "%MPCHC_MINGW64%\i686-w64-mingw32\lib\libmingwex.a" IF EXIST "%MPCHC_MINGW64%\lib\libmingwex.a" COPY /V /Y "%MPCHC_MINGW64%\lib\libmingwex.a" %LIBDIR%\
IF NOT EXIST "%MPCHC_MINGW64%\lib\libmingwex.a" EXIT /B 1
lib -remove:lib32_libmingwex_a-strtoimax.o -remove:lib32_libmingwex_a-strtof.o -remove:lib32_libmingwex_a-cos.o -remove:lib32_libmingwex_a-sin.o -remove:lib32_libmingwex_a-pow.o -remove:lib32_libmingwex_a-sqrt.o -remove:lib32_libmingwex_a-powi.o "%LIBDIR%\libmingwex.a" 
MOVE /Y %LIBDIR%\libmingwex.lib %LIBDIR%\libmingwex-stripped.a

IF EXIST "%MPCHC_MINGW64%\x86_64-w64-mingw32\lib\libmingwex.a" COPY /V /Y "%MPCHC_MINGW64%\x86_64-w64-mingw32\lib\libmingwex.a" %LIBDIR%64\
IF NOT EXIST "%MPCHC_MINGW64%\x86_64-w64-mingw32\lib\libmingwex.a" COPY /V /Y "%MPCHC_MINGW64%\lib\libmingwex.a" %LIBDIR%64\
IF NOT EXIST "%MPCHC_MINGW64%\lib\libmingwex.a" EXIT /B 1
lib -remove:lib64_libmingwex_a-strtoimax.o -remove:lib64_libmingwex_a-strtof.o -remove:lib64_libmingwex_a-cos.o -remove:lib64_libmingwex_a-sin.o -remove:lib64_libmingwex_a-pow.o -remove:lib64_libmingwex_a-sqrt.o -remove:lib64_libmingwex_a-sqrtf.o -remove:lib64_libmingwex_a-powi.o "%LIBDIR%64\libmingwex.a"
MOVE /Y %LIBDIR%64\libmingwex.lib %LIBDIR%64\libmingwex-stripped.a

EXIT /B

:SubGCCVer
SET gccver=%*
@ECHO gccver=%*
EXIT /B
