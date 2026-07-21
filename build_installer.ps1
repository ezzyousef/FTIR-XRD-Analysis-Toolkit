# Builds the standalone FTIR_XRD_Toolkit.exe (PyInstaller, onedir) and then
# wraps it in a Windows installer (Inno Setup) -- the result,
# installer\output\FTIR_XRD_ToolkitSetup.exe, needs nothing installed on the
# target PC (no Python, no dependencies): it is a normal double-click
# Windows installer with a Start Menu shortcut and uninstaller.
#
# Requirements on THIS (build) machine only:
#   - Python with requirements.txt installed (pip install -r requirements.txt)
#   - Inno Setup 6 (free, https://jrsoftware.org/isdl.php)
#
# Usage (from the project root, ftir_xrd_toolkit\):
#   .\build_installer.ps1

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
Set-Location $root

Write-Host "== Step 1/2: building standalone FTIR_XRD_Toolkit.exe with PyInstaller ==" -ForegroundColor Cyan
python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)" }

python -m PyInstaller app.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed (exit $LASTEXITCODE)" }

Write-Host "== Step 2/2: compiling the Windows installer with Inno Setup ==" -ForegroundColor Cyan
$iscc = Get-ChildItem -Path @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
) -ErrorAction SilentlyContinue | Select-Object -First 1

if (-not $iscc) {
    throw "ISCC.exe (Inno Setup compiler) not found. Install Inno Setup 6 from https://jrsoftware.org/isdl.php, then re-run this script."
}

& $iscc.FullName "installer\FTIR_XRD_Toolkit.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed (exit $LASTEXITCODE)" }

Write-Host ""
Write-Host "Done. Installer: installer\output\FTIR_XRD_ToolkitSetup.exe" -ForegroundColor Green
Write-Host "Copy that one file to any Windows PC and run it -- nothing else needs to be installed there." -ForegroundColor Green
