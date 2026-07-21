"""
ftir_tab.py
The FTIR Analysis tab: load spectra (multi-trace overlay), detect peaks,
smooth/baseline-correct/normalize, match against the reference database,
fit peaks, run calculations, and export a CSV/PDF/session.
"""
import os
import csv
import tempfile
import numpy as np
import ttkbootstrap as tb
from tkinter import filedialog
from ttkbootstrap.dialogs import Messagebox

import file_readers
import ftir_analysis
import peak_fitting
import report_export
import session_io
import formula_sources as fs
from ui_common import AnalysisTabBase, DataTable, MultiFieldDialog, parse_float, save_figure_snapshot
from trace_model import Trace


class FTIRTab(AnalysisTabBase):
    def __init__(self, parent, app):
        super().__init__(parent, app, x_label="Wavenumber (cm$^{-1}$)", y_label="Absorbance / %T", invert_x=True)
        self.database = app.ftir_db
        self.mode_var = tb.StringVar(value="absorbance")
        self.prom_var = tb.DoubleVar(value=2.0)
        self.tolerance_var = tb.DoubleVar(value=app.cfg.get("ftir_tolerance_cm1", 10.0))
        self.fit_shape_var = tb.StringVar(value="gaussian")
        self.fit_window_var = tb.DoubleVar(value=25.0)
        self.category_var = tb.StringVar(value=ftir_analysis.ALL_CATEGORIES_LABEL)

        self._build_controls()
        self._build_results_tabs()

    # ---------------------------------------------------------------- controls

    def _build_controls(self):
        c = self.controls

        card = tb.Labelframe(c, text="1. Load Spectrum", padding=10, bootstyle="info")
        card.pack(fill="x", padx=6, pady=6)
        tb.Button(card, text="Load Spectrum (.csv/.txt/.dat/.xy/.dpt/.jdx)", bootstyle="info",
                  command=self._load_spectrum).pack(fill="x")
        tb.Label(card, text="Tip: you can also drag & drop a file onto the plot.",
                 bootstyle="secondary", wraplength=280, font=("", 8)).pack(anchor="w", pady=(4, 0))

        card = tb.Labelframe(c, text="2. Mode & Peak Detection", padding=10, bootstyle="primary")
        card.pack(fill="x", padx=6, pady=6)
        tb.Radiobutton(card, text="Absorbance (peaks up)", variable=self.mode_var, value="absorbance").pack(anchor="w")
        tb.Radiobutton(card, text="%Transmittance (peaks down)", variable=self.mode_var, value="transmittance").pack(anchor="w")
        tb.Label(card, text="Peak sensitivity (prominence %):").pack(anchor="w", pady=(8, 0))
        prom_row = tb.Frame(card)
        prom_row.pack(fill="x")
        tb.Scale(prom_row, from_=0.2, to=20, variable=self.prom_var, bootstyle="info").pack(side="left", fill="x", expand=True)
        tb.Label(prom_row, textvariable=self.prom_var, width=5).pack(side="left")
        tb.Button(card, text="Detect Peaks", bootstyle="primary", command=self.detect_peaks).pack(fill="x", pady=(8, 0))

        card = tb.Labelframe(c, text="3. Processing", padding=10, bootstyle="secondary")
        card.pack(fill="x", padx=6, pady=6)
        tb.Button(card, text="Smooth (Savitzky-Golay)", command=self.smooth_active).pack(fill="x", pady=2)
        tb.Button(card, text="Baseline Correct (linear)", command=self.baseline_correct_active).pack(fill="x", pady=2)
        self.make_action_row(card, "ATR Correction", self.atr_correct_active,
                              info_title="ATR Correction", info_text=fs.ATR_CORRECTION)
        self.make_action_row(card, "1st / 2nd Derivative", self.derivative_active,
                              info_title="Derivative Spectroscopy", info_text=fs.DERIVATIVE_SPECTROSCOPY)
        norm_row = tb.Frame(card)
        norm_row.pack(fill="x")
        tb.Label(norm_row, text="Normalize:").pack(side="left")
        self.norm_method_var = tb.StringVar(value="max")
        tb.Combobox(norm_row, textvariable=self.norm_method_var, state="readonly", width=10,
                    values=["max", "minmax", "area", "vector"]).pack(side="left", padx=(4, 4))
        tb.Button(norm_row, text="ⓘ", width=3, bootstyle="secondary-outline",
                  command=lambda: self.show_formula("Normalization Methods", fs.NORMALIZATION_METHODS)).pack(side="left")
        tb.Button(card, text="Apply Normalization", command=self.normalize_active).pack(fill="x", pady=2)
        tb.Button(card, text="Revert to Raw Data", bootstyle="warning-outline", command=self.revert_active).pack(fill="x", pady=2)

        total_materials = sum(len(self.database.get(cat, [])) for cat in ftir_analysis.MATERIAL_CATEGORIES)
        card = tb.Labelframe(c, text="4. Database Identification", padding=10, bootstyle="success")
        card.pack(fill="x", padx=6, pady=6)
        tol_row = tb.Frame(card)
        tol_row.pack(fill="x")
        tb.Label(tol_row, text="Tolerance (+/- cm-1):").pack(side="left")
        tb.Spinbox(tol_row, from_=1, to=50, textvariable=self.tolerance_var, width=6).pack(side="right")
        tb.Label(card, text="Restrict search to category (more accurate if known):").pack(anchor="w", pady=(8, 0))
        cat_values = [ftir_analysis.ALL_CATEGORIES_LABEL] + [ftir_analysis.CATEGORY_LABELS[k] for k in ftir_analysis.MATERIAL_CATEGORIES]
        tb.Combobox(card, textvariable=self.category_var, values=cat_values, state="readonly").pack(fill="x")
        self.make_action_row(card, f"Match to Database ({total_materials} materials)", self.match_database, bootstyle="success",
                              info_title="FTIR Database Matching Method", info_text=fs.FTIR_DATABASE_MATCHING, pady=(8, 0))

        card = tb.Labelframe(c, text="5. Peak Fitting", padding=10, bootstyle="info")
        card.pack(fill="x", padx=6, pady=6)
        shape_row = tb.Frame(card)
        shape_row.pack(fill="x")
        tb.Label(shape_row, text="Peak shape:").pack(side="left")
        tb.Combobox(shape_row, textvariable=self.fit_shape_var, state="readonly", width=13,
                    values=["gaussian", "lorentzian", "pseudo_voigt"]).pack(side="right")
        win_row = tb.Frame(card)
        win_row.pack(fill="x", pady=(6, 0))
        tb.Label(win_row, text="Fit window (+/- cm-1):").pack(side="left")
        tb.Spinbox(win_row, from_=5, to=200, textvariable=self.fit_window_var, width=6).pack(side="right")
        self.make_action_row(card, "Fit All Detected Peaks", self.fit_peaks,
                              info_title="Peak Fitting Method", info_text=fs.PEAK_FITTING, pady=(8, 0))

        card = tb.Labelframe(c, text="6. Calculations", padding=10, bootstyle="secondary")
        card.pack(fill="x", padx=6, pady=6)
        self.make_action_row(card, "%T <-> Absorbance Converter", self.calc_converter,
                              info_title="%T <-> Absorbance", info_text=fs.TRANSMITTANCE_ABSORBANCE)
        tb.Button(card, text="Peak Area (integrate range)", command=self.calc_peak_area).pack(fill="x", pady=2)
        tb.Button(card, text="FWHM of Nearest Peak", command=self.calc_fwhm).pack(fill="x", pady=2)
        self.make_action_row(card, "Beer-Lambert Concentration", self.calc_beer_lambert,
                              info_title="Beer-Lambert Law", info_text=fs.BEER_LAMBERT)

        card = tb.Labelframe(c, text="7. Export & Session", padding=10, bootstyle="dark")
        card.pack(fill="x", padx=6, pady=(6, 16))
        tb.Button(card, text="Export Peak List (CSV)", command=self.export_peaks_csv).pack(fill="x", pady=2)
        tb.Button(card, text="Export PDF Report", bootstyle="danger", command=self.export_pdf_report).pack(fill="x", pady=2)
        tb.Button(card, text="Save Session...", command=self.save_session).pack(fill="x", pady=2)
        tb.Button(card, text="Load Session...", command=self.load_session).pack(fill="x", pady=2)

    def _build_results_tabs(self):
        nb = self.results_notebook

        peaks_frame = tb.Frame(nb, padding=4)
        nb.add(peaks_frame, text="Peaks")
        self.peaks_table = DataTable(peaks_frame, [("i", "#"), ("x", "Wavenumber (cm-1)"), ("y", "Intensity"), ("prom", "Prominence")],
                                      height=9, widths={"i": 35, "x": 130, "y": 90, "prom": 90})
        self.peaks_table.pack(fill="both", expand=True)

        matches_frame = tb.Frame(nb, padding=4)
        nb.add(matches_frame, text="Database Matches")
        matches_toolbar = tb.Frame(matches_frame)
        matches_toolbar.pack(fill="x")
        tb.Label(matches_toolbar, text="Click a row to overlay its reference peaks (orange bands) on the plot.",
                 bootstyle="secondary", font=("", 8)).pack(side="left")
        tb.Button(matches_toolbar, text="Clear Overlay", bootstyle="secondary-outline",
                  command=self.clear_reference_overlay).pack(side="right")
        self.matches_table = DataTable(matches_frame,
                                        [("name", "Material"), ("category", "Category"), ("score", "Score"),
                                         ("count", "Matched/Total"), ("source", "Source")],
                                        height=7, widths={"name": 220, "category": 80, "score": 60, "count": 90, "source": 200})
        self.matches_table.pack(fill="both", expand=True)
        self.matches_table.on_select = self._show_match_detail
        self.match_detail = tb.Text(matches_frame, height=9, wrap="word")
        self.match_detail.pack(fill="both", expand=False, pady=(6, 0))
        self.match_detail.configure(state="disabled")

        fg_frame = tb.Frame(nb, padding=4)
        nb.add(fg_frame, text="Functional Groups")
        self.fg_table = DataTable(fg_frame, [("x", "Wavenumber"), ("group", "Functional Group"), ("range", "Expected Range"), ("source", "Source")],
                                   height=10, widths={"x": 90, "group": 230, "range": 100, "source": 200})
        self.fg_table.pack(fill="both", expand=True)

        fits_frame = tb.Frame(nb, padding=4)
        nb.add(fits_frame, text="Peak Fits")
        self.fits_table = DataTable(fits_frame,
                                     [("seed", "Seed X"), ("center", "Fitted Center"), ("fwhm", "FWHM"),
                                      ("height", "Height"), ("area", "Area"), ("r2", "R-squared")],
                                     height=9, widths={"seed": 80, "center": 90, "fwhm": 80, "height": 80, "area": 90, "r2": 80})
        self.fits_table.pack(fill="both", expand=True)

    # ---------------------------------------------------------------- plotting

    def _plot_active_extras(self, trace):
        # Text annotations get expensive to render (and unreadable) past a few dozen
        # peaks -- keep the vlines either way but only label peaks below that count.
        label_peaks = len(trace.peaks) <= 60
        for p in trace.peaks:
            self.ax.axvline(p["x"], color="#e03131", alpha=0.35, lw=0.9)
            if label_peaks:
                self.ax.annotate(f"{p['x']:.0f}", (p["x"], p["y"]), fontsize=7, rotation=90, ha="center", va="bottom")
        for fit in trace.fits:
            func = {"gaussian": peak_fitting.gaussian, "lorentzian": peak_fitting.lorentzian,
                    "pseudo_voigt": peak_fitting.pseudo_voigt}[fit["shape"]]
            xs = np.linspace(fit["center"] - fit["fwhm"] * 2.5, fit["center"] + fit["fwhm"] * 2.5, 150)
            if fit["shape"] == "pseudo_voigt":
                ys = func(xs, fit["height"], fit["center"], fit["fwhm"], fit["eta"], fit["offset"])
            else:
                ys = func(xs, fit["height"], fit["center"], fit["fwhm"], fit["offset"])
            self.ax.plot(xs, ys, "--", color="#12b886", lw=1.2, alpha=0.9)

    def _draw_reference_overlay(self):
        label = self.reference_overlay.get("label", "Reference")
        first = True
        for p in self.reference_overlay.get("peaks", []):
            lo, hi = p["range"]
            if lo == 0 and hi == 0:
                continue  # IR-inactive placeholder (e.g. NaCl) -- nothing to plot
            self.ax.axvspan(lo, hi, color="#f59f00", alpha=0.20, lw=0,
                             label=f"Reference: {label}" if first else None)
            self.ax.axvline((lo + hi) / 2, color="#f59f00", alpha=0.6, lw=0.8, linestyle=":")
            first = False

    # ---------------------------------------------------------------- loading

    def _load_spectrum(self):
        self.load_file_dialog([("Spectrum files", "*.csv *.txt *.dat *.xy *.dpt *.jdx *.dx"), ("All files", "*.*")],
                               file_readers.read_ftir_any)

    def handle_dropped_file(self, path):
        self.load_file_path(path, file_readers.read_ftir_any)

    # ---------------------------------------------------------------- results refresh

    def on_active_trace_changed(self):
        if self.reference_overlay is not None:
            # the overlay was tied to a match row for whichever trace was
            # active before -- clear it so it doesn't linger, misleadingly,
            # over a different spectrum.
            self.reference_overlay = None
            self.redraw()
        t = self.get_active()
        if t is None:
            self.peaks_table.clear()
            self.matches_table.clear()
            self.fg_table.clear()
            self.fits_table.clear()
            return
        self.peaks_table.set_rows(t.peaks, lambda p, i=None: (t.peaks.index(p) + 1, f"{p['x']:.1f}", f"{p['y']:.4f}", f"{p['prominence']:.4f}"))
        self.matches_table.set_rows(t.matches, lambda m: (m["name"], m["category"], f"{m['score']*100:.0f}%",
                                                           f"{m['matched_count']}/{m['total_reference_peaks']}", m.get("source", "")))
        self.fg_table.set_rows(t.fg_hits, lambda h: (f"{h['peak_x']:.1f}", h["group"], f"{h['range'][0]}-{h['range'][1]}", h.get("source", "")))
        self.fits_table.set_rows(t.fits, lambda f: (f"{f['seed_x']:.1f}", f"{f['center']:.1f}", f"{f['fwhm']:.2f}",
                                                      f"{f['height']:.4f}", f"{f['area']:.3f}", f"{f['r_squared']:.4f}"))

    def _show_match_detail(self, match):
        entry = ftir_analysis.find_entry(self.database, match["name"])

        self.match_detail.configure(state="normal")
        self.match_detail.delete("1.0", "end")
        lines = [f"{match['name']} [{match['category']}]  Source: {match.get('source','')}"]
        if entry:
            # List EVERY reference peak of the material (not just the subset
            # that happened to fall within tolerance) so the text panel gives
            # the same complete picture as the orange overlay on the plot --
            # marking each one MATCHED or not found in your spectrum.
            lines.append(f"Reference peaks ({match['matched_count']}/{len(entry['peaks'])} matched):")
            matched_by_range = {tuple(mm["reference"]["range"]): mm for mm in match["matches"]}
            for ref in entry["peaks"]:
                mm = matched_by_range.get(tuple(ref["range"]))
                range_txt = f"{ref['range'][0]}-{ref['range'][1]} cm-1" if not (ref["range"][0] == 0 and ref["range"][1] == 0) else "(IR-inactive)"
                if mm:
                    lines.append(f"  [MATCHED]   ref {range_txt} ({ref['assignment']})  "
                                  f"~ observed {mm['observed']['x']:.1f} cm-1, delta={mm['delta_cm1']:+.1f} cm-1")
                else:
                    lines.append(f"  [not found] ref {range_txt} ({ref['assignment']})")
        else:
            for mm in match["matches"]:
                ref = mm["reference"]
                lines.append(f"  observed {mm['observed']['x']:.1f} cm-1  ~  ref {ref['range'][0]}-{ref['range'][1]} cm-1 "
                              f"({ref['assignment']}), delta={mm['delta_cm1']:+.1f} cm-1")
        self.match_detail.insert("1.0", "\n".join(lines))
        self.match_detail.configure(state="disabled")

        # Overlay the material's FULL reference peak list (not just the ones
        # that happened to fall within tolerance) on the plot, so the user
        # can visually compare every expected band against their spectrum --
        # including the ones that DIDN'T show up as a real peak.
        if entry:
            self.set_reference_overlay({"label": match["name"], "peaks": entry["peaks"]})
        else:
            self.clear_reference_overlay()

    # ---------------------------------------------------------------- actions

    def _require_active(self):
        t = self.get_active()
        if t is None:
            Messagebox.show_warning("Load a spectrum first.", "No Data")
        return t

    def detect_peaks(self):
        t = self._require_active()
        if t is None:
            return
        prom_frac = self.prom_var.get() / 100.0
        t.peaks = ftir_analysis.detect_peaks(t.x, t.y, prominence_frac=prom_frac, mode=self.mode_var.get())
        t.fits = []
        self.redraw()
        self.on_active_trace_changed()
        msg = f"Detected {len(t.peaks)} peaks in {t.label}."
        if len(t.peaks) > 100:
            msg += " That's a lot -- consider raising the sensitivity slider for cleaner results."
        self.app.set_status_message(msg)

    def match_database(self):
        t = self._require_active()
        if t is None:
            return
        if not t.peaks:
            self.detect_peaks()
            t = self.get_active()
            if not t.peaks:
                return
        tol = self.tolerance_var.get()
        peaks_snapshot = t.peaks
        label_to_key = {v: k for k, v in ftir_analysis.CATEGORY_LABELS.items()}
        selected_label = self.category_var.get()
        categories = None if selected_label == ftir_analysis.ALL_CATEGORIES_LABEL else [label_to_key[selected_label]]

        def compute():
            matches = ftir_analysis.match_peaks_to_database(peaks_snapshot, self.database, tolerance=tol, categories=categories)
            fg_hits = ftir_analysis.match_functional_groups(peaks_snapshot, self.database, tolerance=tol)
            return matches, fg_hits

        def on_done(result):
            t.matches, t.fg_hits = result
            self.on_active_trace_changed()
            self.results_notebook.select(1)
            scope = "all categories" if categories is None else selected_label
            self.app.set_status_message(f"{len(t.matches)} candidate material(s) in {scope}, {len(t.fg_hits)} functional-group hit(s).")

        self.run_background(compute, on_done, busy_text="Matching against FTIR database...")

    def smooth_active(self):
        t = self._require_active()
        if t is None:
            return
        dlg = MultiFieldDialog(self.app.root, "Smooth Spectrum (Savitzky-Golay)",
                                [("wl", "Window length (odd, points):", "11"), ("po", "Polynomial order:", "3")])
        if not dlg.result:
            return
        try:
            wl = int(float(dlg.result["wl"]))
            po = int(float(dlg.result["po"]))
            t.y = ftir_analysis.smooth_spectrum(t.y, window_length=wl, polyorder=po)
        except Exception as e:
            Messagebox.show_error(str(e), "Smoothing Failed")
            return
        self.redraw()
        self.app.set_status_message(f"Smoothed {t.label} (window={wl}, order={po}). Re-run Detect Peaks to update peaks.")

    def baseline_correct_active(self):
        t = self._require_active()
        if t is None:
            return
        t.y, _baseline = ftir_analysis.baseline_correct(t.x, t.y_raw)
        self.redraw()
        self.app.set_status_message("Applied linear baseline correction (from raw data, anchored at end points). Re-run Detect Peaks.")

    def normalize_active(self):
        t = self._require_active()
        if t is None:
            return
        method = self.norm_method_var.get()
        try:
            t.y = ftir_analysis.normalize_spectrum(t.y, method=method, x=t.x)
        except Exception as e:
            Messagebox.show_error(str(e), "Normalization Failed")
            return
        self.redraw()
        self.app.set_status_message(f"Normalized {t.label} ({method}).")

    def atr_correct_active(self):
        t = self._require_active()
        if t is None:
            return
        dlg = MultiFieldDialog(
            self.app.root, "ATR Correction",
            [("crystal", "ATR crystal (diamond/znse/germanium/silicon/krs-5):", "diamond"),
             ("angle", "Angle of incidence (deg):", "45"),
             ("n_sample", "Sample refractive index:", "1.5")],
            help_text="Corrects for wavenumber-dependent ATR penetration depth so relative "
                       "band intensities compare more fairly with a transmission spectrum.")
        if not dlg.result:
            return
        try:
            crystal = dlg.result["crystal"]
            angle = float(dlg.result["angle"])
            n_sample = float(dlg.result["n_sample"])
            t.y = ftir_analysis.atr_correction(t.x, t.y, crystal=crystal, angle_deg=angle, n_sample=n_sample)
        except Exception as e:
            Messagebox.show_error(str(e), "ATR Correction Failed")
            return
        self.redraw()
        self.app.set_status_message(f"Applied ATR correction to {t.label} ({crystal}, {angle} deg). Re-run Detect Peaks.")

    def derivative_active(self):
        t = self._require_active()
        if t is None:
            return
        dlg = MultiFieldDialog(
            self.app.root, "Derivative Spectrum",
            [("order", "Derivative order (1 or 2):", "1"),
             ("wl", "Savitzky-Golay window length (odd, points):", "15"),
             ("po", "Polynomial order:", "3")])
        if not dlg.result:
            return
        try:
            order = int(float(dlg.result["order"]))
            wl = int(float(dlg.result["wl"]))
            po = int(float(dlg.result["po"]))
            t.y = ftir_analysis.derivative_spectrum(t.x, t.y, order=order, window_length=wl, polyorder=po)
        except Exception as e:
            Messagebox.show_error(str(e), "Derivative Failed")
            return
        self.redraw()
        self.app.set_status_message(f"Computed {order}{'st' if order == 1 else 'nd'} derivative of {t.label}. Re-run Detect Peaks.")

    def revert_active(self):
        t = self._require_active()
        if t is None:
            return
        t.revert_to_raw()
        self._on_traces_changed()
        self.app.set_status_message(f"{t.label} reverted to originally loaded data.")

    def fit_peaks(self):
        t = self._require_active()
        if t is None:
            return
        if not t.peaks:
            Messagebox.show_warning("Run Detect Peaks first.", "No Peaks")
            return
        window, shape = self.fit_window_var.get(), self.fit_shape_var.get()
        x_snap, y_snap, peaks_snap = t.x, t.y, t.peaks

        def compute():
            return peak_fitting.fit_peaks_batch(x_snap, y_snap, peaks_snap, window, shape=shape)

        def on_done(result):
            fits, errors = result
            t.fits = fits
            self.redraw()
            self.on_active_trace_changed()
            msg = f"Fit {len(fits)}/{len(peaks_snap)} peaks."
            if errors:
                msg += f" {len(errors)} peak(s) failed to converge."
            self.app.set_status_message(msg)

        self.run_background(compute, on_done, busy_text="Fitting peaks...")

    # ---------------------------------------------------------------- calculations

    def calc_converter(self):
        dlg = MultiFieldDialog(self.app.root, "%T <-> Absorbance Converter",
                                [("value", "Value:", ""), ("unit", "Unit (%T or A):", "%T")])
        if not dlg.result:
            return
        try:
            num = parse_float(dlg.result["value"], "Value")
            unit = dlg.result["unit"].strip().lower()
            if unit in ("%t", "t"):
                res = ftir_analysis.transmittance_to_absorbance(num)
                Messagebox.show_info(f"{num} %T = {float(res):.4f} Absorbance", "Result")
            elif unit == "a":
                res = ftir_analysis.absorbance_to_transmittance(num)
                Messagebox.show_info(f"{num} A = {float(res):.4f} %T", "Result")
            else:
                raise ValueError("Unit must be %T or A")
        except Exception as e:
            Messagebox.show_error(str(e), "Error")

    def calc_peak_area(self):
        t = self._require_active()
        if t is None:
            return
        dlg = MultiFieldDialog(self.app.root, "Peak Area", [("start", "Start (cm-1):", "1700"), ("end", "End (cm-1):", "1750")])
        if not dlg.result:
            return
        try:
            s = parse_float(dlg.result["start"], "Start")
            e = parse_float(dlg.result["end"], "End")
            area = ftir_analysis.peak_area(t.x, t.y, s, e)
            Messagebox.show_info(f"Integrated area between {s} and {e} cm-1: {area:.4f}", "Peak Area")
        except Exception as ex:
            Messagebox.show_error(str(ex), "Error")

    def calc_fwhm(self):
        t = self._require_active()
        if t is None:
            return
        if not t.peaks:
            Messagebox.show_warning("Run Detect Peaks first.", "No Peaks")
            return
        dlg = MultiFieldDialog(self.app.root, "FWHM", [("pos", "Approx. peak position (cm-1):", "")])
        if not dlg.result:
            return
        try:
            target = parse_float(dlg.result["pos"], "Position")
            nearest = min(t.peaks, key=lambda p: abs(p["x"] - target))
            fwhm = ftir_analysis.fwhm_from_peak(t.x, t.y, nearest["index"])
            Messagebox.show_info(f"Nearest peak at {nearest['x']:.1f} cm-1: FWHM = {fwhm:.2f} cm-1", "FWHM")
        except Exception as ex:
            Messagebox.show_error(str(ex), "Error")

    def calc_beer_lambert(self):
        dlg = MultiFieldDialog(self.app.root, "Beer-Lambert Concentration",
                                [("a", "Absorbance:", ""), ("eps", "Epsilon (L/mol.cm):", ""), ("l", "Path length (cm):", "1.0")])
        if not dlg.result:
            return
        try:
            a = parse_float(dlg.result["a"], "Absorbance")
            eps = parse_float(dlg.result["eps"], "Epsilon")
            l = parse_float(dlg.result["l"], "Path length")
            c = ftir_analysis.beer_lambert_concentration(a, eps, l)
            Messagebox.show_info(f"c = {c:.6g} mol/L", "Concentration")
        except Exception as ex:
            Messagebox.show_error(str(ex), "Error")

    # ---------------------------------------------------------------- export

    def export_peaks_csv(self):
        t = self._require_active()
        if t is None:
            return
        if not t.peaks:
            Messagebox.show_warning("Run Detect Peaks first.", "No Peaks")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["wavenumber_cm-1", "intensity", "prominence"])
            for p in t.peaks:
                w.writerow([p["x"], p["y"], p["prominence"]])
        Messagebox.show_info(f"Saved {len(t.peaks)} peaks to {path}", "Exported")

    def export_pdf_report(self):
        t = self._require_active()
        if t is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        tmp_png = os.path.join(tempfile.gettempdir(), "ftir_report_plot.png")
        save_figure_snapshot(self.fig, tmp_png)

        sections = []
        if t.peaks:
            rows = [["#", "Wavenumber (cm-1)", "Intensity", "Prominence"]]
            for i, p in enumerate(t.peaks, 1):
                rows.append([str(i), f"{p['x']:.1f}", f"{p['y']:.4f}", f"{p['prominence']:.4f}"])
            sections.append(("Detected Peaks", rows, None))
        if t.matches:
            rows = [["Material", "Category", "Score", "Matched/Total", "Source"]]
            for m in t.matches[:12]:
                rows.append([m["name"], m["category"], f"{m['score']*100:.0f}%",
                             f"{m['matched_count']}/{m['total_reference_peaks']}", m.get("source", "")])
            sections.append(("Database Matches (heuristic screening)", rows, None))
        if t.fg_hits:
            rows = [["Wavenumber", "Functional Group", "Expected Range"]]
            for h in t.fg_hits[:20]:
                rows.append([f"{h['peak_x']:.1f}", h["group"], f"{h['range'][0]}-{h['range'][1]}"])
            sections.append(("Functional Group Hits", rows, None))
        if not sections:
            sections.append(("Notes", None, "No peaks were detected/analyzed on this trace."))

        disclaimer = self.database.get("_meta", {}).get("note", "")
        report_export.build_report(path, "FTIR Analysis Report", f"Mode: {self.mode_var.get()}",
                                    tmp_png, sections, disclaimer, source_file=t.label)
        Messagebox.show_info(f"Report saved to {path}", "Exported")

    def save_session(self):
        path = filedialog.asksaveasfilename(defaultextension=".ftirxrd", filetypes=[("FTIR/XRD Session", "*.ftirxrd")])
        if not path:
            return
        state = {
            "tab": "ftir",
            "mode": self.mode_var.get(),
            "prominence": self.prom_var.get(),
            "tolerance": self.tolerance_var.get(),
            "category": self.category_var.get(),
            "active_id": self.active_id,
            "traces": [{
                "label": t.label, "color": t.color, "visible": t.visible,
                "x": t.x, "y": t.y, "y_raw": t.y_raw, "peaks": t.peaks,
                "matches": t.matches, "fg_hits": t.fg_hits, "fits": t.fits,
                "metadata": t.metadata, "id": t.id,
            } for t in self.traces],
        }
        session_io.save_session(path, state)
        Messagebox.show_info(f"Session saved to {path}", "Saved")

    def load_session(self):
        path = filedialog.askopenfilename(filetypes=[("FTIR/XRD Session", "*.ftirxrd"), ("All files", "*.*")])
        if not path:
            return
        try:
            state = session_io.load_session(path)
        except Exception as e:
            Messagebox.show_error(str(e), "Load Failed")
            return
        if state.get("tab") != "ftir":
            Messagebox.show_warning("This session file was saved from the XRD tab.", "Wrong Tab")
            return
        self.mode_var.set(state.get("mode", "absorbance"))
        self.prom_var.set(state.get("prominence", 2.0))
        self.tolerance_var.set(state.get("tolerance", 10.0))
        self.category_var.set(state.get("category", ftir_analysis.ALL_CATEGORIES_LABEL))
        self.traces = []
        for td in state.get("traces", []):
            t = Trace(td["label"], td["x"], td["y"], td["color"], metadata=td.get("metadata"))
            t.y_raw = np.array(td["y_raw"], dtype=float)
            t.visible = td.get("visible", True)
            t.peaks = td.get("peaks", [])
            t.matches = td.get("matches", [])
            t.fg_hits = td.get("fg_hits", [])
            t.fits = td.get("fits", [])
            self.traces.append(t)
        self.active_id = state.get("active_id")
        if self.active_id not in [t.id for t in self.traces] and self.traces:
            self.active_id = self.traces[-1].id
        self._on_traces_changed()
        self.app.set_status_message(f"Loaded session {os.path.basename(path)} ({len(self.traces)} trace(s)).")
