"""
ftir_tab.py
The FTIR page: load spectra (multi-trace overlay), detect peaks, smooth/baseline-correct/
normalize, screen against the reference database, fit peaks, run calculations, and export
CSV / PDF / Origin / Excel / sessions.
"""
import csv
import os
import tempfile

import numpy as np
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QRadioButton, QSplitter, QVBoxLayout,
                               QWidget)
from PySide6.QtCore import Qt

import file_readers
import formula_sources as fs
import ftir_analysis
import ftir_matching
import peak_fitting
import report_export
import ui_common
from labkit.qt.theme import colours
from ui_common import AnalysisTabBase, DataTable, parse_float

# Tier -> (theme foreground token, background token) for the confidence cell. The tier is
# also written in the cell, so colour is never the only signal.
TIER_TOKENS = {"High": ("good", "good_bg"), "Medium": ("warn", "warn_bg"), "Low": (None, None),
               "Weak": ("muted", None)}
BAND_COLOURS = {"matched": "#2B8A3E", "edge": "#F59F00", "missing": "#E03131"}
BAND_MARKS = {"matched": "✓", "edge": "≈", "missing": "✗"}


def format_probability(p):
    if p is None:
        return "—"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def is_weighted(match):
    return match.get("method") == ftir_matching.METHOD_WEIGHTED and "confidence" in match


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
        self._shown_matches = []
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
        self.method_combo = QComboBox()
        for key, label in ftir_matching.METHOD_LABELS.items():
            self.method_combo.addItem(label, key)
        self.method_combo.setToolTip("Weighted evidence uses band intensities, position accuracy, how much of "
                                     "your spectrum a material explains, and the chance of a coincidental "
                                     "match. Coverage is the original fraction-of-bands score.")
        card.body.addWidget(self.labelled("Scoring", self.method_combo))
        self.min_conf_spin = QDoubleSpinBox()
        self.min_conf_spin.setRange(0.0, 95.0)
        self.min_conf_spin.setSingleStep(5.0)
        self.min_conf_spin.setDecimals(0)
        self.min_conf_spin.setValue(float(self.app.cfg.get("ftir_min_confidence_pct", 5.0)))
        self.min_conf_spin.setSuffix(" %")
        self.min_conf_spin.setToolTip("Hide candidates scoring below this. Nothing is recomputed — "
                                      "change it at any time.")
        self.min_conf_spin.valueChanged.connect(lambda _v: self._refresh_matches_table())
        card.body.addWidget(self.labelled("Hide matches below", self.min_conf_spin))
        self.category_combo = QComboBox()
        self.category_combo.addItems([ftir_analysis.ALL_CATEGORIES_LABEL] +
                                     [ftir_analysis.CATEGORY_LABELS[k] for k in ftir_analysis.MATERIAL_CATEGORIES])
        card.body.addWidget(QLabel("Restrict search to a category (more accurate if known):"))
        card.body.addWidget(self.category_combo)
        card.body.addWidget(self.action_button(f"Match to database ({total} materials)", self.match_database,
                                               primary=True, info=("FTIR database matching method",
                                                                   fs.FTIR_DATABASE_MATCHING)))
        card.body.addWidget(self.action_button("Analyse as mixture (up to 3 components)", self.analyse_mixture,
                                               info=("FTIR database matching method",
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
        self.match_filter = QLineEdit()
        self.match_filter.setPlaceholderText("Filter materials…")
        self.match_filter.setClearButtonEnabled(True)
        self.match_filter.setMaximumWidth(220)
        self.match_filter.textChanged.connect(lambda _t: self._refresh_matches_table())
        bar.addWidget(self.match_filter)
        self.match_summary = QLabel("Click a row to overlay its reference bands on the plot.")
        self.match_summary.setObjectName("Hint")
        bar.addWidget(self.match_summary, 1)
        export_refs = QPushButton("Export reference peaks (CSV)…")
        export_refs.clicked.connect(lambda _c=False: self.export_reference_peaks_csv())
        clear = QPushButton("Clear overlay")
        clear.clicked.connect(lambda _c=False: self.clear_reference_overlay())
        bar.addWidget(export_refs)
        bar.addWidget(clear)
        ml.addLayout(bar)
        self.matches_table = DataTable(["#", "Material", "Confidence", "Bands found", "Sample explained",
                                        "Chance p", "Missing strong bands", "Category"])
        self.matches_table.on_select = self._show_match_detail
        self.match_detail = QPlainTextEdit()
        self.match_detail.setReadOnly(True)
        self.match_detail.setObjectName("Mono")
        self.match_detail.setPlaceholderText("Select a candidate to see the evidence band by band.")
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.matches_table)
        split.addWidget(self.match_detail)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setChildrenCollapsible(False)
        ml.addWidget(split, 1)
        self.matches_page = matches
        self.results_tabs.addTab(matches, "Database matches")

        mixture = QWidget()
        xl = QVBoxLayout(mixture)
        xl.setContentsMargins(6, 8, 6, 6)
        self.mixture_summary = QLabel("Analyse as mixture to look for up to three components.")
        self.mixture_summary.setObjectName("Hint")
        self.mixture_summary.setWordWrap(True)
        xl.addWidget(self.mixture_summary)
        self.mixture_table = DataTable(["Component", "Confidence", "Peaks explained", "Share of sample",
                                        "Missing strong bands", "Category"])
        self.mixture_table.on_select = self._show_match_detail
        xl.addWidget(self.mixture_table, 2)
        self.unexplained_label = QLabel("")
        self.unexplained_label.setObjectName("Hint")
        self.unexplained_label.setWordWrap(True)
        xl.addWidget(self.unexplained_label)
        self.mixture_page = mixture
        self.results_tabs.addTab(mixture, "Mixture")

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
                "category": self.category_combo.currentText(), "match_method": self.match_method(),
                "min_confidence_pct": self.min_conf_spin.value()}

    def apply_session_settings(self, state):
        (self.rb_transmittance if state.get("mode") == "transmittance" else self.rb_absorbance).setChecked(True)
        self.prom_spin.setValue(float(state.get("prominence", 2.0)))
        self.tolerance_spin.setValue(float(state.get("tolerance", 10.0)))
        index = self.category_combo.findText(state.get("category", ftir_analysis.ALL_CATEGORIES_LABEL))
        self.category_combo.setCurrentIndex(max(0, index))
        method_index = self.method_combo.findData(state.get("match_method", ftir_matching.METHOD_WEIGHTED))
        self.method_combo.setCurrentIndex(max(0, method_index))
        self.min_conf_spin.setValue(float(state.get("min_confidence_pct", 5.0)))

    def match_method(self):
        return self.method_combo.currentData() or ftir_matching.METHOD_WEIGHTED

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
        overlay = self.reference_overlay
        label = overlay.get("label", "Reference")
        status_by_range = {tuple(b["reference"]["range"]): b["status"] for b in overlay.get("bands", [])}
        for p in overlay.get("peaks", []):
            lo, hi = p["range"]
            if lo == 0 and hi == 0:
                continue                            # IR-inactive placeholder (e.g. NaCl)
            status = status_by_range.get(tuple(p["range"]))
            centre = (lo + hi) / 2
            if status is None:                      # legacy overlay: no per-band status
                ax.axvspan(lo, hi, color="#F59F00", alpha=0.20, lw=0, zorder=0)
                ax.axvline(centre, color="#F59F00", alpha=0.6, lw=0.8, linestyle=":")
                continue
            colour = BAND_COLOURS[status]
            if status == "missing":
                weight, _broad = ftir_matching.parse_intensity(p.get("intensity"))
                strong = weight >= ftir_matching.STRONG_WEIGHT
                ax.axvline(centre, color=colour, alpha=0.75 if strong else 0.45, lw=1.6 if strong else 0.9,
                           linestyle="--", zorder=0)
            else:
                ax.axvspan(lo, hi, color=colour, alpha=0.22, lw=0, zorder=0)
                ax.axvline(centre, color=colour, alpha=0.7, lw=0.8, linestyle="-" if status == "matched" else ":")
        synthetic = overlay.get("synthetic")
        active = self.get_active()
        if synthetic is not None and active is not None and len(active.y):
            sx, sy = synthetic
            top = float(np.max(sy)) if len(sy) else 0.0
            if top > 0:
                y_lo, y_hi = float(np.min(active.y)), float(np.max(active.y))
                scaled = sy / top * (y_hi - y_lo) * 0.9
                curve = (y_hi - scaled) if self.mode() == "transmittance" else (y_lo + scaled)
                ax.plot(sx, curve, color="#D9480F", alpha=0.45, lw=1.0, linestyle=(0, (4, 2)), zorder=1)
        tier = overlay.get("tier")
        suffix = f"  ·  {tier} confidence" if tier else ""
        legend = "   (✓ shaded green = found, ≈ amber = edge, ✗ red dashed = missing)" if status_by_range else ""
        # In the title row, where it cannot collide with the legend or the data.
        ax.set_title(f"Reference bands: {label}{suffix}{legend}", loc="left", fontsize=9, color="#D9480F")

    # ---------------------------------------------------------------- results refresh
    def on_theme_changed(self, theme):
        super().on_theme_changed(theme)
        self._refresh_matches_table()
        self._refresh_mixture()

    def on_active_trace_changed(self):
        if self.reference_overlay is not None and self._current_match_trace != self.active_id:
            self.reference_overlay = None
            self.redraw()
        t = self.get_active()
        if t is None:
            for table in (self.peaks_table, self.matches_table, self.fg_table, self.fits_table, self.mixture_table):
                table.clear_rows()
            self.match_detail.clear()
            self._refresh_mixture()
            return
        self.peaks_table.set_rows(list(enumerate(t.peaks, 1)), lambda ip: (
            ip[0], f"{ip[1]['x']:.1f}", f"{ip[1]['y']:.4f}", f"{ip[1]['prominence']:.4f}"))
        self._refresh_matches_table()
        self._refresh_mixture()
        self.fg_table.set_rows(t.fg_hits, lambda h: (
            f"{h['peak_x']:.1f}", h["group"], f"{h['range'][0]}–{h['range'][1]}", h.get("source", "")))
        self.fits_table.set_rows(t.fits, lambda f: (
            f"{f['seed_x']:.1f}", f"{f['center']:.1f}", f"{f['fwhm']:.2f}", f"{f['height']:.4f}",
            f"{f['area']:.3f}", f"{f['r_squared']:.4f}"))
        if not t.matches:
            self.match_detail.clear()

    def visible_matches(self, trace=None):
        """The active trace's matches after the confidence threshold and the name filter."""
        t = trace or self.get_active()
        if t is None:
            return []
        threshold = self.min_conf_spin.value() / 100.0
        needle = self.match_filter.text().strip().lower()
        shown = []
        for m in t.matches:
            if is_weighted(m) and m["confidence"] < threshold:
                continue
            if needle and needle not in m["name"].lower():
                continue
            shown.append(m)
        return shown

    def _tint(self, table, row, column, tier):
        fg_token, bg_token = TIER_TOKENS.get(tier, (None, None))
        item = table.item(row, column)
        if item is None:
            return
        c = colours(self.theme)
        if fg_token:
            item.setForeground(QBrush(QColor(c[fg_token])))
        if bg_token:
            item.setBackground(QBrush(QColor(c[bg_token])))
        if tier in ("High", "Medium"):
            font = item.font()
            font.setBold(True)
            item.setFont(font)

    @staticmethod
    def _missing_text(match):
        missing = match.get("missing_strong") or []
        return ", ".join(f"{(r['range'][0] + r['range'][1]) / 2:.0f}" for r in missing) or "—"

    def _refresh_matches_table(self):
        t = self.get_active()
        shown = self.visible_matches(t)
        self._shown_matches = shown
        rank = {id(m): i for i, m in enumerate(t.matches, 1)} if t else {}

        def row(m):
            if is_weighted(m):
                return (rank.get(id(m), ""), m["name"], f"{m['tier']} · {m['confidence'] * 100:.0f}%",
                        f"{m['matched_count']}/{m['total_reference_peaks']}  ({m['forward_score'] * 100:.0f}% wt.)",
                        f"{m['reverse_score'] * 100:.0f}%",
                        format_probability(m.get("family_chance_probability")),
                        self._missing_text(m), m["category"])
            return (rank.get(id(m), ""), m["name"], "— (coverage)",
                    f"{m['matched_count']}/{m['total_reference_peaks']}  ({m['score'] * 100:.0f}%)",
                    "—", "—", "—", m["category"])

        self.matches_table.set_rows(shown, row)
        for r, m in enumerate(shown):
            if is_weighted(m):
                self._tint(self.matches_table, r, 2, m["tier"])
        if t is None or not t.matches:
            self.match_summary.setText("Click a row to overlay its reference bands on the plot.")
            return
        hidden = len(t.matches) - len(shown)
        best = t.matches[0]
        text = f"{len(shown)} shown"
        if hidden:
            text += f", {hidden} hidden by the filters"
        if is_weighted(best):
            text += f"  ·  best: {best['name']} ({best['tier']}, {best['confidence'] * 100:.0f}%)"
        self.match_summary.setText(text + "  ·  click a row for the evidence")

    def _refresh_mixture(self):
        t = self.get_active()
        mix = t.metadata.get("mixture") if t is not None else None
        if not mix:
            self.mixture_table.clear_rows()
            self.mixture_summary.setText("Analyse as mixture to look for up to three components — useful for "
                                         "blends, composites and contaminated samples.")
            self.unexplained_label.setText("")
            return
        comps = mix.get("components", [])
        self.mixture_table.set_rows(comps, lambda c: (
            c["name"], f"{c['tier']} · {c['confidence'] * 100:.0f}%", len(c.get("explained_peaks", [])),
            f"{c.get('share', 0) * 100:.0f}%", self._missing_text(c), c["category"]))
        for r, c in enumerate(comps):
            self._tint(self.mixture_table, r, 1, c["tier"])
        names = " + ".join(c["name"] for c in comps) or "no component reached the 35 % confidence floor"
        self.mixture_summary.setText(f"Screening result: {names}. Together they account for "
                                     f"{mix.get('explained_share', 0) * 100:.0f}% of the detected peak "
                                     "prominence. Click a component to see its bands.")
        unexplained = mix.get("unexplained", [])
        if unexplained:
            xs = ", ".join(f"{p['x']:.0f}" for p in sorted(unexplained, key=lambda p: -p.get("prominence", 0))[:15])
            more = f" (+{len(unexplained) - 15} more)" if len(unexplained) > 15 else ""
            self.unexplained_label.setText(f"Unexplained peaks, strongest first (cm⁻¹): {xs}{more}. "
                                           "Check them against the Functional groups tab.")
        else:
            self.unexplained_label.setText("Every detected peak is accounted for.")

    _current_match_trace = None

    def _evidence_lines(self, match, entry):
        full_source = match.get("source", "") or "(no source on file)"
        source_short = full_source.split(";")[0].strip()
        lines = [f"{match['name']}  [{match['category']}]"]
        if is_weighted(match):
            lines.append(f"Confidence: {match['tier']} ({match['confidence'] * 100:.0f}%)  —  screening, "
                         "not identification")
            lines.append("")
            lines.append("Why it ranks here:")
            lines.append(f"  • Reference bands found: {match['matched_count']} of {match['total_reference_peaks']} "
                         f"(intensity-weighted coverage F = {match['forward_score'] * 100:.0f}%)")
            lines.append(f"  • Share of your peaks in its band window that it explains: "
                         f"R = {match['reverse_score'] * 100:.0f}%")
            lines.append(f"  • Chance of a match this good by coincidence: "
                         f"{format_probability(match.get('chance_probability'))} for this material, "
                         f"{format_probability(match.get('family_chance_probability'))} across the whole search")
            if match.get("pattern_r") is not None:
                lines.append(f"  • Pattern r with a synthetic spectrum of its bands: {match['pattern_r']:+.2f} "
                             "(informational)")
            missing = match.get("missing_strong") or []
            if missing:
                lines.append(f"  ⚠ Strong band(s) not found: "
                             + ", ".join(f"{r['range'][0]}–{r['range'][1]} ({r['assignment']})" for r in missing))
            lines.append("")
            lines.append("Bands  (✓ found · ≈ at the tolerance edge · ✗ not found):")
            for b in match.get("bands", []):
                ref = b["reference"]
                rng = f"{ref['range'][0]}–{ref['range'][1]} cm-1"
                intensity = ref.get("intensity", "")
                mark = BAND_MARKS[b["status"]]
                if b["match"]:
                    mm = b["match"]
                    lines.append(f"  {mark} {rng:<16} {ref['assignment']} [{intensity}]  observed "
                                 f"{mm['observed']['x']:.1f}, Δ {mm['delta_cm1']:+.1f}")
                else:
                    flag = "  ⚠ strong" if b["weight"] >= ftir_matching.STRONG_WEIGHT else ""
                    lines.append(f"  {mark} {rng:<16} {ref['assignment']} [{intensity}]{flag}")
            inactive = [r for r in (entry or {}).get("peaks", []) if not ftir_matching.is_matchable(r)]
            for ref in inactive:
                lines.append(f"  · (IR-inactive) {ref['assignment']}")
            lines += ["", f"Source: {full_source}"]
        elif entry:
            lines.append(f"Source: {full_source}")
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
            lines.append(f"Source: {full_source}")
            for mm in match["matches"]:
                ref = mm["reference"]
                lines.append(f"  observed {mm['observed']['x']:.1f} cm-1  ~  ref {ref['range'][0]}-{ref['range'][1]} "
                             f"cm-1 ({ref['assignment']}), delta={mm['delta_cm1']:+.1f} cm-1  [ref: {source_short}]")
        lines += ["", "Full citations: Library › Sources & references."]
        return lines

    def _show_match_detail(self, match):
        entry = ftir_analysis.find_entry(self.database, match["name"])
        self._current_match = match
        self._current_match_entry = entry
        self._current_match_trace = self.active_id
        t = self.get_active()
        if entry and t is not None and is_weighted(match) and "pattern_r" not in match:
            match["pattern_r"] = ftir_matching.pattern_correlation(entry, t.x, t.y, mode=self.mode())
        self.match_detail.setPlainText("\n".join(self._evidence_lines(match, entry)))
        if entry:
            overlay = {"label": match["name"], "peaks": entry["peaks"]}
            if is_weighted(match):
                overlay["bands"] = match.get("bands", [])
                overlay["tier"] = match.get("tier")
                if t is not None and len(t.x):
                    overlay["synthetic"] = (t.x, ftir_matching.synthetic_reference_spectrum(entry, t.x))
            self.set_reference_overlay(overlay)
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
        t.metadata.pop("mixture", None)
        self.redraw()
        self.on_active_trace_changed()
        self.results_tabs.setCurrentWidget(self.peaks_table)
        msg = f"Detected {len(t.peaks)} peaks in {t.label}"
        if len(t.peaks) > 100:
            msg += " — that's a lot; raise the sensitivity for cleaner results"
        self.app.notify(msg, "success" if t.peaks else "warning")
        if record:
            self.record("detect peaks")

    def _match_inputs(self):
        """(trace, peaks, tolerance, categories, scope label, spectral range) or None."""
        t = self.require_active("Load a spectrum first.")
        if t is None:
            return None
        if not t.peaks:
            self.detect_peaks(record=False)
            if not t.peaks:
                return None
        tol = self.tolerance_spin.value()
        self.app.cfg["ftir_tolerance_cm1"] = tol
        self.app.cfg["ftir_min_confidence_pct"] = self.min_conf_spin.value()
        label_to_key = {v: k for k, v in ftir_analysis.CATEGORY_LABELS.items()}
        selected = self.category_combo.currentText()
        categories = None if selected == ftir_analysis.ALL_CATEGORIES_LABEL else [label_to_key[selected]]
        scope = "all categories" if categories is None else selected
        spectral_range = (float(np.min(t.x)), float(np.max(t.x))) if len(t.x) else None
        return t, list(t.peaks), tol, categories, scope, spectral_range

    def match_database(self):
        inputs = self._match_inputs()
        if inputs is None:
            return
        t, peaks_snapshot, tol, categories, scope, spectral_range = inputs
        database, method = self.database, self.match_method()

        def compute():
            return (ftir_analysis.match_peaks_to_database(peaks_snapshot, database, tolerance=tol, categories=categories,
                                                          method=method, spectral_range=spectral_range),
                    ftir_analysis.match_functional_groups(peaks_snapshot, database, tolerance=tol))

        def on_done(result):
            t.matches, t.fg_hits = result
            self.match_filter.clear()
            self.on_active_trace_changed()
            self.results_tabs.setCurrentWidget(self.matches_page)
            msg = f"{len(t.matches)} candidate material(s) in {scope}, {len(t.fg_hits)} functional-group hit(s)"
            level = "success"
            if t.matches and is_weighted(t.matches[0]):
                best = t.matches[0]
                msg += f" — best: {best['name']} ({best['tier']}, {best['confidence'] * 100:.0f}%)"
                if best["tier"] in ("Low", "Weak"):
                    msg += "; no confident match, try Analyse as mixture or a category"
                    level = "warning"
            self.app.notify(msg, level)
            self.record("match database")

        self.run_background(compute, on_done, busy_text="Matching against the FTIR database…")

    def analyse_mixture(self):
        inputs = self._match_inputs()
        if inputs is None:
            return
        t, peaks_snapshot, tol, categories, scope, spectral_range = inputs
        database = self.database

        def compute():
            return ftir_analysis.analyse_mixture(peaks_snapshot, database, tolerance=tol, categories=categories,
                                                 spectral_range=spectral_range)

        def on_done(result):
            t.metadata["mixture"] = result
            self.on_active_trace_changed()
            self.results_tabs.setCurrentWidget(self.mixture_page)
            comps = result["components"]
            if comps:
                self.app.notify(f"Mixture screening in {scope}: " + " + ".join(c["name"] for c in comps)
                                + f" ({result['explained_share'] * 100:.0f}% of peak prominence explained)", "success")
            else:
                self.app.notify("No component reached the confidence floor — the sample may not be in the "
                                "database", "warning")
            self.record("mixture analysis")

        self.run_background(compute, on_done, busy_text="Screening for mixture components…")

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
        t.metadata.pop("mixture", None)
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
            self.results_tabs.setCurrentWidget(self.fits_table)
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
                        "matched_in_your_spectrum", "observed_cm-1", "delta_cm-1", "position_score", "source"])
            for ref in entry["peaks"]:
                mm = matched_by_range.get(tuple(ref["range"]))
                score = mm.get("position_score") if mm else None
                w.writerow([entry["name"], ref["range"][0], ref["range"][1], ref["assignment"], ref.get("intensity", ""),
                            "yes" if mm else "no", f"{mm['observed']['x']:.2f}" if mm else "",
                            f"{mm['delta_cm1']:+.2f}" if mm else "", f"{score:.3f}" if score is not None else "",
                            entry.get("source", "")])
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
            rows = [["Material", "Category", "Confidence", "Matched/Total", "Explained", "Chance p"]]
            for m in t.matches[:12]:
                conf = f"{m['tier']} {m['score'] * 100:.0f}%" if is_weighted(m) else f"{m['score'] * 100:.0f}% (coverage)"
                explained = f"{m['reverse_score'] * 100:.0f}%" if is_weighted(m) else "-"
                rows.append([m["name"], m["category"], conf, f"{m['matched_count']}/{m['total_reference_peaks']}",
                             explained, format_probability(m.get("family_chance_probability")).replace("—", "-")])
            sections.append(("Database Matches (heuristic screening)", rows, None))
        mixture = t.metadata.get("mixture") or {}
        if mixture.get("components"):
            rows = [["Component", "Confidence", "Peaks explained", "Share of sample"]]
            rows += [[c["name"], f"{c['tier']} {c['confidence'] * 100:.0f}%", str(len(c.get("explained_peaks", []))),
                      f"{c.get('share', 0) * 100:.0f}%"] for c in mixture["components"]]
            sections.append(("Mixture screening (heuristic)", rows, None))
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
