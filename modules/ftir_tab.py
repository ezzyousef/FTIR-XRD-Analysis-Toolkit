"""
ftir_tab.py
The FTIR page: load spectra (multi-trace overlay), detect peaks, smooth/baseline-correct/
normalize, screen against the reference database, fit peaks, run calculations, and export
CSV / PDF / Origin / Excel / sessions.
"""
import csv
import os
import tempfile

from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QRadioButton, QVBoxLayout, QWidget)

import file_readers
import formula_sources as fs
import ftir_analysis
import peak_fitting
import report_export
import ui_common
from ui_common import AnalysisTabBase, DataTable, parse_float


class FTIRTab(AnalysisTabBase):
    KIND = "ftir"
    READER = staticmethod(file_readers.read_ftir_any)
    FILE_FILTER = "Spectrum files (*.csv *.txt *.dat *.xy *.dpt *.jdx *.dx);;All files (*.*)"
    LOAD_TEXT = "Load spectra…"
    DROP_HINT = ".csv .txt .dat .xy .dpt .jdx — or drop files anywhere on this page."

    def __init__(self, app):
        super().__init__(app, x_label="Wavenumber (cm-1)", y_label="Absorbance / %T", invert_x=True)
        self.database = app.ftir_db
        self._current_match = None
        self._current_match_entry = None
        self._build_controls()
        self._build_results_tabs()
        self._on_traces_changed()

    # ---------------------------------------------------------------- controls
    def _build_controls(self):
        card = self.add_card("Mode & peak detection")
        mode_row = QWidget()
        mode_layout = QVBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        self.rb_absorbance = QRadioButton("Absorbance (peaks up)")
        self.rb_transmittance = QRadioButton("%Transmittance (peaks down)")
        self.rb_absorbance.setChecked(True)
        self._mode_group = QButtonGroup(self)
        for rb in (self.rb_absorbance, self.rb_transmittance):
            self._mode_group.addButton(rb)
            mode_layout.addWidget(rb)
        self.rb_absorbance.toggled.connect(lambda _c: self.redraw())
        card.body.addWidget(mode_row)
        self.prom_spin = QDoubleSpinBox()
        self.prom_spin.setRange(0.2, 20.0)
        self.prom_spin.setSingleStep(0.2)
        self.prom_spin.setValue(2.0)
        self.prom_spin.setSuffix(" %")
        card.body.addWidget(self.labelled("Peak sensitivity (prominence)", self.prom_spin))
        shoulder = QWidget()
        sl = QHBoxLayout(shoulder)
        sl.setContentsMargins(0, 0, 0, 0)
        self.shoulder_check = QCheckBox("Resolve shoulder bands (2nd derivative)")
        sl.addWidget(self.shoulder_check, 1)
        info = QPushButton("ⓘ")
        info.setObjectName("Ghost")
        info.setFixedWidth(34)
        info.clicked.connect(lambda _c=False: self.show_formula("Second-derivative peak resolution",
                                                                 fs.SECOND_DERIVATIVE_PEAK_DETECTION))
        sl.addWidget(info)
        card.body.addWidget(shoulder)
        card.body.addWidget(self.action_button("Detect peaks", self.detect_peaks, primary=True))

        card = self.add_card("Processing")
        card.body.addWidget(self.action_button("Smooth (Savitzky–Golay)…", self.smooth_active))
        card.body.addWidget(self.action_button("Baseline correct (linear)", self.baseline_correct_active))
        card.body.addWidget(self.action_button("ATR correction…", self.atr_correct_active,
                                               info=("ATR correction", fs.ATR_CORRECTION)))
        card.body.addWidget(self.action_button("1st / 2nd derivative…", self.derivative_active,
                                               info=("Derivative spectroscopy", fs.DERIVATIVE_SPECTROSCOPY)))
        self.norm_combo = QComboBox()
        self.norm_combo.addItems(["max", "minmax", "area", "vector"])
        card.body.addWidget(self.labelled("Normalization method", self.norm_combo))
        card.body.addWidget(self.action_button("Apply normalization", self.normalize_active,
                                               info=("Normalization methods", fs.NORMALIZATION_METHODS)))
        revert = self.action_button("Revert to raw data", self.revert_active)
        revert.button.setObjectName("Danger")
        card.body.addWidget(revert)

        total = sum(len(self.database.get(cat, [])) for cat in ftir_analysis.MATERIAL_CATEGORIES)
        card = self.add_card("Database identification",
                             "Heuristic screening against published correlation tables — confirm against "
                             "a certified reference spectrum.")
        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setRange(1.0, 50.0)
        self.tolerance_spin.setSingleStep(1.0)
        self.tolerance_spin.setValue(float(self.app.cfg.get("ftir_tolerance_cm1", 10.0)))
        self.tolerance_spin.setSuffix(" cm⁻¹")
        card.body.addWidget(self.labelled("Tolerance (±)", self.tolerance_spin))
        self.category_combo = QComboBox()
        self.category_combo.addItems([ftir_analysis.ALL_CATEGORIES_LABEL] +
                                     [ftir_analysis.CATEGORY_LABELS[k] for k in ftir_analysis.MATERIAL_CATEGORIES])
        card.body.addWidget(QLabel("Restrict search to a category (more accurate if known):"))
        card.body.addWidget(self.category_combo)
        card.body.addWidget(self.action_button(f"Match to database ({total} materials)", self.match_database,
                                               primary=True, info=("FTIR database matching method",
                                                                   fs.FTIR_DATABASE_MATCHING)))

        card = self.add_card("Peak fitting")
        self.shape_combo = QComboBox()
        self.shape_combo.addItems(["gaussian", "lorentzian", "pseudo_voigt"])
        card.body.addWidget(self.labelled("Peak shape", self.shape_combo))
        self.window_spin = QDoubleSpinBox()
        self.window_spin.setRange(5.0, 200.0)
        self.window_spin.setSingleStep(5.0)
        self.window_spin.setValue(25.0)
        self.window_spin.setSuffix(" cm⁻¹")
        card.body.addWidget(self.labelled("Fit window (±)", self.window_spin))
        card.body.addWidget(self.action_button("Fit all detected peaks", self.fit_peaks,
                                               info=("Peak fitting method", fs.PEAK_FITTING)))

        card = self.add_card("Calculations")
        card.body.addWidget(self.action_button("%T ↔ absorbance converter…", self.calc_converter,
                                               info=("%T ↔ absorbance", fs.TRANSMITTANCE_ABSORBANCE)))
        card.body.addWidget(self.action_button("Peak area (integrate a range)…", self.calc_peak_area))
        card.body.addWidget(self.action_button("FWHM of nearest peak…", self.calc_fwhm))
        card.body.addWidget(self.action_button("Beer–Lambert concentration…", self.calc_beer_lambert,
                                               info=("Beer–Lambert law", fs.BEER_LAMBERT)))

        card = self.add_card("Files & session", "Origin, Excel and figures: the buttons under the plot.")
        for text, fn in (("Export peak list (CSV)…", self.export_peaks_csv),
                         ("Export PDF report…", self.export_pdf_report),
                         ("Export for OriginLab (CSV)…", self.export_originlab_dialog),
                         ("Export graph (SVG/EPS/PDF/PNG)…", self.export_graph_dialog),
                         ("Save session…", self.save_session),
                         ("Load session…", self.load_session)):
            card.body.addWidget(self.action_button(text, fn))

    def _build_results_tabs(self):
        self.peaks_table = DataTable(["#", "Wavenumber (cm⁻¹)", "Intensity", "Prominence"])
        self.results_tabs.addTab(self.peaks_table, "Peaks")

        matches = QWidget()
        ml = QVBoxLayout(matches)
        ml.setContentsMargins(6, 8, 6, 6)
        bar = QHBoxLayout()
        hint = QLabel("Click a row to overlay its reference bands on the plot.")
        hint.setObjectName("Hint")
        bar.addWidget(hint, 1)
        export_refs = QPushButton("Export reference peaks (CSV)…")
        export_refs.clicked.connect(lambda _c=False: self.export_reference_peaks_csv())
        clear = QPushButton("Clear overlay")
        clear.clicked.connect(lambda _c=False: self.clear_reference_overlay())
        bar.addWidget(export_refs)
        bar.addWidget(clear)
        ml.addLayout(bar)
        self.matches_table = DataTable(["Material", "Category", "Score", "Matched / total", "Source"])
        self.matches_table.on_select = self._show_match_detail
        ml.addWidget(self.matches_table, 3)
        self.match_detail = QPlainTextEdit()
        self.match_detail.setReadOnly(True)
        self.match_detail.setObjectName("Mono")
        ml.addWidget(self.match_detail, 2)
        self.results_tabs.addTab(matches, "Database matches")

        self.fg_table = DataTable(["Wavenumber", "Functional group", "Expected range", "Source"])
        self.results_tabs.addTab(self.fg_table, "Functional groups")
        self.fits_table = DataTable(["Seed", "Fitted centre", "FWHM", "Height", "Area", "R²"])
        self.results_tabs.addTab(self.fits_table, "Peak fits")

    # ---------------------------------------------------------------- state
    def mode(self):
        return "transmittance" if self.rb_transmittance.isChecked() else "absorbance"

    def export_options(self):
        return {"mode": self.mode()}

    def session_settings(self):
        return {"mode": self.mode(), "prominence": self.prom_spin.value(), "tolerance": self.tolerance_spin.value(),
                "category": self.category_combo.currentText()}

    def apply_session_settings(self, state):
        (self.rb_transmittance if state.get("mode") == "transmittance" else self.rb_absorbance).setChecked(True)
        self.prom_spin.setValue(float(state.get("prominence", 2.0)))
        self.tolerance_spin.setValue(float(state.get("tolerance", 10.0)))
        index = self.category_combo.findText(state.get("category", ftir_analysis.ALL_CATEGORIES_LABEL))
        self.category_combo.setCurrentIndex(max(0, index))

    # ---------------------------------------------------------------- plotting
    def _plot_active_extras(self, ax, trace, theme):
        fg = self.foreground(theme)
        label_peaks = len(trace.peaks) <= 60
        for p in trace.peaks:
            ax.axvline(p["x"], color="#E03131", alpha=0.35, lw=0.9, zorder=0)
            if label_peaks:
                ax.annotate(f"{p['x']:.0f}", (p["x"], p["y"]), fontsize=7, rotation=90, ha="center",
                            va="bottom", color=fg)

    def _draw_reference_overlay(self, ax, theme):
        label = self.reference_overlay.get("label", "Reference")
        for p in self.reference_overlay.get("peaks", []):
            lo, hi = p["range"]
            if lo == 0 and hi == 0:
                continue                            # IR-inactive placeholder (e.g. NaCl)
            ax.axvspan(lo, hi, color="#F59F00", alpha=0.20, lw=0, zorder=0)
            ax.axvline((lo + hi) / 2, color="#F59F00", alpha=0.6, lw=0.8, linestyle=":")
        # In the title row, where it cannot collide with the legend or the data.
        ax.set_title(f"Reference bands: {label}", loc="left", fontsize=9, color="#D9480F")

    # ---------------------------------------------------------------- results refresh
    def on_active_trace_changed(self):
        if self.reference_overlay is not None and self._current_match_trace != self.active_id:
            self.reference_overlay = None
            self.redraw()
        t = self.get_active()
        if t is None:
            for table in (self.peaks_table, self.matches_table, self.fg_table, self.fits_table):
                table.clear_rows()
            self.match_detail.clear()
            return
        self.peaks_table.set_rows(list(enumerate(t.peaks, 1)), lambda ip: (
            ip[0], f"{ip[1]['x']:.1f}", f"{ip[1]['y']:.4f}", f"{ip[1]['prominence']:.4f}"))
        self.matches_table.set_rows(t.matches, lambda m: (
            m["name"], m["category"], f"{m['score'] * 100:.0f}%",
            f"{m['matched_count']}/{m['total_reference_peaks']}", m.get("source", "")))
        self.fg_table.set_rows(t.fg_hits, lambda h: (
            f"{h['peak_x']:.1f}", h["group"], f"{h['range'][0]}–{h['range'][1]}", h.get("source", "")))
        self.fits_table.set_rows(t.fits, lambda f: (
            f"{f['seed_x']:.1f}", f"{f['center']:.1f}", f"{f['fwhm']:.2f}", f"{f['height']:.4f}",
            f"{f['area']:.3f}", f"{f['r_squared']:.4f}"))
        if not t.matches:
            self.match_detail.clear()

    _current_match_trace = None

    def _show_match_detail(self, match):
        entry = ftir_analysis.find_entry(self.database, match["name"])
        self._current_match = match
        self._current_match_entry = entry
        self._current_match_trace = self.active_id
        full_source = match.get("source", "") or "(no source on file)"
        source_short = full_source.split(";")[0].strip()
        lines = [f"{match['name']} [{match['category']}]  Source: {full_source}"]
        if entry:
            lines.append(f"Reference peaks ({match['matched_count']}/{len(entry['peaks'])} matched):")
            matched_by_range = {tuple(mm["reference"]["range"]): mm for mm in match["matches"]}
            for ref in entry["peaks"]:
                mm = matched_by_range.get(tuple(ref["range"]))
                inactive = ref["range"][0] == 0 and ref["range"][1] == 0
                range_txt = "(IR-inactive)" if inactive else f"{ref['range'][0]}-{ref['range'][1]} cm-1"
                if mm:
                    lines.append(f"  [MATCHED]   ref {range_txt} ({ref['assignment']})  ~ observed "
                                 f"{mm['observed']['x']:.1f} cm-1, delta={mm['delta_cm1']:+.1f} cm-1  [ref: {source_short}]")
                else:
                    lines.append(f"  [not found] ref {range_txt} ({ref['assignment']})  [ref: {source_short}]")
        else:
            for mm in match["matches"]:
                ref = mm["reference"]
                lines.append(f"  observed {mm['observed']['x']:.1f} cm-1  ~  ref {ref['range'][0]}-{ref['range'][1]} "
                             f"cm-1 ({ref['assignment']}), delta={mm['delta_cm1']:+.1f} cm-1  [ref: {source_short}]")
        lines += ["", "Full citations: Library > Sources & references."]
        self.match_detail.setPlainText("\n".join(lines))
        if entry:
            self.set_reference_overlay({"label": match["name"], "peaks": entry["peaks"]})
        else:
            self.clear_reference_overlay()

    # ---------------------------------------------------------------- actions
    def detect_peaks(self, record=True):
        t = self.require_active("Load a spectrum first.")
        if t is None:
            return
        prom_frac = self.prom_spin.value() / 100.0
        if self.shoulder_check.isChecked():
            t.peaks = ftir_analysis.detect_peaks_second_derivative(t.x, t.y, prominence_frac=prom_frac, mode=self.mode())
        else:
            t.peaks = ftir_analysis.detect_peaks(t.x, t.y, prominence_frac=prom_frac, mode=self.mode())
        t.fits = []
        self.redraw()
        self.on_active_trace_changed()
        self.results_tabs.setCurrentIndex(0)
        msg = f"Detected {len(t.peaks)} peaks in {t.label}"
        if len(t.peaks) > 100:
            msg += " — that's a lot; raise the sensitivity for cleaner results"
        self.app.notify(msg, "success" if t.peaks else "warning")
        if record:
            self.record("detect peaks")

    def match_database(self):
        t = self.require_active("Load a spectrum first.")
        if t is None:
            return
        if not t.peaks:
            self.detect_peaks(record=False)
            if not t.peaks:
                return
        tol = self.tolerance_spin.value()
        self.app.cfg["ftir_tolerance_cm1"] = tol
        peaks_snapshot = list(t.peaks)
        label_to_key = {v: k for k, v in ftir_analysis.CATEGORY_LABELS.items()}
        selected = self.category_combo.currentText()
        categories = None if selected == ftir_analysis.ALL_CATEGORIES_LABEL else [label_to_key[selected]]
        database = self.database

        def compute():
            return (ftir_analysis.match_peaks_to_database(peaks_snapshot, database, tolerance=tol, categories=categories),
                    ftir_analysis.match_functional_groups(peaks_snapshot, database, tolerance=tol))

        def on_done(result):
            t.matches, t.fg_hits = result
            self.on_active_trace_changed()
            self.results_tabs.setCurrentIndex(1)
            scope = "all categories" if categories is None else selected
            self.app.notify(f"{len(t.matches)} candidate material(s) in {scope}, "
                            f"{len(t.fg_hits)} functional-group hit(s)", "success")
            self.record("match database")

        self.run_background(compute, on_done, busy_text="Matching against the FTIR database…")

    def _apply_to_active(self, title, fields, apply, done_message, help_text=None):
        t = self.require_active("Load a spectrum first.")
        if t is None:
            return
        values = ui_common.ask_fields(self, title, fields, help_text) if fields else {}
        if values is None:
            return
        try:
            t.y = apply(t, values)
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, f"{title} failed", str(exc), "error")
            return
        t.peaks, t.fits = [], []
        self.redraw()
        self.on_active_trace_changed()
        self.app.notify(done_message(t, values), "success")
        self.record(title.lower())

    def smooth_active(self):
        self._apply_to_active(
            "Smooth", [("wl", "Window length (odd, points):", "11"), ("po", "Polynomial order:", "3")],
            lambda t, v: ftir_analysis.smooth_spectrum(t.y, window_length=int(float(v["wl"])), polyorder=int(float(v["po"]))),
            lambda t, v: f"Smoothed {t.label} (window {v['wl']}, order {v['po']}) — detect peaks again")

    def baseline_correct_active(self):
        self._apply_to_active(
            "Baseline correction", None,
            lambda t, v: ftir_analysis.baseline_correct(t.x, t.y_raw)[0],
            lambda t, v: f"Linear baseline removed from {t.label} (from raw data) — detect peaks again")

    def normalize_active(self):
        method = self.norm_combo.currentText()
        self._apply_to_active(
            "Normalization", None,
            lambda t, v: ftir_analysis.normalize_spectrum(t.y, method=method, x=t.x),
            lambda t, v: f"Normalized {t.label} ({method})")

    def atr_correct_active(self):
        crystals = list(getattr(ftir_analysis, "ATR_CRYSTAL_REFRACTIVE_INDEX", {"diamond": 2.4}).keys())
        self._apply_to_active(
            "ATR correction",
            [("crystal", "ATR crystal:", "diamond", crystals), ("angle", "Angle of incidence (°):", "45"),
             ("n_sample", "Sample refractive index:", "1.5")],
            lambda t, v: ftir_analysis.atr_correction(t.x, t.y, crystal=v["crystal"], angle_deg=float(v["angle"]),
                                                      n_sample=float(v["n_sample"])),
            lambda t, v: f"ATR correction applied to {t.label} ({v['crystal']}, {v['angle']}°)",
            help_text="Corrects for wavenumber-dependent ATR penetration depth so relative band "
                      "intensities compare more fairly with a transmission spectrum.")

    def derivative_active(self):
        self._apply_to_active(
            "Derivative",
            [("order", "Derivative order:", "1", ["1", "2"]), ("wl", "Savitzky–Golay window (odd, points):", "15"),
             ("po", "Polynomial order:", "3")],
            lambda t, v: ftir_analysis.derivative_spectrum(t.x, t.y, order=int(v["order"]), window_length=int(float(v["wl"])),
                                                           polyorder=int(float(v["po"]))),
            lambda t, v: f"Derivative (order {v['order']}) of {t.label} computed")

    def revert_active(self):
        t = self.require_active("Load a spectrum first.")
        if t is None:
            return
        t.revert_to_raw()
        self.reference_overlay = None
        self._on_traces_changed()
        self.app.notify(f"{t.label} reverted to the data as loaded", "info")
        self.record("revert to raw")

    def fit_peaks(self):
        t = self.require_active("Load a spectrum first.")
        if t is None:
            return
        if not t.peaks:
            self.app.notify("Detect peaks first.", "warning")
            return
        window, shape = self.window_spin.value(), self.shape_combo.currentText()
        x_snap, y_snap, peaks_snap = t.x.copy(), t.y.copy(), list(t.peaks)

        def compute():
            return peak_fitting.fit_peaks_batch(x_snap, y_snap, peaks_snap, window, shape=shape)

        def on_done(result):
            fits, errors = result
            t.fits = fits
            self.redraw()
            self.on_active_trace_changed()
            self.results_tabs.setCurrentIndex(3)
            msg = f"Fitted {len(fits)}/{len(peaks_snap)} peaks"
            if errors:
                msg += f"; {len(errors)} did not converge"
            self.app.notify(msg, "success" if not errors else "warning")
            self.record("fit peaks")

        self.run_background(compute, on_done, busy_text="Fitting peaks…")

    # ---------------------------------------------------------------- calculations
    def calc_converter(self):
        v = ui_common.ask_fields(self, "%T ↔ absorbance", [("value", "Value:", ""), ("unit", "Unit of the value:", "%T", ["%T", "A"])])
        if v is None:
            return
        try:
            num = parse_float(v["value"], "Value")
            if v["unit"] == "%T":
                text = f"{num} %T = {float(ftir_analysis.transmittance_to_absorbance(num)):.4f} absorbance"
            else:
                text = f"{num} A = {float(ftir_analysis.absorbance_to_transmittance(num)):.4f} %T"
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "Conversion failed", str(exc), "error")
            return
        ui_common.show_message(self, "Result", text)

    def calc_peak_area(self):
        t = self.require_active("Load a spectrum first.")
        if t is None:
            return
        v = ui_common.ask_fields(self, "Peak area", [("start", "Start (cm⁻¹):", "1700"), ("end", "End (cm⁻¹):", "1750")])
        if v is None:
            return
        try:
            s, e = parse_float(v["start"], "Start"), parse_float(v["end"], "End")
            area = ftir_analysis.peak_area(t.x, t.y, s, e)
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "Peak area failed", str(exc), "error")
            return
        ui_common.show_message(self, "Peak area", f"Integrated area between {s:g} and {e:g} cm⁻¹: {area:.4f}")

    def calc_fwhm(self):
        t = self.require_active("Load a spectrum first.")
        if t is None:
            return
        if not t.peaks:
            self.app.notify("Detect peaks first.", "warning")
            return
        v = ui_common.ask_fields(self, "FWHM", [("pos", "Approximate peak position (cm⁻¹):", f"{t.peaks[0]['x']:.0f}")])
        if v is None:
            return
        try:
            target = parse_float(v["pos"], "Position")
            nearest = min(t.peaks, key=lambda p: abs(p["x"] - target))
            fwhm = ftir_analysis.fwhm_from_peak(t.x, t.y, nearest["index"], mode=self.mode())
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "FWHM failed", str(exc), "error")
            return
        ui_common.show_message(self, "FWHM", f"Nearest peak at {nearest['x']:.1f} cm⁻¹: FWHM = {fwhm:.2f} cm⁻¹")

    def calc_beer_lambert(self):
        v = ui_common.ask_fields(self, "Beer–Lambert concentration",
                                 [("a", "Absorbance:", ""), ("eps", "Molar absorptivity ε (L/(mol·cm)):", ""),
                                  ("l", "Path length (cm):", "1.0")])
        if v is None:
            return
        try:
            c = ftir_analysis.beer_lambert_concentration(parse_float(v["a"], "Absorbance"), parse_float(v["eps"], "Epsilon"),
                                                         parse_float(v["l"], "Path length"))
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "Calculation failed", str(exc), "error")
            return
        ui_common.show_message(self, "Concentration", f"c = {c:.6g} mol/L")

    # ---------------------------------------------------------------- export
    def export_reference_peaks_csv(self):
        if self._current_match_entry is None:
            self.app.notify("Click a row in the database matches table first.", "warning")
            return
        entry, match = self._current_match_entry, self._current_match
        matched_by_range = {tuple(mm["reference"]["range"]): mm for mm in match["matches"]}
        path = ui_common.get_save_path(self, "Export reference peaks", f"{entry['name']}_reference_peaks.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["material", "range_low_cm-1", "range_high_cm-1", "assignment", "intensity",
                        "matched_in_your_spectrum", "observed_cm-1", "delta_cm-1", "source"])
            for ref in entry["peaks"]:
                mm = matched_by_range.get(tuple(ref["range"]))
                w.writerow([entry["name"], ref["range"][0], ref["range"][1], ref["assignment"], ref.get("intensity", ""),
                            "yes" if mm else "no", f"{mm['observed']['x']:.2f}" if mm else "",
                            f"{mm['delta_cm1']:+.2f}" if mm else "", entry.get("source", "")])
        self.app.notify(f"Saved {len(entry['peaks'])} reference peak(s) for {entry['name']}", "success")

    def export_peaks_csv(self):
        t = self.require_active("Load a spectrum first.")
        if t is None:
            return
        if not t.peaks:
            self.app.notify("Detect peaks first.", "warning")
            return
        path = ui_common.get_save_path(self, "Export peak list", f"{self.project_name()}_peaks.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["wavenumber_cm-1", "intensity", "prominence"])
            for p in t.peaks:
                w.writerow([p["x"], p["y"], p["prominence"]])
        self.app.notify(f"Saved {len(t.peaks)} peaks", "success")

    def export_pdf_report(self, path=None):
        t = self.require_active("Load a spectrum first.")
        if t is None:
            return None
        path = path or ui_common.get_save_path(self, "Export PDF report", f"{self.project_name()}_report.pdf", "PDF (*.pdf)")
        if not path:
            return None
        tmp_png = os.path.join(tempfile.gettempdir(), "ftir_report_plot.png")
        self.snapshot_png(tmp_png)
        sections = []
        if t.peaks:
            rows = [["#", "Wavenumber (cm-1)", "Intensity", "Prominence"]]
            rows += [[str(i), f"{p['x']:.1f}", f"{p['y']:.4f}", f"{p['prominence']:.4f}"] for i, p in enumerate(t.peaks, 1)]
            sections.append(("Detected Peaks", rows, None))
        if t.matches:
            rows = [["Material", "Category", "Score", "Matched/Total", "Source"]]
            rows += [[m["name"], m["category"], f"{m['score'] * 100:.0f}%", f"{m['matched_count']}/{m['total_reference_peaks']}",
                      m.get("source", "")] for m in t.matches[:12]]
            sections.append(("Database Matches (heuristic screening)", rows, None))
        if t.fg_hits:
            rows = [["Wavenumber", "Functional Group", "Expected Range"]]
            rows += [[f"{h['peak_x']:.1f}", h["group"], f"{h['range'][0]}-{h['range'][1]}"] for h in t.fg_hits[:20]]
            sections.append(("Functional Group Hits", rows, None))
        if t.fits:
            rows = [["Centre", "FWHM", "Height", "Area", "R-squared"]]
            rows += [[f"{f['center']:.1f}", f"{f['fwhm']:.2f}", f"{f['height']:.4f}", f"{f['area']:.3f}",
                      f"{f['r_squared']:.4f}"] for f in t.fits]
            sections.append((f"Peak Fits ({t.fits[0]['shape']})", rows, None))
        if not sections:
            sections.append(("Notes", None, "No peaks were detected or analysed on this trace."))
        try:
            report_export.build_report(path, "FTIR Analysis Report", f"Mode: {self.mode()}", tmp_png, sections,
                                       self.database.get("_meta", {}).get("note", ""), source_file=t.label)
        except PermissionError:
            ui_common.show_message(self, "Export failed", "That PDF is open in another program — close it and try again.", "error")
            return None
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "Export failed", str(exc), "error")
            return None
        self.app.notify(f"Report saved to {os.path.basename(path)}", "success")
        return path
