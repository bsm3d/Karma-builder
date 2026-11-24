@echo off
REM BSM Karma Builder
REM © Benoit Saint-Moulin - 2026
REM Version du fichier : 1.6.0
REM Fonction du fichier : Batch script that removes the package file written by Install.bat through the PowerShell install script, leaving the tool folder in place.

rem Removes the package file written by Install.bat. The folder of the tool is not touched.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install_windows.ps1" -Uninstall
