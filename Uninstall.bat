@echo off
rem Removes the package file written by Install.bat. The folder of the tool is not touched.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install_windows.ps1" -Uninstall
