<#
    Build the FTIR & XRD Analysis Toolkit end to end.

        .\build.ps1                 tests, executable, self-test, portable zip, installer
        .\build.ps1 -SkipTests      skip the pytest run
        .\build.ps1 -SkipInstaller  stop after the portable zip

    Outputs:
        dist\FTIR_XRD_Toolkit\                               the application folder
        dist\FTIR_XRD_Toolkit-<version>-portable.zip
        installer\output\FTIR_XRD_ToolkitSetup-<version>.exe
#>
param(
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

# Native tools write progress to stderr, which PowerShell turns into ErrorRecords. "Continue"
# keeps that from aborting, and every native call is checked with $LASTEXITCODE rather than
# $? — $? is false whenever anything reached stderr, even on a successful build.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

function Step($text) { Write-Host "`n=== $text" -ForegroundColor Cyan }
function Fail($text) { Write-Host "`nFAILED: $text" -ForegroundColor Red; exit 1 }
function CheckExit($text) { if ($LASTEXITCODE -ne 0) { Fail $text } }

$version = (python -c "import sys; sys.path.insert(0,'modules'); from app_info import APP_VERSION; print(APP_VERSION)").Trim()
CheckExit "could not read the version - is Python on PATH?"
Write-Host "FTIR & XRD Analysis Toolkit $version" -ForegroundColor Green

Step "Checking the build tools"
python -c "import PyInstaller, PySide6, matplotlib, scipy, reportlab, xlsxwriter"
CheckExit "a build dependency is missing. Run: pip install -r requirements.txt"

if (-not $SkipTests) {
    Step "Running the test suite"
    python -m pytest tests -q -p no:cacheprovider
    CheckExit "tests failed - fix them before shipping a build"
}

Step "Building the executable"
if (Test-Path dist\FTIR_XRD_Toolkit) { Remove-Item dist\FTIR_XRD_Toolkit -Recurse -Force }
python -m PyInstaller app.spec --noconfirm --distpath dist --workpath build
CheckExit "PyInstaller could not build the application"

Step "Self-testing the built application"
# The exe is a windowed app, so it is started with its output redirected to a file.
$log = Join-Path $env:TEMP "ftirxrd-selftest.txt"
$proc = Start-Process -FilePath dist\FTIR_XRD_Toolkit\FTIR_XRD_Toolkit.exe -ArgumentList "--selftest" `
    -RedirectStandardOutput $log -Wait -PassThru -WindowStyle Hidden
Get-Content $log
if ($proc.ExitCode -ne 0) { Fail "the built application failed its own self-test" }

Step "Packing the portable zip"
# Compress-Archive gives up quietly on a tree this size, so the .NET API does the work.
$zip = Join-Path (Resolve-Path dist) "FTIR_XRD_Toolkit-$version-portable.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    (Resolve-Path dist\FTIR_XRD_Toolkit).Path, $zip,
    [System.IO.Compression.CompressionLevel]::Optimal, $true)
if (-not (Test-Path $zip)) { Fail "the portable zip was not created" }
Write-Host "  $zip  ($([math]::Round((Get-Item $zip).Length / 1MB, 1)) MB)"

if (-not $SkipInstaller) {
    Step "Compiling the installer"
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    $iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $iscc) {
        Write-Host "  Inno Setup not found - skipping the installer." -ForegroundColor Yellow
        Write-Host "  Install it with:  winget install JRSoftware.InnoSetup" -ForegroundColor Yellow
    } else {
        & $iscc "/DMyAppVersion=$version" installer\FTIR_XRD_Toolkit.iss | Select-Object -Last 3
        CheckExit "the installer could not be compiled"
    }
}

Step "Done"
