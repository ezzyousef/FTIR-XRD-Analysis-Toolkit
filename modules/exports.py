"""
exports.py
The loaded traces as labkit figures, OriginLab workbooks and an Excel report.

One place builds the plot the tabs show, the graphs sent to Origin and the charts in the
Excel workbook, so all three agree by construction. No Qt imports: tested directly.
"""
from __future__ import annotations

import math

import numpy as np

import peak_fitting
from labkit.excel import ExcelAnalysis, ExcelReport, ExcelTable
from labkit.figure import FigureSpec, SeriesSpec
from labkit.origin import OriginBook

APP_NAME = "FTIR & XRD Analysis Toolkit"

AXES = {
    "ftir": {"title": "FTIR spectra", "x_label": "Wavenumber", "x_unit": "cm⁻¹", "invert_x": True},
    "xrd": {"title": "XRD patterns", "x_label": "2θ", "x_unit": "°", "invert_x": False},
}

_FIT_FUNCS = {"gaussian": peak_fitting.gaussian, "lorentzian": peak_fitting.lorentzian,
              "pseudo_voigt": peak_fitting.pseudo_voigt}


def y_axis(kind: str, mode: str = "absorbance") -> tuple[str, str]:
    if kind == "xrd":
        return "Intensity", "a.u."
    return ("Transmittance", "%") if mode == "transmittance" else ("Absorbance", "")


def evaluate_fit(fit: dict, x) -> np.ndarray:
    """One fitted peak evaluated at x."""
    x = np.asarray(x, dtype=float)
    func = _FIT_FUNCS[fit["shape"]]
    if fit["shape"] == "pseudo_voigt":
        return func(x, fit["height"], fit["center"], fit["fwhm"], fit.get("eta", 0.5), fit.get("offset", 0.0))
    return func(x, fit["height"], fit["center"], fit["fwhm"], fit.get("offset", 0.0))


def composite_fit(x, fits: list[dict], y=None) -> np.ndarray | None:
    """All fitted peaks of a trace as one continuous model curve.

    Inside each peak's span (centre ± 2.5 FWHM) the model is the fitted profile — profiles
    summed where spans overlap, on the offset of the nearest peak. Outside every span it is
    the data itself (`y`), so the model line only departs from the spectrum where a fit
    exists. (Each peak is fitted in its own window with its own local offset; stretching
    those offsets across regions no fit covers would draw a baseline nobody measured.)
    Without `y`, uncovered points take the offset of the nearest peak.
    """
    if not fits:
        return None
    x = np.asarray(x, dtype=float)
    covered = np.zeros(x.shape, dtype=bool)
    excess = np.zeros(x.shape, dtype=float)
    local_offset = np.zeros(x.shape, dtype=float)
    best = np.full(x.shape, np.inf)
    for fit in fits:
        centre, fwhm, offset = float(fit["center"]), abs(float(fit["fwhm"])), float(fit.get("offset", 0.0))
        if not (np.isfinite(centre) and np.isfinite(fwhm) and fwhm > 0):
            continue
        distance = np.abs(x - centre)
        inside = distance <= 2.5 * fwhm
        excess[inside] += evaluate_fit(fit, x[inside]) - offset
        nearer = inside & (distance < best)
        local_offset[nearer] = offset
        best[nearer] = distance[nearer]
        covered |= inside
    if y is not None:
        model = np.asarray(y, dtype=float).copy()
    else:
        ordered = sorted(fits, key=lambda f: f["center"])
        model = np.interp(x, [f["center"] for f in ordered], [f.get("offset", 0.0) for f in ordered])
    model[covered] = local_offset[covered] + excess[covered]
    return model


def spectrum_figure(kind: str, traces, active_id=None, *, mode: str = "absorbance",
                    wavelength: float | None = None, title: str = "", only=None) -> FigureSpec:
    """Every visible trace as a line in its own colour, plus the active trace's fitted peaks.

    `only`: restrict to one trace (the Excel report draws one chart per trace).
    """
    axes = AXES[kind]
    y_label, y_unit = y_axis(kind, mode)
    spec = FigureSpec(title, axes["x_label"], y_label, x_unit=axes["x_unit"], y_unit=y_unit,
                      invert_x=axes["invert_x"], name=f"{kind}_spectra")
    chosen = [only] if only is not None else [t for t in traces if t.visible]
    for t in chosen:
        spec.series.append(SeriesSpec(t.label, t.x, t.y, style="line", colour=t.color))
    fitted = only if only is not None else next((t for t in chosen if t.id == active_id), None)
    if fitted is not None and fitted.fits:
        model = composite_fit(fitted.x, fitted.fits, fitted.y)
        spec.series.append(SeriesSpec(f"{fitted.label} — fitted peaks", fitted.x, model, role="fit",
                                      style="line", parent=fitted.label, colour=fitted.color))
    return spec


def _num(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return v if math.isfinite(v) else float("nan")


def peak_columns(kind: str, trace, wavelength: float | None = None) -> dict[str, list]:
    """The detected peaks of a trace as named columns (header -> values)."""
    if not trace.peaks:
        return {}
    if kind == "ftir":
        return {
            "Peak": list(range(1, len(trace.peaks) + 1)),
            "Wavenumber (cm⁻¹)": [_num(p["x"]) for p in trace.peaks],
            "Intensity": [_num(p["y"]) for p in trace.peaks],
            "Prominence": [_num(p.get("prominence")) for p in trace.peaks],
        }
    return {
        "2θ (°)": [_num(p["two_theta"]) for p in trace.peaks],
        "Intensity": [_num(p["intensity"]) for p in trace.peaks],
        "FWHM (°)": [_num(p.get("fwhm_deg")) for p in trace.peaks],
        "d-spacing (Å)": [_num(p.get("d_A")) for p in trace.peaks],
        "Crystallite size (nm)": [_num(p.get("size_nm")) for p in trace.peaks],
    }


FIT_HEADERS = ["Seed", "Centre", "FWHM", "Height", "Area", "R²", "Shape"]


def fit_rows(trace) -> list[list]:
    return [[_num(f["seed_x"]), _num(f["center"]), _num(f["fwhm"]), _num(f["height"]),
             _num(f["area"]), _num(f["r_squared"]), f["shape"]] for f in trace.fits]


MATCH_HEADERS = ["Material", "Category", "Score (%)", "Matched peaks", "Reference peaks", "Source"]


def match_rows(trace) -> list[list]:
    return [[m["name"], m["category"], round(m["score"] * 100, 1), m["matched_count"],
             m["total_reference_peaks"], m.get("source", "")] for m in trace.matches]


def results(kind: str, trace, *, mode: str = "absorbance", wavelength: float | None = None) -> list[tuple]:
    """(quantity, value, unit, note) rows summarising one trace."""
    rows: list[tuple] = [("Data points", len(trace.x), "", ""), ("Peaks detected", len(trace.peaks), "", "")]
    if kind == "ftir":
        rows.append(("Mode", mode, "", ""))
        if trace.matches:
            best = trace.matches[0]
            rows.append(("Best database match", best["name"], "",
                         f"score {best['score'] * 100:.0f}%, {best['matched_count']}/"
                         f"{best['total_reference_peaks']} reference peaks — screening, not identification"))
        if trace.fg_hits:
            rows.append(("Functional-group hits", len(trace.fg_hits), "", ""))
    else:
        if wavelength:
            rows.append(("X-ray wavelength", float(wavelength), "Å", ""))
        sizes = [p["size_nm"] for p in trace.peaks if p.get("size_nm")]
        if sizes:
            rows.append(("Mean Scherrer crystallite size", float(np.mean(sizes)), "nm",
                         f"{len(sizes)} peaks; not corrected for instrumental broadening"))
        wh = trace.metadata.get("wh_result")
        if wh:
            if wh.get("crystallite_size_nm"):
                rows.append(("Williamson–Hall crystallite size", float(wh["crystallite_size_nm"]), "nm",
                             f"{wh.get('n_peaks', '')} peaks"))
            rows.append(("Williamson–Hall microstrain", float(wh["microstrain"]), "",
                         "" if wh.get("strain_physical", True) else "negative fit: treat as ~0"))
        pct = trace.metadata.get("crystallinity_pct")
        if pct is not None:
            regions = trace.metadata.get("crystallinity_regions", {})
            rows.append(("Crystallinity", float(pct), "%", f"regions {regions}"))
    if trace.fits:
        rows.append(("Peaks fitted", len(trace.fits), "", f"{trace.fits[0]['shape']} profile"))
    return rows


def origin_books(kind: str, traces, active_id=None, *, mode: str = "absorbance",
                 wavelength: float | None = None) -> list[OriginBook]:
    """One workbook: every visible trace in one styled graph, the active trace's peaks and results."""
    visible = [t for t in traces if t.visible]
    if not visible:
        return []
    active = next((t for t in traces if t.id == active_id), visible[-1])
    title = f"{AXES[kind]['title']} — {active.label}" if len(visible) == 1 else AXES[kind]["title"]
    figure = spectrum_figure(kind, traces, active.id, mode=mode, title=title)
    table = peak_columns(kind, active, wavelength) or None
    rows = results(kind, active, mode=mode, wavelength=wavelength)
    return [OriginBook(f"{kind.upper()} {active.label}", figures=[figure], table=table,
                       results=[r[:3] for r in rows], note=f"{APP_NAME} — {len(visible)} trace(s)")]


def excel_report(kind: str, traces, active_id=None, *, version: str = "", author: str = "",
                 settings: dict | None = None, mode: str = "absorbance",
                 wavelength: float | None = None, project: str = "") -> ExcelReport | None:
    """One analysis sheet and chart per trace, plus match and fit tables."""
    if not traces:
        return None
    analyses, tables = [], []
    for t in traces:
        analyses.append(ExcelAnalysis(
            title=t.label, group=kind.upper(),
            results=results(kind, t, mode=mode, wavelength=wavelength),
            figures=[spectrum_figure(kind, traces, t.id, mode=mode, title=t.label, only=t)],
            table=peak_columns(kind, t, wavelength) or None,
            settings=dict(settings or {}), source=str(t.metadata.get("path", ""))))
        if t.matches:
            tables.append(ExcelTable(f"Matches {t.label}", MATCH_HEADERS, match_rows(t),
                                     subtitle="Heuristic screening against the built-in reference database"))
        if t.fits:
            tables.append(ExcelTable(f"Fits {t.label}", FIT_HEADERS, fit_rows(t)))
    provenance = {"Method": "Peak detection, fitting and calculations as cited by the ⓘ buttons in the app"}
    if wavelength:
        provenance["X-ray wavelength (Å)"] = f"{wavelength:.6f}"
    return ExcelReport(APP_NAME, version, project=project or AXES[kind]["title"], author=author,
                       analyses=analyses, tables=tables, extra_provenance=provenance)
