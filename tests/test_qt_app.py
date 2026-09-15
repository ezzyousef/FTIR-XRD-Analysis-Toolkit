"""The Qt application: exports, both analysis pages, undo/redo, sessions, reports (offscreen)."""
import csv
import time
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

import exports  # noqa: E402
import peak_fitting  # noqa: E402
from selftest import write_ftir_csv, write_xrd_xy  # noqa: E402
from trace_model import Trace  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    return app


@pytest.fixture
def ftir_csv(tmp_path):
    return str(write_ftir_csv(tmp_path / "sample_ftir.csv"))


@pytest.fixture
def xrd_xy(tmp_path):
    return str(write_xrd_xy(tmp_path / "sample_xrd.xy"))


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    import app_config
    import ui_common

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path / "settings"))
    monkeypatch.setattr(app_config, "get_config_dir", lambda: str(tmp_path))
    messages = []
    monkeypatch.setattr(ui_common, "show_message",
                        lambda parent, title, text, level="info": messages.append((title, text, level)))
    monkeypatch.setattr(ui_common, "ask_yes_no", lambda *a, **k: True)
    from app_window import MainWindow
    w = MainWindow()
    w.messages = messages
    w.show()
    yield w
    w.close()


def pump(qapp, until=None, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        qapp.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until is None


def _ftir_trace():
    x = np.linspace(4000, 400, 1801)
    y = 0.02 + 0.8 * np.exp(-4 * np.log(2) * ((x - 1720) / 14) ** 2) + 0.5 * np.exp(-4 * np.log(2) * ((x - 2920) / 18) ** 2)
    t = Trace("a.csv", x, y, "#0072B2")
    import ftir_analysis
    t.peaks = ftir_analysis.detect_peaks(x, y, prominence_frac=0.02)
    t.fits, _ = peak_fitting.fit_peaks_batch(x, y, t.peaks, 25)
    return t


# ------------------------------------------------------------------ exports (no display)
def test_figure_has_every_visible_trace_and_a_composite_fit():
    t = _ftir_trace()
    hidden = Trace("hidden.csv", t.x, t.y * 0.5, "#D55E00")
    hidden.visible = False
    spec = exports.spectrum_figure("ftir", [t, hidden], t.id)
    assert spec.invert_x and [s.role for s in spec.series] == ["data", "fit"]
    model = spec.series[1].y
    peak = int(np.argmin(abs(t.x - 1720)))
    assert abs(model[peak] - t.y[peak]) < 0.08, "the composite follows the fitted band"
    assert np.isfinite(model).all()
    far = int(np.argmin(abs(t.x - 2400)))
    assert model[far] == pytest.approx(t.y[far]), "away from every fitted peak the model is the data itself"


def test_origin_book_and_labtalk_package(tmp_path):
    from labkit.origin import write_labtalk_package
    t = _ftir_trace()
    books = exports.origin_books("ftir", [t], t.id)
    assert len(books) == 1 and books[0].results
    result = write_labtalk_package(books, tmp_path)
    assert result.graphs == 1
    assert "%%" not in (tmp_path / "AeroLab_build.ogs").read_text(encoding="utf-8")


def test_excel_report_has_a_chart_and_sheet_per_trace(tmp_path):
    import openpyxl
    from labkit.excel import write_workbook
    a, b = _ftir_trace(), _ftir_trace()
    b.label = "b.csv"
    a.matches = [{"name": "Poly(x)", "category": "polymers", "score": 0.5, "matched_count": 1,
                  "total_reference_peaks": 2, "source": "ref", "matches": []}]
    path = write_workbook(exports.excel_report("ftir", [a, b], a.id, version="3.0.0"), tmp_path / "r.xlsx")
    book = openpyxl.load_workbook(path)
    assert len(book["Charts"]._charts) == 2
    assert any(name.startswith("Matches") for name in book.sheetnames)
    assert any(name.startswith("Fits") for name in book.sheetnames)


def test_xrd_results_include_sizes_and_williamson_hall():
    t = Trace("p.xy", [1, 2], [1, 2], "#0072B2")
    t.peaks = [{"two_theta": 28.4, "intensity": 10, "fwhm_deg": 0.2, "d_A": 3.14, "size_nm": 40.0}]
    t.metadata["wh_result"] = {"crystallite_size_nm": 35.0, "microstrain": -0.001, "strain_physical": False,
                               "n_peaks": 4, "slope": 0, "intercept": 0}
    names = {r[0]: r for r in exports.results("xrd", t, wavelength=1.540562)}
    assert names["Mean Scherrer crystallite size"][1] == 40.0
    assert "~0" in names["Williamson–Hall microstrain"][3]


# ------------------------------------------------------------------ window
def test_every_page_builds_in_both_themes_without_shortcut_clashes(window, qapp):
    for theme in ("dark", "light"):
        window.apply_theme(theme)
        for key in window.page_keys:
            window.go_to(key)
            pump(qapp, timeout=0.05)
            assert window.is_page_built(key)
    assert window.shortcut_conflicts() == []


def test_ftir_load_detect_undo_redo(window, qapp, ftir_csv):
    ftir = window.page("ftir")
    assert ftir.load_paths([ftir_csv]) == [ftir_csv]
    ftir.detect_peaks()
    t = ftir.get_active()
    assert len(t.peaks) >= 4 and ftir.peaks_table.rowCount() == len(t.peaks)
    window.undo()
    assert not ftir.get_active().peaks
    window.undo()
    assert ftir.traces == [] and ftir.peaks_table.rowCount() == 0
    window.redo()
    window.redo()
    assert len(ftir.get_active().peaks) >= 4


def test_ftir_matching_and_fitting_run_in_the_background(window, qapp, ftir_csv):
    ftir = window.page("ftir")
    ftir.load_paths([ftir_csv])
    ftir.detect_peaks()
    ftir.match_database()
    assert ftir.is_busy
    assert pump(qapp, lambda: not ftir.is_busy)
    t = ftir.get_active()
    assert ftir.matches_table.rowCount() == len(t.matches)
    ftir.fit_peaks()
    assert pump(qapp, lambda: not ftir.is_busy)
    assert len(t.fits) >= 3 and ftir.fits_table.rowCount() == len(t.fits)
    assert [s.role for s in ftir.figure_spec().series][-1] == "fit"
    window.undo()
    assert not ftir.get_active().fits


def test_processing_asks_then_applies(window, qapp, ftir_csv, monkeypatch):
    import ui_common
    ftir = window.page("ftir")
    ftir.load_paths([ftir_csv])
    before = ftir.get_active().y.copy()
    monkeypatch.setattr(ui_common, "ask_fields", lambda *a, **k: {"wl": "21", "po": "3"})
    ftir.smooth_active()
    assert not np.allclose(before, ftir.get_active().y)
    monkeypatch.setattr(ui_common, "ask_fields", lambda *a, **k: None)
    after = ftir.get_active().y.copy()
    ftir.smooth_active()
    assert np.allclose(after, ftir.get_active().y), "cancelling a dialog changes nothing"
    ftir.revert_active()
    assert np.allclose(before, ftir.get_active().y)


def test_xrd_calculations(window, qapp, xrd_xy, monkeypatch):
    import ui_common
    window.go_to("xrd")
    pump(qapp, timeout=0.1)
    xrd = window.page("xrd")
    xrd.load_paths([xrd_xy])
    xrd.detect_peaks()
    t = xrd.get_active()
    assert len(t.peaks) >= 4
    xrd.run_all_calcs()
    assert abs(t.peaks[0]["d_A"] - 3.1357) < 0.01 and t.peaks[0]["size_nm"] > 0
    xrd.run_williamson_hall()
    assert "Williamson" in xrd.wh_text.toPlainText()
    monkeypatch.setattr(ui_common, "ask_fields", lambda *a, **k: {"crys": "27-30,46-49", "amorph": "12-20"})
    xrd.run_crystallinity()
    assert 0 < t.metadata["crystallinity_pct"] <= 100


def test_custom_wavelength(window, qapp, monkeypatch):
    import ui_common
    xrd = window.page("xrd")
    monkeypatch.setattr(ui_common, "ask_fields", lambda *a, **k: {"wl": "1.789"})
    xrd.wl_combo.setCurrentText("Custom...")
    assert xrd.get_wavelength() == pytest.approx(1.789)


def test_session_round_trip_and_wrong_page(window, qapp, ftir_csv, tmp_path):
    ftir = window.page("ftir")
    ftir.load_paths([ftir_csv])
    ftir.detect_peaks()
    ftir.rb_transmittance.setChecked(True)
    path = ftir.save_session(str(tmp_path / "s.ftirxrd"))
    ftir._on_trace_clear()
    ftir.rb_absorbance.setChecked(True)
    assert ftir.load_session(path)
    assert len(ftir.traces) == 1 and ftir.get_active().peaks and ftir.mode() == "transmittance"
    window.go_to("xrd")
    pump(qapp, timeout=0.1)
    assert window.page("xrd").load_session(path) is False
    assert window.messages[-1][0] == "Wrong page"


def test_reports_and_csv_exports(window, qapp, ftir_csv, tmp_path):
    ftir = window.page("ftir")
    ftir.load_paths([ftir_csv])
    ftir.detect_peaks()
    pdf = ftir.export_pdf_report(str(tmp_path / "r.pdf"))
    assert pdf and Path(pdf).stat().st_size > 5000
    ftir.export_originlab_csv(str(tmp_path / "o.csv"))
    rows = list(csv.reader(open(tmp_path / "o.csv", encoding="utf-8")))
    assert rows[0] == ["sample_ftir.csv X", "sample_ftir.csv Y"] and len(rows) == 2 + len(ftir.get_active().x)


def test_bad_file_is_reported_not_loaded(window, qapp, tmp_path):
    bad = tmp_path / "nonsense.csv"
    bad.write_text("hello\nworld\n", encoding="utf-8")
    ftir = window.page("ftir")
    assert ftir.load_paths([str(bad)]) == []
    assert window.messages and window.messages[-1][0] == "Could not load file"


def test_open_files_routes_by_extension(window):
    assert window.route_for("x.jdx") == "ftir"
    assert window.route_for("x.xrdml") == "xrd"
    window.go_to("xrd")
    assert window.route_for("x.csv") == "xrd"


def test_actions_without_data_warn(window, monkeypatch):
    levels = []
    monkeypatch.setattr(window, "notify", lambda text, level="info": levels.append(level))
    window.page("ftir").detect_peaks()
    window.page("ftir").fit_peaks()
    assert levels == ["warning", "warning"]


def test_database_page_filters(window, qapp):
    page = window.page("database")
    total = page.materials.rowCount()
    assert total > 100
    page.category.setCurrentIndex(page.category.findData("salts_inorganic"))
    assert 0 < page.materials.rowCount() < total
    page.materials.selectRow(0)
    assert page.peaks.rowCount() > 0
