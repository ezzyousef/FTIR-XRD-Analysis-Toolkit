"""
recipes.py
Reproducible FTIR processing recipes and batch processing.

A recipe is an ordered list of named steps with their parameters, saved as JSON
("ftir-xrd-recipe/1"). Applying it to a spectrum runs the same functions as the buttons in the
app, in order, and returns the processed curve with a log line per step. Batch processing applies
one recipe to many files, detects peaks with stated settings, and writes a CSV summary plus a
provenance file (input file names, sizes and SHA-256 digests, recipe, app version) beside it.
The raw files are never modified.
"""
import csv
import json
import os

import numpy as np

try:
    import ftir_analysis
    import file_readers
except ImportError:  # pragma: no cover
    from modules import ftir_analysis, file_readers

FORMAT = "ftir-xrd-recipe/1"


def _smooth(x, y, window_length=11, polyorder=3):
    return ftir_analysis.smooth_spectrum(y, window_length=int(window_length), polyorder=int(polyorder))


def _baseline(x, y, anchors=None):
    return ftir_analysis.baseline_correct(x, y, anchor_points=anchors)[0]


def _normalize(x, y, method="max"):
    return ftir_analysis.normalize_spectrum(y, method=method, x=x)


def _to_absorbance(x, y):
    return ftir_analysis.transmittance_to_absorbance(y)


def _atr(x, y, crystal="diamond", angle_deg=45.0, n_sample=1.5, reference_wavenumber=1000.0):
    return ftir_analysis.atr_correction(x, y, crystal=crystal, angle_deg=float(angle_deg), n_sample=float(n_sample),
                                        reference_wavenumber=float(reference_wavenumber))


def _derivative(x, y, order=2, window_length=15, polyorder=3):
    return ftir_analysis.derivative_spectrum(x, y, order=int(order), window_length=int(window_length),
                                             polyorder=int(polyorder))


def _crop(x, y, low=None, high=None):
    return y   # handled in apply_recipe, because it changes x as well


STEPS = {
    "crop": (_crop, {"low": None, "high": None}, "Keep {low}–{high} cm⁻¹"),
    "to_absorbance": (_to_absorbance, {}, "%T → absorbance, A = 2 − log10(%T)"),
    "atr": (_atr, {"crystal": "diamond", "angle_deg": 45.0, "n_sample": 1.5, "reference_wavenumber": 1000.0},
            "ATR correction ({crystal}, {angle_deg}°)"),
    "smooth": (_smooth, {"window_length": 11, "polyorder": 3}, "Savitzky–Golay smoothing, window {window_length}, order {polyorder}"),
    "baseline": (_baseline, {"anchors": None}, "Linear baseline (anchors {anchors})"),
    "normalize": (_normalize, {"method": "max"}, "Normalization ({method})"),
    "derivative": (_derivative, {"order": 2, "window_length": 15, "polyorder": 3}, "Derivative order {order}"),
}


def make_recipe(name, steps, peak_settings=None, notes=""):
    """steps: [(op, {params})]. Unknown operations or parameters are refused now, not at run time."""
    out = []
    for op, params in steps:
        if op not in STEPS:
            raise ValueError(f"Unknown recipe step {op!r}. Known: {', '.join(STEPS)}.")
        defaults = STEPS[op][1]
        unknown = set(params or {}) - set(defaults)
        if unknown:
            raise ValueError(f"Step {op!r} has unknown parameter(s): {', '.join(sorted(unknown))}.")
        merged = dict(defaults)
        merged.update(params or {})
        out.append({"op": op, "params": merged})
    return {"format": FORMAT, "name": str(name), "steps": out, "notes": str(notes),
            "peak_settings": dict(peak_settings or {"prominence_frac": 0.02, "noise_floor": True, "mode": "absorbance"})}


def describe(step):
    params = {k: ("ends" if v is None else v) for k, v in step["params"].items()}
    return STEPS[step["op"]][2].format(**params)


def save_recipe(recipe, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(recipe, f, indent=2, ensure_ascii=False)


def load_recipe(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError(f"Not a recipe file (expected format {FORMAT!r}).")
    return make_recipe(data.get("name", ""), [(s.get("op"), s.get("params")) for s in data.get("steps", [])],
                       data.get("peak_settings"), data.get("notes", ""))


def apply_recipe(x, y, recipe):
    """Returns (x, y, log). The input arrays are not modified."""
    x = np.array(x, dtype=float)
    y = np.array(y, dtype=float)
    log = []
    for step in recipe["steps"]:
        op, params = step["op"], step["params"]
        if op == "crop":
            lo = -np.inf if params.get("low") is None else float(params["low"])
            hi = np.inf if params.get("high") is None else float(params["high"])
            keep = (x >= min(lo, hi)) & (x <= max(lo, hi))
            if keep.sum() < 5:
                raise ValueError(f"Crop {lo}–{hi} leaves fewer than 5 points.")
            x, y = x[keep], y[keep]
        else:
            y = np.asarray(STEPS[op][0](x, y, **params), dtype=float)
        log.append(describe(step))
    return x, y, log


def process_file(path, recipe, reader=None):
    reader = reader or file_readers.read_ftir_any
    data = reader(path)
    x, y, log = apply_recipe(data.x, data.y, recipe)
    ps = recipe.get("peak_settings") or {}
    mode = ps.get("mode", "absorbance")
    if any(s["op"] in ("to_absorbance",) for s in recipe["steps"]):
        mode = "absorbance"
    peaks = ftir_analysis.detect_peaks(x, y, prominence_frac=float(ps.get("prominence_frac", 0.02)), mode=mode,
                                       noise_floor=bool(ps.get("noise_floor", True)),
                                       exclude_regions=[ftir_analysis.CO2_REGION])
    return {"file": os.path.basename(path), "x": x, "y": y, "log": log, "peaks": peaks,
            "warning": data.metadata.get("warning", "")}


def run_batch(paths, recipe, out_csv, app_name="FTIR & XRD Analysis Toolkit", app_version="", reader=None):
    """Process every file; one failing file does not stop the rest. Writes out_csv (one row per
    peak, plus a row per failed file) and out_csv.provenance.json. Returns the per-file results."""
    results = []
    for p in paths:
        try:
            results.append(process_file(p, recipe, reader))
        except Exception as exc:  # noqa: BLE001 - recorded in the report
            results.append({"file": os.path.basename(p), "error": str(exc), "peaks": [], "log": []})
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["File", "Status", "Peak (cm-1)", "Height", "Prominence", "FWHM (cm-1)", "Processing"])
        for r in results:
            if r.get("error"):
                w.writerow([r["file"], "FAILED: " + r["error"], "", "", "", "", ""])
                continue
            status = "ok" + (f" ({r['warning']})" if r.get("warning") else "")
            if not r["peaks"]:
                w.writerow([r["file"], status + "; no peaks", "", "", "", "", " | ".join(r["log"])])
            for pk in r["peaks"]:
                w.writerow([r["file"], status, f"{pk['x']:.2f}", f"{pk['y']:.6g}", f"{pk['prominence']:.6g}",
                            f"{pk['fwhm_cm1']:.2f}", " | ".join(r["log"])])
    try:
        from labkit.io import Provenance
        prov = Provenance(app_name, app_version, method="Batch processing recipe: " + recipe["name"],
                          parameters={"recipe": recipe})
        for p in paths:
            if os.path.isfile(p):
                prov.add_source(p)
        prov.write_beside(out_csv)
    except ImportError:  # labkit older than 1.2.0
        pass
    return results
