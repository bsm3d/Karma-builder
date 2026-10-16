# install_windows.ps1 - installs BSM Karma Builder as a Houdini package, or removes it (-Uninstall).
#
# Run it through Install.bat / Uninstall.bat at the root of the repository. It writes one small file,
# packages/bsm_karma.json, in the preferences folder of every Houdini 21 or later found in your Documents folder. That
# file points Houdini at this folder: the tool, the BSM menu and the shelf are then loaded at start. Nothing is copied.
#
#   -Uninstall    remove that file again
#   -PrefsDir     use this preferences folder only (when Houdini keeps them somewhere else)
#   -Documents    look for houdiniNN.N folders here instead of in the Documents folder (for tests)
#   -NoPause      do not wait for a key at the end
#
# Revision : 16-10-2026 | Auteur : BSM
param(
    [switch]$Uninstall,
    [string]$PrefsDir = "",
    [string]$Documents = "",
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$script:failed = $false


# ------------------------------------------------------------
function Say($text) { Write-Host $text }


# ------------------------------------------------------------
function Finish($code) {
    if (-not $NoPause) { Read-Host "Press Enter to close" | Out-Null }
    exit $code
}


# ------------------------------------------------------------
# The folder of the repository: the one that holds bsm_karma and tools.
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$marker = Join-Path (Join-Path $root "bsm_karma") "__init__.py"
if (-not (Test-Path -LiteralPath $marker)) {
    Say "This script must stay in the tools folder of BSM Karma Builder (bsm_karma was not found next to it)."
    Finish 1
}
$rootJson = $root -replace "\\", "/"


# ------------------------------------------------------------
# Houdini 21 or later preferences folders: houdini21.0, houdini22.0 ... in Documents.
if ($PrefsDir) {
    if (-not (Test-Path -LiteralPath $PrefsDir -PathType Container)) {
        Say "The folder does not exist: $PrefsDir"
        Finish 1
    }
    $targets = @(Get-Item -LiteralPath $PrefsDir)
} else {
    if (-not $Documents) { $Documents = [Environment]::GetFolderPath("MyDocuments") }
    $targets = @(Get-ChildItem -LiteralPath $Documents -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^houdini(\d+)\.(\d+)$' -and [int]$Matches[1] -ge 21 })
    if ($targets.Count -eq 0) {
        Say "No Houdini 21 or 22 preferences folder found in $Documents."
        Say "Start Houdini once so that it creates its folder, then run this again."
        Say "If Houdini keeps its preferences elsewhere, run in PowerShell:"
        Say "  tools\install_windows.ps1 -PrefsDir 'C:\path\to\houdini22.0'"
        Finish 1
    }
}


# ------------------------------------------------------------
$packageJson = @"
{
    "enable": true,
    "path": "$rootJson",
    "env": [
        { "BSM_KARMA_ROOT": "$rootJson" },
        { "PYTHONPATH": { "method": "prepend", "value": "`$BSM_KARMA_ROOT" } }
    ]
}
"@


# ------------------------------------------------------------
# A copy of the tool made by an earlier way of installing would be loaded instead of this one: put it aside.
function Move-OldCopy($prefs) {
    $old = Join-Path (Join-Path (Join-Path $prefs "scripts") "python") "bsm_karma"
    if (Test-Path -LiteralPath (Join-Path $old "__init__.py")) {
        $kept = $old + ".old"
        if (Test-Path -LiteralPath $kept) { Remove-Item -LiteralPath $kept -Recurse -Force }
        Rename-Item -LiteralPath $old -NewName "bsm_karma.old"
        Say "  An older copy in scripts\python was renamed to bsm_karma.old."
    }
    $shelf = Join-Path (Join-Path $prefs "toolbar") "bsm_karma.shelf"
    if (Test-Path -LiteralPath $shelf) {
        $kept = $shelf + ".old"
        if (Test-Path -LiteralPath $kept) { Remove-Item -LiteralPath $kept -Force }
        Rename-Item -LiteralPath $shelf -NewName "bsm_karma.shelf.old"
        Say "  An older shelf file in toolbar was renamed to bsm_karma.shelf.old."
    }
}


# ------------------------------------------------------------
foreach ($prefs in $targets) {
    $packages = Join-Path $prefs.FullName "packages"
    $file = Join-Path $packages "bsm_karma.json"
    try {
        if ($Uninstall) {
            if (Test-Path -LiteralPath $file) {
                Remove-Item -LiteralPath $file -Force
                Say "$($prefs.Name): removed $file"
            } else {
                Say "$($prefs.Name): nothing to remove."
            }
        } else {
            New-Item -ItemType Directory -Force -Path $packages | Out-Null
            [System.IO.File]::WriteAllText($file, $packageJson, (New-Object System.Text.UTF8Encoding($false)))
            Say "$($prefs.Name): written $file"
            Move-OldCopy $prefs.FullName
        }
    } catch {
        Say "$($prefs.Name): failed: $($_.Exception.Message)"
        $script:failed = $true
    }
}

Say ""
if ($script:failed) {
    Say "Something failed, see above."
    Finish 1
}
if ($Uninstall) {
    Say "Done. Restart Houdini. The folder of the tool was not touched."
} else {
    Say "Done. Restart Houdini, then use the menu BSM > Karma Builder."
    Say "The tool is loaded from: $root"
    Say "Keep that folder where it is. If you move it, run Install.bat again."
}
Finish 0
