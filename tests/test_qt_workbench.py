"""The 3.4 menu actions in the real window (offscreen): one window for the whole module."""
import csv
import json
import math
import os

import numpy as np
import pytest

pytest.importorskip("PySide6")

from selftest import write_ftir_csv, write_xrd_xy  # noqa: E402

LAM = 1.540562


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    return app


@pytest.fixture(scope="module")
def win(qapp, tmp_path_factory):
    from PySide6.QtCore import QSettings
    import app_config
    import ui_common
    tmp = tmp_path_factory.mktemp("wb")
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp / "settings"))
    mp = pytest.MonkeyPatch()
    mp.setattr(app_config, "get_config_dir", lambda: str(tmp))
    messages = []
    mp.setattr(ui_common, "show_message", lambda parent, title, text, level="info": messages.append((title, text, level)))
    mp.setattr(ui_common, "ask_yes_no", lambda *a, **k: True)
    from app_window import MainWindow
    w = MainWindow()
    w.messages = messages
    w.tmp = tmp
    w.show()
    w.page("ftir").load_paths([str(write_ftir_csv(tmp / "s.csv"))])
    w.page("xrd").load_paths([str(write_xrd_xy(tmp / "p.xy"))])
    yield w
    w.close()
    mp.undo()


def test_new_actions_are_in_the_menu_without_shortcut_clashes(win):
    labels = [a.text() for m in win.menuBar().actions() if m.menu() for a in m.menu().actions()]
    for wanted in ("FTIR: &global peak fit…", "FTIR: &validation laboratory…", "XRD: &calibrate with a standard…",
                   "Sample &evidence report (FTIR + XRD)…", "Colour-blind-safe &palette"):
        assert wanted in labels
    assert win.shortcut_conflicts() == []


def test_global_fit_and_assignment_with_undo(win):
    import workbench
    ftir = win.page("ftir")
    t = ftir.get_active()
    import ftir_analysis
    t.peaks = ftir_analysis.detect_peaks(t.x, t.y, prominence_frac=0.02)
    dlg = workbench.global_fit_active(ftir, robust=True, x_range=(1650, 1800))
    assert dlg is not None and "1720" in dlg.text and "±" in dlg.text
    assert t.metadata["global_fit"]["peaks"][0]["center"] == pytest.approx(1720, abs=0.5)
    json.dumps(t.metadata["global_fit"])                       # session-safe (no functions inside)
    dlg.close()
    ftir.on_active_trace_changed()
    row = next(i for i, p in enumerate(t.peaks) if abs(p["x"] - 1720) < 2)
    ftir.peaks_table.selectRow(row)
    workbench.assign_selected_peak(ftir, "C=O stretch")
    assert t.peaks[row]["assignment"] == "C=O stretch"
    assert "C=O stretch" in ftir.peaks_table.item(row, 4).text()
    win.undo()
    assert not ftir.get_active().peaks[row].get("assignment")


def test_recipe_batch_and_validation_lab(win, tmp_path):
    import recipes
    import workbench
    r = recipes.make_recipe("t", [("baseline", {})])
    rp = tmp_path / "r.json"
    recipes.save_recipe(r, rp)
    files = [str(write_ftir_csv(tmp_path / f"f{i}.csv")) for i in range(2)]
    dlg = workbench.batch_dialog(win, str(rp), files, str(tmp_path / "out.csv"))
    assert "f0.csv: " in dlg.text and os.path.isfile(tmp_path / "out.csv")
    dlg.close()
    # a manifest with one synthetic spectrum: the dialog shows the report (plumbing only)
    with open(tmp_path / "m.csv", "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([["file", "label", "split"], ["f0.csv", "none", "test"]])
    dlg = workbench.run_validation_lab(win, str(tmp_path / "m.csv"))
    assert dlg is not None and "screening score" in dlg.text
    dlg.close()


def test_xrd_tools_from_the_window(win, tmp_path, monkeypatch):
    import ui_common
    import workbench
    xrd = win.page("xrd")
    t = xrd.get_active()
    import xrd_analysis
    t.peaks = xrd_analysis.detect_xrd_peaks(t.x, t.y)
    d = [float(xrd_analysis.bragg_d_spacing(p["two_theta"] - 0.03, xrd.get_wavelength())) for p in t.peaks]
    dlg = workbench.xrd_calibrate(win, certified_d=d, displacement=False)
    assert t.metadata["calibration"]["zero_shift_deg"] == pytest.approx(0.03, abs=1e-6)
    dlg.close()
    workbench.xrd_index_cubic(win).close()
    workbench.xrd_pattern_warnings(win).close()
    card = tmp_path / "card.csv"
    card.write_text("# name=test card\nd,intensity\n" + "\n".join(f"{v:.5f},100" for v in d), encoding="utf-8")
    dlg = workbench.xrd_phase_card(win, str(card))
    assert "not an identification" in dlg.text
    dlg.close()
    info = workbench.xrd_export_refinement(win, str(tmp_path / "p.xye"))
    assert info["points"] == len(t.x)


def test_evidence_report_and_palette_and_cursor(win, tmp_path):
    import workbench
    from labkit.style import PALETTES
    rec = workbench.evidence_report(win, sample_id="S-1", path=str(tmp_path / "e.html"), assumptions=["test"])
    assert rec["ftir"] and rec["xrd"] and (tmp_path / "e.json").is_file()
    assert "S-1" in (tmp_path / "e.html").read_text(encoding="utf-8")
    win.use_colour_blind_palette()
    assert win.page("ftir").get_active().color in PALETTES["publication"]
    text = workbench.describe_cursor("xrd", 30.0, 10.0, win.page("xrd").get_active(), LAM)
    assert f"d = {LAM / (2 * math.sin(math.radians(15))):.4f} Å" in text


def test_display_decimation_keeps_extremes():
    import workbench
    x = np.arange(200000.0)
    y = np.sin(x / 1000.0)
    y[123457] = 5.0
    xd, yd = workbench.decimate_minmax(x, y, 20000)
    assert len(xd) <= 20000 and yd.max() == 5.0 and xd[np.argmax(yd)] == 123457
    assert yd.min() == pytest.approx(y.min())
    assert np.all(np.diff(xd) > 0)


def test_preferences_persist_and_apply(win):
    import workbench
    from labkit.style import PALETTES
    workbench.preferences_dialog(win, {"display_max_points": 5000, "palette": "house"})
    assert workbench.load_preferences() == {"display_max_points": 5000, "palette": "house"}
    assert win.page("ftir").DISPLAY_MAX_POINTS == 5000
    assert win.page("ftir").get_active().color in PALETTES["review"]
    workbench.preferences_dialog(win, {"display_max_points": 20000, "palette": "colour-blind"})
    assert win.page("xrd").get_active().color in PALETTES["publication"]
    assert win.shortcut_conflicts() == []
