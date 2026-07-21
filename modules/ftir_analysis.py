"""
ftir_analysis.py
FTIR peak detection, reference-database matching, and common calculations.
"""
import json
import numpy as np
# scipy is imported lazily, inside the functions that actually need it (see
# detect_peaks/peak_area/fwhm_from_peak below) rather than here at module
# level: scipy's own cold-import cost (~1-2s) would otherwise be paid every
# time this module is imported -- which happens just to build the FTIR tab's
# UI, before the user has done anything that needs scipy at all. Deferring
# it keeps the startup splash screen short; the one-time cost is paid on
# first actual "Detect Peaks" click instead, well after the window is
# already up and responsive.

try:
    from signal_utils import smooth_savgol
except ImportError:
    from modules.signal_utils import smooth_savgol

# Material categories screened by match_peaks_to_database (functional_groups is
# handled separately by match_functional_groups since it's a flat list, not
# grouped by named material).
MATERIAL_CATEGORIES = ["polymers", "hydrogels", "salts_inorganic", "inorganics_minerals", "organics_biomolecules", "elements_allotropes"]

# Friendly labels for the category filter UI -- letting the user restrict a
# search to (e.g.) just "Organic/Biomolecules" avoids cross-category false
# positives (a polymer band coincidentally overlapping a salt's band) and
# speeds up the search.
CATEGORY_LABELS = {
    "polymers": "Polymers",
    "hydrogels": "Hydrogels",
    "salts_inorganic": "Salts",
    "inorganics_minerals": "Inorganic (Oxides/Minerals)",
    "organics_biomolecules": "Organic/Biomolecules",
    "elements_allotropes": "Elements/Allotropes",
}
ALL_CATEGORIES_LABEL = "All Categories"


def load_database(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_references(database):
    """Return the bibliography list ({id, citation}) embedded in the database's _meta."""
    return database.get("_meta", {}).get("references", [])


def search_database(database, query="", category=None):
    """
    Search all material entries (name substring match, case-insensitive) optionally
    filtered by category key (e.g. 'polymers'). Used by the Database Viewer UI.
    Returns a flat list of entries, each tagged with its source category key.
    """
    query = (query or "").strip().lower()
    cats = [category] if category else MATERIAL_CATEGORIES
    results = []
    for cat in cats:
        for entry in database.get(cat, []):
            if not query or query in entry["name"].lower():
                tagged = dict(entry)
                tagged["_db_category"] = cat
                results.append(tagged)
    return results


def find_entry(database, name):
    """
    Looks up a single material entry by exact name across every material
    category. Used to fetch a match result's FULL reference peak list (not
    just the subset that happened to fall within tolerance) for the
    "overlay this material's reference peaks on my plot" comparison
    feature. Returns None if not found.

    Note: match_peaks_to_database's "category" field is the entry's
    descriptive tag (e.g. "polymer", "salt"), not a MATERIAL_CATEGORIES
    dict key (e.g. "polymers", "salts_inorganic") -- so this deliberately
    doesn't take a category filter and just searches everything, which is
    safe since material names are unique across the whole database.
    """
    for cat in MATERIAL_CATEGORIES:
        for entry in database.get(cat, []):
            if entry["name"] == name:
                return entry
    return None


def smooth_spectrum(y, window_length=11, polyorder=3):
    """Savitzky-Golay smoothing wrapper (see signal_utils.smooth_savgol)."""
    return smooth_savgol(y, window_length=window_length, polyorder=polyorder)


def detect_peaks(x, y, prominence_frac=0.02, min_distance_pts=3, mode="absorbance"):
    """
    Detect peaks in a spectrum.
    mode: "absorbance" (peaks point up) or "transmittance" (peaks point down -> invert first).
    prominence_frac: required peak prominence as a fraction of the y-range.
    Returns list of dicts: {index, x, y, prominence, fwhm}
    """
    from scipy.signal import find_peaks, peak_widths

    y_work = np.asarray(y, dtype=float)
    if mode == "transmittance":
        y_work = y_work.max() - y_work  # invert so absorption dips become peaks

    y_range = y_work.max() - y_work.min()
    prominence = max(prominence_frac * y_range, 1e-9)

    idx, props = find_peaks(y_work, prominence=prominence, distance=min_distance_pts)
    widths_result = peak_widths(y_work, idx, rel_height=0.5)

    peaks = []
    for i, pk in enumerate(idx):
        peaks.append({
            "index": int(pk),
            "x": float(x[pk]),
            "y": float(y[pk]),
            "prominence": float(props["prominences"][i]),
            "fwhm_pts": float(widths_result[0][i]),
        })
    # sort by x for readability
    peaks.sort(key=lambda p: p["x"])
    return peaks


def match_peaks_to_database(peaks, database, tolerance=10.0, categories=None):
    """
    Match detected peaks against the reference database within +/- tolerance (cm-1)
    of each reference range. Returns a scored list of candidate matches per material.

    categories: optional list of category keys (from MATERIAL_CATEGORIES) to
    restrict the search to -- e.g. ["organics_biomolecules"] if you already
    know the sample isn't a polymer/salt/mineral. None or empty searches
    every category. Restricting the search reduces cross-category false
    positives and is faster.

    Scoring is a simple coverage fraction: (# reference peaks matched) / (# reference peaks total)
    for each material entry. This is a heuristic screening tool, not definitive
    identification -- always confirm with a domain expert / reference spectrum
    for anything consequential.
    """
    search_categories = [c for c in (categories or MATERIAL_CATEGORIES) if c in MATERIAL_CATEGORIES]
    if not search_categories:
        search_categories = MATERIAL_CATEGORIES

    all_entries = []
    for group in search_categories:
        for entry in database.get(group, []):
            all_entries.append(entry)

    results = []
    for entry in all_entries:
        # peaks with range [0,0] are placeholders for IR-inactive materials
        # (e.g. cubic alkali halides) and are not matchable numerically.
        matchable_peaks = [rp for rp in entry["peaks"] if not (rp["range"][0] == 0 and rp["range"][1] == 0)]
        if not matchable_peaks:
            continue
        matched = []
        for ref_peak in matchable_peaks:
            lo, hi = ref_peak["range"][0] - tolerance, ref_peak["range"][1] + tolerance
            hit = None
            best_dist = None
            for p in peaks:
                if lo <= p["x"] <= hi:
                    center = (ref_peak["range"][0] + ref_peak["range"][1]) / 2
                    dist = abs(p["x"] - center)
                    if best_dist is None or dist < best_dist:
                        best_dist = dist
                        hit = p
            if hit:
                matched.append({"reference": ref_peak, "observed": hit, "delta_cm1": hit["x"] - (ref_peak["range"][0] + ref_peak["range"][1]) / 2})
        if matched:
            score = len(matched) / len(matchable_peaks)
            results.append({
                "name": entry["name"],
                "category": entry["category"],
                "source": entry.get("source", ""),
                "score": score,
                "matched_count": len(matched),
                "total_reference_peaks": len(matchable_peaks),
                "matches": matched,
            })

    # Rank by absolute evidence (how many reference peaks corroborated the
    # match) before fractional score -- otherwise a material with only one
    # (necessarily "100% matched") reference peak outranks a material with
    # five matched peaks out of six, which is backwards: more corroborating
    # peaks is stronger evidence than a single lucky/coincidental hit.
    results.sort(key=lambda r: (r["matched_count"], r["score"]), reverse=True)
    return results


def match_functional_groups(peaks, database, tolerance=10.0):
    """Match peaks against generic functional-group ranges (broader, less specific)."""
    hits = []
    for p in peaks:
        for fg in database.get("functional_groups", []):
            lo, hi = fg["range"][0] - tolerance, fg["range"][1] + tolerance
            if lo <= p["x"] <= hi:
                hits.append({"peak_x": p["x"], "peak_y": p["y"], "group": fg["name"],
                             "range": fg["range"], "intensity_expected": fg.get("intensity", ""),
                             "source": fg.get("source", "")})
    return hits


# ---------------- Calculations ----------------

def transmittance_to_absorbance(pct_transmittance):
    """A = 2 - log10(%T). Guards against non-positive values."""
    t = np.asarray(pct_transmittance, dtype=float)
    t_clipped = np.clip(t, 1e-6, None)
    return 2 - np.log10(t_clipped)


def absorbance_to_transmittance(absorbance):
    """%T = 10^(2 - A)"""
    a = np.asarray(absorbance, dtype=float)
    return 10 ** (2 - a)


def baseline_correct(x, y, anchor_points=None):
    """
    Simple linear (or piecewise-linear) baseline subtraction.
    anchor_points: list of x-values assumed to be baseline (non-absorbing) regions.
    If None, uses the first and last points of the spectrum.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if not anchor_points or len(anchor_points) < 2:
        anchor_x = [x[0], x[-1]]
        anchor_y = [y[0], y[-1]]
    else:
        anchor_x = sorted(anchor_points)
        anchor_y = [y[np.argmin(np.abs(x - ax))] for ax in anchor_x]
    baseline = np.interp(x, anchor_x, anchor_y)
    return y - baseline, baseline


def peak_area(x, y, x_start, x_end):
    """Integrate the spectrum between x_start and x_end (trapezoidal rule)."""
    from scipy import integrate

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    lo, hi = min(x_start, x_end), max(x_start, x_end)
    mask = (x >= lo) & (x <= hi)
    if mask.sum() < 2:
        raise ValueError("Not enough points in the specified range to integrate.")
    xs, ys = x[mask], y[mask]
    order = np.argsort(xs)
    return float(integrate.trapezoid(ys[order], xs[order]))


def fwhm_from_peak(x, y, peak_index, rel_height=0.5):
    """Full width at half max (in x-units) for a given peak index."""
    from scipy.signal import peak_widths

    widths_result = peak_widths(y, [peak_index], rel_height=rel_height)
    width_pts = widths_result[0][0]
    # convert points to x-units using local spacing
    if peak_index + 1 < len(x):
        dx = abs(x[peak_index + 1] - x[peak_index])
    else:
        dx = abs(x[peak_index] - x[peak_index - 1])
    return float(width_pts * dx)


def beer_lambert_concentration(absorbance, molar_absorptivity, path_length_cm):
    """c = A / (epsilon * l).  Units of c depend on units of epsilon (typically mol/L)."""
    if molar_absorptivity <= 0 or path_length_cm <= 0:
        raise ValueError("Molar absorptivity and path length must be positive.")
    return absorbance / (molar_absorptivity * path_length_cm)


def normalize_spectrum(y, method="max", x=None):
    """
    method: 'max' (scale so peak = 1.0), 'minmax' (scale range to [0,1]),
    'area' (scale so the total absorption area = 1, requires x -- useful for
    comparing spectra recorded at different concentrations/pathlengths), or
    'vector' (scale so the Euclidean/L2 norm = 1, the standard chemometrics
    preprocessing step used before PCA/PLS/library-matching in most
    spectroscopy software).
    """
    y = np.asarray(y, dtype=float)
    if method == "max":
        return y / np.max(np.abs(y))
    elif method == "minmax":
        return (y - y.min()) / (y.max() - y.min())
    elif method == "area":
        if x is None:
            raise ValueError("Area normalization requires x-axis values.")
        from scipy.integrate import trapezoid

        area = abs(trapezoid(np.abs(y), np.asarray(x, dtype=float)))
        if area == 0:
            raise ValueError("Cannot area-normalize a zero spectrum.")
        return y / area
    elif method == "vector":
        norm = np.sqrt(np.sum(y ** 2))
        if norm == 0:
            raise ValueError("Cannot vector-normalize a zero spectrum.")
        return y / norm
    raise ValueError("method must be 'max', 'minmax', 'area', or 'vector'")


# Approximate refractive index at mid-IR wavelengths for common ATR crystal
# materials (Socrates 2001 Table A.1; manufacturer datasheets).
ATR_CRYSTAL_REFRACTIVE_INDEX = {
    "diamond": 2.4,
    "zinc selenide (znse)": 2.4,
    "znse": 2.4,
    "germanium": 4.0,
    "ge": 4.0,
    "silicon": 3.4,
    "si": 3.4,
    "krs-5 (thallium bromoiodide)": 2.37,
    "krs-5": 2.37,
}


def atr_correction(x, y, crystal="diamond", angle_deg=45.0, n_sample=1.5, reference_wavenumber=1000.0):
    """
    Standard "advanced ATR correction" (as offered by OMNIC/OPUS): rescales
    absorbance to compensate for the fact that in ATR sampling the IR
    penetration depth -- and therefore the effective pathlength/apparent
    absorbance -- is proportional to wavelength (1/wavenumber), unlike
    transmission spectra where pathlength is fixed. Raw ATR spectra therefore
    under-represent high-wavenumber bands (e.g. C-H/O-H stretches) relative to
    the fingerprint region; this correction multiplies by wavenumber (relative
    to reference_wavenumber, chosen only to keep the output on a familiar
    intensity scale) to remove that bias, making relative band intensities
    comparable to a transmission spectrum of the same material.

    This is the standard first-order correction and does NOT correct for
    anomalous dispersion (refractive-index changes near strong absorption
    bands), which requires a full Kramers-Kronig transform.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n1 = ATR_CRYSTAL_REFRACTIVE_INDEX.get(str(crystal).strip().lower(), 2.4)
    theta = np.radians(angle_deg)
    sin2theta = np.sin(theta) ** 2
    ratio2 = (n_sample / n1) ** 2
    if sin2theta <= ratio2:
        raise ValueError(
            "Total internal reflection is not satisfied for these ATR parameters "
            "(sin(angle) must exceed n_sample / n_crystal). Check the crystal, "
            "angle of incidence, and sample refractive index."
        )
    correction = np.abs(x) / float(reference_wavenumber)
    return y * correction


def derivative_spectrum(x, y, order=1, window_length=15, polyorder=3):
    """
    1st or 2nd derivative via Savitzky-Golay differentiation (Savitzky & Golay,
    Anal. Chem. 1964) -- the standard derivative-spectroscopy method offered by
    OMNIC/OPUS. Derivatives resolve overlapping bands (2nd derivative peaks are
    narrower and point-down at the original peak center) and remove sloping/
    curved baselines without amplifying high-frequency noise as much as naive
    finite differencing, because the differentiation is done on the local
    polynomial fit rather than on raw adjacent points.
    """
    from scipy.signal import savgol_filter

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if order not in (1, 2):
        raise ValueError("order must be 1 or 2.")
    window_length = int(window_length)
    if window_length % 2 == 0:
        window_length += 1
    if window_length <= polyorder:
        raise ValueError("window_length must be greater than polyorder.")
    if len(x) < 2:
        raise ValueError("Need at least 2 points to compute a derivative.")
    dx = float(np.mean(np.abs(np.diff(x))))
    return savgol_filter(y, window_length=window_length, polyorder=polyorder, deriv=order, delta=dx)
