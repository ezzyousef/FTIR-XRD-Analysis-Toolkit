"""
workbench.py
Menu actions for the 3.4 tools: validation laboratory, processing recipes and batch runs,
global peak fitting, peak assignments, XRD calibration / indexing / phase-card checks /
pattern warnings / export for refinement, and the sample evidence report.

Every action reads the traces already loaded, writes only files the user picks, and shows
its result in a dialog that can be saved. Nothing is sent anywhere.
"""
import json
import os

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout)

import app_info
import ui_common


# ------------------------------------------------------------------------------- report dialog
class ReportDialog(QDialog):
    """Read-only text with Save… and Close. Keyboard: Esc closes, Ctrl+S saves."""

    def __init__(self, parent, title, text, default_name="report.md", file_filter="Markdown (*.md);;Text (*.txt)"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 600)
        self.text = text
        lay = QVBoxLayout(self)
        self.view = QPlainTextEdit(text)
        self.view.setReadOnly(True)
        self.view.setAccessibleName(title)
        self.view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        lay.addWidget(self.view)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Save).setShortcut("Ctrl+S")
        buttons.accepted.connect(lambda: self.save(default_name, file_filter))
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def save(self, default_name, file_filter):
        path = ui_common.get_save_path(self, "Save report", default_name, file_filter)
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text)
            self.saved_path = path


def show_report(parent, title, text, default_name="report.md"):
    dlg = ReportDialog(parent, title, text, default_name)
    dlg.setAttribute(Qt.WA_DeleteOnClose)
    dlg.show()
    return dlg


# ------------------------------------------------------------------------------- FTIR tools
def run_validation_lab(app, manifest_path=None):
    import validation_lab
    path = manifest_path or next(iter(ui_common.get_open_paths(app, "Validation manifest (CSV)", "CSV (*.csv)")), None)
    if not path:
        return None
    try:
        items = validation_lab.load_manifest(path)
        report = validation_lab.run_validation(items, app.ftir_db)
    except Exception as exc:  # noqa: BLE001 - shown to the user
        ui_common.show_message(app, "Validation laboratory", str(exc), "error")
        return None
    return show_report(app, "Validation laboratory", validation_lab.report_markdown(report), "validation_report.md")


def edit_recipe(app, defaults=None):
    """A recipe from a short form; saved as JSON. Returns the recipe or None."""
    import recipes
    d = {"low": "", "high": "", "to_abs": "no", "smooth": "11", "baseline": "yes", "normalize": "none",
         "mode": "absorbance", "name": "My recipe"}
    d.update(defaults or {})
    v = ui_common.ask_fields(app, "Processing recipe", [
        ("name", "Name:", d["name"]),
        ("low", "Keep from (cm⁻¹, empty = all):", d["low"]),
        ("high", "Keep to (cm⁻¹, empty = all):", d["high"]),
        ("to_abs", "Convert %T to absorbance:", d["to_abs"], ["no", "yes"]),
        ("smooth", "Smoothing window (0 = none):", d["smooth"]),
        ("baseline", "Linear baseline:", d["baseline"], ["yes", "no"]),
        ("normalize", "Normalization:", d["normalize"], ["none", "max", "minmax", "area", "vector"]),
        ("mode", "Peaks are measured on:", d["mode"], ["absorbance", "transmittance"]),
    ], help_text="Steps run in the order listed. The same recipe gives the same result on every file.")
    if v is None:
        return None
    steps = []
    try:
        low = float(v["low"]) if v["low"].strip() else None
        high = float(v["high"]) if v["high"].strip() else None
        if low is not None or high is not None:
            steps.append(("crop", {"low": low, "high": high}))
        if v["to_abs"] == "yes":
            steps.append(("to_absorbance", {}))
        win = int(float(v["smooth"] or 0))
        if win > 0:
            steps.append(("smooth", {"window_length": win}))
        if v["baseline"] == "yes":
            steps.append(("baseline", {}))
        if v["normalize"] != "none":
            steps.append(("normalize", {"method": v["normalize"]}))
    except ValueError as exc:
        ui_common.show_message(app, "Processing recipe", f"Not a number: {exc}", "error")
        return None
    return recipes.make_recipe(v["name"], steps, {"prominence_frac": 0.02, "noise_floor": True, "mode": v["mode"]})


def save_recipe_dialog(app):
    import recipes
    r = edit_recipe(app)
    if r is None:
        return None
    path = ui_common.get_save_path(app, "Save recipe", f"{r['name']}.recipe.json", "Recipe (*.recipe.json *.json)")
    if path:
        recipes.save_recipe(r, path)
        app.notify(f"Recipe saved: {os.path.basename(path)}")
    return r


def batch_dialog(app, recipe_path=None, files=None, out_csv=None):
    import recipes
    if recipe_path is None:
        recipe_path = next(iter(ui_common.get_open_paths(app, "Recipe to apply", "Recipe (*.json)")), None)
    if not recipe_path:
        return None
    try:
        recipe = recipes.load_recipe(recipe_path)
    except Exception as exc:  # noqa: BLE001
        ui_common.show_message(app, "Batch processing", str(exc), "error")
        return None
    files = files or ui_common.get_open_paths(app, "Spectra to process", "Spectra (*.csv *.txt *.dat *.xy *.dpt *.jdx *.dx)")
    if not files:
        return None
    out_csv = out_csv or ui_common.get_save_path(app, "Batch summary", "batch_summary.csv", "CSV (*.csv)")
    if not out_csv:
        return None
    results = recipes.run_batch(files, recipe, out_csv, app_version=app_info.APP_VERSION)
    failed = [r for r in results if r.get("error")]
    text = (f"Recipe '{recipe['name']}': " + " → ".join(recipes.describe(s) for s in recipe["steps"]) + "\n\n"
            + "\n".join(f"{r['file']}: " + (f"FAILED — {r['error']}" if r.get("error") else f"{len(r['peaks'])} peaks"
                                            + (f" ({r['warning']})" if r.get("warning") else ""))
                        for r in results)
            + f"\n\nSummary written to {out_csv} (with a .provenance.json beside it). Raw files were not changed.")
    app.notify(f"Batch: {len(results) - len(failed)} of {len(results)} files processed",
               "warning" if failed else "info")
    return show_report(app, "Batch processing", text, "batch_log.txt")


def global_fit_active(tab, robust=True, shape="gaussian", x_range=None):
    """Fit all peaks of the active FTIR spectrum inside a range at once."""
    import global_fit
    t = tab.require_active("Load a spectrum and detect peaks first.")
    if t is None:
        return None
    if x_range is None:
        lo_d = min((p["x"] for p in t.peaks), default=float(np.min(t.x)))
        hi_d = max((p["x"] for p in t.peaks), default=float(np.max(t.x)))
        v = ui_common.ask_fields(tab, "Global peak fit", [
            ("lo", "From (cm⁻¹):", f"{lo_d - 30:.0f}"), ("hi", "To (cm⁻¹):", f"{hi_d + 30:.0f}"),
            ("shape", "Shape:", shape, ["gaussian", "lorentzian", "pseudo_voigt"]),
            ("robust", "Robust to spikes:", "yes" if robust else "no", ["yes", "no"]),
            ("shift", "Max. centre shift (cm⁻¹):", "10")],
            help_text="All peaks in the range are fitted together on a straight baseline; errors are 1σ.")
        if v is None:
            return None
        x_range = (float(v["lo"]), float(v["hi"]))
        shape, robust, max_shift = v["shape"], v["robust"] == "yes", float(v["shift"])
    else:
        max_shift = 10.0
    seeds = [p["x"] for p in t.peaks if min(x_range) <= p["x"] <= max(x_range)]
    if not seeds:
        tab.app.notify("No peaks in that range: detect or add peaks first.", "warning")
        return None
    try:
        fit = global_fit.fit_peaks_global(t.x, t.y, seeds, shape=shape, x_range=x_range, max_shift=max_shift,
                                          loss="soft_l1" if robust else "linear")
    except Exception as exc:  # noqa: BLE001
        ui_common.show_message(tab, "Global peak fit", str(exc), "error")
        return None
    public = {k: v for k, v in fit.items() if not k.startswith("_") and k != "cov"}
    t.metadata["global_fit"] = public
    tab.record("global fit")
    lines = [f"Global {shape} fit, {len(seeds)} peaks, {x_range[0]:g}–{x_range[1]:g} cm⁻¹, loss {fit['loss']}, "
             f"R² {fit['r_squared']:.5f}, RMSE {fit['rmse']:.3g}", "",
             "Centre (cm⁻¹)        FWHM (cm⁻¹)        Height             Area"]
    for p in fit["peaks"]:
        se = p["stderr"]
        lines.append(f"{p['center']:.2f} ± {se['center']:.2f}   {p['fwhm']:.2f} ± {se['fwhm']:.2f}   "
                     f"{p['height']:.4g} ± {se['height']:.2g}   {p['area']:.4g}" + ("   (at a limit)" if p["at_bound"] else ""))
    lines += ["", "Errors are 1σ from the fit covariance: they assume the peak count and shape are right."]
    return show_report(tab, "Global peak fit", "\n".join(lines), "global_fit.txt")


def assign_selected_peak(tab, text=None):
    """Give the selected peak (Peaks table) an assignment label; Ctrl+Z undoes it."""
    t = tab.get_active()
    table = getattr(tab, "peaks_table", None)
    row = table.currentRow() if table is not None else -1
    if t is None or row < 0 or row >= len(t.peaks):
        tab.app.notify("Select a peak in the Peaks table first.", "warning")
        return None
    peak = t.peaks[row]
    if text is None:
        pos = peak.get("x", peak.get("two_theta", 0.0))
        v = ui_common.ask_fields(tab, "Assign peak", [("a", f"Assignment for {pos:.2f}:", peak.get("assignment", ""))])
        if v is None:
            return None
        text = v["a"]
    peak["assignment"] = text.strip()
    tab.record(f"assign peak {peak.get('x', peak.get('two_theta', 0.0)):.0f}")
    tab.on_active_trace_changed()
    return peak


# ------------------------------------------------------------------------------- XRD tools
def _xrd(app):
    tab = app.page("xrd")
    t = tab.require_active("Load an XRD pattern first.")
    return tab, t


def xrd_calibrate(app, certified_d=None, displacement=None):
    import xrd_tools
    tab, t = _xrd(app)
    if t is None:
        return None
    if not t.peaks:
        app.notify("Detect the standard's peaks first.", "warning")
        return None
    obs = [p["two_theta"] for p in t.peaks]
    if certified_d is None:
        v = ui_common.ask_fields(tab, "Calibrate with a standard", [
            ("d", "Certified d-spacings (Å), one per detected peak, in order:", ""),
            ("disp", "Model:", "zero shift", ["zero shift", "zero shift + displacement"])],
            help_text=f"Detected peaks: {', '.join(f'{x:.3f}°' for x in obs)}. Enter the d-values from the "
                      "standard's certificate (e.g. a NIST SRM certificate). No values are built in.")
        if v is None:
            return None
        try:
            certified_d = [float(s) for s in v["d"].replace(";", " ").replace(",", " ").split()]
        except ValueError:
            ui_common.show_message(tab, "Calibrate", "The d-spacings must be numbers.", "error")
            return None
        displacement = v["disp"] != "zero shift"
    try:
        cal = xrd_tools.calibrate(obs[:len(certified_d)], certified_d, tab.get_wavelength(), bool(displacement))
    except ValueError as exc:
        ui_common.show_message(tab, "Calibrate", str(exc), "error")
        return None
    tab.metadata_calibration = cal
    t.metadata["calibration"] = cal
    tab.record("calibrate")
    text = (f"Model: {cal['model']}\nZero shift: {cal['zero_shift_deg']:+.4f}° 2θ\nDisplacement term: "
            f"{cal['displacement_deg']:+.4f}° (× cos θ)\nRMS residual: {cal['rms_deg']:.4f}° over {cal['n']} peaks\n\n"
            "Apply it to a sample pattern measured with the same set-up: corrected 2θ = 2θ − (zero + displacement·cos θ).")
    return show_report(tab, "Calibration", text, "calibration.txt")


def xrd_index_cubic(app):
    import xrd_tools
    tab, t = _xrd(app)
    if t is None or not t.peaks:
        app.notify("Detect peaks first.", "warning")
        return None
    usable = [p["two_theta"] for p in t.peaks if p.get("usable", True)][:10]
    cands = xrd_tools.index_cubic(usable, tab.get_wavelength())
    if not cands:
        text = "No cubic indexing fits these peaks within 2 %. The phase may not be cubic, or a peak belongs to another phase."
    else:
        text = "Candidates (check them; this is not an indexing result):\n\n" + "\n\n".join(
            f"a = {c['a']:.4f} ± {c['a_sd']:.4f} Å, lattices consistent: {', '.join(c['lattices_consistent'])}, "
            f"rms misfit {c['rms_misfit']:.3f}\n" + ", ".join(f"{tt:.2f}° → ({''.join(map(str, h))})"
                                                            for tt, h in zip(c["two_theta"], c["hkl"]))
            for c in cands)
    return show_report(tab, "Cubic indexing helper", text, "indexing.txt")


def xrd_phase_card(app, card_path=None):
    import xrd_tools
    tab, t = _xrd(app)
    if t is None or not t.peaks:
        app.notify("Detect peaks first.", "warning")
        return None
    card_path = card_path or next(iter(ui_common.get_open_paths(tab, "Phase card (CSV) from your licensed source",
                                                                   "CSV (*.csv)")), None)
    if not card_path:
        return None
    try:
        card = xrd_tools.load_phase_card(card_path)
    except (OSError, ValueError) as exc:
        ui_common.show_message(tab, "Phase card", str(exc), "error")
        return None
    r = xrd_tools.cross_check_card([p["two_theta"] for p in t.peaks], [p["intensity"] for p in t.peaks], card,
                                   tab.get_wavelength(), measured_range=(float(np.min(t.x)), float(np.max(t.x))))
    lines = [f"Card: {r['card'] or os.path.basename(card_path)}" + (f" — source: {r['source']}" if r["source"] else ""),
             f"Verdict: {r['verdict']}", f"Strong card lines found: {100 * r['fraction_found']:.0f} %, mean |Δ2θ| "
             f"{r['mean_abs_delta_deg']:.3f}°", ""]
    lines += [f"  {m['card_two_theta']:.3f}° ({m['hkl']}) ↔ {m['observed_two_theta']:.3f}°" for m in r["matched"]]
    if r["missing_strong"]:
        lines += ["", "Missing card lines: " + ", ".join(f"{m['card_two_theta']:.2f}° (I={m['card_intensity']:g})"
                                                       for m in r["missing_strong"])]
    if r["unexplained_peaks"]:
        lines += ["", "Peaks the card does not explain: " + ", ".join(f"{x:.2f}°" for x in r["unexplained_peaks"])]
    lines += [""] + r["warnings"] + ["", r["caveat"]]
    return show_report(tab, "Phase-card cross-check", "\n".join(lines), "phase_card_check.txt")


def xrd_pattern_warnings(app):
    import xrd_analysis
    import xrd_tools
    tab, t = _xrd(app)
    if t is None:
        return None
    bg = xrd_analysis.snip_background(t.y, iterations=xrd_analysis.snip_iterations(t.x, 3.0))
    w = xrd_tools.amorphous_background_warning(t.x, t.y, bg)
    text = (f"Background share of the integrated intensity: {100 * w['background_fraction']:.0f} %\n"
            f"Largest rise of the background over a straight line: ×{w['hump_ratio']:.2f}\n\n"
            + ("\n\n".join(w["warnings"]) if w["warnings"] else "No amorphous-background warning for this pattern.")
            + "\n\nBackground: SNIP with a 3° window. Preferred orientation is checked when you cross-check a phase card.")
    return show_report(tab, "Pattern warnings", text, "pattern_warnings.txt")


def xrd_export_refinement(app, path=None):
    import refinement_export
    tab, t = _xrd(app)
    if t is None:
        return None
    processed = bool(t.metadata.get("processing")) or not np.array_equal(t.y, t.y_raw)
    if processed:
        app.notify("The pattern has been processed: exporting the RAW counts, which keep their √N uncertainties.",
                   "warning")
    path = path or ui_common.get_save_path(tab, "Export for refinement", os.path.splitext(t.label)[0] + ".xye",
                                           "xye (*.xye)")
    if not path:
        return None
    info = refinement_export.export_for_refinement(path, t.x, t.y_raw, tab.get_wavelength(),
                                                   source_path=t.metadata.get("path"), processing=[],
                                                   app_version=app_info.APP_VERSION)
    app.notify(f"Wrote {os.path.basename(path)} ({info['points']} points, σ = √counts). No refinement was run.")
    return info


# ------------------------------------------------------------------------------- evidence
def evidence_report(app, sample_id=None, path=None, assumptions=None):
    import evidence
    ftir = app.page("ftir").get_active() if app.is_page_built("ftir") else None
    xrd_tab = app.page("xrd") if app.is_page_built("xrd") else None
    xrd = xrd_tab.get_active() if xrd_tab is not None else None
    if ftir is None and xrd is None:
        app.notify("Load an FTIR spectrum, an XRD pattern, or both, first.", "warning")
        return None
    if sample_id is None:
        v = ui_common.ask_fields(app, "Sample evidence report", [
            ("id", "Sample ID:", ""), ("assume", "Assumptions (separate with ;):", ""), ("notes", "Notes:", "")],
            help_text=f"Links FTIR: {ftir.label if ftir else '—'} and XRD: {xrd.label if xrd else '—'} (the active "
                      "trace on each page).",
            validate=lambda vals: None if vals["id"].strip() else ("Give the sample an ID.", "id"))
        if v is None:
            return None
        sample_id, assumptions, notes = v["id"], [a for a in v["assume"].split(";")], v["notes"]
    else:
        notes = ""
    results = {}
    if xrd is not None:
        wh = xrd.metadata.get("wh_result")
        if wh and wh.get("crystallite_size_nm"):
            results["Williamson–Hall size (nm)"] = f"{wh['crystallite_size_nm']:.1f}"
            results["Microstrain"] = f"{wh['microstrain']:.2e}"
        if xrd.metadata.get("crystallinity_pct") is not None:
            results["Crystallinity (%, area method)"] = f"{xrd.metadata['crystallinity_pct']:.1f}"
    db_meta = (getattr(app, "ftir_db", {}) or {}).get("_meta", {})
    rec = evidence.build_record(sample_id, ftir, xrd, wavelength_a=xrd_tab.get_wavelength() if xrd else None,
                                assumptions=assumptions or [], notes=notes, app_version=app_info.APP_VERSION,
                                database_version=str(db_meta.get("version", "")), xrd_results=results,
                                references=sorted({m.get("source", "") for m in (ftir.matches[:5] if ftir else [])
                                                   if m.get("source")}))
    path = path or ui_common.get_save_path(app, "Save evidence report", f"{sample_id}_evidence.html", "HTML (*.html)")
    if not path:
        return None
    evidence.write_report(rec, path)
    evidence.save_record(rec, os.path.splitext(path)[0] + ".json")
    app.notify(f"Evidence report written: {os.path.basename(path)} (and its .json record)")
    return rec


# ------------------------------------------------------------------------------- display
def decimate_minmax(x, y, max_points):
    """At most ~max_points points for drawing: each bucket keeps its minimum and maximum (in
    order), so peaks and dips stay visible. Data and exports are never decimated."""
    x = np.asarray(x)
    y = np.asarray(y)
    n = len(x)
    if max_points is None or n <= max_points or max_points < 4:
        return x, y
    buckets = max_points // 2
    edges = np.linspace(0, n, buckets + 1).astype(int)
    idx = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        seg = y[a:b]
        finite = np.isfinite(seg)
        if not finite.any():
            idx.append(a)
            continue
        i_min = a + int(np.nanargmin(seg))
        i_max = a + int(np.nanargmax(seg))
        idx.extend(sorted({i_min, i_max}))
    idx = np.asarray(idx)
    return x[idx], y[idx]


def describe_cursor(kind, x, y, active=None, wavelength=None):
    """Status-bar text for the cursor: position, the active trace's value there, and the
    d-spacing for XRD."""
    parts = [f"x = {x:,.2f}", f"y = {y:,.4g}"]
    if active is not None and len(active.x) > 1:
        order = np.argsort(active.x)
        xs, ys = active.x[order], active.y[order]
        if xs[0] <= x <= xs[-1]:
            parts.append(f"{active.label}: {float(np.interp(x, xs, ys)):,.4g}")
    if kind == "xrd" and wavelength and x > 0:
        import xrd_analysis
        try:
            parts.append(f"d = {float(xrd_analysis.bragg_d_spacing(x, wavelength)):.4f} Å")
        except ValueError:
            pass
    return "    ".join(parts)


def colour_blind_palette():
    from labkit.style import PALETTES
    return list(PALETTES["publication"])          # Okabe–Ito based


def apply_palette(tab, palette):
    """Recolour every trace on a page (in load order) and use the palette for new traces."""
    import itertools
    for t, c in zip(tab.traces, itertools.cycle(palette)):
        t.color = c
    tab.color_cycle._cycle = itertools.cycle(palette)
    for _ in tab.traces:
        tab.color_cycle.next()
    tab._on_traces_changed()


PREF_DEFAULTS = {"display_max_points": 20000, "palette": "house"}


def load_preferences():
    """Preferences stored with QSettings (the same store the app uses for folded cards)."""
    from PySide6.QtCore import QSettings
    s = QSettings()
    try:
        n = int(s.value("prefs/display_max_points", PREF_DEFAULTS["display_max_points"]))
    except (TypeError, ValueError):
        n = PREF_DEFAULTS["display_max_points"]
    palette = str(s.value("prefs/palette", PREF_DEFAULTS["palette"]))
    return {"display_max_points": max(1000, n),
            "palette": palette if palette in ("house", "colour-blind") else PREF_DEFAULTS["palette"]}


def save_preferences(prefs):
    from PySide6.QtCore import QSettings
    s = QSettings()
    s.setValue("prefs/display_max_points", int(prefs["display_max_points"]))
    s.setValue("prefs/palette", prefs["palette"])
    s.sync()


def preferences_dialog(app, values=None):
    """Preferences: points drawn per curve, and the trace palette. Applied at once and kept."""
    cur = load_preferences()
    if values is None:
        def check(v):
            try:
                return None if int(v["n"]) >= 1000 else ("At least 1000 points.", "n")
            except ValueError:
                return ("A whole number, please.", "n")
        v = ui_common.ask_fields(app, "Preferences", [
            ("n", "Points drawn per curve (data keep all):", str(cur["display_max_points"])),
            ("palette", "Trace colours:", cur["palette"], ["house", "colour-blind"])], validate=check)
        if v is None:
            return None
        values = {"display_max_points": int(v["n"]), "palette": v["palette"]}
    save_preferences(values)
    from labkit.style import PALETTES
    palette = colour_blind_palette() if values["palette"] == "colour-blind" else list(PALETTES["review"])
    for key in ("ftir", "xrd"):
        if app.is_page_built(key):
            tab = app.page(key)
            tab.DISPLAY_MAX_POINTS = values["display_max_points"]
            apply_palette(tab, palette)
    app.notify("Preferences saved")
    return values


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
