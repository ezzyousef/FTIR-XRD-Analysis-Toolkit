"""
FTIR & XRD Analysis Toolkit -- desktop application entry point.

    python main.py                  start the app
    python main.py file.csv ...     start and open those files
    python main.py --selftest       check the whole application without a window
    python main.py --version        print the version

Build the Windows executable and installer with build.ps1 (see README.md).
"""
import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
for _path in (APP_DIR, os.path.join(APP_DIR, "modules")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app_info import APP_ID, APP_NAME, APP_VERSION, resource_path  # noqa: E402


def _claim_taskbar_identity():
    """Group the window under its own taskbar icon instead of python.exe's."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001 - cosmetic only
        pass


def _show_splash(app):
    """A window that paints at once, before the slow imports (matplotlib, scipy) -- without
    it Windows shows its own 'not responding yet' placeholder during the wait."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPixmap
    from PySide6.QtWidgets import QSplashScreen

    pixmap = QPixmap(resource_path(os.path.join("assets", "eml_logo.png")))
    if pixmap.isNull():
        pixmap = QPixmap(360, 220)
        pixmap.fill(QColor("#F3F4F6"))
    else:
        pixmap = pixmap.scaledToWidth(280, Qt.SmoothTransformation)
    splash = QSplashScreen(pixmap)
    splash.showMessage(f"Loading {APP_NAME}…", Qt.AlignBottom | Qt.AlignHCenter, QColor("#1B1E22"))
    splash.show()
    app.processEvents()
    return splash


def _prewarm_heavy_imports(app):
    """Import the heavy libraries one at a time, pumping events in between, so the splash
    window never looks hung to Windows."""
    for name in ("numpy", "scipy.signal", "scipy.optimize", "matplotlib", "matplotlib.backends.backend_qtagg",
                 "labkit.figure", "labkit.qt.shell", "ftir_analysis", "xrd_analysis", "ui_common",
                 "ftir_tab", "xrd_tab"):
        try:
            __import__(name)
        except ImportError:
            pass
        app.processEvents()


def main():
    if "--version" in sys.argv:
        print(f"{APP_NAME} {APP_VERSION}")
        return 0
    if "--selftest" in sys.argv:
        from selftest import run_selftest
        return run_selftest()

    os.environ.setdefault("MPLBACKEND", "QtAgg")
    _claim_taskbar_identity()
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("EML")
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(QIcon(resource_path(os.path.join("assets", "icon.png"))))
    # Fusion draws combo-box popups itself; the window applies the labkit stylesheet on top.
    app.setStyle("Fusion")

    splash = _show_splash(app)
    _prewarm_heavy_imports(app)
    from app_window import MainWindow

    window = MainWindow()
    window.show()
    splash.finish(window)
    files = [a for a in sys.argv[1:] if not a.startswith("--") and os.path.isfile(a)]
    if files:
        window.open_files(files)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
