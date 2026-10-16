# Runs the BSM Karma Builder tests against an installed Houdini.
#
#   .\tests\run_tests.ps1               headless tests (hython), about 30 s
#   .\tests\run_tests.ps1 -Gui          also the dialog lifecycle test in Houdini, windows hidden
#   .\tests\run_tests.ps1 -Gui -Visible same, with the windows shown (a Karma viewport race only shows when visible)
#   .\tests\run_tests.ps1 -Screenshots  regenerates docs\screenshots (hidden windows); no test is run
#
# Exit code: 0 when every check passed, 1 otherwise.
param(
    [switch]$Gui,
    [switch]$Visible,
    [switch]$Screenshots,
    [string]$Hfs = "C:\Program Files\Side Effects Software\Houdini 22.0.459",
    [int]$GuiTimeoutSec = 170
)

$root = Split-Path -Parent $PSScriptRoot
$hython = Join-Path $Hfs "bin\hython.exe"
$houdini = Join-Path $Hfs "bin\houdini.exe"
if (-not (Test-Path $hython)) { Write-Error "hython not found: $hython (use -Hfs)"; exit 2 }

$failed = 0
$env:QT_QPA_PLATFORM = "offscreen"

if ($Screenshots) { $Gui = $true }
$tests = if ($Screenshots) { @() } else { @("test_build_modes", "test_material_linker", "test_cameras_nodes", "test_clouds2d", "test_hdrireader", "test_mxdownload", "test_materialeditor", "test_shelf", "test_hda", "test_security") }
foreach ($test in $tests) {
    $out = & $hython (Join-Path $PSScriptRoot "$test.py") 2>&1 | Out-String
    $pass = ([regex]::Matches($out, "(?m)^PASS")).Count
    $fail = ([regex]::Matches($out, "(?m)^FAIL ")).Count
    $crashed = ($LASTEXITCODE -ne 0) -and ($fail -eq 0)
    "{0,-24} {1,3} pass  {2,3} fail{3}" -f $test, $pass, $fail, $(if ($crashed) { "  (script error)" } else { "" })
    if ($fail -gt 0 -or $crashed) {
        $failed++
        ($out -split "`n") | Where-Object { $_ -match "^FAIL |Traceback|Error" } | ForEach-Object { "    " + $_.Trim() }
    }
}

if ($Gui) {
    if (-not (Test-Path $houdini)) { Write-Error "houdini.exe not found: $houdini"; exit 2 }
    $result = Join-Path ([System.IO.Path]::GetTempPath()) "bsm_gui_result.txt"
    Remove-Item $result -ErrorAction SilentlyContinue
    $env:BSM_RESULT = $result
    $env:BSM_ROOT = $root
    $guiDir = if ($Screenshots) { "screenshots" } else { "gui" }
    $env:HOUDINI_PATH = (Join-Path $PSScriptRoot $guiDir) + ";&"
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue

    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class BsmWinHider {
    public delegate bool EnumProc(IntPtr h, IntPtr l);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc p, IntPtr l);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] static extern bool SetWindowPos(IntPtr h, IntPtr a, int x, int y, int cx, int cy, uint f);
    public static void HideAll(uint pid) {
        EnumWindows(delegate(IntPtr h, IntPtr l) {
            uint p; GetWindowThreadProcessId(h, out p);
            if (p == pid && IsWindowVisible(h)) { SetWindowPos(h, IntPtr.Zero, -32000, -32000, 0, 0, 0x15); ShowWindow(h, 0); }
            return true;
        }, IntPtr.Zero);
    }
}
"@
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $houdini
    $psi.Arguments = "-foreground"
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    if (-not $Visible) { $psi.CreateNoWindow = $true; $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden }
    $proc = [System.Diagnostics.Process]::Start($psi)
    $deadline = (Get-Date).AddSeconds($GuiTimeoutSec)
    while (-not $proc.HasExited -and (Get-Date) -lt $deadline) {
        if (-not $Visible) { [BsmWinHider]::HideAll([uint32]$proc.Id) }
        # the test ends with DONE in the result file; do not wait for Houdini's own (sometimes crashing) exit
        if ((Test-Path $result) -and ((Get-Content $result -Raw) -match "(?m)^DONE")) { Start-Sleep -Seconds 2; break }
        Start-Sleep -Milliseconds 40
    }
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }

    if (Test-Path $result) {
        $text = Get-Content $result -Raw
        $pass = ([regex]::Matches($text, "(?m)^PASS")).Count
        $fail = ([regex]::Matches($text, "(?m)^FAIL ")).Count
        $exc = ([regex]::Matches($text, "(?m)^EXCEPTION")).Count
        $done = $text -match "(?m)^DONE"
        "{0,-24} {1,3} pass  {2,3} fail{3}{4}" -f $(if ($Screenshots) { "screenshots" } else { "gui lifecycle" }), $pass, $fail, $(if ($exc) { "  ($exc exception)" } else { "" }), $(if (-not $done) { "  (did not finish)" } else { "" })
        if ($fail -gt 0 -or $exc -gt 0 -or -not $done) {
            $failed++
            ($text -split "`n") | Where-Object { $_ -match "^FAIL |^EXCEPTION" } | ForEach-Object { "    " + $_.Trim() }
        }
    } else {
        "gui lifecycle           no result file (Houdini did not start the test)"
        $failed++
    }
}

if ($failed) { "`n$failed test file(s) failed"; exit 1 } else { "`nall tests passed"; exit 0 }
