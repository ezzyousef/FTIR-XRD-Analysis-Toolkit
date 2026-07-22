# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the FTIR & XRD Analysis Toolkit.
# Build with:  pyinstaller app.spec   (run on Windows to get a Windows build)
#
# Deliberately onedir, not onefile: onefile re-extracts its entire bundled
# runtime to a fresh %TEMP% folder on EVERY launch, which is a well-documented
# cause of flaky/slow startup (antivirus real-time scanning the newly-written
# payload each time, often combined with UPX-compressed unsigned executables
# specifically tripping AV heuristics). onedir extracts once, at install time
# (via the Inno Setup installer copying the whole folder) instead of once per
# launch -- see installer/FTIR_XRD_Toolkit.iss.

import os

_datas = [
    ('database/ftir_reference_db.json', 'database'),
    ('database/xrd_reference_db.json', 'database'),
    ('assets', 'assets'),
]
# Bundled COD reference database (~1GB+, built from a HighScore .hsrdb file
# via scripts/build_cod_database.py) -- not committed to git (see
# .gitignore), so only include it if it's actually present on this build
# machine. Ship it in the installer, never in the git repo.
if os.path.exists('database/cod_reference.sqlite'):
    _datas.append(('database/cod_reference.sqlite', 'database'))

a = Analysis(
    ['main.py'],
    pathex=['modules'],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        'file_readers', 'ftir_analysis', 'xrd_analysis', 'signal_utils',
        'peak_fitting', 'report_export', 'session_io', 'app_config',
        'ui_common', 'trace_model', 'workers', 'formula_sources',
        'ftir_tab', 'xrd_tab',
        'scipy.signal', 'scipy.integrate', 'scipy.optimize',
        'PIL._tkinter_finder',
        'ttkbootstrap', 'tkinterdnd2', 'mplcursors',
        'reportlab.pdfbase._fontdata',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # This app only ever uses matplotlib's TkAgg canvas (see the
    # matplotlib.use("TkAgg") pin in main.py) -- explicitly excluding every
    # other GUI toolkit backend keeps a shared/polluted build environment
    # (e.g. another project's PySide6 on the same machine) from getting
    # needlessly pulled in by matplotlib's own backend auto-discovery hook.
    excludes=['PySide6', 'PySide2', 'PyQt5', 'PyQt6', 'shiboken6', 'shiboken2',
              'gi', 'wx', 'IPython', 'notebook', 'jupyter'],
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
