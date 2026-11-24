@echo off
REM BSM Karma Builder
REM © Benoit Saint-Moulin - 2026
REM Version du fichier : 1.6.0
REM Fonction du fichier : Batch script that installs Karma Builder as a Houdini package for Houdini 21 and later by running the PowerShell install script.

rem Installs Karma Builder for Houdini 21 and later: one small package file, nothing is copied.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install_windows.ps1"
