"""
ftir_tab.py
The FTIR page: load spectra (multi-trace overlay), process, detect peaks, screen against the
reference database (single materials and mixtures) with band-by-band evidence, fit peaks,
run calculations, and export CSV / PDF / Origin / Excel / sessions.
"""
import csv
import datetime
import html
import os
import tempfile

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPushButton, QRadioButton, QSplitter, QTextBrowser,
                               QVBoxLayout, QWidget)

import exports
import file_readers
import formula_sources as fs
import ftir_analysis
import ftir_matching
import peak_fitting
import report_export
import ui_common
from app_info import APP_VERSION
from labkit.qt.theme import colours
from ui_common import AnalysisTabBase, DataTable, parse_float

# Tier -> (foreground token, background token) for the match-score cell. The tier is also
# written in the cell, so colour is never the only signal.
TIER_TOKENS = {"Strong": ("good", "good_bg"), "Moderate": ("warn", "warn_bg"), "Weak": (None, None),
               "Poor": ("muted", None)}
# Okabe-Ito colours (safe for red/green colour blindness); the status is also carried by the
# line style and the marker above each band.
BAND_STYLE = {
    "light": {"matched": "#0072B2", "edge": "#E69F00", "missing": "#D55E00"},
    "dark": {"matched": "#56B4E9", "edge": "#F0E442", "missing": "#FF7F50"},
}
BAND_MARKERS = {"matched": "v", "edge": "d", "missing": "x"}
BAND_MARKS = {"matched": "✓", "edge": "≈", "missing": "✗", "outside": "–"}
BAND_WORDS = {"matched": "found", "edge": "at the tolerance edge", "missing": "not found",
              "outside": "outside the measured range"}
COMPONENT_COLOURS = ["#0072B2", "#E69F00", "#009E73"]
PEAK_LABEL_LIMIT = 15
PEAK_LABEL_MIN_GAP = 25.0           # cm-1 between two printed peak labels
UNEXPLAINED_MIN_REL = 0.10          # unexplained peaks weaker than this are counted, not listed

MATCH_COLUMNS = [
    ("#", "Rank by match score"),
    ("Material", "Reference material from the built-in database"),
    ("Match score", "Screening score from 0 to 1 with its tier (Strong ≥ 0.60, Moderate ≥ 0.40, Weak ≥ 0.20, "
                    "Poor). Not the probability that the identification is correct."),
    ("Bands found", "Reference bands found in your spectrum / bands in the measured range, and the "
                    "intensity-weighted coverage"),
    ("Peaks explained", "Share of your peak prominence, within this material's band region, that its bands account for"),
    ("Chance p", "Probability that some material in the search would match this well by coincidence, "
                 "given how crowded your peak list is. Smaller is better."),
    ("Missing strong", "Strong reference bands (cm⁻¹) with no peak in your spectrum — a warning sign"),
    ("Verdict", "Your own decision after checking a reference spectrum"),
]


def format_probability(p):
    if p is None or p == "":
        return "—"
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def is_weighted(match):
    return match.get("method") == ftir_matching.METHOD_WEIGHTED and "confidence" in match


def missing_text(match):
    missing = match.get("missing_strong") or []
    return ", ".join(f"{(r['range'][0] + r['range'][1]) / 2:.0f}" for r in missing) or "—"


def evidence_lines(match, entry, verdict=None, pattern_r=None):
    """Plain-text, band-by-band evidence for one candidate (evidence panel copy, PDF)."""
    full_source = match.get("source", "") or "(no source on file)"
    lines = [f"{match['name']}  [{match['category']}]"]
    if verdict:
        lines.append(f"Verdict: {verdict['status'].upper()} on {verdict['date']}"
                     + (f" — {verdict['note']}" if verdict.get("note") else ""))
    if not is_weighted(match):
        lines.append(f"Coverage score {match['score'] * 100:.0f}% ({match['matched_count']}/"
                     f"{match['total_reference_peaks']} reference bands within tolerance; legacy method)")
        matched_by_range = {tuple(mm["reference"]["range"]): mm for mm in match.get("matches", [])}
        for ref in (entry or {}).get("peaks", []):
            mm = matched_by_range.get(tuple(ref["range"]))
            if not ftir_matching.is_matchable(ref):
                lines.append(f"  · (IR-inactive) {ref['assignment']}")
            elif mm:
                lines.append(f"  ✓ {ref['range'][0]}–{ref['range'][1]} cm-1  {ref['assignment']}  observed "
                             f"{mm['observed']['x']:.1f}, Δ {mm['delta_cm1']:+.1f}")
            else:
                lines.append(f"  ✗ {ref['range'][0]}–{ref['range'][1]} cm-1  {ref['assignment']}")
        lines += ["", f"Source: {full_source}"]
        return lines
    lines.append(f"Match score: {match['tier']} ({match['confidence']:.2f}) — a screening score, not the "
                 "probability that this identification is correct")
    lines.append(f"  Bands found: {match['matched_count']} of {match['total_reference_peaks']} in the measured range "
                 f"(intensity-weighted coverage {match['forward_score'] * 100:.0f}%)")
    if match.get("outside_count"):
        lines.append(f"  {match['outside_count']} band(s) lie outside the measured range and were not scored")
    lines.append(f"  Peaks explained in its band region: {match['reverse_score'] * 100:.0f}%")
    lines.append(f"  Chance of a match this good by coincidence: {format_probability(match.get('chance_probability'))} "
                 f"for this material, {format_probability(match.get('family_chance_probability'))} across the "
                 f"{match.get('n_searched', '?')} materials searched")
    if pattern_r is not None:
        lines.append(f"  Pattern r with a synthetic spectrum of its bands: {pattern_r:+.2f} (informational)")
    for r in match.get("missing_strong") or []:
        lines.append(f"  ⚠ Strong band not found: {r['range'][0]}–{r['range'][1]} cm-1 ({r['assignment']})")
    if match.get("ambiguous_with"):
        lines.append("  ⚠ Close call with " + ", ".join(match["ambiguous_with"][:3]))
    if match.get("look_alikes"):
        lines.append("  ⚠ Band table nearly identical to " + ", ".join(match["look_alikes"]) +
                     " — a peak list cannot separate them")
    for reason in match.get("tier_capped_because") or []:
        lines.append(f"  Tier limited to Moderate: {reason}")
    lines.append("")
    lines.append("Bands (✓ found · ≈ tolerance edge · ✗ not found · – outside measured range):")
    for b in match.get("bands", []):
        ref = b["reference"]
        rng = f"{ref['range'][0]}–{ref['range'][1]} cm-1"
        text = f"  {BAND_MARKS[b['status']]} {rng:<15} {ref['assignment']} [{ref.get('intensity', '')}]"
        if b["match"]:
            text += f"  observed {b['match']['observed']['x']:.1f}, Δ {b['match']['delta_cm1']:+.1f}"
        elif b["status"] == "missing" and b["weight"] >= ftir_matching.STRONG_WEIGHT:
            text += "  ⚠ strong"
        lines.append(text)
    for ref in (entry or {}).get("peaks", []):
        if not ftir_matching.is_matchable(ref):
            lines.append(f"  · (IR-inactive) {ref['assignment']}")
    prov = (entry or {}).get("provenance") or {}
    if prov.get("verify"):
        lines.append(f"  ⚠ Entry added from literature excerpts ({prov.get('confidence', '?')} confidence) — verify")
    lines += ["", f"Source: {full_source}"]
    return lines


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
        self._current_match_trace = None
        self._shown_matches = []
        self._build_controls()
        self._build_results_tabs()
        self._on_traces_changed()
        self.fit_controls_width()
        self.right_splitter.setSizes([560, 360])        # room for the evidence panel

    # ---------------------------------------------------------------- controls
    def _build_controls(self):
        card = self.add_card("1 · Processing", "Optional, before detecting peaks: ATR correction, then baseline, "
                                               "then smoothing. Processing clears peaks and matches.")
        card.body.addWidget(self.action_button("ATR correction…", self.atr_correct_active,
                                               info=("ATR correction", fs.ATR_CORRECTION)))
        card.body.addWidget(self.action_button("Baseline correct (linear, from raw)", self.baseline_correct_active))
        card.body.addWidget(self.action_button("Smooth (Savitzky–Golay)…", self.smooth_active))
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

        card = self.add_card("2 · Peak detection")
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
        self.prom_spin.setToolTip("Minimum peak prominence as a percentage of the spectrum's intensity range.")
        card.body.addWidget(self.labelled("Sensitivity (prominence)", self.prom_spin))
        self.noise_check = QCheckBox("Ignore peaks below the noise floor (5σ)")
        self.noise_check.setChecked(True)
        self.noise_check.setToolTip("Estimates the noise from point-to-point differences and ignores peaks "
                                    "smaller than five times it, so baseline noise is not reported as bands.")
        card.body.addWidget(self.noise_check)
        self.co2_check = QCheckBox("Skip the CO₂ region (2280–2400 cm⁻¹)")
        self.co2_check.setChecked(True)
        self.co2_check.setToolTip("Atmospheric CO₂ residue is the most common artefact in routine spectra.")
        card.body.addWidget(self.co2_check)
        shoulder = QWidget()
        sl = QHBoxLayout(shoulder)
        sl.setContentsMargins(0, 0, 0, 0)
        self.shoulder_check = QCheckBox("Resolve shoulders (2nd derivative)")
        sl.addWidget(self.shoulder_check, 1)
        info = QPushButton("ⓘ")
        info.setObjectName("Ghost")
        info.setFixedWidth(34)
        info.clicked.connect(lambda _c=False: self.show_formula("Second-derivative peak resolution",
                                                                 fs.SECOND_DERIVATIVE_PEAK_DETECTION))
        sl.addWidget(info)
        card.body.addWidget(shoulder)
        card.body.addWidget(self.action_button("Detect peaks", self.detect_peaks, primary=True))

        self.n_materials = sum(len(self.database.get(cat, [])) for cat in ftir_analysis.MATERIAL_CATEGORIES)
        card = self.add_card("3 · Database screening",
                             "Screening against literature band tables, not identification — confirm against "
                             "a certified reference spectrum.")
        self.category_combo = QComboBox()
        self.category_combo.addItems([ftir_analysis.ALL_CATEGORIES_LABEL] +
                                     [ftir_analysis.CATEGORY_LABELS[k] for k in ftir_analysis.MATERIAL_CATEGORIES])
        self.category_combo.setToolTip("Searching one category, when you know it, avoids look-alikes from "
                                       "other classes and raises the scores of real matches.")
        card.body.addWidget(self.labelled("Search", self.category_combo))
        self.tolerance_spin = QDoubleSpinBox()
        self.tolerance_spin.setRange(1.0, 50.0)
        self.tolerance_spin.setSingleStep(1.0)
        self.tolerance_spin.setValue(float(self.app.cfg.get("ftir_tolerance_cm1", 10.0)))
        self.tolerance_spin.setSuffix(" cm⁻¹")
        self.tolerance_spin.setToolTip("How far a peak may sit outside a reference band range. ATR spectra: "
                                       "8–12 cm⁻¹ is usual; widen to 15–20 if strong bands are shifted and no "
                                       "ATR correction was applied. Broad bands get twice this.")
        card.body.addWidget(self.labelled("Tolerance (±)", self.tolerance_spin))
        self.method_combo = QComboBox()
        for key, label in ftir_matching.METHOD_LABELS.items():
            self.method_combo.addItem(label, key)
        self.method_combo.setToolTip("Weighted evidence uses band intensities, position accuracy, how much of "
                                     "your spectrum a material explains and the chance of a coincidental "
                                     "match. Coverage (legacy) is the fraction-of-bands score of earlier versions.")
        self.method_combo.currentIndexChanged.connect(lambda _i: self._on_method_changed())
        card.body.addWidget(self.labelled("Scoring", self.method_combo))
        self.min_conf_spin = QDoubleSpinBox()
        self.min_conf_spin.setRange(0.0, 0.95)
        self.min_conf_spin.setSingleStep(0.05)
        self.min_conf_spin.setDecimals(2)
        self.min_conf_spin.setValue(float(self.app.cfg.get("ftir_min_score", 0.05)))
        self.min_conf_spin.setToolTip("Only changes what is listed — nothing is recomputed. Does not apply to "
                                      "Coverage (legacy) results.")
        self.min_conf_spin.valueChanged.connect(lambda _v: self._refresh_matches_table())
        card.body.addWidget(self.labelled("Hide scores below", self.min_conf_spin))
        card.body.addWidget(self.action_button(f"Match to database ({self.n_materials} materials)  ·  Ctrl+M",
                                               self.match_database, primary=True,
                                               info=("FTIR database matching method", fs.FTIR_DATABASE_MATCHING)))
        mix = self.action_button("Analyse as mixture (up to 3 components)", self.analyse_mixture,
                                 info=("FTIR database matching method", fs.FTIR_DATABASE_MATCHING))
        mix.button.setToolTip("Always uses Weighted evidence. Accepts the best material scoring ≥ 0.35, "
                              "removes the peaks it explains and searches again.")
        card.body.addWidget(mix)

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

        # ---- database matches
        matches = QWidget()
        ml = QVBoxLayout(matches)
        ml.setContentsMargins(6, 8, 6, 6)
        ml.setSpacing(4)
        bar = QHBoxLayout()
        self.match_filter = QLineEdit()
        self.match_filter.setPlaceholderText("Filter…")
        self.match_filter.setToolTip("Show only materials whose name contains this text (Ctrl+F)")
        self.match_filter.setClearButtonEnabled(True)
        self.match_filter.setMinimumWidth(120)
        self.match_filter.setMaximumWidth(220)
        self.match_filter.textChanged.connect(lambda _t: self._refresh_matches_table())
        self.match_filter.returnPressed.connect(lambda: self.matches_table.selectRow(0)
                                                if self.matches_table.rowCount() else None)
        QShortcut(QKeySequence.Find, matches, activated=self.match_filter.setFocus,
                  context=Qt.WidgetWithChildrenShortcut)
        bar.addWidget(self.match_filter)
        run = QPushButton("Match to database")
        run.setObjectName("Primary")
        run.clicked.connect(lambda _c=False: self.match_database())
        bar.addWidget(run)
        bar.addStretch(1)
        for text, fn in (("Copy evidence", self.copy_evidence), ("Reference bands (CSV)…", self.export_reference_peaks_csv),
                         ("Clear overlay", self.clear_reference_overlay)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            bar.addWidget(b)
        ml.addLayout(bar)
        self.match_summary = QLabel("")
        self.match_summary.setObjectName("Hint")
        ml.addWidget(self.match_summary)

        self.matches_table = DataTable([c[0] for c in MATCH_COLUMNS])
        for i, (_name, tip) in enumerate(MATCH_COLUMNS):
            self.matches_table.horizontalHeaderItem(i).setToolTip(tip)
        header = self.matches_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        self.matches_table.setColumnWidth(1, 230)
        self.matches_table.setHorizontalScrollMode(self.matches_table.ScrollMode.ScrollPerPixel)
        self.matches_table.on_select = self._show_match_detail

        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(4)
        self.match_detail = QTextBrowser()
        self.match_detail.setOpenLinks(False)
        self.match_detail.setPlaceholderText("Select a candidate to see the evidence band by band.")
        dl.addWidget(self.match_detail, 1)
        verdict_row = QHBoxLayout()
        for text, status in (("Confirm…", "confirmed"), ("Reject…", "rejected")):
            b = QPushButton(text)
            b.setToolTip(f"Record that you have {status} this candidate (e.g. against a reference spectrum). "
                         "Saved in the session and in the exports.")
            b.clicked.connect(lambda _c=False, s=status: self.set_verdict(s))
            verdict_row.addWidget(b)
        clear_v = QPushButton("Clear verdict")
        clear_v.clicked.connect(lambda _c=False: self.set_verdict(None))
        verdict_row.addWidget(clear_v)
        verdict_row.addStretch(1)
        dl.addLayout(verdict_row)

        self.match_split = QSplitter(Qt.Horizontal)
        self.match_split.addWidget(self.matches_table)
        self.match_split.addWidget(detail)
        self.match_split.setStretchFactor(0, 3)
        self.match_split.setStretchFactor(1, 2)
        self.match_split.setChildrenCollapsible(False)
        self.match_split.setSizes([600, 380])
        ml.addWidget(self.match_split, 1)
        self.matches_page = matches
        self.results_tabs.addTab(matches, "Database matches")

        # ---- mixture
        mixture = QWidget()
        xl = QVBoxLayout(mixture)
        xl.setContentsMargins(6, 8, 6, 6)
        xl.setSpacing(4)
        mbar = QHBoxLayout()
        run_mix = QPushButton("Analyse as mixture")
        run_mix.setObjectName("Primary")
        run_mix.clicked.connect(lambda _c=False: self.analyse_mixture())
        mbar.addWidget(run_mix)
        show_all = QPushButton("Show all components")
        show_all.setToolTip("Overlay the found bands of every component, each in its own colour.")
        show_all.clicked.connect(lambda _c=False: self.show_all_components())
        mbar.addWidget(show_all)
        self.mixture_summary = QLabel("")
        self.mixture_summary.setObjectName("Hint")
        mbar.addWidget(self.mixture_summary, 1)
        xl.addLayout(mbar)
        self.mixture_table = DataTable(["Component", "Match score", "Peaks explained", "Share of peak intensity",
                                        "Missing strong", "Category"])
        self.mixture_table.horizontalHeaderItem(3).setToolTip(
            "Fraction of the summed peak prominence assigned to this component. NOT a concentration — use "
            "calibrated quantitative analysis for composition.")
        self.mixture_table.setMinimumHeight(27 * 3 + 30)
        self.mixture_table.on_select = self._show_match_detail
        xl.addWidget(self.mixture_table, 1)
        self.unexplained_label = QLabel("")
        self.unexplained_label.setObjectName("Hint")
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
                "min_score": self.min_conf_spin.value(), "noise_floor": self.noise_check.isChecked(),
                "skip_co2": self.co2_check.isChecked(), "shoulders": self.shoulder_check.isChecked()}

    def apply_session_settings(self, state):
        (self.rb_transmittance if state.get("mode") == "transmittance" else self.rb_absorbance).setChecked(True)
        self.prom_spin.setValue(float(state.get("prominence", 2.0)))
        self.tolerance_spin.setValue(float(state.get("tolerance", 10.0)))
        index = self.category_combo.findText(state.get("category", ftir_analysis.ALL_CATEGORIES_LABEL))
        self.category_combo.setCurrentIndex(max(0, index))
        method_index = self.method_combo.findData(state.get("match_method", ftir_matching.METHOD_WEIGHTED))
        self.method_combo.setCurrentIndex(max(0, method_index))
        self.min_conf_spin.setValue(float(state.get("min_score", 0.05)))
        self.noise_check.setChecked(bool(state.get("noise_floor", True)))
        self.co2_check.setChecked(bool(state.get("skip_co2", True)))
        self.shoulder_check.setChecked(bool(state.get("shoulders", False)))

    def match_method(self):
        return self.method_combo.currentData() or ftir_matching.METHOD_WEIGHTED

    def _on_method_changed(self):
        self.min_conf_spin.setEnabled(self.match_method() == ftir_matching.METHOD_WEIGHTED)

    def _reset_current_match(self):
        self._current_match = None
        self._current_match_entry = None
        self._current_match_trace = None
        self.reference_overlay = None
        self.match_detail.clear()

    def restore(self, state):
        self._reset_current_match()
        super().restore(state)

    def _is_live(self, trace):
        """False when undo, a session load or a removal replaced the trace a job was started on."""
        return any(t is trace for t in self.traces)

    def _band_colours(self, theme):
        return BAND_STYLE.get(theme, BAND_STYLE["light"])

    # ---------------------------------------------------------------- plotting
    def _plot_active_extras(self, ax, trace, theme):
        fg = self.foreground(theme)
        if not trace.peaks:
            return
        overlay = self.reference_overlay
        xs = [p["x"] for p in trace.peaks]
        # Short neutral ticks along the bottom edge: never a band-status colour, never full height.
        ax.vlines(xs, 0, 0.035, transform=ax.get_xaxis_transform(), color=fg, alpha=0.55, lw=0.9, zorder=2)
        if overlay and overlay.get("bands"):
            labelled_x = {round(b["match"]["observed"]["x"], 3) for b in overlay["bands"] if b.get("match")}
            candidates = [p for p in trace.peaks if round(p["x"], 3) in labelled_x]
        else:
            candidates = sorted(trace.peaks, key=lambda p: -float(p.get("prominence", 0) or 0))[:PEAK_LABEL_LIMIT]
        placed = []
        for p in sorted(candidates, key=lambda p: -float(p.get("prominence", 0) or 0)):
            if any(abs(p["x"] - q) < PEAK_LABEL_MIN_GAP for q in placed):
                continue
            placed.append(p["x"])
            va = "top" if self.mode() == "transmittance" else "bottom"
            ax.annotate(f"{p['x']:.0f}", (p["x"], p["y"]), fontsize=7, rotation=90, ha="center", va=va,
                        color=fg, xytext=(0, -3 if va == "top" else 3), textcoords="offset points")

    def _draw_reference_overlay(self, ax, theme):
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch

        overlay = self.reference_overlay
        fg = self.foreground(theme)
        colour = self._band_colours(theme)
        handles = []
        if overlay.get("layers"):                       # several mixture components at once
            for layer in overlay["layers"]:
                for b in layer["bands"]:
                    if b["status"] in ("matched", "edge"):
                        lo, hi = b["reference"]["range"]
                        ax.axvspan(lo, hi, color=layer["colour"], alpha=0.25, lw=0, zorder=0)
                handles.append(Patch(color=layer["colour"], alpha=0.5, label=layer["label"]))
            title = "Mixture components (found bands)"
        else:
            status_by_range = {tuple(b["reference"]["range"]): b["status"] for b in overlay.get("bands", [])}
            used = set()
            for p in overlay.get("peaks", []):
                lo, hi = p["range"]
                if not ftir_matching.is_matchable(p):
                    continue                            # IR-inactive placeholder (e.g. NaCl)
                status = status_by_range.get(tuple(p["range"]), "matched" if not status_by_range else None)
                if status in (None, "outside"):
                    continue
                centre = (lo + hi) / 2
                c = colour[status]
                used.add(status)
                if status == "missing":
                    strong = ftir_matching.parse_intensity(p.get("intensity"))[0] >= ftir_matching.STRONG_WEIGHT
                    ax.axvline(centre, color=c, alpha=0.85 if strong else 0.55, lw=1.8 if strong else 1.2,
                               linestyle="--", zorder=1)
                else:
                    ax.axvspan(lo, hi, color=c, alpha=0.22, lw=0, zorder=0)
                    ax.axvline(centre, color=c, alpha=0.8, lw=1.2, linestyle="-" if status == "matched" else ":")
                ax.plot([centre], [1.0], marker=BAND_MARKERS[status], color=c, markersize=6, clip_on=False,
                        transform=ax.get_xaxis_transform(), zorder=4, linestyle="none")
            labels = {"matched": "found", "edge": "at tolerance edge", "missing": "not found"}
            styles = {"matched": "-", "edge": ":", "missing": "--"}
            for status in ("matched", "edge", "missing"):
                if status in used:
                    handles.append(Line2D([], [], color=colour[status], lw=1.6, linestyle=styles[status],
                                          marker=BAND_MARKERS[status], label=labels[status]))
            synthetic = overlay.get("synthetic")
            active = self.get_active()
            if synthetic is not None and active is not None and len(active.y):
                sx, sy = synthetic
                top = float(np.max(sy)) if len(sy) else 0.0
                if top > 0:
                    y_lo, y_hi = float(np.min(active.y)), float(np.max(active.y))
                    scaled = sy / top * (y_hi - y_lo) * 0.9
                    curve = (y_hi - scaled) if self.mode() == "transmittance" else (y_lo + scaled)
                    ax.plot(sx, curve, color=fg, alpha=0.55, lw=1.0, linestyle=(0, (4, 2)), zorder=3)
                    handles.append(Line2D([], [], color=fg, alpha=0.55, lw=1.0, linestyle=(0, (4, 2)),
                                          label="bands as a synthetic spectrum"))
            tier = overlay.get("tier")
            title = f"{overlay.get('label', 'Reference')}" + (f" — {tier.lower()} match (screening)" if tier else "")
        trace_label = overlay.get("trace_label")
        if trace_label:
            title += f"  ·  {trace_label}"
        ax.set_title(title, loc="left", fontsize=9, color=fg)
        if handles:
            existing = ax.get_legend()
            ax.legend(handles=handles, loc="upper left", fontsize=7.5, framealpha=0.85)
            if existing is not None:
                ax.add_artist(existing)

    # ---------------------------------------------------------------- results refresh
    def on_theme_changed(self, theme):
        super().on_theme_changed(theme)
        self._refresh_matches_table()
        self._refresh_mixture()
        if self._current_match is not None:
            self._render_evidence()

    def on_active_trace_changed(self):
        if self._current_match_trace is not None and self._current_match_trace != self.active_id:
            self._reset_current_match()
            self.redraw()
        t = self.get_active()
        if t is None:
            for table in (self.peaks_table, self.matches_table, self.fg_table, self.fits_table, self.mixture_table):
                table.clear_rows()
            self.match_detail.clear()
            self._refresh_matches_table()
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
        if not t.matches and self._current_match is None:
            self.match_detail.clear()

    def visible_matches(self, trace=None):
        """The trace's matches after the score threshold and the name filter."""
        t = trace or self.get_active()
        if t is None:
            return []
        threshold = self.min_conf_spin.value()
        needle = self.match_filter.text().strip().lower()
        return [m for m in t.matches
                if not (is_weighted(m) and m["confidence"] < threshold)
                and not (needle and needle not in m["name"].lower())]

    @staticmethod
    def verdicts(trace):
        return trace.metadata.setdefault("verdicts", {}) if trace is not None else {}

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
        if tier in ("Strong", "Moderate"):
            font = item.font()
            font.setBold(True)
            item.setFont(font)

    @staticmethod
    def score_text(m):
        if not is_weighted(m):
            return "n/a (coverage mode)"
        text = f"{m['tier']} · {m['confidence']:.2f}"
        if m.get("ambiguous_with"):
            text += "  (close call)"
        elif m.get("look_alikes"):
            text += "  (+ look-alikes)"
        return text

    def _refresh_matches_table(self):
        t = self.get_active()
        shown = self.visible_matches(t)
        self._shown_matches = shown
        rank = {id(m): i for i, m in enumerate(t.matches, 1)} if t else {}
        verdicts = self.verdicts(t)

        def row(m):
            v = verdicts.get(m["name"], {}).get("status", "")
            if is_weighted(m):
                return (rank.get(id(m), ""), m["name"], self.score_text(m),
                        f"{m['matched_count']}/{m['total_reference_peaks']}  ({m['forward_score'] * 100:.0f}% wt.)",
                        f"{m['reverse_score'] * 100:.0f}%", format_probability(m.get("family_chance_probability")),
                        missing_text(m), v)
            return (rank.get(id(m), ""), m["name"], self.score_text(m),
                    f"{m['matched_count']}/{m['total_reference_peaks']}  ({m['score'] * 100:.0f}%)", "—", "—", "—", v)

        self.matches_table.set_rows(shown, row)
        muted = QBrush(QColor(colours(self.theme)["muted"]))
        for r, m in enumerate(shown):
            if is_weighted(m):
                self._tint(self.matches_table, r, 2, m["tier"])
            else:
                self.matches_table.item(r, 2).setForeground(muted)
        if t is None or not t.matches:
            self.match_summary.setText("No results yet — detect peaks, then Match to database (Ctrl+M)."
                                       if t is not None else "Load a spectrum to start.")
            return
        hidden_score = sum(1 for m in t.matches if is_weighted(m) and m["confidence"] < self.min_conf_spin.value())
        parts = [f"Screening: {len(shown)} of {len(t.matches)} candidates listed"]
        if hidden_score:
            parts.append(f"{hidden_score} scoring below {self.min_conf_spin.value():.2f} hidden")
        if self.match_filter.text().strip():
            parts.append(f"name filter “{self.match_filter.text().strip()}”")
        best = t.matches[0]
        if is_weighted(best):
            text = f"best: {best['name']} ({best['tier'].lower()}, {best['confidence']:.2f})"
            if best.get("ambiguous_with"):
                text += f" — close to {', '.join(best['ambiguous_with'][:2])}"
            parts.append(text)
        self.match_summary.setText("  ·  ".join(parts) + "  ·  click a row for the evidence")
        self.match_summary.setToolTip(self.match_summary.text())

    def _refresh_mixture(self):
        t = self.get_active()
        mix = t.metadata.get("mixture") if t is not None else None
        if not mix:
            self.mixture_table.clear_rows()
            self.mixture_summary.setText("For blends, composites and contaminated samples: finds up to three "
                                         "components and the peaks none of them explains.")
            self.unexplained_label.setText("")
            return
        comps = mix.get("components", [])
        self.mixture_table.set_rows(comps, lambda c: (
            c["name"], self.score_text(c), len(c.get("explained_peak_ids", [])), f"{c.get('share', 0) * 100:.0f}%",
            missing_text(c), c["category"]))
        for r, c in enumerate(comps):
            self._tint(self.mixture_table, r, 1, c["tier"])
        if comps:
            summary = (f"Screening: {' + '.join(c['name'] for c in comps)} — together "
                       f"{mix.get('explained_share', 0) * 100:.0f}% of the peak intensity.")
        else:
            summary = (f"Screening: no component reached {mix.get('min_confidence', 0.35):.2f}. The material may not "
                       "be in the database — compare with NIST WebBook / SDBS.")
        self.mixture_summary.setText(summary)
        self.mixture_summary.setToolTip(summary)
        prom = [float(p.get("prominence", 0) or 0) for p in t.peaks] or [1.0]
        top = max(prom) or 1.0
        unexplained = sorted(mix.get("unexplained", []), key=lambda p: -float(p.get("prominence", 0) or 0))
        strong = [p for p in unexplained if float(p.get("prominence", 0) or 0) / top >= UNEXPLAINED_MIN_REL]
        minor = len(unexplained) - len(strong)
        if not unexplained:
            text = "Every detected peak is accounted for."
        elif not strong:
            text = f"Unexplained: only {minor} weak peak(s) below 10% of the strongest (likely noise)."
        else:
            text = ("Unexplained peaks, strongest first (cm⁻¹): " + ", ".join(f"{p['x']:.0f}" for p in strong[:12])
                    + (f"  (+{minor} weak)" if minor else ""))
            xs = [p["x"] for p in strong]
            if any(3200 <= x <= 3500 for x in xs) and any(1620 <= x <= 1660 for x in xs):
                text += "  ·  3200–3500 + ~1640 together suggest absorbed water."
            text += "  ·  See the Functional groups tab."
        self.unexplained_label.setText(text)
        self.unexplained_label.setToolTip(text)

    # ---------------------------------------------------------------- evidence
    def _ensure_detail(self, match):
        """Results ranked below the detail cut-off keep only their summary; re-score on demand."""
        if not is_weighted(match) or match.get("detail", True):
            return match
        t = self.get_active()
        entry = ftir_analysis.find_entry(self.database, match["name"])
        params = (t.metadata.get("match_params") or {}) if t is not None else {}
        if t is None or entry is None:
            return match
        full = ftir_matching.score_entry(entry, t.peaks, tolerance=params.get("tolerance_cm1", 10.0),
                                         n_searched=params.get("materials_searched", 1),
                                         spectral_range=params.get("spectral_range"))
        if full is not None:
            match.update({k: full[k] for k in ("bands", "matches", "explained_peak_ids")})
            match["detail"] = True
        return match

    def _render_evidence(self):
        match, entry = self._current_match, self._current_match_entry
        if match is None:
            self.match_detail.clear()
            return
        t = self.get_active()
        verdict = self.verdicts(t).get(match["name"])
        c = colours(self.theme)
        band_colour = {"matched": c["good"], "edge": c["warn"], "missing": c["bad"], "outside": c["muted"]}
        e = html.escape
        out = [f"<div style='font-size:13px'><b>{e(match['name'])}</b> "
               f"<span style='color:{c['muted']}'>[{e(match['category'])}]</span></div>"]
        if verdict:
            colour = c["good"] if verdict["status"] == "confirmed" else c["bad"]
            out.append(f"<div style='color:{colour}'><b>{e(verdict['status'].capitalize())}</b> by you on "
                       f"{e(verdict['date'])}{(' — ' + e(verdict['note'])) if verdict.get('note') else ''}</div>")
        if is_weighted(match):
            tier_colour = {"Strong": c["good"], "Moderate": c["warn"]}.get(match["tier"], c["muted"])
            out.append(f"<div style='margin-top:4px'><span style='color:{tier_colour}'><b>{e(match['tier'])} match</b>"
                       f" · score {match['confidence']:.2f}</span> <span style='color:{c['muted']}'>— screening, "
                       "not the probability of being right</span></div>")
            facts = [f"{match['matched_count']} of {match['total_reference_peaks']} bands found "
                     f"(weighted {match['forward_score'] * 100:.0f}%)",
                     f"explains {match['reverse_score'] * 100:.0f}% of your peaks in its region",
                     f"chance p {format_probability(match.get('family_chance_probability'))}"]
            if self._current_pattern_r is not None:
                facts.append(f"pattern r {self._current_pattern_r:+.2f}")
            out.append(f"<div style='color:{c['muted']}'>{e(' · '.join(facts))}</div>")
            warns = []
            if match.get("ambiguous_with"):
                warns.append("Close call with " + ", ".join(match["ambiguous_with"][:3]) +
                             " — the bands do not separate them well.")
            for r in match.get("missing_strong") or []:
                warns.append(f"Strong band {r['range'][0]}–{r['range'][1]} cm⁻¹ ({r['assignment']}) not found.")
            if match.get("could_be_coincidence"):
                warns.append("This many hits could be coincidence at your peak density.")
            if match.get("few_bands"):
                warns.append("Only one or two bands in the database: weak evidence by nature.")
            if match.get("look_alikes"):
                warns.append("Its bands nearly coincide in the database with " + ", ".join(match["look_alikes"][:4])
                             + (" …" if len(match["look_alikes"]) > 4 else "") +
                             " — a peak list cannot tell these apart; treat the match as the family.")
            if match.get("outside_count"):
                warns.append(f"{match['outside_count']} band(s) outside the measured range were not scored.")
            prov = (entry or {}).get("provenance") or {}
            if prov.get("verify"):
                warns.append(f"This entry was added in {prov.get('added', '')[:4]} from literature excerpts "
                             f"({prov.get('confidence', '?')} confidence) and is marked for verification — "
                             "see docs/FTIR_DATABASE_ADDITIONS.md.")
            for w in warns:
                out.append(f"<div style='color:{c['warn']}'>⚠ {e(w)}</div>")
            rows = []
            for b in match.get("bands", []):
                ref = b["reference"]
                obs = (f"{b['match']['observed']['x']:.1f} ({b['match']['delta_cm1']:+.1f})" if b["match"] else "")
                rows.append(f"<tr><td style='color:{band_colour[b['status']]}'><b>{BAND_MARKS[b['status']]}</b></td>"
                            f"<td>{ref['range'][0]}–{ref['range'][1]}</td><td>{e(ref['assignment'])}</td>"
                            f"<td style='color:{c['muted']}'>{e(str(ref.get('intensity', '')))}</td><td>{obs}</td></tr>")
            out.append("<table cellspacing='0' cellpadding='2' style='margin-top:6px'>"
                       f"<tr style='color:{c['muted']}'><td></td><td>Band (cm⁻¹)</td><td>Assignment</td>"
                       "<td>Intensity</td><td>Observed (Δ)</td></tr>" + "".join(rows) + "</table>")
            out.append(f"<div style='color:{c['muted']}'>✓ found · ≈ tolerance edge · ✗ not found · – outside the "
                       "measured range</div>")
        else:
            out.append("<pre>" + e("\n".join(evidence_lines(match, entry)[1:])) + "</pre>")
        out.append(f"<div style='color:{c['muted']};margin-top:6px'>Source: {e(match.get('source', '') or '—')} — "
                   "full citations under Library › Sources &amp; references.</div>")
        self.match_detail.setHtml("".join(out))

    def evidence_text(self, match=None):
        match = match or self._current_match
        if match is None:
            return ""
        t = self.get_active()
        entry = ftir_analysis.find_entry(self.database, match["name"])
        return "\n".join(evidence_lines(self._ensure_detail(match), entry, self.verdicts(t).get(match["name"])))

    def copy_evidence(self):
        text = self.evidence_text()
        if not text:
            self.app.notify("Click a candidate first.", "warning")
            return
        QApplication.clipboard().setText(text)
        self.app.notify("Evidence copied to the clipboard", "success")

    _current_pattern_r = None

    def _show_match_detail(self, match):
        t = self.get_active()
        match = self._ensure_detail(match)
        entry = ftir_analysis.find_entry(self.database, match["name"])
        self._current_match = match
        self._current_match_entry = entry
        self._current_match_trace = self.active_id
        self._current_pattern_r = None
        if entry and t is not None and is_weighted(match):
            self._current_pattern_r = ftir_matching.pattern_correlation(entry, t.x, t.y, mode=self.mode())
        self._render_evidence()
        if entry:
            overlay = {"label": match["name"], "peaks": entry["peaks"],
                       "trace_label": t.label if t is not None and len(self.traces) > 1 else ""}
            if is_weighted(match):
                overlay["bands"] = match.get("bands", [])
                overlay["tier"] = match.get("tier")
                if t is not None and len(t.x):
                    overlay["synthetic"] = (t.x, ftir_matching.synthetic_reference_spectrum(entry, t.x))
            self.set_reference_overlay(overlay)
        else:
            self.clear_reference_overlay()

    def clear_reference_overlay(self):
        self._current_match_trace = None if self.reference_overlay is None else self._current_match_trace
        super().clear_reference_overlay()

    def show_all_components(self):
        t = self.get_active()
        mix = t.metadata.get("mixture") if t is not None else None
        comps = (mix or {}).get("components", [])
        if not comps:
            self.app.notify("Analyse as mixture first.", "warning")
            return
        layers = [{"label": c["name"], "bands": c.get("bands", []), "colour": COMPONENT_COLOURS[i % 3]}
                  for i, c in enumerate(comps)]
        self._current_match_trace = self.active_id
        self.set_reference_overlay({"layers": layers, "trace_label": t.label if len(self.traces) > 1 else ""})

    def set_verdict(self, status):
        t = self.get_active()
        if t is None or self._current_match is None:
            self.app.notify("Click a candidate first.", "warning")
            return
        name = self._current_match["name"]
        verdicts = self.verdicts(t)
        if status is None:
            if verdicts.pop(name, None) is None:
                return
            self.app.notify(f"Verdict cleared for {name}", "info")
        else:
            v = ui_common.ask_fields(self, f"Mark as {status}", [("note", "Note (e.g. compared with SDBS no. …):", "")],
                                     f"Record that you have {status} {name}. It is saved in the session and "
                                     "printed in the PDF and Excel exports.")
            if v is None:
                return
            verdicts[name] = {"status": status, "note": v.get("note", "").strip(),
                              "date": datetime.date.today().isoformat()}
            self.app.notify(f"{name} marked {status}", "success")
        self._refresh_matches_table()
        self._render_evidence()
        self.record(f"verdict {name}")

    # ---------------------------------------------------------------- actions
    def _clear_results(self, t):
        """Peaks changed: every result derived from the old peak list is now wrong."""
        had = bool(t.matches or t.fg_hits or t.metadata.get("mixture"))
        t.matches, t.fg_hits = [], []
        for key in ("mixture", "match_params", "mixture_params"):
            t.metadata.pop(key, None)
        self._reset_current_match()
        return had

    def detect_peaks(self, record=True):
        t = self.require_active("Load a spectrum first.")
        if t is None:
            return
        prom_frac = self.prom_spin.value() / 100.0
        kwargs = {"prominence_frac": prom_frac, "mode": self.mode(), "noise_floor": self.noise_check.isChecked(),
                  "exclude_regions": [ftir_analysis.CO2_REGION] if self.co2_check.isChecked() else None}
        if self.shoulder_check.isChecked():
            t.peaks = ftir_analysis.detect_peaks_second_derivative(t.x, t.y, **kwargs)
        else:
            t.peaks = ftir_analysis.detect_peaks(t.x, t.y, **kwargs)
        t.fits = []
        had = self._clear_results(t)
        t.metadata["detection"] = {"prominence_pct": self.prom_spin.value(), "mode": self.mode(),
                                   "noise_floor": self.noise_check.isChecked(), "skip_co2": self.co2_check.isChecked(),
                                   "shoulders": self.shoulder_check.isChecked()}
        self.redraw()
        self.on_active_trace_changed()
        self.results_tabs.setCurrentWidget(self.peaks_table)
        msg = f"Detected {len(t.peaks)} peaks in {t.label}"
        level = "success" if t.peaks else "warning"
        if len(t.peaks) > 60:
            msg += " — many peaks: smooth the spectrum or lower the sensitivity before matching"
            level = "warning"
        elif had:
            msg += " — run Match to database again"
        self.app.notify(msg, level)
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
        self.app.cfg["ftir_min_score"] = self.min_conf_spin.value()
        label_to_key = {v: k for k, v in ftir_analysis.CATEGORY_LABELS.items()}
        selected = self.category_combo.currentText()
        categories = None if selected == ftir_analysis.ALL_CATEGORIES_LABEL else [label_to_key[selected]]
        scope = "all categories" if categories is None else selected
        spectral_range = (float(np.min(t.x)), float(np.max(t.x))) if len(t.x) else None
        return t, list(t.peaks), tol, categories, scope, spectral_range

    def _params(self, t, tol, categories, scope, spectral_range, method):
        n = len(ftir_analysis._entries_for(self.database, categories))
        meta = self.database.get("_meta", {})
        return {"method": ftir_matching.METHOD_LABELS.get(method, method), "tolerance_cm1": tol,
                "category": scope, "materials_searched": n, "spectral_range": spectral_range,
                "hide_below": self.min_conf_spin.value(), "peaks_used": len(t.peaks),
                "detection": dict(t.metadata.get("detection") or {}),
                "processing": list(t.metadata.get("processing") or []),
                "database_version": str(meta.get("version", "")), "app_version": APP_VERSION,
                "run_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}

    def _discarded(self):
        self.app.notify("Result discarded — the spectrum changed (undo or a new session) while it was running.",
                        "warning")

    def match_database(self):
        inputs = self._match_inputs()
        if inputs is None:
            return
        t, peaks_snapshot, tol, categories, scope, spectral_range = inputs
        database, method = self.database, self.match_method()
        params = self._params(t, tol, categories, scope, spectral_range, method)

        def compute():
            return (ftir_analysis.match_peaks_to_database(peaks_snapshot, database, tolerance=tol, categories=categories,
                                                          method=method, spectral_range=spectral_range),
                    ftir_analysis.match_functional_groups(peaks_snapshot, database, tolerance=tol))

        def on_done(result):
            if not self._is_live(t):
                self._discarded()
                return
            t.matches, t.fg_hits = result
            t.metadata["match_params"] = params
            self._reset_current_match()
            self.match_filter.clear()
            self.redraw()
            self.on_active_trace_changed()
            self.results_tabs.setCurrentWidget(self.matches_page)
            msg = f"{len(t.matches)} candidate(s) in {scope}, {len(t.fg_hits)} functional-group hit(s)"
            level = "success"
            if t.matches and is_weighted(t.matches[0]):
                best = t.matches[0]
                msg += f" — best: {best['name']} ({best['tier'].lower()}, {best['confidence']:.2f})"
                if best["tier"] in ("Weak", "Poor"):
                    msg += (". No convincing match: check baseline/ATR correction, try a category or a wider "
                            "tolerance, try Analyse as mixture — or the material is not among the "
                            f"{self.n_materials} entries (compare with NIST WebBook / SDBS)")
                    level = "warning"
            elif not t.matches:
                msg = "No candidates — the material may not be in the database (compare with NIST WebBook / SDBS)"
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
        params = self._params(t, tol, categories, scope, spectral_range, ftir_matching.METHOD_WEIGHTED)

        def compute():
            return ftir_analysis.analyse_mixture(peaks_snapshot, database, tolerance=tol, categories=categories,
                                                 spectral_range=spectral_range)

        def on_done(result):
            if not self._is_live(t):
                self._discarded()
                return
            t.metadata["mixture"] = result
            params["mixture_floor"] = result.get("min_confidence")
            t.metadata["mixture_params"] = params
            self.on_active_trace_changed()
            self.results_tabs.setCurrentWidget(self.mixture_page)
            comps = result["components"]
            if comps:
                self.app.notify(f"Mixture screening in {scope}: " + " + ".join(c["name"] for c in comps)
                                + f" ({result['explained_share'] * 100:.0f}% of peak intensity explained)", "success")
                self.show_all_components()
            else:
                self.app.notify("No component reached the score floor — the sample may not be in the "
                                "database (compare with NIST WebBook / SDBS)", "warning")
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
        had = self._clear_results(t)
        log = [] if title == "Baseline correction" else list(t.metadata.get("processing") or [])
        log.append(title + (" (" + ", ".join(f"{k}={v}" for k, v in values.items()) + ")" if values else ""))
        t.metadata["processing"] = log
        self.redraw()
        self.on_active_trace_changed()
        self.app.notify(done_message(t, values) + (" — peaks and matches cleared" if had else ""), "success")
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
            lambda t, v: f"Linear baseline removed from {t.label} (from raw data; earlier processing undone) "
                         "— detect peaks again")

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
        for key in ("processing", "match_params", "mixture_params", "detection"):
            t.metadata.pop(key, None)
        self._reset_current_match()
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
            if not self._is_live(t):
                self._discarded()
                return
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
        entry, match = self._current_match_entry, self._ensure_detail(self._current_match)
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
        e = html.escape
        params = exports.match_parameter_rows(t)
        if params:
            sections.append(("Method &amp; parameters", [["Parameter", "Value"]] + [[str(k), str(v)] for k, v in params],
                             None))
        if t.matches:
            rows = [["#", "Material", "Match score", "Bands found", "Peaks explained", "Chance p", "Verdict"]]
            verdicts = self.verdicts(t)
            for i, m in enumerate(t.matches[:12], 1):
                explained = f"{m['reverse_score'] * 100:.0f}%" if is_weighted(m) else "-"
                rows.append([str(i), m["name"], self.score_text(m), f"{m['matched_count']}/{m['total_reference_peaks']}",
                             explained, format_probability(m.get("family_chance_probability")).replace("—", "-"),
                             verdicts.get(m["name"], {}).get("status", "")])
            sections.append(("Database screening (not identification)", rows, None))
            chosen = self._current_match if self._current_match_trace == self.active_id and self._current_match else None
            chosen = chosen or t.matches[0]
            sections.append((f"Evidence: {e(chosen['name'])}", None, e(self.evidence_text(chosen))))
        mixture = t.metadata.get("mixture") or {}
        if mixture.get("components"):
            rows = [["Component", "Match score", "Peaks explained", "Share of peak intensity*"]]
            rows += [[c["name"], self.score_text(c), str(len(c.get("explained_peak_ids", []))),
                      f"{c.get('share', 0) * 100:.0f}%"] for c in mixture["components"]]
            sections.append(("Mixture screening", rows, None))
            notes = ["* Fraction of summed peak prominence, not a concentration."]
            for c in mixture["components"]:
                notes += ["", *evidence_lines(c, ftir_analysis.find_entry(self.database, c["name"]))]
            sections.append(("Mixture evidence", None, e("\n".join(notes))))
        verdicts = {k: v for k, v in self.verdicts(t).items()}
        if verdicts:
            rows = [["Material", "Verdict", "Date", "Note"]]
            rows += [[k, v["status"], v["date"], v.get("note", "")] for k, v in verdicts.items()]
            sections.append(("Analyst verdicts", rows, None))
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
            disclaimer = (self.database.get("_meta", {}).get("note", "") + " Database screening scores are "
                          "heuristic; the scoring was tested on synthetic data only and is not yet validated on lab "
                          "spectra of known materials (docs/FTIR_MATCHING_PLAN.md).")
            report_export.build_report(path, "FTIR Analysis Report", f"Mode: {self.mode()}  |  App v{APP_VERSION}",
                                       tmp_png, sections, e(disclaimer), source_file=t.label)
        except PermissionError:
            ui_common.show_message(self, "Export failed", "That PDF is open in another program — close it and try again.", "error")
            return None
        except Exception as exc:  # noqa: BLE001
            ui_common.show_message(self, "Export failed", str(exc), "error")
            return None
        self.app.notify(f"Report saved to {os.path.basename(path)}", "success")
        return path
