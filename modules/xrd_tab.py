"""
xrd_tab.py
The XRD Analysis tab: load diffraction patterns (multi-trace overlay),
detect peaks, compute d-spacing/Scherrer size, Williamson-Hall, %
crystallinity, cubic lattice parameter, match against the phase database,
fit peaks, and export a CSV/PDF/session.
"""
import os
import csv
import tempfile
import numpy as np
import ttkbootstrap as tb
from tkinter import filedialog
from ttkbootstrap.dialogs import Messagebox
from ttkbootstrap.widgets.scrolled import ScrolledFrame

import file_readers
import xrd_analysis
import peak_fitting
import report_export
import session_io
import formula_sources as fs
from ui_common import AnalysisTabBase, DataTable, MultiFieldDialog, parse_float, save_figure_snapshot, DatabaseViewerDialog
import ftir_analysis
from trace_model import Trace


class XRDTab(AnalysisTabBase):
    def __init__(self, parent, app):
        super().__init__(parent, app, x_label="2theta (deg)", y_label="Intensity", invert_x=False)
        self.database = app.xrd_db
        self.wl_var = tb.StringVar(value="Cu Ka1")
        self.custom_wl = None
        self.prom_var = tb.DoubleVar(value=2.0)
        self.d_tolerance_var = tb.DoubleVar(value=app.cfg.get("d_tolerance_pct", 1.5))
        self.fit_shape_var = tb.StringVar(value="gaussian")
        self.fit_window_var = tb.DoubleVar(value=0.5)
        self.category_var = tb.StringVar(value=xrd_analysis.ALL_CATEGORIES_LABEL)
        self._current_match = None
        self._current_match_phase = None
        self._current_match_ref_peaks = None

        self._build_controls()
        self._build_results_tabs()

    # ---------------------------------------------------------------- controls

    def _build_controls(self):
        c = self.controls

        card = tb.Labelframe(c, text="1. Load XRD File", padding=10, bootstyle="info")
        card.pack(fill="x", padx=6, pady=6)
        tb.Button(card, text="Load XRD File (auto-detect format)", bootstyle="info",
                  command=self._load_pattern).pack(fill="x")
        tb.Label(card, text=".xy/.txt/.dat/.csv, .uxd, .ras, .xrdml (high confidence); "
                            ".raw (Bruker, best-effort). Drag & drop also works.",
                 bootstyle="secondary", wraplength=280, font=("", 8)).pack(anchor="w", pady=(4, 0))

        card = tb.Labelframe(c, text="2. Wavelength & Peak Detection", padding=10, bootstyle="primary")
        card.pack(fill="x", padx=6, pady=6)
        tb.Label(card, text="X-ray wavelength:").pack(anchor="w")
        wl_combo = tb.Combobox(card, textvariable=self.wl_var, state="readonly",
                                values=list(xrd_analysis.WAVELENGTHS.keys()) + ["Custom..."])
        wl_combo.pack(fill="x")
        wl_combo.bind("<<ComboboxSelected>>", lambda e: self._maybe_prompt_custom_wl())
        tb.Label(card, text="Peak sensitivity (prominence %):").pack(anchor="w", pady=(8, 0))
        prom_row = tb.Frame(card)
        prom_row.pack(fill="x")
        tb.Scale(prom_row, from_=0.2, to=20, variable=self.prom_var, bootstyle="info").pack(side="left", fill="x", expand=True)
        tb.Label(prom_row, textvariable=self.prom_var, width=5).pack(side="left")
        tb.Button(card, text="Detect Peaks", bootstyle="primary", command=self.detect_peaks).pack(fill="x", pady=(8, 2))
        tb.Button(card, text="Smooth (Savitzky-Golay)", command=self.smooth_active).pack(fill="x", pady=2)
        self.make_action_row(card, "Subtract Background (SNIP)", self.subtract_background_active,
                              info_title="XRD Background Subtraction (SNIP)", info_text=fs.XRD_BACKGROUND_SUBTRACTION)

        card = tb.Labelframe(c, text="3. Calculations", padding=10, bootstyle="success")
        card.pack(fill="x", padx=6, pady=6)
        self.make_action_row(card, "Run All Calculations (d-spacing + Scherrer)", self.run_all_calcs, bootstyle="success",
                              info_title="Bragg's Law & Scherrer Equation", info_text=fs.BRAGG_LAW + "\n\n" + fs.SCHERRER_EQUATION)
        self.make_action_row(card, "Williamson-Hall (size + strain)", self.run_williamson_hall,
                              info_title="Williamson-Hall Method", info_text=fs.WILLIAMSON_HALL)
        self.make_action_row(card, "% Crystallinity (select regions)", self.run_crystallinity,
                              info_title="% Crystallinity Method", info_text=fs.PERCENT_CRYSTALLINITY)
        self.make_action_row(card, "Cubic Lattice Parameter (quick, single-peak)", self.run_lattice_param,
                              info_title="Cubic Lattice Parameter", info_text=fs.CUBIC_LATTICE_PARAMETER)
        self.make_action_row(card, "Iterative Lattice Refinement (multi-peak, accurate)", self.open_lattice_refinement,
                              bootstyle="success", info_title="Iterative Lattice Refinement Method",
                              info_text=fs.ITERATIVE_LATTICE_REFINEMENT)
        self.make_action_row(card, "2theta / d-spacing / Q Converter", self.open_unit_converter,
                              info_title="XRD Unit Converter", info_text=fs.XRD_UNIT_CONVERTER)

        card = tb.Labelframe(c, text="4. Phase Identification", padding=10, bootstyle="warning")
        card.pack(fill="x", padx=6, pady=6)
        tol_row = tb.Frame(card)
        tol_row.pack(fill="x")
        tb.Label(tol_row, text="d-spacing tolerance (%):").pack(side="left")
        tb.Spinbox(tol_row, from_=0.1, to=10, increment=0.1, textvariable=self.d_tolerance_var, width=6).pack(side="right")
        tb.Label(card, text="Restrict search to category (more accurate if known):").pack(anchor="w", pady=(8, 0))
        cat_values = [xrd_analysis.ALL_CATEGORIES_LABEL] + [xrd_analysis.PHASE_CATEGORY_LABELS[k] for k in sorted(xrd_analysis.PHASE_CATEGORY_LABELS)]
        tb.Combobox(card, textvariable=self.category_var, values=cat_values, state="readonly").pack(fill="x")
        self.make_action_row(card, "Match to Phase Database", self.match_phases, bootstyle="warning",
                              info_title="XRD Phase Matching Method", info_text=fs.XRD_PHASE_MATCHING, pady=(8, 2))
        tb.Button(card, text="Open Database Viewer / Import CSV...", command=self.open_database_viewer).pack(fill="x", pady=2)

        card = tb.Labelframe(c, text="5. Peak Fitting", padding=10, bootstyle="info")
        card.pack(fill="x", padx=6, pady=6)
        shape_row = tb.Frame(card)
        shape_row.pack(fill="x")
        tb.Label(shape_row, text="Peak shape:").pack(side="left")
        tb.Combobox(shape_row, textvariable=self.fit_shape_var, state="readonly", width=13,
                    values=["gaussian", "lorentzian", "pseudo_voigt"]).pack(side="right")
        win_row = tb.Frame(card)
        win_row.pack(fill="x", pady=(6, 0))
        tb.Label(win_row, text="Fit window (+/- deg 2theta):").pack(side="left")
        tb.Spinbox(win_row, from_=0.05, to=5, increment=0.05, textvariable=self.fit_window_var, width=6).pack(side="right")
        self.make_action_row(card, "Fit All Detected Peaks", self.fit_peaks,
                              info_title="Peak Fitting Method", info_text=fs.PEAK_FITTING, pady=(8, 0))

        card = tb.Labelframe(c, text="6. Export & Session", padding=10, bootstyle="dark")
        card.pack(fill="x", padx=6, pady=(6, 16))
        tb.Button(card, text="Export Peak List (CSV)", command=self.export_peaks_csv).pack(fill="x", pady=2)
        tb.Button(card, text="Export PDF Report", bootstyle="danger", command=self.export_pdf_report).pack(fill="x", pady=2)
        tb.Button(card, text="Export Data for OriginLab (CSV)...", command=self.export_originlab_dialog).pack(fill="x", pady=2)
        tb.Button(card, text="Export Graph (SVG/EPS/PDF/PNG)...", command=self.export_graph_dialog).pack(fill="x", pady=2)
        tb.Button(card, text="Save Session...", command=self.save_session).pack(fill="x", pady=2)
        tb.Button(card, text="Load Session...", command=self.load_session).pack(fill="x", pady=2)

    def _build_results_tabs(self):
        nb = self.results_notebook

        peaks_frame = tb.Frame(nb, padding=4)
        nb.add(peaks_frame, text="Peaks")
        self.peaks_table = DataTable(peaks_frame,
                                      [("tt", "2theta (deg)"), ("i", "Intensity"), ("fwhm", "FWHM (deg)"),
                                       ("d", "d-spacing (A)"), ("size", "Crystallite Size (nm)")],
                                      height=9, widths={"tt": 90, "i": 80, "fwhm": 80, "d": 100, "size": 130})
        self.peaks_table.pack(fill="both", expand=True)

        matches_frame = tb.Frame(nb, padding=4)
        nb.add(matches_frame, text="Phase Matches")
        matches_toolbar = tb.Frame(matches_frame)
        matches_toolbar.pack(fill="x")
        tb.Label(matches_toolbar, text="Click a row to overlay its reference lines (orange) on the pattern.",
                 bootstyle="secondary", font=("", 8)).pack(side="left")
        tb.Button(matches_toolbar, text="Clear Overlay", bootstyle="secondary-outline",
                  command=self.clear_reference_overlay).pack(side="right")
        tb.Button(matches_toolbar, text="Export Reference Peaks (CSV)...", bootstyle="secondary-outline",
                  command=self.export_reference_peaks_csv).pack(side="right", padx=(0, 4))
        self.matches_table = DataTable(matches_frame,
                                        [("name", "Phase"), ("category", "Category"), ("system", "System"),
                                         ("score", "Score"), ("count", "Matched/Total"), ("source", "Source")],
                                        height=7, widths={"name": 190, "category": 80, "system": 90, "score": 60, "count": 90, "source": 160})
        self.matches_table.pack(fill="both", expand=True)
        self.matches_table.on_select = self._show_match_detail
        self.match_detail = tb.Text(matches_frame, height=9, wrap="word")
        self.match_detail.pack(fill="both", expand=False, pady=(6, 0))
        self.match_detail.configure(state="disabled")

        wh_frame = tb.Frame(nb, padding=4)
        nb.add(wh_frame, text="Williamson-Hall")
        self.wh_text = tb.Text(wh_frame, height=12, wrap="word")
        self.wh_text.pack(fill="both", expand=True)
        self.wh_text.insert("1.0", "Run Detect Peaks (3+ peaks with resolvable FWHM), then click "
                                    "'Williamson-Hall (size + strain)'.")
        self.wh_text.configure(state="disabled")

        fits_frame = tb.Frame(nb, padding=4)
        nb.add(fits_frame, text="Peak Fits")
        self.fits_table = DataTable(fits_frame,
                                     [("seed", "Seed 2theta"), ("center", "Fitted Center"), ("fwhm", "FWHM (deg)"),
                                      ("height", "Height"), ("area", "Area"), ("r2", "R-squared")],
                                     height=9, widths={"seed": 90, "center": 90, "fwhm": 80, "height": 80, "area": 90, "r2": 80})
        self.fits_table.pack(fill="both", expand=True)

    # ---------------------------------------------------------------- plotting

    def _plot_active_extras(self, trace):
        for p in trace.peaks:
            self.ax.axvline(p["two_theta"], color="#e03131", alpha=0.35, lw=0.9)
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
        wl = self._get_wavelength()
        tol_pct = self.d_tolerance_var.get() / 100.0
        label = self.reference_overlay.get("label", "Reference")
        first = True
        for p in self.reference_overlay.get("peaks", []):
            d = p["d_A"]
            two_theta = xrd_analysis.two_theta_from_d(d, wl)
            if two_theta is None:
                continue  # this reflection isn't observable at the current wavelength
            tt_hi = xrd_analysis.two_theta_from_d(d * (1 - tol_pct), wl)  # smaller d -> larger 2theta
            tt_lo = xrd_analysis.two_theta_from_d(d * (1 + tol_pct), wl)
            tt_lo = tt_lo if tt_lo is not None else two_theta
            tt_hi = tt_hi if tt_hi is not None else two_theta
            self.ax.axvspan(tt_lo, tt_hi, color="#f59f00", alpha=0.20, lw=0,
                             label=f"Reference: {label}" if first else None)
            self.ax.axvline(two_theta, color="#f59f00", alpha=0.6, lw=0.8, linestyle=":")
            first = False

    # ---------------------------------------------------------------- loading

    def _load_pattern(self):
        self.load_file_dialog([("All supported", "*.xy *.txt *.dat *.csv *.uxd *.ras *.xrdml *.raw"),
                                ("All files", "*.*")], file_readers.read_any)

    def handle_dropped_file(self, path):
        self.load_file_path(path, file_readers.read_any)

    def _get_wavelength(self):
        if self.wl_var.get() == "Custom...":
            if self.custom_wl is None:
                self._maybe_prompt_custom_wl()
            return self.custom_wl or xrd_analysis.WAVELENGTHS["Cu Ka1"]
        return xrd_analysis.WAVELENGTHS[self.wl_var.get()]

    def _maybe_prompt_custom_wl(self):
        if self.wl_var.get() != "Custom...":
            return
        dlg = MultiFieldDialog(self.app.root, "Custom Wavelength", [("wl", "Wavelength (Angstrom):", "1.540562")])
        if dlg.result:
            try:
                self.custom_wl = parse_float(dlg.result["wl"], "Wavelength")
            except Exception as e:
                Messagebox.show_error(str(e), "Error")

    # ---------------------------------------------------------------- results refresh

    def on_active_trace_changed(self):
        if self.reference_overlay is not None:
            # the overlay was tied to a match row for whichever trace was
            # active before -- clear it so it doesn't linger, misleadingly,
            # over a different pattern.
            self.reference_overlay = None
            self.redraw()
        t = self.get_active()
        if t is None:
            self.peaks_table.clear()
            self.matches_table.clear()
            self.fits_table.clear()
            return
        self.peaks_table.set_rows(t.peaks, self._format_peak_row)
        self.matches_table.set_rows(t.matches, lambda m: (m["name"], m["category"], m.get("crystal_system", ""),
                                                           f"{m['score']*100:.0f}%",
                                                           f"{m['matched_count']}/{m['total_reference_peaks']}", m.get("source", "")))
        self.fits_table.set_rows(t.fits, lambda f: (f"{f['seed_x']:.3f}", f"{f['center']:.3f}", f"{f['fwhm']:.3f}",
                                                      f"{f['height']:.2f}", f"{f['area']:.3f}", f"{f['r_squared']:.4f}"))
        wh = t.metadata.get("wh_result")
        self._show_wh_result(wh)

    def _format_peak_row(self, p):
        d = f"{p['d_A']:.4f}" if "d_A" in p else "-"
        size = f"{p['size_nm']:.2f}" if p.get("size_nm") is not None else "-"
        return (f"{p['two_theta']:.3f}", f"{p['intensity']:.1f}", f"{p['fwhm_deg']:.3f}", d, size)

    def _show_match_detail(self, match):
        merged = xrd_analysis.merged_database(self.database)
        phase = xrd_analysis.find_phase(merged, match["name"])
        self._current_match = match
        self._current_match_phase = phase
        self._current_match_ref_peaks = (
            sorted(phase["peaks"], key=lambda r: -r.get("rel_intensity", 0))[:match["total_reference_peaks"]]
            if phase else None
        )

        self.match_detail.configure(state="normal")
        self.match_detail.delete("1.0", "end")
        lines = [f"{match['name']} [{match.get('crystal_system','')}]  Source: {match.get('source','')}"]
        if phase:
            # List every reference line actually CONSIDERED for this match
            # (match_xrd_phases only scores the top_n strongest lines, which
            # is what "total_reference_peaks" counts) so the text panel gives
            # the same complete picture as the orange overlay -- marking each
            # one MATCHED or not found in your pattern.
            n_considered = match["total_reference_peaks"]
            ref_peaks = sorted(phase["peaks"], key=lambda r: -r.get("rel_intensity", 0))[:n_considered]
            lines.append(f"Reference lines ({match['matched_count']}/{len(ref_peaks)} matched, "
                         f"strongest {n_considered} lines considered):")
            matched_by_d = {round(mm["reference"]["d_A"], 6): mm for mm in match["matches"]}
            for ref in ref_peaks:
                mm = matched_by_d.get(round(ref["d_A"], 6))
                if mm:
                    lines.append(f"  [MATCHED]   ref d={ref['d_A']:.4f} A (hkl {ref.get('hkl','')}, "
                                 f"I={ref.get('rel_intensity','')})  ~ observed d={mm['observed_d_A']:.4f} A, "
                                 f"delta={mm['delta_d_A']:+.4f} A")
                else:
                    lines.append(f"  [not found] ref d={ref['d_A']:.4f} A (hkl {ref.get('hkl','')}, "
                                 f"I={ref.get('rel_intensity','')})")
        else:
            for mm in match["matches"]:
                ref = mm["reference"]
                lines.append(f"  observed d={mm['observed_d_A']:.4f} A  ~  ref d={ref['d_A']:.4f} A "
                             f"(hkl {ref.get('hkl','')}, I={ref.get('rel_intensity','')}), delta={mm['delta_d_A']:+.4f} A")
        self.match_detail.insert("1.0", "\n".join(lines))
        self.match_detail.configure(state="disabled")

        # Overlay the phase's FULL reference line list (not just the ones
        # that happened to fall within tolerance) on the pattern, so the
        # user can visually compare every expected reflection against their
        # data -- including the ones that DIDN'T show up as a real peak.
        if phase:
            self.set_reference_overlay({"label": match["name"], "peaks": phase["peaks"]})
        else:
            self.clear_reference_overlay()

    def _show_wh_result(self, wh):
        self.wh_text.configure(state="normal")
        self.wh_text.delete("1.0", "end")
        if not wh:
            self.wh_text.insert("1.0", "Run Detect Peaks (3+ peaks with resolvable FWHM), then click "
                                        "'Williamson-Hall (size + strain)'.")
        else:
            size_txt = f"{wh['crystallite_size_nm']:.2f} nm" if wh["crystallite_size_nm"] else "not resolvable (non-physical intercept)"
            strain_note = (
                "\n\nNote: this fit came out NEGATIVE. Real strain broadening can only add "
                "width to a peak, never subtract it, so a negative microstrain has no direct "
                "physical meaning -- it means the data doesn't show a strain contribution "
                "resolvable above noise (and/or uncorrected instrumental broadening), not a "
                "real 'negative strain'. Treat this result as strain ~ 0."
                if not wh.get("strain_physical", True) else ""
            )
            self.wh_text.insert("1.0", f"Williamson-Hall analysis ({wh['n_peaks']} peaks):\n\n"
                                        f"  Crystallite size: {size_txt}\n"
                                        f"  Microstrain: {wh['microstrain']:.5f}\n"
                                        f"  Linear fit: slope={wh['slope']:.5f}, intercept={wh['intercept']:.5f}\n\n"
                                        f"Note: separates size vs. strain broadening across peaks; still not "
                                        f"corrected for instrumental broadening.{strain_note}")
        self.wh_text.configure(state="disabled")

    # ---------------------------------------------------------------- actions

    def _require_active(self):
        t = self.get_active()
        if t is None:
            Messagebox.show_warning("Load an XRD file first.", "No Data")
        return t

    def detect_peaks(self):
        t = self._require_active()
        if t is None:
            return
        prom_frac = self.prom_var.get() / 100.0
        t.peaks = xrd_analysis.detect_xrd_peaks(t.x, t.y, prominence_frac=prom_frac)
        t.fits = []
        t.metadata.pop("wh_result", None)
        self.redraw()
        self.on_active_trace_changed()
        msg = f"Detected {len(t.peaks)} peaks in {t.label}."
        if len(t.peaks) > 100:
            msg += " That's a lot -- consider raising the sensitivity slider for cleaner results."
        self.app.set_status_message(msg)

    def smooth_active(self):
        t = self._require_active()
        if t is None:
            return
        dlg = MultiFieldDialog(self.app.root, "Smooth Pattern (Savitzky-Golay)",
                                [("wl", "Window length (odd, points):", "11"), ("po", "Polynomial order:", "3")])
        if not dlg.result:
            return
        try:
            wl = int(float(dlg.result["wl"]))
            po = int(float(dlg.result["po"]))
            t.y = xrd_analysis.smooth_pattern(t.y, window_length=wl, polyorder=po)
        except Exception as e:
            Messagebox.show_error(str(e), "Smoothing Failed")
            return
        self.redraw()
        self.app.set_status_message(f"Smoothed {t.label} (window={wl}, order={po}). Re-run Detect Peaks to update peaks.")

    def subtract_background_active(self):
        t = self._require_active()
        if t is None:
            return
        try:
            background = xrd_analysis.snip_background(t.y_raw)
            t.y = t.y_raw - background
        except Exception as e:
            Messagebox.show_error(str(e), "Background Subtraction Failed")
            return
        self.redraw()
        self.app.set_status_message(f"Subtracted SNIP background from {t.label} (from raw data). Re-run Detect Peaks.")

    def run_all_calcs(self):
        t = self._require_active()
        if t is None:
            return
        if not t.peaks:
            self.detect_peaks()
            t = self.get_active()
            if not t.peaks:
                return
        wl = self._get_wavelength()
        for p in t.peaks:
            try:
                p["d_A"] = float(xrd_analysis.bragg_d_spacing(p["two_theta"], wl))
                p["size_nm"] = float(xrd_analysis.scherrer_crystallite_size(p["fwhm_deg"], p["two_theta"], wl)) if p["fwhm_deg"] > 0 else None
            except Exception:
                p["d_A"] = None
                p["size_nm"] = None
        self.on_active_trace_changed()
        self.app.set_status_message(f"Computed d-spacing/crystallite size for {len(t.peaks)} peaks "
                                     f"using {wl:.6f} A ({self.wl_var.get()}).")

    def run_williamson_hall(self):
        t = self._require_active()
        if t is None:
            return
        if not t.peaks:
            Messagebox.show_warning("Run Detect Peaks first.", "No Peaks")
            return
        try:
            wl = self._get_wavelength()
            tt = [p["two_theta"] for p in t.peaks if p["fwhm_deg"] > 0]
            fw = [p["fwhm_deg"] for p in t.peaks if p["fwhm_deg"] > 0]
            res = xrd_analysis.williamson_hall(tt, fw, wl)
            res["n_peaks"] = len(tt)
            t.metadata["wh_result"] = res
            self._show_wh_result(res)
            self.results_notebook.select(2)
        except Exception as e:
            Messagebox.show_error(str(e), "Error")

    def run_crystallinity(self):
        t = self._require_active()
        if t is None:
            return
        dlg = MultiFieldDialog(self.app.root, "% Crystallinity",
                                [("crys", "Crystalline region(s) 2theta, e.g. 18-24,26-28:", ""),
                                 ("amorph", "Amorphous region(s) 2theta, e.g. 15-18:", "")],
                                help_text="Area-under-curve method: %Xc = crystalline area / (crystalline + amorphous area).")
        if not dlg.result:
            return
        try:
            def parse_regions(s):
                regions = []
                for chunk in s.strip().split(","):
                    if not chunk.strip():
                        continue
                    a, b = chunk.strip().split("-")
                    regions.append((float(a), float(b)))
                return regions
            crys_regions = parse_regions(dlg.result["crys"])
            amorph_regions = parse_regions(dlg.result["amorph"])
            pct = xrd_analysis.percent_crystallinity(t.x, t.y, crys_regions, amorph_regions)
            t.metadata["crystallinity_pct"] = pct
            t.metadata["crystallinity_regions"] = {"crystalline": crys_regions, "amorphous": amorph_regions}
            Messagebox.show_info(f"Approximate % Crystallinity: {pct:.1f}%\n\n"
                                  f"Crystalline regions: {crys_regions}\nAmorphous regions: {amorph_regions}\n\n"
                                  f"This is method-dependent and sensitive to region choice -- report the "
                                  f"regions used alongside the number.", "% Crystallinity")
        except Exception as e:
            Messagebox.show_error(f"Could not parse input: {e}", "Error")

    def run_lattice_param(self):
        t = self._require_active()
        if t is None:
            return
        if not t.peaks:
            Messagebox.show_warning("Run Detect Peaks first.", "No Peaks")
            return
        dlg = MultiFieldDialog(self.app.root, "Cubic Lattice Parameter",
                                [("tt", "2theta (deg):", ""), ("h", "h:", "1"), ("k", "k:", "1"), ("l", "l:", "1")],
                                help_text="Only valid for cubic crystal systems.")
        if not dlg.result:
            return
        try:
            tt = parse_float(dlg.result["tt"], "2theta")
            h = parse_float(dlg.result["h"], "h")
            k = parse_float(dlg.result["k"], "k")
            l = parse_float(dlg.result["l"], "l")
            wl = self._get_wavelength()
            d = xrd_analysis.bragg_d_spacing(tt, wl)
            a = xrd_analysis.cubic_lattice_parameter(d, h, k, l)
            Messagebox.show_info(f"d-spacing = {d:.4f} A\nLattice parameter a = {a:.4f} A (cubic system assumption)",
                                  "Lattice Parameter")
        except Exception as e:
            Messagebox.show_error(str(e), "Error")

    def fit_peaks(self):
        t = self._require_active()
        if t is None:
            return
        if not t.peaks:
            Messagebox.show_warning("Run Detect Peaks first.", "No Peaks")
            return
        seed_list = [{"x": p["two_theta"]} for p in t.peaks]
        window, shape = self.fit_window_var.get(), self.fit_shape_var.get()
        x_snap, y_snap = t.x, t.y

        def compute():
            return peak_fitting.fit_peaks_batch(x_snap, y_snap, seed_list, window, shape=shape)

        def on_done(result):
            fits, errors = result
            t.fits = fits
            self.redraw()
            self.on_active_trace_changed()
            msg = f"Fit {len(fits)}/{len(seed_list)} peaks."
            if errors:
                msg += f" {len(errors)} peak(s) failed to converge."
            self.app.set_status_message(msg)

        self.run_background(compute, on_done, busy_text="Fitting peaks...")

    def match_phases(self):
        t = self._require_active()
        if t is None:
            return
        if not t.peaks:
            self.detect_peaks()
            t = self.get_active()
            if not t.peaks:
                return
        wl = self._get_wavelength()
        tol = self.d_tolerance_var.get()
        peaks_snapshot = t.peaks
        merged = xrd_analysis.merged_database(self.database)
        label_to_key = {v: k for k, v in xrd_analysis.PHASE_CATEGORY_LABELS.items()}
        selected_label = self.category_var.get()
        categories = None if selected_label == xrd_analysis.ALL_CATEGORIES_LABEL else [label_to_key[selected_label]]

        def compute():
            return xrd_analysis.match_xrd_phases(peaks_snapshot, wl, merged, d_tolerance_pct=tol, categories=categories)

        def on_done(matches):
            t.matches = matches
            self.on_active_trace_changed()
            self.results_notebook.select(1)
            scope = "all categories" if categories is None else selected_label
            self.app.set_status_message(f"{len(t.matches)} candidate phase(s) found in {scope} (tolerance {tol}%).")

        self.run_background(compute, on_done, busy_text="Matching against XRD phase database...")

    def open_database_viewer(self):
        DatabaseViewerDialog(self.app.root, self.app.ftir_db, ftir_analysis,
                              lambda: xrd_analysis.merged_database(self.database), xrd_analysis)

    def open_lattice_refinement(self):
        t = self._require_active()
        if t is None:
            return
        LatticeRefinementDialog(self.app.root, self)

    def open_unit_converter(self):
        wl = self._get_wavelength()
        dlg = MultiFieldDialog(
            self.app.root, "2theta / d-spacing / Q Converter",
            [("value", "Value:", ""), ("unit", "Unit of value (2theta / d / q):", "2theta")],
            help_text=f"Using current wavelength = {wl:.6f} A. Converts between 2theta (deg), "
                      "d-spacing (Angstrom), and Q = 4*pi*sin(theta)/lambda (A^-1).")
        if not dlg.result:
            return
        try:
            value = parse_float(dlg.result["value"], "Value")
            unit = dlg.result["unit"].strip().lower()
            result = xrd_analysis.convert_xrd_units(value, unit, wl)
        except Exception as e:
            Messagebox.show_error(str(e), "Conversion Failed")
            return
        if result["two_theta_deg"] is None:
            Messagebox.show_warning("Not reachable at this wavelength (would require sin(theta) > 1).",
                                     "Unit Converter")
            return
        msg = (f"2theta = {result['two_theta_deg']:.4f} deg\n"
               f"d-spacing = {result['d_spacing_a']:.5f} A\n"
               f"Q = {result['q_inv_a']:.5f} A^-1")
        Messagebox.show_info(msg, "Conversion Result")

    # ---------------------------------------------------------------- export

    def export_reference_peaks_csv(self):
        if self._current_match_phase is None:
            Messagebox.show_warning("Click a row in the Phase Matches table first.", "No Phase Selected")
            return
        phase = self._current_match_phase
        match = self._current_match
        ref_peaks = self._current_match_ref_peaks
        matched_by_d = {round(mm["reference"]["d_A"], 6): mm for mm in match["matches"]}
        wl = self._get_wavelength()
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                             initialfile=f"{phase['name']}_reference_peaks.csv")
        if not path:
            return
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["phase", "d_spacing_A", "two_theta_deg", "hkl", "rel_intensity",
                        "matched_in_your_pattern", "observed_d_A", "delta_d_A", "source"])
            for ref in ref_peaks:
                mm = matched_by_d.get(round(ref["d_A"], 6))
                tt = xrd_analysis.two_theta_from_d(ref["d_A"], wl)
                w.writerow([phase["name"], f"{ref['d_A']:.5f}", f"{tt:.4f}" if tt is not None else "",
                            ref.get("hkl", ""), ref.get("rel_intensity", ""),
                            "yes" if mm else "no",
                            f"{mm['observed_d_A']:.5f}" if mm else "",
                            f"{mm['delta_d_A']:+.5f}" if mm else "",
                            phase.get("source", "")])
        Messagebox.show_info(f"Saved {len(ref_peaks)} reference peak(s) for {phase['name']} to {path}", "Exported")

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
        wl = self._get_wavelength()
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["two_theta_deg", "intensity", "fwhm_deg", "d_spacing_A", "crystallite_size_nm"])
            for p in t.peaks:
                d = p.get("d_A")
                if d is None:
                    d = xrd_analysis.bragg_d_spacing(p["two_theta"], wl)
                size = p.get("size_nm")
                if size is None and p["fwhm_deg"] > 0:
                    size = xrd_analysis.scherrer_crystallite_size(p["fwhm_deg"], p["two_theta"], wl)
                w.writerow([p["two_theta"], p["intensity"], p["fwhm_deg"], f"{d:.4f}" if d else "", size if size else ""])
        Messagebox.show_info(f"Saved {len(t.peaks)} peaks to {path}", "Exported")

    def export_pdf_report(self):
        t = self._require_active()
        if t is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        tmp_png = os.path.join(tempfile.gettempdir(), "xrd_report_plot.png")
        save_figure_snapshot(self.fig, tmp_png)

        sections = []
        if t.peaks:
            rows = [["2theta (deg)", "Intensity", "FWHM (deg)", "d (A)", "Size (nm)"]]
            for p in t.peaks:
                rows.append([f"{p['two_theta']:.3f}", f"{p['intensity']:.1f}", f"{p['fwhm_deg']:.3f}",
                             f"{p['d_A']:.4f}" if p.get("d_A") else "-", f"{p['size_nm']:.2f}" if p.get("size_nm") else "-"])
            sections.append(("Detected Peaks", rows, None))
        if t.matches:
            rows = [["Phase", "Category", "System", "Score", "Matched/Total", "Source"]]
            for m in t.matches[:12]:
                rows.append([m["name"], m["category"], m.get("crystal_system", ""), f"{m['score']*100:.0f}%",
                             f"{m['matched_count']}/{m['total_reference_peaks']}", m.get("source", "")])
            sections.append(("Phase Matches (heuristic screening)", rows, None))
        wh = t.metadata.get("wh_result")
        if wh:
            size_txt = f"{wh['crystallite_size_nm']:.2f} nm" if wh["crystallite_size_nm"] else "not resolvable"
            sections.append(("Williamson-Hall Analysis", None,
                              f"Crystallite size: {size_txt}\nMicrostrain: {wh['microstrain']:.5f}"))
        if not sections:
            sections.append(("Notes", None, "No peaks were detected/analyzed on this trace."))

        disclaimer = self.database.get("_meta", {}).get("note", "")
        report_export.build_report(path, "XRD Analysis Report",
                                    f"Wavelength: {self._get_wavelength():.6f} A ({self.wl_var.get()})",
                                    tmp_png, sections, disclaimer, source_file=t.label)
        Messagebox.show_info(f"Report saved to {path}", "Exported")

    def save_session(self):
        path = filedialog.asksaveasfilename(defaultextension=".ftirxrd", filetypes=[("FTIR/XRD Session", "*.ftirxrd")])
        if not path:
            return
        state = {
            "tab": "xrd",
            "wavelength_name": self.wl_var.get(),
            "custom_wl": self.custom_wl,
            "prominence": self.prom_var.get(),
            "d_tolerance": self.d_tolerance_var.get(),
            "category": self.category_var.get(),
            "active_id": self.active_id,
            "traces": [{
                "label": t.label, "color": t.color, "visible": t.visible,
                "x": t.x, "y": t.y, "y_raw": t.y_raw, "peaks": t.peaks,
                "matches": t.matches, "fits": t.fits, "metadata": t.metadata, "id": t.id,
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
        if state.get("tab") != "xrd":
            Messagebox.show_warning("This session file was saved from the FTIR tab.", "Wrong Tab")
            return
        self.wl_var.set(state.get("wavelength_name", "Cu Ka1"))
        self.custom_wl = state.get("custom_wl")
        self.prom_var.set(state.get("prominence", 2.0))
        self.d_tolerance_var.set(state.get("d_tolerance", 1.5))
        self.category_var.set(state.get("category", xrd_analysis.ALL_CATEGORIES_LABEL))
        self.traces = []
        for td in state.get("traces", []):
            t = Trace(td["label"], td["x"], td["y"], td["color"], metadata=td.get("metadata"))
            t.y_raw = np.array(td["y_raw"], dtype=float)
            t.visible = td.get("visible", True)
            t.peaks = td.get("peaks", [])
            t.matches = td.get("matches", [])
            t.fits = td.get("fits", [])
            self.traces.append(t)
        self.active_id = state.get("active_id")
        if self.active_id not in [t.id for t in self.traces] and self.traces:
            self.active_id = self.traces[-1].id
        self._on_traces_changed()
        self.app.set_status_message(f"Loaded session {os.path.basename(path)} ({len(self.traces)} trace(s)).")


class LatticeRefinementDialog(tb.Toplevel):
    """
    Iterative multi-peak unit-cell refinement: the user indexes several
    detected peaks with (h,k,l), picks a crystal system, and the lattice
    parameter(s) are refined by nonlinear least squares across ALL of them
    at once, with automatic outlier (misindexed-peak) rejection -- see
    formula_sources.ITERATIVE_LATTICE_REFINEMENT for the method and why
    this is materially more accurate than the single-peak quick-calc.
    """
    def __init__(self, parent, xrd_tab):
        super().__init__(parent)
        self.xrd_tab = xrd_tab
        self.title("Iterative Lattice Parameter Refinement")
        self.geometry("880x680")
        self.row_widgets = []

        self._build_ui()
        self._populate_from_detected_peaks()

    def _build_ui(self):
        top = tb.Frame(self, padding=10)
        top.pack(fill="x")
        tb.Label(top, text="Crystal system:").pack(side="left")
        self.system_var = tb.StringVar(value="cubic")
        tb.Combobox(top, textvariable=self.system_var, state="readonly", width=14,
                    values=list(xrd_analysis.LATTICE_SYSTEMS.keys())).pack(side="left", padx=(4, 16))
        tb.Label(top, text="Outlier threshold (sigma):").pack(side="left")
        self.sigma_var = tb.DoubleVar(value=3.0)
        tb.Spinbox(top, from_=1.5, to=10, increment=0.5, textvariable=self.sigma_var, width=6).pack(side="left", padx=4)
        tb.Button(top, text="ⓘ", width=3, bootstyle="secondary-outline", command=self._show_formula).pack(side="left", padx=(12, 0))

        btn_row = tb.Frame(self, padding=(10, 0))
        btn_row.pack(fill="x")
        tb.Button(btn_row, text="Populate from Detected Peaks", command=self._populate_from_detected_peaks).pack(side="left", padx=(0, 4))
        tb.Button(btn_row, text="Auto-fill hkl from Top Phase Match", command=self._autofill_hkl).pack(side="left", padx=4)
        tb.Button(btn_row, text="Add Blank Row", command=lambda: self._add_row()).pack(side="left", padx=4)
        tb.Button(btn_row, text="Clear All Rows", bootstyle="danger-outline", command=self._clear_rows).pack(side="left", padx=4)

        header = tb.Frame(self, padding=(10, 10, 10, 0))
        header.pack(fill="x")
        for text, w in [("2theta (deg)", 14), ("h", 6), ("k", 6), ("l", 6), ("", 4)]:
            tb.Label(header, text=text, width=w, bootstyle="secondary").pack(side="left", padx=2)

        self.rows_scroll = ScrolledFrame(self, autohide=True, height=180)
        self.rows_scroll.pack(fill="x", padx=10, pady=(0, 6))

        tb.Button(self, text="Run Iterative Refinement", bootstyle="success",
                  command=self._run_refinement).pack(fill="x", padx=10, pady=(0, 8))

        results_frame = tb.Frame(self, padding=10)
        results_frame.pack(fill="both", expand=True)
        tb.Label(results_frame, text="Summary", bootstyle="secondary").pack(anchor="w")
        self.summary_text = tb.Text(results_frame, height=6, wrap="word")
        self.summary_text.pack(fill="x")
        self.summary_text.insert("1.0", "Enter/populate peaks with their (h,k,l) indices above, then click "
                                         "'Run Iterative Refinement'.")
        self.summary_text.configure(state="disabled")

        tb.Label(results_frame, text="Per-Peak Residuals", bootstyle="secondary").pack(anchor="w", pady=(8, 0))
        self.results_table = DataTable(results_frame,
                                        [("hkl", "hkl"), ("obs", "2theta obs"), ("calc", "2theta calc"),
                                         ("delta", "Delta (deg)"), ("used", "Used")],
                                        height=9, widths={"hkl": 70, "obs": 100, "calc": 100, "delta": 100, "used": 60})
        self.results_table.pack(fill="both", expand=True, pady=(4, 0))

    # ---- row management ----

    def _add_row(self, two_theta="", h="", k="", l=""):
        row_frame = tb.Frame(self.rows_scroll)
        row_frame.pack(fill="x", pady=1)
        tt_var = tb.StringVar(value=str(two_theta))
        h_var = tb.StringVar(value=str(h))
        k_var = tb.StringVar(value=str(k))
        l_var = tb.StringVar(value=str(l))
        tb.Entry(row_frame, textvariable=tt_var, width=14).pack(side="left", padx=2)
        tb.Entry(row_frame, textvariable=h_var, width=6).pack(side="left", padx=2)
        tb.Entry(row_frame, textvariable=k_var, width=6).pack(side="left", padx=2)
        tb.Entry(row_frame, textvariable=l_var, width=6).pack(side="left", padx=2)
        row_record = {"frame": row_frame, "two_theta": tt_var, "h": h_var, "k": k_var, "l": l_var}
        tb.Button(row_frame, text="×", width=3, bootstyle="danger-outline",
                  command=lambda: self._remove_row(row_record)).pack(side="left", padx=2)
        self.row_widgets.append(row_record)

    def _remove_row(self, row_record):
        row_record["frame"].destroy()
        self.row_widgets.remove(row_record)

    def _clear_rows(self):
        for r in list(self.row_widgets):
            self._remove_row(r)

    def _populate_from_detected_peaks(self):
        t = self.xrd_tab.get_active()
        if t is None or not t.peaks:
            return
        self._clear_rows()
        for p in t.peaks:
            self._add_row(two_theta=f"{p['two_theta']:.3f}")

    def _autofill_hkl(self):
        t = self.xrd_tab.get_active()
        if t is None or not t.matches:
            Messagebox.show_warning("Run 'Match to Phase Database' on this trace first (Section 4), "
                                     "then reopen this dialog.", "No Phase Match")
            return
        top_match = t.matches[0]
        wl = self.xrd_tab._get_wavelength()
        filled = 0
        for row in self.row_widgets:
            try:
                tt = float(row["two_theta"].get())
            except ValueError:
                continue
            d_obs = xrd_analysis.bragg_d_spacing(tt, wl)
            candidates = top_match["matches"]
            if not candidates:
                continue
            best = min(candidates, key=lambda m: abs(m["reference"]["d_A"] - d_obs))
            if abs(best["reference"]["d_A"] - d_obs) / best["reference"]["d_A"] > 0.03:
                continue
            try:
                hkl = xrd_analysis.parse_hkl(best["reference"].get("hkl", ""))
            except ValueError:
                hkl = None
            if hkl is None or len(hkl) != 3:
                continue
            row["h"].set(str(hkl[0]))
            row["k"].set(str(hkl[1]))
            row["l"].set(str(hkl[2]))
            filled += 1
        Messagebox.show_info(f"Filled hkl for {filled} row(s) from '{top_match['name']}'. "
                              f"Double-check these before refining -- auto-fill matches by nearest "
                              f"d-spacing and can be wrong for closely-spaced or weak reflections.",
                              "Auto-fill Complete")

    def _show_formula(self):
        fs.show_formula_dialog(self, "Iterative Lattice Refinement Method", fs.ITERATIVE_LATTICE_REFINEMENT)

    # ---- refinement ----

    def _run_refinement(self):
        peaks = []
        for row in self.row_widgets:
            tt_s = row["two_theta"].get().strip()
            h_s, k_s, l_s = row["h"].get().strip(), row["k"].get().strip(), row["l"].get().strip()
            if not (tt_s and h_s and k_s and l_s):
                continue
            try:
                peaks.append({"two_theta": float(tt_s), "h": int(h_s), "k": int(k_s), "l": int(l_s)})
            except ValueError:
                Messagebox.show_error(f"Could not parse row: 2theta={tt_s!r} h={h_s!r} k={k_s!r} l={l_s!r}", "Invalid Row")
                return
        if len(peaks) < 2:
            Messagebox.show_warning("Enter 2theta and h,k,l for enough peaks (more than the number of lattice "
                                     "parameters being refined) -- blank rows are ignored.", "Not Enough Peaks")
            return
        wl = self.xrd_tab._get_wavelength()
        system = self.system_var.get()
        sigma = self.sigma_var.get()
        try:
            res = xrd_analysis.refine_lattice_parameters(peaks, wl, crystal_system=system, outlier_sigma=sigma)
        except Exception as e:
            Messagebox.show_error(str(e), "Refinement Failed")
            return
        self._show_results(res)

    def _show_results(self, res):
        lines = [f"Crystal system: {res['crystal_system']}"]
        for name, val in res["params"].items():
            err = res["param_errors"].get(name, float("nan"))
            lines.append(f"  {name} = {val:.5f} +/- {err:.5f} A")
        lines.append(f"R-squared: {res['r_squared']:.6f}    Reduced chi-square: {res['reduced_chi_square']:.3e}")
        lines.append(f"Peaks used: {res['n_peaks_used']}    Excluded as outliers: {res['n_peaks_excluded']}    "
                      f"Refinement rounds: {res['rounds']}")
        if not res["converged"]:
            lines.append("WARNING: the fit did not fully converge -- treat these results with caution.")
        self.summary_text.configure(state="normal")
        self.summary_text.delete("1.0", "end")
        self.summary_text.insert("1.0", "\n".join(lines))
        self.summary_text.configure(state="disabled")

        def fmt(p):
            calc = f"{p['two_theta_calc']:.3f}" if p["two_theta_calc"] is not None else "-"
            delta = f"{p['delta_two_theta']:+.3f}" if p["delta_two_theta"] is not None else "-"
            return (f"{p['h']}{p['k']}{p['l']}", f"{p['two_theta_obs']:.3f}", calc, delta, "Yes" if p["used"] else "No")

        self.results_table.set_rows(res["per_peak"], fmt)
