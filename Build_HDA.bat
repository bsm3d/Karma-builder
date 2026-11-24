@echo off
REM BSM Karma Builder
REM © Benoit Saint-Moulin - 2026
REM Version du fichier : 1.6.0
REM Fonction du fichier : Batch script that rebuilds bsm_karma_builder.hda from the sources with hython, using the newest Houdini found or a given folder.

rem Rebuilds bsm_karma_builder.hda from the sources with hython.
rem Uses the newest Houdini found in Program Files, or the folder given as argument:
rem   Build_HDA.bat "C:\Program Files\Side Effects Software\Houdini 22.0.466"
setlocal
set "HFS=%~1"
if "%HFS%"=="" for /f "delims=" %%d in ('dir /b /ad /o-n "C:\Program Files\Side Effects Software\Houdini 2*" 2^>nul') do if not defined HFS set "HFS=C:\Program Files\Side Effects Software\%%d"
if not exist "%HFS%\bin\hython.exe" (
    echo hython not found, pass the Houdini folder as argument.
    pause
    exit /b 1
)
echo Using %HFS%
"%HFS%\bin\hython.exe" "%~dp0build_hda.py"
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)
echo Done: %~dp0bsm_karma_builder.hda
pause
