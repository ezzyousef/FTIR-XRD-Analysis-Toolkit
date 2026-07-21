@echo off
REM Builds the standalone FTIR_XRD_Toolkit app (onedir) on Windows.
REM Requires Python 3.10+ installed and on PATH (https://python.org).
REM
REM For a proper Setup.exe installer (Start Menu shortcut, uninstaller),
REM run build_installer.ps1 instead (needs Inno Setup 6 installed too).

echo Installing dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo pip install failed - check that Python and pip are installed and on PATH.
    pause
    exit /b 1
)

echo Building executable with PyInstaller...
pyinstaller app.spec --noconfirm
if errorlevel 1 (
    echo Build failed - see the error above.
    pause
    exit /b 1
)

echo.
echo Done. Your app is at: dist\FTIR_XRD_Toolkit\FTIR_XRD_Toolkit.exe
echo Copy the WHOLE dist\FTIR_XRD_Toolkit\ folder anywhere on a Windows machine
echo and run the .exe inside it - it needs every file alongside it, not just the exe.
echo (For a single Setup.exe installer instead, run build_installer.ps1.)
pause
