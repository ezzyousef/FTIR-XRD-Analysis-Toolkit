"""
xrd_tab.py
The XRD page: load diffraction patterns (multi-trace overlay), detect peaks, compute
d-spacing / Scherrer size, Williamson-Hall, % crystallinity and a single-peak cubic lattice
parameter, fit peaks, and export CSV / PDF / Origin / Excel / sessions.
Phase identification against reference cards is deliberately out of scope.
"""
import csv
import os
import tempfile

from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLabel, QPlainTextEdit

import file_readers
import formula_sources as fs
import peak_fitting
import report_export
import ui_common
import xrd_analysis
from ui_common import AnalysisTabBase, DataTable, parse_float

CUSTOM_WAVELENGTH = "Custom..."
WH_PLACEHOLDER = ("Detect peaks (3 or more with a resolvable FWHM), then run "
                  "Williamson–Hall (size + strain).")


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
        self._build_controls()
        self._build_results_tabs()
        self._on_traces_changed()

    # ---------------------------------------------------------------- controls
    def _build_controls(self):
        card = self.add_card("Wavelength & peak detection")
        self.wl_combo = QComboBox()
        self.wl_combo.addItems(list(xrd_analysis.WAVELENGTHS.keys()) + [CUSTOM_WAVELENGTH])
        self.wl_combo.currentTextChanged.connect(self._wavelength_changed)
        card.body.addWidget(self.labelled("X-ray wavelength", self.wl_combo))
        self.wl_label = QLabel()
        self.wl_label.setObjectName("Hint")
        card.body.addWidget(self.wl_label)
        self.prom_spin = QDoubleSpinBox()
        self.prom_spin.setRange(0.2, 20.0)
        self.prom_spin.setSingleStep(0.2)
        self.prom_spin.setValue(2.0)
        self.prom_spin.setSuffix(" %")
        card.body.addWidget(self.labelled("Peak sensitivity (prominence)", self.prom_spin))
        card.body.addWidget(self.action_button("Detect peaks", self.detect_peaks, primary=True))
        card.body.addWidget(self.action_button("Smooth (Savitzky–Golay)…", self.smooth_active))
        card.body.addWidget(self.action_button("Subtract background (SNIP)", self.subtract_background_active,
                                               info=("XRD background subtraction (SNIP)", fs.XRD_BACKGROUND_SUBTRACTION)))

        card = self.add_card("Calculations")
        card.body.addWidget(self.action_button("d-spacing + Scherrer size (all peaks)", self.run_all_calcs, primary=True,
                                               info=("Bragg's law & Scherrer equation",
                                                     fs.BRAGG_LAW + "\n\n" + fs.SCHERRER_EQUATION)))
        card.body.addWidget(self.action_button("Williamson–Hall (size + strain)", self.run_williamson_hall,
                                               info=("Williamson–Hall method", fs.WILLIAMSON_HALL)))
        card.body.addWidget(self.action_button("% crystallinity (select regions)…", self.run_crystallinity,
                                               info=("% crystallinity method", fs.PERCENT_CRYSTALLINITY)))
        card.body.addWidget(self.action_button("Cubic lattice parameter (single peak)…", self.run_lattice_param,
                                               info=("Cubic lattice parameter", fs.CUBIC_LATTICE_PARAMETER)))
        card.body.addWidget(self.action_button("2θ / d-spacing / Q converter…", self.open_unit_converter,
                                               info=("XRD unit converter", fs.XRD_UNIT_CONVERTER)))

        card = self.add_card("Peak fitting")
        self.shape_combo = QComboBox()
        self.shape_combo.addItems(["gaussian", "lorentzian", "pseudo_voigt"])
        card.body.addWidget(self.labelled("Peak shape", self.shape_combo))
        self.window_spin = QDoubleSpinBox()
        self.window_spin.setRange(0.05, 5.0)
        self.window_spin.setSingleStep(0.05)
        self.window_spin.setValue(0.5)
        self.window_spin.setSuffix(" °")
        card.body.addWidget(self.labelled("Fit window (± 2θ)", self.window_spin))
        card.body.addWidget(self.action_button("Fit all detected peaks", self.fit_peaks,
                                               info=("Peak fitting method", fs.PEAK_FITTING)))

        card = self.add_card("Files & session", "Origin, Excel and figures: the buttons under the plot.")
        for text, fn in (("Export peak list (CSV)…", self.export_peaks_csv),
                         ("Export PDF report…", self.export_pdf_report),
                         ("Export for OriginLab (CSV)…", self.export_originlab_dialog),
                         ("Export graph (SVG/EPS/PDF/PNG)…", self.export_graph_dialog),
                         ("Save session…", self.save_session),
                         ("Load session…", self.load_session)):
            card.body.addWidget(self.action_button(text, fn))
        self._update_wavelength_label()

    def _build_results_tabs(self):
        self.peaks_table = DataTable(["2θ (°)", "Intensity", "FWHM (°)", "d-spacing (Å)", "Crystallite size (nm)"])
        self.results_tabs.addTab(self.peaks_table, "Peaks")
        self.wh_text = QPlainTextEdit()
        self.wh_text.setReadOnly(True)
        self.wh_text.setPlainText(WH_PLACEHOLDER)
        self.results_tabs.addTab(self.wh_text, "Williamson–Hall")
        self.fits_table = DataTable(["Seed 2θ", "Fitted centre", "FWHM (°)", "Height", "Area", "R²"])
        self.results_tabs.addTab(self.fits_table, "Peak fits")

    # ---------------------------------------------------------------- wavelength
    def _wavelength_changed(self, name):
        if name == CUSTOM_WAVELENGTH:
            self._prompt_custom_wavelength()
        self._update_wavelength_label()

    def _prompt_custom_wavelength(self):
        v = ui_common.ask_fields(self, "Custom wavelength", [("wl", "Wavelength (Å):", f"{self.custom_wl or 1.540562}")])
        if v is None:
            return
        try:
            value = parse_float(v["wl"], "Wavelength")
            if value <= 0:
                raise ValueError("The wavelength must be positive.")
            self.custom_wl = value
        except ValueError as exc:
            ui_common.show_message(self, "Invalid wavelength", str(exc), "error")

    def _update_wavelength_label(self):
        self.wl_label.setText(f"λ = {self.get_wavelength():.6f} Å")

    def get_wavelength(self):
        name = self.wl_combo.currentText()
        if name == CUSTOM_WAVELENGTH:
            return self.custom_wl or xrd_analysis.WAVELENGTHS["Cu Ka1"]
        return xrd_analysis.WAVELENGTHS[name]

    # ---------------------------------------------------------------- state
    def export_options(self):
        return {"wavelength": self.get_wavelength()}

    def session_settings(self):
        return {"wavelength_name": self.wl_combo.currentText(), "custom_wl": self.custom_wl,
                "prominence": self.prom_spin.value()}

    def apply_session_settings(self, state):
        self.custom_wl = state.get("custom_wl")
        self.wl_combo.blockSignals(True)
        index = self.wl_combo.findText(state.get("wavelength_name", "Cu Ka1"))
        self.wl_combo.setCurrentIndex(max(0, index))
        self.wl_combo.blockSignals(False)
        self.prom_spin.setValue(float(state.get("prominence", 2.0)))
        self._update_wavelength_label()

    # ---------------------------------------------------------------- plotting
    def _plot_active_extras(self, ax, trace, theme):
        for p in trace.peaks:
            ax.axvline(p["two_theta"], color="#E03131", alpha=0.35, lw=0.9, zorder=0)

    # ---------------------------------------------------------------- results refresh
    def on_active_trace_changed(self):
        t = self.get_active()
        if t is None:
            self.peaks_table.clear_rows()
            self.fits_table.clear_rows()
            self.wh_text.setPlainText(WH_PLACEHOLDER)
            return
        self.peaks_table.set_rows(t.peaks, self._format_peak_row)
        self.fits_table.set_rows(t.fits, lambda f: (
            f"{f['seed_x']:.3f}", f"{f['center']:.3f}", f"{f['fwhm']:.3f}", f"{f['height']:.2f}",
            f"{f['area']:.3f}", f"{f['r_squared']:.4f}"))
        self._show_wh_result(t.metadata.get("wh_result"))

    @staticmethod
    def _format_peak_row(p):
        d = f"{p['d_A']:.4f}" if p.get("d_A") else "–"
        size = f"{p['size_nm']:.2f}" if p.get("size_nm") else "–"
        return (f"{p['two_theta']:.3f}", f"{p['intensity']:.1f}", f"{p['fwhm_deg']:.3f}", d, size)

    def _show_wh_result(self, wh):
        if not wh:
            self.wh_text.setPlainText(WH_PLACEHOLDER)
            return
        size_txt = (f"{wh['crystallite_size_nm']:.2f} nm" if wh["crystallite_size_nm"]
                    else "not resolvable (non-physical intercept)")
        strain_note = ("\n\nNote: the strain came out NEGATIVE. Strain broadening can only add width to a peak, so a "
                       "negative microstrain has no direct physical meaning — the data shows no strain contribution "
                       "resolvable above noise (and/or uncorrected instrumental broadening). Treat it as strain ≈ 0."
                       if not wh.get("strain_physical", True) else "")
        self.wh_text.setPlainText(
            f"Williamson–Hall analysis ({wh['n_peaks']} peaks):\n\n"
            f"  Crystallite size: {size_txt}\n"
            f"  Microstrain: {wh['microstrain']:.5f}\n"
            f"  Linear fit: slope = {wh['slope']:.5f}, intercept = {wh['intercept']:.5f}\n\n"
            f"Separates size and strain broadening across peaks; not corrected for instrumental broadening.{strain_note}")

    # ---------------------------------------------------------------- actions
    def detect_peaks(self, record=True):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        t.peaks = xrd_analysis.detect_xrd_peaks(t.x, t.y, prominence_frac=self.prom_spin.value() / 100.0)
        t.fits = []
        t.metadata.pop("wh_result", None)
        self.redraw()
        self.on_active_trace_changed()
        self.results_tabs.setCurrentIndex(0)
        msg = f"Detected {len(t.peaks)} peaks in {t.label}"
        if len(t.peaks) > 100:
            msg += " — that's a lot; raise the sensitivity for cleaner results"
        self.app.notify(msg, "success" if t.peaks else "warning")
        if record:
            self.record("detect peaks")

    def smooth_active(self):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        v = ui_common.ask_fields(self, "Smooth pattern", [("wl", "Window length (odd, points):", "11"),
                                                          ("po", "Polynomial order:", "3")])
        if v is None:
            return
        try:
            t.y = xrd_analysis.smooth_pattern(t.y, window_length=int(float(v["wl"])), polyorder=int(float(v["po"])))
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "Smoothing failed", str(exc), "error")
            return
        t.peaks, t.fits = [], []
        self._after_processing(f"Smoothed {t.label} (window {v['wl']}, order {v['po']}) — detect peaks again", "smooth")

    def subtract_background_active(self):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        try:
            t.y = t.y_raw - xrd_analysis.snip_background(t.y_raw)
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "Background subtraction failed", str(exc), "error")
            return
        t.peaks, t.fits = [], []
        self._after_processing(f"SNIP background subtracted from {t.label} (from raw data) — detect peaks again",
                               "subtract background")

    def _after_processing(self, message, label):
        self.get_active().metadata.pop("wh_result", None)
        self.redraw()
        self.on_active_trace_changed()
        self.app.notify(message, "success")
        self.record(label)

    def run_all_calcs(self):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        if not t.peaks:
            self.detect_peaks(record=False)
            if not t.peaks:
                return
        wl = self.get_wavelength()
        for p in t.peaks:
            try:
                p["d_A"] = float(xrd_analysis.bragg_d_spacing(p["two_theta"], wl))
                p["size_nm"] = (float(xrd_analysis.scherrer_crystallite_size(p["fwhm_deg"], p["two_theta"], wl))
                                if p["fwhm_deg"] > 0 else None)
            except Exception:  # noqa: BLE001 - one unreachable peak must not stop the rest
                p["d_A"], p["size_nm"] = None, None
        self.on_active_trace_changed()
        self.results_tabs.setCurrentIndex(0)
        self.app.notify(f"d-spacing and crystallite size for {len(t.peaks)} peaks (λ = {wl:.6f} Å)", "success")
        self.record("d-spacing + Scherrer")

    def run_williamson_hall(self):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        if not t.peaks:
            self.app.notify("Detect peaks first.", "warning")
            return
        try:
            wl = self.get_wavelength()
            usable = [p for p in t.peaks if p["fwhm_deg"] > 0]
            res = xrd_analysis.williamson_hall([p["two_theta"] for p in usable], [p["fwhm_deg"] for p in usable], wl)
            res["n_peaks"] = len(usable)
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "Williamson–Hall failed", str(exc), "error")
            return
        t.metadata["wh_result"] = res
        self._show_wh_result(res)
        self.results_tabs.setCurrentIndex(1)
        self.app.notify("Williamson–Hall analysis done", "success")
        self.record("Williamson–Hall")

    def run_crystallinity(self):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        v = ui_common.ask_fields(self, "% crystallinity",
                                 [("crys", "Crystalline region(s) 2θ, e.g. 18-24,26-28:", ""),
                                  ("amorph", "Amorphous region(s) 2θ, e.g. 15-18:", "")],
                                 help_text="Area-under-curve method: %Xc = crystalline area / (crystalline + amorphous area).")
        if v is None:
            return

        def parse_regions(text):
            regions = []
            for chunk in text.strip().split(","):
                if chunk.strip():
                    a, b = chunk.strip().split("-")
                    regions.append((float(a), float(b)))
            return regions

        try:
            crys, amorph = parse_regions(v["crys"]), parse_regions(v["amorph"])
            pct = xrd_analysis.percent_crystallinity(t.x, t.y, crys, amorph)
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "% crystallinity failed", f"Could not use those regions: {exc}", "error")
            return
        t.metadata["crystallinity_pct"] = pct
        t.metadata["crystallinity_regions"] = {"crystalline": crys, "amorphous": amorph}
        self.record("% crystallinity")
        ui_common.show_message(self, "% crystallinity",
                               f"Approximate crystallinity: {pct:.1f}%\n\nCrystalline regions: {crys}\n"
                               f"Amorphous regions: {amorph}\n\nThis is method-dependent and sensitive to the regions "
                               "chosen — report them alongside the number.")

    def run_lattice_param(self):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        default = f"{t.peaks[0]['two_theta']:.3f}" if t.peaks else ""
        v = ui_common.ask_fields(self, "Cubic lattice parameter",
                                 [("tt", "2θ (°):", default), ("h", "h:", "1"), ("k", "k:", "1"), ("l", "l:", "1")],
                                 help_text="Only valid for cubic crystal systems.")
        if v is None:
            return
        try:
            wl = self.get_wavelength()
            d = xrd_analysis.bragg_d_spacing(parse_float(v["tt"], "2θ"), wl)
            a = xrd_analysis.cubic_lattice_parameter(d, parse_float(v["h"], "h"), parse_float(v["k"], "k"),
                                                     parse_float(v["l"], "l"))
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "Lattice parameter failed", str(exc), "error")
            return
        ui_common.show_message(self, "Lattice parameter",
                               f"d-spacing = {d:.4f} Å\nLattice parameter a = {a:.4f} Å (cubic system assumed)")

    def fit_peaks(self):
        t = self.require_active("Load an XRD pattern first.")
        if t is None:
            return
        if not t.peaks:
            self.app.notify("Detect peaks first.", "warning")
            return
        seeds = [{"x": p["two_theta"]} for p in t.peaks]
        window, shape = self.window_spin.value(), self.shape_combo.currentText()
        x_snap, y_snap = t.x.copy(), t.y.copy()

        def compute():
            return peak_fitting.fit_peaks_batch(x_snap, y_snap, seeds, window, shape=shape)

        def on_done(result):
            fits, errors = result
            t.fits = fits
            self.redraw()
            self.on_active_trace_changed()
            self.results_tabs.setCurrentIndex(2)
            msg = f"Fitted {len(fits)}/{len(seeds)} peaks"
            if errors:
                msg += f"; {len(errors)} did not converge"
            self.app.notify(msg, "success" if not errors else "warning")
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
            result = xrd_analysis.convert_xrd_units(parse_float(v["value"], "Value"), v["unit"], wl)
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "Conversion failed", str(exc), "error")
            return
        if result["two_theta_deg"] is None:
            ui_common.show_message(self, "Unit converter", "Not reachable at this wavelength (it would need sin θ > 1).",
                                   "warning")
            return
        ui_common.show_message(self, "Conversion result",
                               f"2θ = {result['two_theta_deg']:.4f}°\nd-spacing = {result['d_spacing_a']:.5f} Å\n"
                               f"Q = {result['q_inv_a']:.5f} Å⁻¹")

    # ---------------------------------------------------------------- export
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
        wl = self.get_wavelength()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["two_theta_deg", "intensity", "fwhm_deg", "d_spacing_A", "crystallite_size_nm"])
            for p in t.peaks:
                d = p.get("d_A") or xrd_analysis.bragg_d_spacing(p["two_theta"], wl)
                size = p.get("size_nm")
                if size is None and p["fwhm_deg"] > 0:
                    size = xrd_analysis.scherrer_crystallite_size(p["fwhm_deg"], p["two_theta"], wl)
                w.writerow([p["two_theta"], p["intensity"], p["fwhm_deg"], f"{d:.4f}" if d else "", size if size else ""])
        self.app.notify(f"Saved {len(t.peaks)} peaks", "success")

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
        if t.peaks:
            rows = [["2theta (deg)", "Intensity", "FWHM (deg)", "d (A)", "Size (nm)"]]
            rows += [[f"{p['two_theta']:.3f}", f"{p['intensity']:.1f}", f"{p['fwhm_deg']:.3f}",
                      f"{p['d_A']:.4f}" if p.get("d_A") else "-", f"{p['size_nm']:.2f}" if p.get("size_nm") else "-"]
                     for p in t.peaks]
            sections.append(("Detected Peaks", rows, None))
        wh = t.metadata.get("wh_result")
        if wh:
            size_txt = f"{wh['crystallite_size_nm']:.2f} nm" if wh["crystallite_size_nm"] else "not resolvable"
            sections.append(("Williamson-Hall Analysis", None,
                             f"Crystallite size: {size_txt}\nMicrostrain: {wh['microstrain']:.5f}"))
        if t.metadata.get("crystallinity_pct") is not None:
            sections.append(("% Crystallinity", None, f"{t.metadata['crystallinity_pct']:.1f}% "
                                                     f"(regions {t.metadata.get('crystallinity_regions')})"))
        if not sections:
            sections.append(("Notes", None, "No peaks were detected or analysed on this trace."))
        disclaimer = ("Peak positions, d-spacings and crystallite sizes are computed from the measured pattern. "
                      "Scherrer and Williamson-Hall sizes are not corrected for instrumental broadening.")
        try:
            report_export.build_report(path, "XRD Analysis Report",
                                       f"Wavelength: {self.get_wavelength():.6f} A ({self.wl_combo.currentText()})",
                                       tmp_png, sections, disclaimer, source_file=t.label)
        except PermissionError:
            ui_common.show_message(self, "Export failed", "That PDF is open in another program — close it and try again.", "error")
            return None
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "Export failed", str(exc), "error")
            return None
        self.app.notify(f"Report saved to {os.path.basename(path)}", "success")
        return path
