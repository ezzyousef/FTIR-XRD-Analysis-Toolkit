"""`FTIR_XRD_Toolkit.exe --selftest`: exercise the whole application without a visible window.

Used to verify a packaged build: reads synthetic FTIR and XRD files, runs detection,
database screening and fitting, writes Excel / Origin / PDF exports, then opens every page
in both themes and checks loading, undo and shortcuts. Settings go to a temporary folder,
so the user's own preferences and recent files are untouched. Prints plain ASCII, because a
frozen Windows console uses the legacy code page.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _gaussian(x, centre, height, fwhm):
    import numpy as np
    return height * np.exp(-4 * np.log(2) * ((x - centre) / fwhm) ** 2)


def write_ftir_csv(path):
    import numpy as np
    x = np.linspace(4000, 400, 1801)
    y = (0.02 + _gaussian(x, 1720, 0.8, 14) + _gaussian(x, 2920, 0.5, 18) + _gaussian(x, 1050, 0.6, 24)
         + _gaussian(x, 3400, 0.35, 120))
    with open(path, "w", encoding="utf-8") as f:
        f.write("wavenumber,absorbance\n")
        f.writelines(f"{a:.3f},{b:.6f}\n" for a, b in zip(x, y))
    return path


def write_xrd_xy(path):
    import numpy as np
    tt = np.linspace(10, 80, 3501)
    y = (50 + _gaussian(tt, 28.44, 1000, 0.18) + _gaussian(tt, 47.30, 600, 0.20) + _gaussian(tt, 56.12, 350, 0.22)
         + _gaussian(tt, 69.13, 120, 0.24))
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(f"{a:.4f} {b:.3f}\n" for a, b in zip(tt, y))
    return path


def run_selftest() -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["MPLBACKEND"] = "Agg"
    for p in (str(ROOT), str(ROOT / "modules")):
        if p not in sys.path:
            sys.path.insert(0, p)
    failures: list[str] = []

    def check(label, ok, detail=""):
        print(("ok    " if ok else "FAIL  ") + label + ("" if ok else f"  ({detail})"))
        if not ok:
            failures.append(label)

    try:
        import exports
        import file_readers
        import ftir_analysis
        import peak_fitting
        import report_export
        import xrd_analysis
        from app_info import APP_NAME, APP_VERSION
        from trace_model import Trace
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  imports: {type(exc).__name__}: {exc}")
        return 1
    frozen = "frozen" if getattr(sys, "frozen", False) else "source"
    print(f"{APP_NAME} {APP_VERSION} ({frozen} build)\n")

    tmp = Path(tempfile.mkdtemp(prefix="ftirxrd_selftest_"))
    ftir_csv = write_ftir_csv(tmp / "sample_ftir.csv")
    xrd_xy = write_xrd_xy(tmp / "sample_xrd.xy")

    trace = None
    try:
        from app_window import load_ftir_database
        db = load_ftir_database()
        data = file_readers.read_ftir_any(str(ftir_csv))
        peaks = ftir_analysis.detect_peaks(data.x, data.y, prominence_frac=0.02)
        check(f"FTIR: {len(peaks)} peaks detected in a synthetic spectrum", len(peaks) >= 4)
        matches = ftir_analysis.match_peaks_to_database(peaks, db, tolerance=10)
        check(f"FTIR: database screening ran ({len(matches)} candidates)", isinstance(matches, list))
        fits, _errors = peak_fitting.fit_peaks_batch(data.x, data.y, peaks, 25, shape="gaussian")
        check(f"FTIR: {len(fits)} peaks fitted", len(fits) >= 3)
        trace = Trace("sample_ftir.csv", data.x, data.y, "#0072B2")
        trace.peaks, trace.fits, trace.matches = peaks, fits, matches
    except Exception as exc:  # noqa: BLE001
        check("FTIR core", False, f"{type(exc).__name__}: {exc}")

    try:
        pattern = file_readers.read_any(str(xrd_xy))
        xpeaks = xrd_analysis.detect_xrd_peaks(pattern.x, pattern.y, prominence_frac=0.02)
        d = xrd_analysis.bragg_d_spacing(28.44, xrd_analysis.WAVELENGTHS["Cu Ka1"])
        check(f"XRD: {len(xpeaks)} peaks detected, d(28.44 deg) = {d:.4f} A", len(xpeaks) >= 4 and abs(d - 3.1357) < 0.01)
    except Exception as exc:  # noqa: BLE001
        check("XRD core", False, f"{type(exc).__name__}: {exc}")

    if trace is not None:
        try:
            from labkit.excel import write_workbook
            path = write_workbook(exports.excel_report("ftir", [trace], trace.id, version=APP_VERSION), tmp / "report.xlsx")
            check(f"Excel workbook written ({path.stat().st_size // 1024} kB)", path.stat().st_size > 8000)
        except Exception as exc:  # noqa: BLE001
            check("Excel workbook", False, f"{type(exc).__name__}: {exc}")
        try:
            from labkit.origin import origin_available, write_labtalk_package
            result = write_labtalk_package(exports.origin_books("ftir", [trace], trace.id), tmp / "origin")
            check(f"Origin LabTalk package written ({result.graphs} graph)", result.graphs >= 1)
            print(f"note  {origin_available()[1]}")
        except Exception as exc:  # noqa: BLE001
            check("Origin package", False, f"{type(exc).__name__}: {exc}")
        try:
            pdf = report_export.build_report(str(tmp / "report.pdf"), "FTIR Analysis Report", "self-test", None,
                                             [("Notes", None, "Self-test report.")], "Self-test.")
            check("PDF report written", Path(pdf).stat().st_size > 1000)
        except Exception as exc:  # noqa: BLE001
            check("PDF report", False, f"{type(exc).__name__}: {exc}")

    try:
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        import app_config
        import ui_common

        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp / "settings"))
        app_config.get_config_dir = lambda: str(tmp)
        ui_common.show_message = lambda *a, **k: None
        ui_common.ask_yes_no = lambda *a, **k: True

        app = QApplication.instance() or QApplication([])
        app.setStyle("Fusion")
        from app_window import MainWindow
        window = MainWindow()
        window.show()

        def pump(n=5):
            for _ in range(n):
                app.processEvents()

        for theme in ("light", "dark"):
            window.apply_theme(theme)
            for key in window.page_keys:
                window.go_to(key)
                pump()
        built = sum(window.is_page_built(k) for k in window.page_keys)
        check(f"interface: {built} of {len(window.page_keys)} pages built in light and dark", built == len(window.page_keys))
        window.apply_theme("light")

        ftir = window.page("ftir")
        window.go_to("ftir")
        ftir.load_paths([str(ftir_csv)])
        ftir.detect_peaks()
        loaded_ok = len(ftir.traces) == 1 and len(ftir.get_active().peaks) >= 4
        window.undo()
        window.undo()
        check("FTIR page: load + detect, then undo both", loaded_ok and not ftir.traces)

        xrd = window.page("xrd")
        window.go_to("xrd")
        pump()
        xrd.load_paths([str(xrd_xy)])
        xrd.run_all_calcs()
        first = xrd.get_active().peaks[0] if xrd.traces and xrd.get_active().peaks else {}
        check("XRD page: load + d-spacing/Scherrer", abs(first.get("d_A", 0) - 3.1357) < 0.01, str(first))
        pdf = xrd.export_pdf_report(str(tmp / "xrd.pdf"))
        check("XRD page: PDF report", bool(pdf) and Path(pdf).exists())
        check("no duplicate keyboard shortcuts", window.shortcut_conflicts() == [], str(window.shortcut_conflicts()))
        window.close()
    except Exception as exc:  # noqa: BLE001
        check("interface", False, f"{type(exc).__name__}: {exc}")

    print()
    if failures:
        print(f"SELF-TEST FAILED - {len(failures)} problem(s): {', '.join(failures)}")
        return 1
    print("SELF-TEST PASSED - this build is working.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_selftest())
