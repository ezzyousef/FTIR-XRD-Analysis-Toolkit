"""
xrd_tab.py
The XRD page: load diffraction patterns (multi-trace overlay), set the instrument (wavelength,
Scherrer K, instrument profile), process (SNIP background, Kalpha2 stripping, smoothing),
detect peaks, compute d-spacing / Scherrer size / Williamson-Hall size and strain with their
uncertainties, % crystallinity and a cubic lattice parameter, fit peaks, and export CSV / PDF /
Origin / Excel / sessions. Every result keeps the parameters it was computed with.
Phase identification against reference cards is deliberately out of scope.
"""
import csv
import datetime
import html
import os
import tempfile

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QSplitter,
                               QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

import file_readers
import formula_sources as fs
import peak_fitting
import report_export
import ui_common
import xrd_analysis
from app_info import APP_VERSION
from labkit.qt.theme import colours
from labkit.style import THEMES
from ui_common import AnalysisTabBase, DataTable, parse_float

CUSTOM_WAVELENGTH = "Custom..."
WH_PLACEHOLDER = ("Detect peaks (3 or more with a resolvable width), then run Williamson–Hall. Strip Kα2 and set "
                  "the instrument profile first: both change the widths a lot.")
REGION_COLOURS = {"crystalline": "#E69F00", "amorphous": "#56B4E9"}
WIDTH_SOURCES = {"fitted": "Fitted peak where available", "detected": "Detected (raw points)"}
PEAK_LABEL_LIMIT = 20


def _fmt_sig(value, digits=3):
    return "–" if value is None else f"{value:.{digits}g}"


class XRDTab(AnalysisTabBase):
    KIND = "xrd"
    READER = staticmethod(file_readers.read_any)
    FILE_FILTER = "Diffraction patterns (*.xy *.txt *.dat *.csv *.uxd *.ras *.xrdml *.raw);;All files (*.*)"
    LOAD_TEXT = "Load patterns…"
    DROP_HINT = (".xy .txt .dat .csv .uxd .ras .xrdml (high confidence), .raw (Bruker, best effort) — "
                 "or drop files anywhere on this page.")

    def __init__(self, app):
        super().__init__(app, x_label="2theta (deg)", y_label="Intensity", invert_x=False)
        self.custom_wl = None
        self._last_wl_name = "Cu Ka1"
        self.instrument = {"U": 0.0, "V": 0.0, "W": 0.0, "mode": "gaussian", "source": "none"}
        self.calc_log = []
        self._build_controls()
        self._build_results_tabs()
        self._on_traces_changed()

    # ---------------------------------------------------------------- controls
    def _build_controls(self):
        card = self.add_card("1 · Instrument", "Changing any of these clears results computed with the old values.")
        self.wl_combo = QComboBox()
        self.wl_combo.addItems(list(xrd_analysis.WAVELENGTHS.keys()) + [CUSTOM_WAVELENGTH])
        self.wl_combo.currentTextChanged.connect(self._wavelength_changed)
        card.body.addWidget(self.labelled("X-ray wavelength", self.wl_combo))
        self.wl_label = QLabel()
        self.wl_label.setObjectName("Hint")
        self.wl_label.setWordWrap(True)
        card.body.addWidget(self.wl_label)
        self.k_spin = QDoubleSpinBox()
        self.k_spin.setRange(0.5, 2.1)
        self.k_spin.setDecimals(2)
        self.k_spin.setSingleStep(0.01)
        self.k_spin.setValue(0.9)
        self.k_spin.setToolTip("Scherrer shape factor. 0.9 is a common default for roughly spherical crystallites; "
                               "values from about 0.6 to 2 are used for other shapes and width definitions.")
        self.k_spin.valueChanged.connect(lambda _v: self._instrument_changed("Scherrer K"))
        card.body.addWidget(self.labelled("Scherrer K", self.k_spin))
        card.body.addWidget(self.action_button("Instrument profile…", self.edit_instrument_profile,
                                               info=("Instrumental broadening", fs.XRD_INSTRUMENT_PROFILE)))
        card.body.addWidget(self.action_button("Refine profile from this pattern (standard)", self.refine_instrument))
        self.inst_label = QLabel()
        self.inst_label.setObjectName("Hint")
        self.inst_label.setWordWrap(True)
        card.body.addWidget(self.inst_label)

        card = self.add_card("2 · Processing", "In this order: background, then Kα2, then (only if needed) "
                                               "smoothing. Processing clears peaks and size/strain results.")
        card.body.addWidget(self.action_button("Subtract background (SNIP)…", self.subtract_background_active,
                                               info=("XRD background subtraction (SNIP)", fs.XRD_BACKGROUND_SUBTRACTION)))
        card.body.addWidget(self.action_button("Strip Kα2 (Rachinger)…", self.strip_kalpha2_active,
                                               info=("Kα2 stripping", fs.XRD_KALPHA2_STRIPPING)))
        card.body.addWidget(self.action_button("Smooth (Savitzky–Golay)…", self.smooth_active))
        revert = self.action_button("Revert to raw data", self.revert_active)
        revert.button.setObjectName("Danger")
        card.body.addWidget(revert)

        card = self.add_card("3 · Peak detection")
        self.prom_spin = QDoubleSpinBox()
        self.prom_spin.setRange(0.2, 20.0)
        self.prom_spin.setSingleStep(0.2)
        self.prom_spin.setValue(2.0)
        self.prom_spin.setSuffix(" %")
        card.body.addWidget(self.labelled("Sensitivity (prominence)", self.prom_spin))
        self.noise_check = QCheckBox("Ignore noise (7σ of the local noise)")
        self.noise_check.setChecked(True)
        self.noise_check.setToolTip("Counting noise grows with intensity, so each peak is judged against the noise "
                                    "around it; weaker maxima inside a stronger peak and spikes are dropped.")
        card.body.addWidget(self.noise_check)
        card.body.addWidget(self.action_button("Detect peaks", self.detect_peaks, primary=True))

        card = self.add_card("4 · Size & strain")
        self.width_combo = QComboBox()
        for key, label in WIDTH_SOURCES.items():
            self.width_combo.addItem(label, key)
        self.width_combo.setToolTip("Fitted widths are far more reliable than widths read from raw points, "
                                    "especially for overlapping or noisy peaks. Fit the peaks first (card 6).")
        card.body.addWidget(self.labelled("Peak width", self.width_combo))
        card.body.addWidget(self.action_button("d-spacing + Scherrer size", self.run_all_calcs, primary=True,
                                               info=("Bragg's law & Scherrer equation",
                                                     fs.BRAGG_LAW + "\n\n" + fs.SCHERRER_EQUATION)))
        card.body.addWidget(self.action_button("Williamson–Hall (size + strain)", self.run_williamson_hall,
                                               info=("Williamson–Hall method", fs.WILLIAMSON_HALL)))
        hint = QLabel("Untick a peak in the Peaks table to leave it out of both.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        card.body.addWidget(hint)

        card = self.add_card("5 · Crystallinity")
        card.body.addWidget(self.action_button("% crystallinity (regions)…", self.run_crystallinity,
                                               info=("% crystallinity method", fs.PERCENT_CRYSTALLINITY)))

        card = self.add_card("6 · Peak fitting")
        self.shape_combo = QComboBox()
        self.shape_combo.addItems(["pseudo_voigt", "gaussian", "lorentzian"])
        card.body.addWidget(self.labelled("Peak shape", self.shape_combo))
        self.auto_window = QCheckBox("Window ±3 × each peak's width")
        self.auto_window.setChecked(True)
        self.auto_window.setToolTip("A fixed window cuts broad peaks short or takes in neighbours.")
        self.auto_window.toggled.connect(lambda on: self.window_spin.setEnabled(not on))
        card.body.addWidget(self.auto_window)
        self.window_spin = QDoubleSpinBox()
        self.window_spin.setRange(0.05, 5.0)
        self.window_spin.setSingleStep(0.05)
        self.window_spin.setValue(0.5)
        self.window_spin.setSuffix(" °")
        self.window_spin.setEnabled(False)
        card.body.addWidget(self.labelled("Fixed window (± 2θ)", self.window_spin))
        card.body.addWidget(self.action_button("Fit all detected peaks", self.fit_peaks,
                                               info=("Peak fitting method", fs.PEAK_FITTING)))

        card = self.add_card("Tools")
        card.body.addWidget(self.action_button("Cubic lattice parameter (single peak)…", self.run_lattice_param,
                                               info=("Cubic lattice parameter", fs.CUBIC_LATTICE_PARAMETER)))
        card.body.addWidget(self.action_button("2θ / d-spacing / Q converter…", self.open_unit_converter,
                                               info=("XRD unit converter", fs.XRD_UNIT_CONVERTER)))

        card = self.add_card("Files & session", "Origin, Excel and figures: the buttons under the plot.")
        for text, fn in (("Export peak list (CSV)…", self.export_peaks_csv),
                         ("Export PDF report…", self.export_pdf_report),
                         ("Export for OriginLab (CSV)…", self.export_originlab_dialog),
                         ("Export graph (SVG/EPS/PDF/PNG)…", self.export_graph_dialog),
                         ("Save session…", self.save_session),
                         ("Load session…", self.load_session)):
            card.body.addWidget(self.action_button(text, fn))
        self._update_wavelength_label()
        self._update_instrument_label()

    def _build_results_tabs(self):
        self.peaks_table = DataTable(["Use", "2θ (°)", "d (Å)", "I/I₀ (%)", "FWHM (°)", "Sample β (°)",
                                      "Apparent size* (nm)", "Note"])
        tips = ["Tick to include the peak in Scherrer and Williamson–Hall",
                "Peak position", "Bragg d-spacing at the wavelength used", "Relative intensity",
                "Measured width (fitted if available and selected, else from raw points)",
                "Width after removing the instrument profile", "Scherrer size from the sample width. *Apparent: "
                "a lower bound when strain or uncorrected broadening is present", "Why a peak is excluded"]
        for i, tip in enumerate(tips):
            self.peaks_table.horizontalHeaderItem(i).setToolTip(tip)
        self.peaks_table.itemChanged.connect(self._peak_use_toggled)
        self.results_tabs.addTab(self.peaks_table, "Peaks")

        wh = QWidget()
        wl = QHBoxLayout(wh)
        wl.setContentsMargins(4, 4, 4, 4)
        split = QSplitter(Qt.Horizontal)
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure
        self.wh_figure = Figure(figsize=(4, 2.6), dpi=100)
        self.wh_canvas = FigureCanvasQTAgg(self.wh_figure)
        self.wh_canvas.setMinimumWidth(260)
        split.addWidget(self.wh_canvas)
        self.wh_text = QTextBrowser()
        self.wh_text.setPlainText(WH_PLACEHOLDER)
        split.addWidget(self.wh_text)
        split.setSizes([420, 420])
        split.setChildrenCollapsible(False)
        wl.addWidget(split)
        self.wh_page = wh
        self.results_tabs.addTab(wh, "Williamson–Hall")

        self.cryst_text = QTextBrowser()
        self.cryst_text.setPlainText("Run % crystallinity: the regions are drawn on the plot and the result appears here.")
        self.results_tabs.addTab(self.cryst_text, "Crystallinity")
        self.fits_table = DataTable(["Detected 2θ (°)", "Fitted centre (°)", "FWHM (°)", "Height", "Area", "R²", "Shape"])
        self.results_tabs.addTab(self.fits_table, "Peak fits")
        self.log_table = DataTable(["When", "Calculation", "Inputs", "Result"])
        self.results_tabs.addTab(self.log_table, "Calculations")

    def load_file_path(self, path, reader=None, record=True):
        trace = super().load_file_path(path, reader=reader, record=record)
        if trace is None:
            return None
        meta = trace.metadata
        file_wl = meta.get("wavelength_kalpha1") or meta.get("HW_XG_WAVE_LENGTH_ALPHA1")
        try:
            file_wl = float(file_wl) if file_wl else None
        except ValueError:
            file_wl = None
        if file_wl and abs(file_wl - self.get_wavelength()) > 1e-3:
            self.app.notify(f"{trace.label} was measured at Kα1 = {file_wl:.6f} Å but λ is set to "
                            f"{self.get_wavelength():.6f} Å — choose the matching wavelength (or Custom…)", "warning")
        return trace

    # ---------------------------------------------------------------- instrument
    def _wavelength_changed(self, name):
        if name == CUSTOM_WAVELENGTH and not self._prompt_custom_wavelength():
            self.wl_combo.blockSignals(True)
            self.wl_combo.setCurrentText(self._last_wl_name)
            self.wl_combo.blockSignals(False)
            self._update_wavelength_label()
            return
        self._last_wl_name = self.wl_combo.currentText()
        self._update_wavelength_label()
        self._instrument_changed("wavelength")

    def _prompt_custom_wavelength(self):
        v = ui_common.ask_fields(self, "Custom wavelength", [("wl", "Wavelength (Å):", f"{self.custom_wl or 1.540562}")])
        if v is None:
            return False
        try:
            value = parse_float(v["wl"], "Wavelength")
            if value <= 0:
                raise ValueError("The wavelength must be positive.")
            self.custom_wl = value
            return True
        except ValueError as exc:
            ui_common.show_message(self, "Invalid wavelength", str(exc), "error")
            return False

    def _update_wavelength_label(self):
        name = self.wl_combo.currentText()
        text = f"λ = {self.get_wavelength():.6f} Å"
        if name == "Cu Ka (weighted avg)":
            text += " — for patterns with Kα2 left in; strip Kα2 and use Cu Ka1 for size/strain"
        elif name != "Cu Ka1":
            text += " — check against your instrument's documentation"
        self.wl_label.setText(text)

    def get_wavelength(self):
        name = self.wl_combo.currentText()
        if name == CUSTOM_WAVELENGTH:
            return self.custom_wl or xrd_analysis.WAVELENGTHS["Cu Ka1"]
        return xrd_analysis.WAVELENGTHS[name]

    def instrument_fwhm(self, two_theta):
        i = self.instrument
        return xrd_analysis.caglioti_fwhm(two_theta, i["U"], i["V"], i["W"])

    def _update_instrument_label(self):
        i = self.instrument
        if i["source"] == "none":
            self.inst_label.setText("Instrument profile: none — sizes are NOT corrected for instrumental broadening.")
        else:
            self.inst_label.setText(f"Instrument profile ({i['source']}): FWHM {self.instrument_fwhm(30):.3f}° at 30°, "
                                    f"{self.instrument_fwhm(90):.3f}° at 90° 2θ; {i['mode']} correction.")

    def _instrument_changed(self, what):
        stale = 0
        for t in self.traces:
            stale += self._clear_size_results(t)
        self._update_instrument_label()
        self.redraw()
        self.on_active_trace_changed()
        if stale:
            self.app.notify(f"{what} changed — size/strain results cleared; recalculate", "warning")

    def edit_instrument_profile(self):
        i = self.instrument
        v = ui_common.ask_fields(
            self, "Instrument profile",
            [("const", "Constant instrument FWHM (°), or leave empty to use U, V, W:",
              "" if i["U"] or i["V"] else (f"{np.sqrt(i['W']):.4f}" if i["W"] > 0 else "")),
             ("U", "Caglioti U (deg²):", f"{i['U']:g}"), ("V", "Caglioti V (deg²):", f"{i['V']:g}"),
             ("W", "Caglioti W (deg²):", f"{i['W']:g}"),
             ("mode", "Correction:", i["mode"], ["gaussian", "lorentzian"])],
            help_text="FWHM² = U·tan²θ + V·tanθ + W, measured on a line-profile standard (e.g. LaB6 or Si) with the "
                      "same optics. All zero = no correction.")
        if v is None:
            return
        try:
            if v["const"].strip():
                b = parse_float(v["const"], "Instrument FWHM")
                U, V, W = 0.0, 0.0, b * b
            else:
                U, V, W = (parse_float(v[k], k) for k in ("U", "V", "W"))
        except ValueError as exc:
            ui_common.show_message(self, "Invalid profile", str(exc), "error")
            return
        source = "none" if (U, V, W) == (0.0, 0.0, 0.0) else "entered"
        self.instrument = {"U": U, "V": V, "W": W, "mode": v["mode"], "source": source}
        self._instrument_changed("Instrument profile")
        self.record("instrument profile")

    def refine_instrument(self):
        t = self.require_active("Load the pattern of a line-profile standard first.")
        if t is None:
            return
        widths = self._widths(t, prefer="fitted")
        pts = [(p["two_theta"], w) for p, w in zip(t.peaks, widths) if w and p.get("use", True)]
        if len(pts) < 3:
            self.app.notify("Detect (and ideally fit) at least 3 peaks of the standard first.", "warning")
            return
        try:
            res = xrd_analysis.fit_caglioti([a for a, _ in pts], [b for _, b in pts])
        except ValueError as exc:
            ui_common.show_message(self, "Refinement failed", str(exc), "error")
            return
        if not ui_common.ask_yes_no(self, "Use this instrument profile?",
                                    f"U = {res['U']:.3g}, V = {res['V']:.3g}, W = {res['W']:.3g} deg² from "
                                    f"{res['n_peaks']} peaks of {t.label} (R² {res['r_squared']:.3f}).\n\nOnly use a "
                                    "pattern of a well-crystallised standard measured with the same optics."):
            return
        self.instrument = {"U": res["U"], "V": res["V"], "W": res["W"], "mode": self.instrument["mode"],
                           "source": f"refined from {t.label}"}
        self._log("Instrument profile", f"{res['n_peaks']} peaks of {t.label}",
                  f"U={res['U']:.3g}, V={res['V']:.3g}, W={res['W']:.3g}, R²={res['r_squared']:.3f}")
        self._instrument_changed("Instrument profile")
        self.record("refine instrument profile")

    def params(self, t=None):
        """Everything a size/strain result depends on, recorded with the result."""
        return {"wavelength_a": self.get_wavelength(), "wavelength_name": self.wl_combo.currentText(),
                "K": self.k_spin.value(), "instrument": dict(self.instrument),
                "width_source": self.width_combo.currentData(),
                "processing": list((t.metadata.get("processing") if t is not None else None) or []),
                "app_version": APP_VERSION, "run_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}

    # ---------------------------------------------------------------- state
    def export_options(self):
        t = self.get_active()
        stored = (t.metadata.get("xrd_params") or {}) if t is not None else {}
        return {"wavelength": stored.get("wavelength_a", self.get_wavelength())}

    def session_settings(self):
        return {"wavelength_name": self.wl_combo.currentText(), "custom_wl": self.custom_wl,
                "prominence": self.prom_spin.value(), "K": self.k_spin.value(), "instrument": dict(self.instrument),
                "width_source": self.width_combo.currentData(), "noise_floor": self.noise_check.isChecked(),
                "calc_log": list(self.calc_log)}

    def apply_session_settings(self, state):
        self.custom_wl = state.get("custom_wl")
        for w in (self.wl_combo, self.k_spin):
            w.blockSignals(True)
        index = self.wl_combo.findText(state.get("wavelength_name", "Cu Ka1"))
        self.wl_combo.setCurrentIndex(max(0, index))
        self._last_wl_name = self.wl_combo.currentText()
        self.k_spin.setValue(float(state.get("K", 0.9)))
        for w in (self.wl_combo, self.k_spin):
            w.blockSignals(False)
        self.prom_spin.setValue(float(state.get("prominence", 2.0)))
        self.instrument = dict(state.get("instrument") or {"U": 0.0, "V": 0.0, "W": 0.0, "mode": "gaussian",
                                                           "source": "none"})
        self.width_combo.setCurrentIndex(max(0, self.width_combo.findData(state.get("width_source", "fitted"))))
        self.noise_check.setChecked(bool(state.get("noise_floor", True)))
        self.calc_log = list(state.get("calc_log") or [])
        self._refresh_log()
        self._update_wavelength_label()
        self._update_instrument_label()

    def _is_live(self, trace, y_snapshot=None):
        """False when undo, a session load, a removal or processing changed the trace a job used."""
        if not any(t is trace for t in self.traces):
            return False
        return y_snapshot is None or (len(trace.y) == len(y_snapshot) and np.array_equal(trace.y, y_snapshot))

    def _discarded(self):
        self.app.notify("Result discarded — the pattern changed (undo, processing or a new session) while it was "
                        "running.", "warning")

    @staticmethod
    def _clear_size_results(t):
        had = bool(t.metadata.get("wh_result")) or any(p.get("size_nm") or p.get("d_A") for p in t.peaks)
        for p in t.peaks:
            for key in ("d_A", "size_nm", "beta_deg", "width_used_deg", "note"):
                p.pop(key, None)
        for key in ("wh_result", "xrd_params"):
            t.metadata.pop(key, None)
        return int(had)

    # ---------------------------------------------------------------- plotting
    def _plot_active_extras(self, ax, trace, theme):
        fg = self.foreground(theme)
        regions = trace.metadata.get("crystallinity_regions")
        if regions:
            for kind, hatch in (("crystalline", None), ("amorphous", "//")):
                for lo, hi in regions.get(kind, []):
                    ax.axvspan(lo, hi, color=REGION_COLOURS[kind], alpha=0.18, lw=0, hatch=hatch, zorder=0)
        if not trace.peaks:
            return
        used = [p for p in trace.peaks if p.get("use", True) and p.get("usable", True)]
        skipped = [p for p in trace.peaks if p not in used]
        ax.plot([p["two_theta"] for p in used], [p["intensity"] for p in used], linestyle="none", marker="v",
                markersize=5, color=fg, alpha=0.8, zorder=4, clip_on=False)
        if skipped:
            ax.plot([p["two_theta"] for p in skipped], [p["intensity"] for p in skipped], linestyle="none", marker="v",
                    markersize=5, markerfacecolor="none", markeredgecolor=fg, alpha=0.6, zorder=4)
        placed = []
        span = float(np.ptp(trace.x)) if len(trace.x) else 1.0
        for p in sorted(trace.peaks, key=lambda p: -p["intensity"])[:PEAK_LABEL_LIMIT]:
            if any(abs(p["two_theta"] - q) < span / 60 for q in placed):
                continue
            placed.append(p["two_theta"])
            ax.annotate(f"{p['two_theta']:.2f}", (p["two_theta"], p["intensity"]), xytext=(0, 7),
                        textcoords="offset points", fontsize=7, rotation=90, ha="center", va="bottom", color=fg)

    # ---------------------------------------------------------------- results refresh
    def on_theme_changed(self, theme):
        super().on_theme_changed(theme)
        self.on_active_trace_changed()

    def on_active_trace_changed(self):
        t = self.get_active()
        if t is None:
            self.peaks_table.clear_rows()
            self.fits_table.clear_rows()
            self._show_wh_result(None)
            self._show_crystallinity(None)
            return
        top = max((p["intensity"] for p in t.peaks), default=1.0) or 1.0
        self.peaks_table.set_rows(t.peaks, lambda p: self._format_peak_row(p, top))
        self.peaks_table.blockSignals(True)
        muted = QBrush(QColor(colours(self.theme)["muted"]))
        for r, p in enumerate(t.peaks):
            item = QTableWidgetItem("")
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            item.setCheckState(Qt.Checked if p.get("use", True) and p.get("usable", True) else Qt.Unchecked)
            if not p.get("usable", True):
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.peaks_table.setItem(r, 0, item)
            if not (p.get("use", True) and p.get("usable", True)):
                for c in range(1, self.peaks_table.columnCount()):
                    cell = self.peaks_table.item(r, c)
                    if cell is not None:
                        cell.setForeground(muted)
        self.peaks_table.blockSignals(False)
        self.fits_table.set_rows(t.fits, lambda f: (
            f"{f['seed_x']:.3f}", f"{f['center']:.3f}", f"{f['fwhm']:.4f}", f"{f['height']:.4g}",
            f"{f['area']:.4g}", f"{f['r_squared']:.4f}", f["shape"]))
        self._show_wh_result(t.metadata.get("wh_result"), t)
        self._show_crystallinity(t)

    @staticmethod
    def _format_peak_row(p, top):
        return ("", f"{p['two_theta']:.3f}", f"{p['d_A']:.4f}" if p.get("d_A") else "–",
                f"{100 * p['intensity'] / top:.0f}", f"{p.get('width_used_deg', p['fwhm_deg']):.4f}",
                f"{p['beta_deg']:.4f}" if p.get("beta_deg") else "–", _fmt_sig(p.get("size_nm")),
                p.get("note") or ("" if p.get("usable", True) else "spike (narrower than 3 points)"))

    def _peak_use_toggled(self, item):
        if item.column() != 0:
            return
        t = self.get_active()
        if t is None or item.row() >= len(t.peaks):
            return
        p = t.peaks[item.row()]
        p["use"] = item.checkState() == Qt.Checked
        cleared = bool(t.metadata.pop("wh_result", None))
        self.redraw()
        self.on_active_trace_changed()
        self.app.notify(f"Peak at {p['two_theta']:.2f}° {'included' if p['use'] else 'excluded'}"
                        + (" — run Williamson–Hall again" if cleared else ""), "info")
        self.record("toggle peak use")

    def _draw_wh_plot(self, wh):
        fig = self.wh_figure
        fig.clear()
        theme = THEMES.get(self.theme, THEMES["light"])
        fig.set_facecolor(theme.panel)
        ax = fig.add_subplot(111)
        ax.set_facecolor(theme.panel)
        for spine in ax.spines.values():
            spine.set_color(theme.muted)
        ax.tick_params(colors=theme.foreground, labelsize=7)
        if wh and wh.get("x"):
            x, y = np.array(wh["x"]), np.array(wh["y"]) * 1e3
            ax.plot(x, y, "o", color="#0072B2", markersize=5)
            xx = np.linspace(0, max(x) * 1.05, 50)
            ax.plot(xx, (wh["slope"] * xx + wh["intercept"]) * 1e3, "-", color=theme.foreground, lw=1)
            for xi, yi, tt in zip(x, y, wh.get("two_theta", [])):
                ax.annotate(f"{tt:.1f}°", (xi, yi), xytext=(3, 3), textcoords="offset points", fontsize=6,
                            color=theme.muted)
            ax.set_xlim(left=0)
        ax.set_xlabel("4 sin θ", fontsize=8, color=theme.foreground)
        ax.set_ylabel("β cos θ (×10⁻³ rad)", fontsize=8, color=theme.foreground)
        fig.tight_layout(pad=0.6)
        self.wh_canvas.draw_idle()

    def _show_wh_result(self, wh, t=None):
        self._draw_wh_plot(wh)
        if not wh:
            self.wh_text.setPlainText(WH_PLACEHOLDER)
            return
        c = colours(self.theme)
        e = html.escape
        D, sD = wh.get("crystallite_size_nm"), wh.get("crystallite_size_se_nm")
        eps, seps = wh["microstrain"], wh.get("microstrain_se")
        size_txt = (f"{D:.3g} ± {sD:.2g} nm" if D and sD is not None else
                    f"{D:.3g} nm" if D else "not resolvable (intercept ≤ 0)")
        strain_txt = f"{eps * 1e3:.3g} ± {seps * 1e3:.2g} ×10⁻³" if seps is not None else f"{eps * 1e3:.3g} ×10⁻³"
        params = (t.metadata.get("xrd_params") if t is not None else None) or {}
        inst = params.get("instrument", {})
        warns = []
        if not wh.get("strain_physical", True):
            warns.append("The strain came out negative: no strain is resolvable above the scatter — treat it as ≈ 0.")
        if sD is not None and D and sD > 0.5 * D:
            warns.append("The size uncertainty is large: too few peaks or too much scatter.")
        if seps is not None and seps > abs(eps):
            warns.append("The strain is smaller than its uncertainty.")
        if not inst or inst.get("source") == "none":
            warns.append("No instrument profile: sizes are underestimated, most for large crystallites.")
        if "Kα2 stripped" not in " ".join(params.get("processing", [])) and \
                params.get("wavelength_name") in ("Cu Ka1", "Cu Ka (weighted avg)"):
            warns.append("Kα2 not stripped: unresolved doublets widen peaks with angle and mimic strain.")
        rows = "".join(f"<div style='color:{c['warn']}'>⚠ {e(w)}</div>" for w in warns)
        self.wh_text.setHtml(
            f"<div style='font-size:13px'><b>Williamson–Hall</b> ({wh['n_peaks']} peaks)</div>"
            f"<div>Apparent domain size: <b>{e(size_txt)}</b></div>"
            f"<div>Microstrain ε: <b>{e(strain_txt)}</b> (dimensionless)</div>"
            f"<div style='color:{c['muted']}'>β cos θ = Kλ/D + 4ε sin θ · R² {wh.get('r_squared', float('nan')):.3f} "
            "(low R² is expected when there is no strain) · K "
            f"{wh.get('K', params.get('K', 0.9)):.2f} · λ {wh.get('wavelength_a', params.get('wavelength_a', 0)):.6f} Å · "
            f"widths: {e(WIDTH_SOURCES.get(params.get('width_source'), '?').lower())} · instrument: "
            f"{e(inst.get('source', 'none'))}</div>"
            f"<div style='color:{c['muted']}'>Peaks used (2θ): "
            f"{e(', '.join(f'{v:.2f}' for v in wh.get('two_theta', [])))}</div>{rows}")

    def _show_crystallinity(self, t):
        if t is None or t.metadata.get("crystallinity_pct") is None:
            self.cryst_text.setPlainText("Run % crystallinity: the regions are drawn on the plot and the result "
                                         "appears here.")
            return
        r = t.metadata.get("crystallinity_regions", {})
        fmt = lambda regs: ", ".join(f"{a:g}–{b:g}°" for a, b in regs) or "—"  # noqa: E731
        c = colours(self.theme)
        self.cryst_text.setHtml(
            f"<div style='font-size:13px'><b>Crystallinity ≈ {t.metadata['crystallinity_pct']:.1f} %</b></div>"
            f"<div>Crystalline regions (orange): {html.escape(fmt(r.get('crystalline', [])))}</div>"
            f"<div>Amorphous regions (blue, hatched): {html.escape(fmt(r.get('amorphous', [])))}</div>"
            f"<div style='color:{c['muted']}'>Area method on the raw pattern minus a straight baseline across the "
            "regions. Method- and region-dependent: report the regions with the number.</div>")

    # ---------------------------------------------------------------- processing
    def _process(self, title, compute, message, keep_log=True):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        try:
            t.y = compute(t)
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, f"{title} failed", str(exc), "error")
            return
        had = bool(t.peaks or t.fits or t.metadata.get("wh_result"))
        t.peaks, t.fits = [], []
        for key in ("wh_result", "xrd_params"):
            t.metadata.pop(key, None)
        log = list(t.metadata.get("processing") or []) if keep_log else []
        log.append(message)
        t.metadata["processing"] = log
        self.redraw()
        self.on_active_trace_changed()
        self.app.notify(f"{message} on {t.label}" + (" — peaks and results cleared" if had else ""), "success")
        self.record(title.lower())

    def subtract_background_active(self):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        widest = max((p["fwhm_deg"] for p in t.peaks), default=0.3)
        v = ui_common.ask_fields(self, "SNIP background",
                                 [("w", "Clipping window (° 2θ):", f"{max(1.0, 3 * widest):.2f}")],
                                 help_text="About 2–3 × the widest peak's FWHM. Too narrow eats into broad peaks; too "
                                           "wide leaves background under them. SNIP also removes an amorphous halo — "
                                           "% crystallinity always uses the raw data.")
        if v is None:
            return
        try:
            w = parse_float(v["w"], "Window")
        except ValueError as exc:
            ui_common.show_message(self, "Invalid window", str(exc), "error")
            return
        n = xrd_analysis.snip_iterations(t.x, w)
        self._process("Subtract background",
                      lambda tr: tr.y - xrd_analysis.snip_background(tr.y, iterations=n),
                      f"SNIP background subtracted ({w:g}° window)")

    def strip_kalpha2_active(self):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        name = self.wl_combo.currentText()
        l1, l2 = xrd_analysis.KALPHA_PAIRS.get(name, (self.get_wavelength(), None))
        v = ui_common.ask_fields(self, "Strip Kα2 (Rachinger)",
                                 [("l1", "Kα1 wavelength (Å):", f"{l1:.6f}"),
                                  ("l2", "Kα2 wavelength (Å):", f"{l2:.6f}" if l2 else ""),
                                  ("r", "Intensity ratio Kα2/Kα1:", f"{xrd_analysis.KALPHA2_RATIO:g}")],
                                 help_text="Removes the Kα2 component point by point from low angle. Subtract the "
                                           "background first. Use Cu Ka1 (not the weighted average) afterwards. Only Cu "
                                           "is pre-filled: for other anodes enter Kα2 from your instrument documentation.")
        if v is None:
            return
        try:
            a, b, r = (parse_float(v[k], k) for k in ("l1", "l2", "r"))
            if not (b > a > 0 and 0 < r < 1):
                raise ValueError("Need Kα2 > Kα1 > 0 and a ratio between 0 and 1.")
        except ValueError as exc:
            ui_common.show_message(self, "Invalid values", str(exc), "error")
            return
        if name == "Cu Ka (weighted avg)":
            self.wl_combo.setCurrentText("Cu Ka1")
        self._process("Strip Kα2", lambda tr: xrd_analysis.strip_kalpha2(tr.x, tr.y, a, b, r),
                      f"Kα2 stripped (λ1 {a:.6f}, λ2 {b:.6f} Å, ratio {r:g})")

    def smooth_active(self):
        v = ui_common.ask_fields(self, "Smooth pattern", [("wl", "Window length (odd, points):", "11"),
                                                          ("po", "Polynomial order:", "3")],
                                 help_text="Smoothing also broadens sharp peaks: avoid it before size analysis "
                                           "unless the pattern is very noisy.")
        if v is None:
            return
        self._process("Smooth", lambda tr: xrd_analysis.smooth_pattern(tr.y, window_length=int(float(v["wl"])),
                                                                       polyorder=int(float(v["po"]))),
                      f"Smoothed (Savitzky–Golay {v['wl']}/{v['po']})")

    def revert_active(self):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        t.revert_to_raw()
        for key in ("processing", "wh_result", "xrd_params"):
            t.metadata.pop(key, None)
        self._on_traces_changed()
        self.app.notify(f"{t.label} reverted to the data as loaded", "info")
        self.record("revert to raw")

    # ---------------------------------------------------------------- calculations
    def detect_peaks(self, record=True):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        had = bool(t.fits or t.metadata.get("wh_result") or any(p.get("size_nm") for p in t.peaks))
        t.peaks = xrd_analysis.detect_xrd_peaks(t.x, t.y, prominence_frac=self.prom_spin.value() / 100.0,
                                                noise_floor=self.noise_check.isChecked())
        t.fits = []
        for key in ("wh_result", "xrd_params"):
            t.metadata.pop(key, None)
        t.metadata["detection"] = {"prominence_pct": self.prom_spin.value(), "noise_floor": self.noise_check.isChecked()}
        self.redraw()
        self.on_active_trace_changed()
        self.results_tabs.setCurrentWidget(self.peaks_table)
        msg = f"Detected {len(t.peaks)} peaks in {t.label}" + (" — earlier results cleared" if had else "")
        level = "success" if t.peaks else "warning"
        if len(t.peaks) > 100:
            msg += " — that's a lot; raise the sensitivity or keep the noise filter on"
            level = "warning"
        self.app.notify(msg, level)
        if record:
            self.record("detect peaks")

    def _widths(self, t, prefer=None):
        """Measured FWHM per peak (degrees): the fitted width of the nearest fit when wanted and
        available, else the width from the raw points."""
        prefer = prefer or self.width_combo.currentData()
        out = []
        for p in t.peaks:
            w = p["fwhm_deg"]
            if prefer == "fitted" and t.fits:
                fit = min(t.fits, key=lambda f: abs(f["center"] - p["two_theta"]))
                if abs(fit["center"] - p["two_theta"]) < max(p["fwhm_deg"], 0.05) and fit.get("r_squared", 0) > 0.9:
                    w = fit["fwhm"]
            out.append(w)
        return out

    def _size_inputs(self, t):
        """(peak, measured width, sample width or None, reason) for each peak."""
        rows = []
        for p, w in zip(t.peaks, self._widths(t)):
            b_inst = self.instrument_fwhm(p["two_theta"]) if self.instrument["source"] != "none" else 0.0
            if not p.get("usable", True):
                rows.append((p, w, None, "spike (narrower than 3 points)"))
            elif not p.get("use", True):
                rows.append((p, w, None, "excluded by you"))
            elif b_inst and w < b_inst:
                rows.append((p, w, None, "narrower than the instrument — noise?"))
            else:
                beta = xrd_analysis.correct_instrumental(w, b_inst, self.instrument["mode"])
                rows.append((p, w, beta, "" if beta else "not broader than the instrument"))
        return rows

    def run_all_calcs(self):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        if not t.peaks:
            self.detect_peaks(record=False)
            if not t.peaks:
                return
        wl, K = self.get_wavelength(), self.k_spin.value()
        sized = 0
        for p, w, beta, note in self._size_inputs(t):
            try:
                p["d_A"] = float(xrd_analysis.bragg_d_spacing(p["two_theta"], wl))
            except ValueError:
                p["d_A"] = None
            p["width_used_deg"], p["beta_deg"], p["note"] = w, beta, note
            p["size_nm"] = (float(xrd_analysis.scherrer_crystallite_size(beta, p["two_theta"], wl, K=K))
                            if beta else None)
            if p["size_nm"] and p["size_nm"] > 150:
                p["note"] = "> 150 nm: beyond reliable Scherrer range"
            sized += int(bool(p["size_nm"]))
        t.metadata["xrd_params"] = self.params(t)
        self.on_active_trace_changed()
        self.results_tabs.setCurrentWidget(self.peaks_table)
        sizes = [p["size_nm"] for p in t.peaks if p.get("size_nm")]
        msg = f"d-spacing for {len(t.peaks)} peaks, Scherrer size for {sized} (λ {wl:.6f} Å, K {K:.2f})"
        if sizes:
            msg += f" — median apparent size {np.median(sizes):.3g} nm"
        self.app.notify(msg, "success" if sized else "warning")
        self.record("d-spacing + Scherrer")

    def run_williamson_hall(self):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        if not t.peaks:
            self.app.notify("Detect peaks first.", "warning")
            return
        rows = [(p, beta) for p, _w, beta, _n in self._size_inputs(t) if beta]
        try:
            res = xrd_analysis.williamson_hall([p["two_theta"] for p, _ in rows], [b for _, b in rows],
                                               self.get_wavelength(), K=self.k_spin.value())
            res["n_peaks"] = len(rows)
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "Williamson–Hall failed", f"{exc}\n\nUsable peaks: {len(rows)}.", "error")
            return
        t.metadata["wh_result"] = res
        t.metadata["xrd_params"] = self.params(t)
        self._show_wh_result(res, t)
        self.results_tabs.setCurrentWidget(self.wh_page)
        D = res.get("crystallite_size_nm")
        self.app.notify(f"Williamson–Hall ({len(rows)} peaks): D ≈ {D:.3g} nm, ε = {res['microstrain'] * 1e3:.3g}×10⁻³, "
                        f"R² {res['r_squared']:.2f}" if D else
                        f"Williamson–Hall ({len(rows)} peaks): size not resolvable, ε = {res['microstrain'] * 1e3:.3g}×10⁻³",
                        "success")
        self.record("Williamson–Hall")

    def run_crystallinity(self):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        old = t.metadata.get("crystallinity_regions") or {}
        fmt = lambda regs: ",".join(f"{a:g}-{b:g}" for a, b in regs)  # noqa: E731
        v = ui_common.ask_fields(self, "% crystallinity",
                                 [("crys", "Crystalline region(s) 2θ, e.g. 18-24,26-28:", fmt(old.get("crystalline", []))),
                                  ("amorph", "Amorphous region(s) 2θ, e.g. 15-18:", fmt(old.get("amorphous", [])))],
                                 help_text="Area method on the RAW pattern minus a straight baseline across the regions: "
                                           "%Xc = crystalline area / (crystalline + amorphous area). Background "
                                           "subtraction is ignored here because SNIP also removes the amorphous halo.")
        if v is None:
            return

        def parse_regions(text):
            regions = []
            for chunk in text.strip().split(","):
                if chunk.strip():
                    a, b = chunk.strip().split("-")
                    regions.append((min(float(a), float(b)), max(float(a), float(b))))
            return regions

        try:
            crys, amorph = parse_regions(v["crys"]), parse_regions(v["amorph"])
            if not crys or not amorph:
                raise ValueError("give at least one crystalline and one amorphous region")
            pct = xrd_analysis.percent_crystallinity(t.x, t.y_raw, crys, amorph, linear_baseline=True)
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "% crystallinity failed", f"Could not use those regions: {exc}", "error")
            return
        t.metadata["crystallinity_pct"] = pct
        t.metadata["crystallinity_regions"] = {"crystalline": crys, "amorphous": amorph}
        self.redraw()
        self._show_crystallinity(t)
        self.results_tabs.setCurrentWidget(self.cryst_text)
        self.app.notify(f"Crystallinity ≈ {pct:.1f} % (regions on the plot)", "success")
        self.record("% crystallinity")

    def _log(self, what, inputs, result):
        self.calc_log.append({"when": datetime.datetime.now().strftime("%H:%M"), "what": what, "inputs": inputs,
                              "result": result})
        self._refresh_log()

    def _refresh_log(self):
        self.log_table.set_rows(self.calc_log, lambda r: (r["when"], r["what"], r["inputs"], r["result"]))

    def run_lattice_param(self):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        default = f"{max(t.peaks, key=lambda p: p['two_theta'])['two_theta']:.3f}" if t.peaks else ""
        v = ui_common.ask_fields(self, "Cubic lattice parameter",
                                 [("tt", "2θ (°):", default), ("h", "h:", "1"), ("k", "k:", "1"), ("l", "l:", "1")],
                                 help_text="Only valid for cubic crystal systems. A high-angle peak gives the most "
                                           "precise value (σd/d = cot θ · σθ).")
        if v is None:
            return
        try:
            wl = self.get_wavelength()
            tt = parse_float(v["tt"], "2θ")
            hkl = [parse_float(v[c], c) for c in "hkl"]
            if any(x != int(x) for x in hkl):
                raise ValueError("h, k and l must be whole numbers.")
            h, k, l_ = (int(x) for x in hkl)
            d = xrd_analysis.bragg_d_spacing(tt, wl)
            a = xrd_analysis.cubic_lattice_parameter(d, h, k, l_)
            sa = xrd_analysis.d_spacing_uncertainty(tt, wl, 0.01) * np.sqrt(h * h + k * k + l_ * l_)
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "Lattice parameter failed", str(exc), "error")
            return
        note = xrd_analysis.cubic_extinction_note(h, k, l_)
        self._log("Cubic lattice parameter", f"2θ {tt:g}°, ({h}{k}{l_}), λ {wl:.6f} Å",
                  f"d = {d:.5f} Å, a = {a:.5f} Å (±{sa:.1g} per 0.01° in 2θ); {note}")
        self.results_tabs.setCurrentWidget(self.log_table)
        self.app.notify(f"a = {a:.5f} Å for ({h}{k}{l_}) at {tt:g}° — {note}", "success")
        self.record("lattice parameter")

    def fit_peaks(self):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        if not t.peaks:
            self.app.notify("Detect peaks first.", "warning")
            return
        shape = self.shape_combo.currentText()
        auto, fixed = self.auto_window.isChecked(), self.window_spin.value()
        seeds = [(p["two_theta"], max(3 * p["fwhm_deg"], 0.1) if auto else fixed) for p in t.peaks]
        x_snap, y_snap = t.x.copy(), t.y.copy()

        def compute():
            fits, errors = [], []
            for x0, window in seeds:
                part, err = peak_fitting.fit_peaks_batch(x_snap, y_snap, [{"x": x0}], window, shape=shape)
                fits += part
                errors += err
            return fits, errors

        def on_done(result):
            if not self._is_live(t, y_snap):
                self._discarded()
                return
            fits, errors = result
            t.fits = fits
            self._clear_size_results(t)
            self.redraw()
            self.on_active_trace_changed()
            self.results_tabs.setCurrentWidget(self.fits_table)
            msg = f"Fitted {len(fits)}/{len(seeds)} peaks" + (" (window ±3×FWHM)" if auto else f" (window ±{fixed:g}°)")
            if errors:
                msg += f"; {len(errors)} did not converge"
            self.app.notify(msg + " — recalculate size/strain to use the fitted widths", "success" if not errors else "warning")
            self.record("fit peaks")

        self.run_background(compute, on_done, busy_text="Fitting peaks…")

    def open_unit_converter(self):
        wl = self.get_wavelength()
        v = ui_common.ask_fields(self, "2θ / d-spacing / Q converter",
                                 [("value", "Value:", ""), ("unit", "Unit of the value:", "2theta", ["2theta", "d", "q"])],
                                 help_text=f"Using λ = {wl:.6f} Å. Q = 4π·sin(θ)/λ in Å⁻¹, d in Å.")
        if v is None:
            return
        try:
            value = parse_float(v["value"], "Value")
            if value <= 0:
                raise ValueError("The value must be positive.")
            result = xrd_analysis.convert_xrd_units(value, v["unit"], wl)
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "Conversion failed", str(exc), "error")
            return
        if result["two_theta_deg"] is None:
            ui_common.show_message(self, "Unit converter", "Not reachable at this wavelength: it would need sin θ > 1.",
                                   "warning")
            return
        self._log("Unit conversion", f"{value:g} {v['unit']}, λ {wl:.6f} Å",
                  f"2θ = {result['two_theta_deg']:.4f}°, d = {result['d_spacing_a']:.5f} Å, Q = {result['q_inv_a']:.5f} Å⁻¹")
        self.results_tabs.setCurrentWidget(self.log_table)
        self.app.notify(f"2θ = {result['two_theta_deg']:.4f}°, d = {result['d_spacing_a']:.5f} Å, "
                        f"Q = {result['q_inv_a']:.5f} Å⁻¹", "success")

    # ---------------------------------------------------------------- export
    def excel_report(self):
        """Excel's "settings used" are the parameters stored with the active trace's results."""
        import exports
        t = self.get_active()
        settings = dict(self.parameter_rows(t)) if t is not None else {}
        info = getattr(self.app, "info", None)
        return exports.excel_report(self.KIND, self.traces, self.active_id, version=getattr(info, "version", ""),
                                    author=getattr(info, "author", ""),
                                    settings=settings or {"Size/strain": "not computed yet"},
                                    project=self.project_name(), **self.export_options())

    def parameter_rows(self, t):
        p = t.metadata.get("xrd_params") or {}
        if not p:
            return []
        inst = p.get("instrument", {})
        rows = [("Wavelength", f"{p.get('wavelength_a', 0):.6f} Å ({p.get('wavelength_name', '')})"),
                ("Scherrer K", f"{p.get('K', 0.9):.2f}"),
                ("Peak widths", WIDTH_SOURCES.get(p.get("width_source"), "")),
                ("Instrument profile", "none (not corrected)" if inst.get("source", "none") == "none" else
                 f"U={inst.get('U', 0):.3g}, V={inst.get('V', 0):.3g}, W={inst.get('W', 0):.3g} deg², "
                 f"{inst.get('mode', '')} correction ({inst.get('source', '')})"),
                ("Processing", "; ".join(p.get("processing") or []) or "none"),
                ("App version", p.get("app_version", "")), ("Computed at", p.get("run_at", ""))]
        return rows

    def export_peaks_csv(self):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        if not t.peaks:
            self.app.notify("Detect peaks first.", "warning")
            return
        path = ui_common.get_save_path(self, "Export peak list", f"{self.project_name()}_peaks.csv", "CSV (*.csv)")
        if not path:
            return
        p_used = t.metadata.get("xrd_params") or {}
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            for k, v in self.parameter_rows(t):
                w.writerow([f"# {k}", v])
            w.writerow(["two_theta_deg", "intensity", "used", "fwhm_measured_deg", "beta_sample_deg", "d_spacing_A",
                        "apparent_size_nm", "note"])
            for p in t.peaks:
                w.writerow([p["two_theta"], p["intensity"], "yes" if p.get("use", True) and p.get("usable", True) else "no",
                            p.get("width_used_deg", p["fwhm_deg"]), p.get("beta_deg") or "",
                            f"{p['d_A']:.5f}" if p.get("d_A") else "", p.get("size_nm") or "", p.get("note", "")])
        msg = f"Saved {len(t.peaks)} peaks"
        if not p_used:
            msg += " (no d/size yet — run d-spacing + Scherrer to include them)"
        self.app.notify(msg, "success")

    def export_pdf_report(self, path=None):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return None
        path = path or ui_common.get_save_path(self, "Export PDF report", f"{self.project_name()}_report.pdf", "PDF (*.pdf)")
        if not path:
            return None
        tmp_png = os.path.join(tempfile.gettempdir(), "xrd_report_plot.png")
        self.snapshot_png(tmp_png)
        sections = []
        params = self.parameter_rows(t)
        if params:
            sections.append(("Method &amp; parameters", [["Parameter", "Value"]] + [[k, str(v)] for k, v in params], None))
        if t.peaks:
            rows = [["2theta (deg)", "I/I0 (%)", "Used", "FWHM (deg)", "beta (deg)", "d (A)", "Size* (nm)", "Note"]]
            top = max(p["intensity"] for p in t.peaks) or 1.0
            rows += [[f"{p['two_theta']:.3f}", f"{100 * p['intensity'] / top:.0f}",
                      "yes" if p.get("use", True) and p.get("usable", True) else "no",
                      f"{p.get('width_used_deg', p['fwhm_deg']):.4f}", f"{p['beta_deg']:.4f}" if p.get("beta_deg") else "-",
                      f"{p['d_A']:.4f}" if p.get("d_A") else "-", _fmt_sig(p.get("size_nm")).replace("–", "-"),
                      p.get("note", "")] for p in t.peaks]
            sections.append(("Peaks (*apparent Scherrer size)", rows, None))
        wh = t.metadata.get("wh_result")
        if wh:
            D, sD = wh.get("crystallite_size_nm"), wh.get("crystallite_size_se_nm")
            size_txt = f"{D:.3g} +/- {sD:.2g} nm" if D and sD is not None else (f"{D:.3g} nm" if D else "not resolvable")
            seps = wh.get("microstrain_se")
            sections.append(("Williamson-Hall", None, html.escape(
                f"Apparent domain size: {size_txt}\nMicrostrain: {wh['microstrain'] * 1e3:.3g}"
                + (f" +/- {seps * 1e3:.2g}" if seps is not None else "") + " x10^-3\n"
                f"R2 {wh.get('r_squared', float('nan')):.3f}, {wh['n_peaks']} peaks at "
                + ", ".join(f"{v:.2f}" for v in wh.get("two_theta", [])) + " deg 2theta")))
        if t.fits:
            rows = [["Detected 2theta", "Centre", "FWHM", "Height", "Area", "R2", "Shape"]]
            rows += [[f"{f['seed_x']:.3f}", f"{f['center']:.4f}", f"{f['fwhm']:.4f}", f"{f['height']:.4g}",
                      f"{f['area']:.4g}", f"{f['r_squared']:.4f}", f["shape"]] for f in t.fits]
            sections.append(("Peak fits", rows, None))
        if t.metadata.get("crystallinity_pct") is not None:
            r = t.metadata.get("crystallinity_regions", {})
            fmt = lambda regs: ", ".join(f"{a:g}-{b:g} deg" for a, b in regs)  # noqa: E731
            sections.append(("% Crystallinity", None, html.escape(
                f"{t.metadata['crystallinity_pct']:.1f} % (area method on the raw pattern, straight baseline)\n"
                f"Crystalline: {fmt(r.get('crystalline', []))}\nAmorphous: {fmt(r.get('amorphous', []))}")))
        if self.calc_log:
            rows = [["Calculation", "Inputs", "Result"]] + [[r["what"], r["inputs"], r["result"]] for r in self.calc_log]
            sections.append(("Other calculations", rows, None))
        if not sections:
            sections.append(("Notes", None, "No peaks were detected or analysed on this trace."))
        disclaimer = ("Sizes are apparent (volume-weighted, shape-factor dependent) and are lower bounds when "
                      "instrumental broadening or strain is not accounted for. Williamson-Hall assumes uniform strain "
                      "and isotropic broadening.")
        stored = t.metadata.get("xrd_params") or {}
        wl_txt = (f"Wavelength: {stored['wavelength_a']:.6f} A ({stored.get('wavelength_name', '')})" if stored
                  else f"Wavelength: {self.get_wavelength():.6f} A ({self.wl_combo.currentText()})")
        try:
            report_export.build_report(path, "XRD Analysis Report", f"{wl_txt}  |  App v{APP_VERSION}", tmp_png,
                                       sections, disclaimer, source_file=t.label)
        except PermissionError:
            ui_common.show_message(self, "Export failed", "That PDF is open in another program — close it and try again.", "error")
            return None
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "Export failed", str(exc), "error")
            return None
        self.app.notify(f"Report saved to {os.path.basename(path)}", "success")
        return path
