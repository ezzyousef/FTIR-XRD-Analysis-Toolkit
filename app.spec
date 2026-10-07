# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the FTIR & XRD Analysis Toolkit (PySide6 + labkit).
# Build with .\build.ps1, or:  python -m PyInstaller app.spec --noconfirm
#
# Deliberately onedir, not onefile: onefile re-extracts its whole runtime to a fresh %TEMP%
# folder on every launch -- a well-documented cause of slow, flaky startup as antivirus
# rescans it. onedir extracts once, at install time (installer/FTIR_XRD_Toolkit.iss).
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = [
    'app_info', 'app_window', 'exports', 'file_readers', 'ftir_analysis', 'ftir_matching', 'xrd_analysis',
    'signal_utils', 'peak_fitting', 'report_export', 'session_io', 'app_config', 'ui_common',
    'trace_model', 'workers', 'formula_sources', 'ftir_tab', 'xrd_tab', 'selftest',
    'scipy.signal', 'scipy.integrate', 'scipy.optimize',
    'matplotlib.backends.backend_qtagg', 'matplotlib.backends.backend_agg',
    'xlsxwriter', 'reportlab.pdfbase._fontdata',
] + collect_submodules('labkit')
try:
    import originpro                        # noqa: F401
    hiddenimports += collect_submodules('originpro') + ['win32com.client', 'pythoncom', 'pywintypes']
except ImportError:
    pass

a = Analysis(
    ['main.py'],
    pathex=['modules', '.'],
    binaries=[],
    datas=[('database/ftir_reference_db.json', 'database'), ('assets', 'assets')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'ttkbootstrap', 'tkinterdnd2', 'PySide2', 'PyQt5', 'PyQt6', 'gi', 'wx',
              'IPython', 'notebook', 'jupyter', 'pytest', 'matplotlib.backends.backend_tkagg'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FTIR_XRD_Toolkit',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='FTIR_XRD_Toolkit',
)
