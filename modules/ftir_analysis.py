"""
ftir_analysis.py
FTIR peak detection, reference-database matching, and common calculations.
"""
import json
import warnings

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
    import ftir_matching
except ImportError:
    from modules.signal_utils import smooth_savgol
    from modules import ftir_matching

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

# Groups for browsing the reference cards. Metal oxides and (oxy)hydroxides are a subset of
# "inorganics_minerals", tagged "group": "metal_oxide" in the database.
CARD_GROUPS = [
    ("all", "All materials"),
    ("polymers", "Polymers"),
    ("metal_oxide", "Metal oxides & hydroxides"),
    ("hydrogels", "Hydrogels"),
    ("salts_inorganic", "Salts"),
    ("minerals", "Minerals & silicates"),
    ("organics_biomolecules", "Organics & biomolecules"),
    ("elements_allotropes", "Elements & carbons"),
]


def card_group(entry, category):
    """The browsing group of a material entry found under database key `category`."""
    if category == "inorganics_minerals":
        return "metal_oxide" if entry.get("group") == "metal_oxide" else "minerals"
    return category


def cards_in_group(database, group):
    """Material names in a browsing group ("all" for every card), sorted case-insensitively."""
    names = [e["name"] for cat in MATERIAL_CATEGORIES for e in database.get(cat, [])
             if group == "all" or card_group(e, cat) == group]
    return sorted(names, key=str.lower)

# Atmospheric CO2 asymmetric stretch: background-subtraction residue here is the most common
# artefact in routine FTIR spectra, so peak picking can skip it.
CO2_REGION = ftir_matching.CO2_REGION
NOISE_FLOOR_SIGMAS = 5.0


def estimate_noise_sigma(y):
    """Robust noise standard deviation from point-to-point differences (median absolute
    deviation, scaled for Gaussian noise; differencing removes slow baseline and band shape)."""
    d = np.diff(np.asarray(y, dtype=float))
    d = d[np.isfinite(d)]
    if len(d) < 3:
        return 0.0
    return float(1.4826 * np.median(np.abs(d - np.median(d))) / np.sqrt(2.0))


def absorbance_like(y, mode="absorbance"):
    """The signal peaks are measured on. Absorbance as is; %transmittance (or a 0-1
    transmittance) converted to absorbance, A = -log10(T), so band heights and widths mean
    the same thing in both modes (%T compresses strong bands and widens them)."""
    y = np.asarray(y, dtype=float)
    if mode != "transmittance":
        return y.copy()
    finite = y[np.isfinite(y)]
    scale = 100.0 if finite.size and np.nanmax(finite) > 1.5 else 1.0
    return -np.log10(np.clip(y / scale, 1e-4, None))


def _widths_cm1(x, widths_result):
    """FWHM in cm-1 per peak from scipy.signal.peak_widths, using the interpolated
    half-height crossings (correct on uneven grids and in either x direction)."""
    x = np.asarray(x, dtype=float)
    if not len(widths_result[0]):
        return []
    idx = np.arange(len(x))
    left = np.interp(widths_result[2], idx, x)
    right = np.interp(widths_result[3], idx, x)
    return [float(w) for w in np.abs(right - left)]


def _distance_pts(x, min_distance_pts, min_distance_cm1):
    """Minimum peak separation in points, from a separation in cm-1 when one is given."""
    if not min_distance_cm1 or len(x) < 2:
        return max(1, int(min_distance_pts))
    step = float(np.nanmedian(np.abs(np.diff(np.asarray(x, dtype=float)))))
    if not np.isfinite(step) or step <= 0:
        return max(1, int(min_distance_pts))
    return max(int(min_distance_pts), int(round(float(min_distance_cm1) / step)))


def _keep_strongest(peaks, max_peaks):
    """At most `max_peaks` peaks, the most prominent ones, in wavenumber order."""
    if max_peaks and len(peaks) > int(max_peaks):
        peaks = sorted(peaks, key=lambda p: -p["prominence"])[:int(max_peaks)]
    return sorted(peaks, key=lambda p: p["x"])


def _outside_regions(x_value, regions):
    return not any(min(r) <= x_value <= max(r) for r in (regions or ()))


def load_database(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_references(database):
    """Return the bibliography list ({id, citation}) embedded in the database's _meta."""
    return database.get("_meta", {}).get("references", [])


def citations_for(database, source):
    """
    The full citations behind an entry's `source` string ("socrates2001, coates2000;
    cross-check: sdbs"), in order: (id, citation, role) with role "source" or "cross-check".
    A token that is not in the bibliography comes back with citation None, so it is shown
    as written rather than hidden.
    """
    import re

    by_id = {r["id"]: r["citation"] for r in get_references(database)}
    out, seen = [], set()
    marker = re.compile(r"cross-?check\s*:?", re.IGNORECASE)
    for part in re.split(r";", "" if source is None else str(source)):
        role = "cross-check" if marker.search(part) else "source"
        part = re.sub(r"\([^)]*\)", "", marker.sub(",", part))     # drop "(minerals)"-style annotations
        for token in part.split(","):
            key = token.strip()
            if not key or (key, role) in seen:
                continue
            seen.add((key, role))
            out.append((key, by_id.get(key), role))
    return out


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


def detect_peaks(x, y, prominence_frac=0.02, min_distance_pts=3, mode="absorbance", noise_floor=False,
                 exclude_regions=None, min_distance_cm1=None, max_peaks=None):
    """
    Detect peaks in a spectrum.
    mode: "absorbance" (peaks point up) or "transmittance" (peaks point down -> invert first).
    prominence_frac: required peak prominence as a fraction of the y-range.
    noise_floor: also require prominence >= NOISE_FLOOR_SIGMAS x the estimated noise, so
    baseline noise is not reported as peaks.
    exclude_regions: (low, high) cm-1 ranges whose peaks are dropped (e.g. CO2_REGION).
    min_distance_cm1: minimum separation of two peaks in cm-1 (instead of points only).
    max_peaks: keep at most this many, the most prominent.
    In transmittance mode prominence and width are measured on absorbance (A = -log10 T).
    Returns list of dicts: {index, x, y, prominence, fwhm}
    """
    from scipy.signal import find_peaks, peak_widths

    y_work = absorbance_like(y, mode)

    y_range = y_work.max() - y_work.min()
    prominence = max(prominence_frac * y_range, 1e-9)
    if noise_floor:
        prominence = max(prominence, NOISE_FLOOR_SIGMAS * estimate_noise_sigma(y_work))

    idx, props = find_peaks(y_work, prominence=prominence,
                            distance=_distance_pts(x, min_distance_pts, min_distance_cm1))
    widths_result = peak_widths(y_work, idx, rel_height=0.5)
    widths = _widths_cm1(x, widths_result)

    peaks = []
    for i, pk in enumerate(idx):
        if not _outside_regions(float(x[pk]), exclude_regions):
            continue
        peaks.append({
            "index": int(pk),
            "x": float(x[pk]),
            "y": float(y[pk]),
            "prominence": float(props["prominences"][i]),
            "fwhm_pts": float(widths_result[0][i]),
            "fwhm_cm1": widths[i],
        })
    return _keep_strongest(peaks, max_peaks)


MANUAL_SNAP_CM1 = 10.0               # a click snaps to the strongest point within this distance


def peak_at(x, y, x_click, mode="absorbance", snap_cm1=MANUAL_SNAP_CM1):
    """
    A peak placed by hand at `x_click`, with the same fields as detect_peaks plus
    "manual": True. It snaps to the nearest true local maximum (in absorbance) within
    `snap_cm1`; when there is none -- a shoulder, or the flank of a broad band -- the clicked
    point is kept, marked "shoulder": True, its prominence measured above the chord between
    the lowest points on either side and its width left unknown. Returns None when the click
    is outside the spectrum.
    """
    from scipy.signal import peak_prominences, peak_widths

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    if finite.sum() < 3:
        return None
    clicked = int(np.nanargmin(np.where(finite, np.abs(x - x_click), np.inf)))
    if abs(x[clicked] - x_click) > snap_cm1:
        return None                                     # outside the spectrum, or inside a data gap
    y_work = absorbance_like(y, mode)
    y_work = np.where(np.isfinite(y_work), y_work, np.nanmin(y_work[finite]))
    n = len(x)
    # Locate the top on a lightly smoothed copy (about half the snap distance), so noise on a
    # band top does not pull the peak off its centre; the reported intensity stays the raw one.
    y_find = y_work
    step = float(np.nanmedian(np.abs(np.diff(x[finite]))))
    win = int(round(0.5 * snap_cm1 / step)) if step > 0 else 0
    win += 1 - win % 2
    if win >= 5 and n > win + 2:
        from scipy.signal import savgol_filter
        y_find = savgol_filter(y_work, win, 3)
    near = np.flatnonzero(finite & (np.abs(x - x_click) <= snap_cm1))
    maxima = [i for i in near if 0 < i < n - 1 and y_find[i] >= y_find[i - 1] and y_find[i] >= y_find[i + 1]
              and (y_find[i] > y_find[i - 1] or y_find[i] > y_find[i + 1])]
    proms = []
    if maxima:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            proms = list(peak_prominences(y_find, maxima)[0])
    # A real band top stands well above the noise; a wiggle on a flank does not. (The noise
    # estimate needs a real spectrum; on a handful of points it is meaningless.)
    floor = 3.0 * estimate_noise_sigma(y_work[finite]) if finite.sum() >= 50 else 0.0
    real = [(p, i) for p, i in zip(proms, maxima) if p > floor]
    shoulder = not real
    pk = clicked if shoulder else int(max(real)[1])     # the most prominent maximum in the window
    width = None
    width_pts = 0.0
    prominence = 0.0
    if not shoulder:
        prominence = float(max(real)[0])
        res = peak_widths(y_find, [pk], rel_height=0.5)
        if prominence > 0 and len(res[0]):
            width_pts = float(res[0][0])
            width = _widths_cm1(x, res)[0]
    if prominence <= 0:
        # Height above the chord joining the lowest points within 5 snap widths on each side.
        around = np.abs(x - x[pk]) <= 5 * snap_cm1
        left = np.flatnonzero(around & (np.arange(n) < pk))
        right = np.flatnonzero(around & (np.arange(n) > pk))
        if left.size and right.size:
            i_l = int(left[np.argmin(y_work[left])])
            i_r = int(right[np.argmin(y_work[right])])
            chord = np.interp(x[pk], sorted([x[i_l], x[i_r]]),
                              [y_work[i_l], y_work[i_r]] if x[i_l] <= x[i_r] else [y_work[i_r], y_work[i_l]])
            prominence = max(float(y_work[pk] - chord), 0.0)
        else:
            prominence = max(float(y_work[pk] - y_work[around].min()), 0.0)
    return {"index": pk, "x": float(x[pk]), "y": float(y[pk]), "prominence": prominence,
            "fwhm_pts": width_pts, "fwhm_cm1": width, "manual": True, "shoulder": shoulder}


def detect_peaks_second_derivative(x, y, mode="absorbance", prominence_frac=0.02,
                                    smooth_window=15, smooth_polyorder=3, min_distance_pts=3,
                                    noise_floor=False, exclude_regions=None, min_distance_cm1=None,
                                    max_peaks=None):
    """
    Second-derivative-assisted peak detection: resolves overlapping/shouldered
    bands that blend into a single broad hump in the raw spectrum and are
    missed by ordinary local-maximum peak picking on y itself. Each real
    absorption band -- even a shoulder riding on a stronger neighbor --
    produces its own local minimum in the (smoothed) second derivative,
    because d^2/dx^2 of a peak-shaped feature is most negative at its center,
    regardless of whether it's tall enough to show as its own local maximum
    in the raw envelope. Detecting maxima of -d^2y/dx^2 therefore resolves
    bands that plain peak-picking on y merges into one.

    This is the standard "peak resolution enhancement" technique used in
    FTIR/protein-secondary-structure analysis for exactly this failure mode
    (a database reference band exists at a real wavenumber, but ordinary
    peak-picking only ever finds one broad peak covering several reference
    ranges at once). It is intentionally a separate, opt-in detection mode
    rather than a replacement for detect_peaks(): being far more sensitive to
    noise (differentiation amplifies noise even after smoothing), it can
    produce spurious extra peaks on a noisy spectrum, so it should be used
    when you have reason to expect overlapping bands, not as a blanket
    default.

    Source: Susi & Byler, Appl. Spectrosc. 37 (1983) 130 -- second-derivative
    resolution enhancement for overlapping IR/protein amide bands.
    """
    from scipy.signal import find_peaks, peak_widths

    y_work = absorbance_like(y, mode)

    d2 = derivative_spectrum(x, y_work, order=2, window_length=smooth_window, polyorder=smooth_polyorder)
    neg_d2 = -d2  # bands in the original spectrum -> minima of d2 -> maxima of -d2

    d2_range = neg_d2.max() - neg_d2.min()
    prominence = max(prominence_frac * d2_range, 1e-12)
    if noise_floor:
        prominence = max(prominence, NOISE_FLOOR_SIGMAS * estimate_noise_sigma(neg_d2))
    idx, props = find_peaks(neg_d2, prominence=prominence,
                            distance=_distance_pts(x, min_distance_pts, min_distance_cm1))
    # A maximum of -d2 that is not above zero lies between two side lobes, not on a band.
    keep = neg_d2[idx] > 0 if len(idx) else np.array([], dtype=bool)
    idx = idx[keep]
    props = {k: v[keep] for k, v in props.items()}
    widths_result = peak_widths(neg_d2, idx, rel_height=0.5) if len(idx) else (np.array([]),) * 4
    d2_widths = _widths_cm1(x, widths_result) if len(idx) else []

    peaks = []
    for i, pk in enumerate(idx):
        if not _outside_regions(float(x[pk]), exclude_regions):
            continue
        peaks.append({
            "index": int(pk),
            "x": float(x[pk]),
            "y": float(y[pk]),  # report the ORIGINAL spectrum's intensity for display/overlay
            "prominence": float(props["prominences"][i]),
            # The width of a second-derivative lobe is not the band's width (about 2/3 of it for
            # a Gaussian, depending on shape), so the band width is left unknown for matching.
            "fwhm_cm1": None,
            "d2_fwhm_cm1": d2_widths[i] if d2_widths else 0.0,
        })
    return _keep_strongest(peaks, max_peaks)


def _entries_for(database, categories):
    search_categories = [c for c in (categories or MATERIAL_CATEGORIES) if c in MATERIAL_CATEGORIES]
    if not search_categories:
        search_categories = MATERIAL_CATEGORIES
    return [entry for group in search_categories for entry in database.get(group, [])]


def match_peaks_to_database(peaks, database, tolerance=10.0, categories=None, method="weighted",
                            spectral_range=None):
    """
    Rank database materials against a detected peak list.

    method="weighted" (default): intensity-weighted, one-to-one, forward + reverse evidence
    with a chance-coincidence correction -- see ftir_matching and docs/FTIR_MATCHING_PLAN.md.
    "score" is then the confidence (0-1). method="coverage": the original fraction-of-bands
    screening, kept for comparison and reproducibility of older results.

    categories: optional list of MATERIAL_CATEGORIES keys to restrict the search to; None,
    empty or only unknown keys search every category. spectral_range: (low, high) cm-1 of the
    measured spectrum, used to estimate how crowded the peak list is.
    """
    entries = _entries_for(database, categories)
    if method == ftir_matching.METHOD_COVERAGE:
        return _match_coverage(peaks, entries, tolerance)
    return ftir_matching.match_weighted(peaks, entries, tolerance=tolerance, spectral_range=spectral_range,
                                        all_entries=_entries_for(database, None))


def analyse_mixture(peaks, database, tolerance=10.0, categories=None, spectral_range=None,
                    max_components=3, min_confidence=0.35):
    """Multi-component screening (see ftir_matching.analyse_mixture)."""
    return ftir_matching.analyse_mixture(peaks, _entries_for(database, categories), tolerance=tolerance,
                                         spectral_range=spectral_range, max_components=max_components,
                                         min_confidence=min_confidence)


def _match_coverage(peaks, all_entries, tolerance=10.0):
    """
    Legacy screening: match detected peaks against each reference range +/- tolerance (cm-1).

    Scoring is a simple coverage fraction: (# reference peaks matched) / (# reference peaks total)
    for each material entry. This is a heuristic screening tool, not definitive
    identification -- always confirm with a domain expert / reference spectrum
    for anything consequential.
    """
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
                "method": ftir_matching.METHOD_COVERAGE,
                "score": score,
                "coverage": score,
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


def fwhm_from_peak(x, y, peak_index, rel_height=0.5, mode="absorbance"):
    """
    Full width at half max (in x-units) for a given peak index.
    mode: "absorbance" (peaks point up, the default scipy.signal.peak_widths
    assumption) or "transmittance" (peaks point down as dips -- must be
    inverted first, exactly as detect_peaks() does, otherwise peak_widths
    measures the width of a valley as though it were a summit and returns
    meaningless results).
    """
    from scipy.signal import peak_widths

    y_work = absorbance_like(y, mode)        # %T is converted to absorbance, not just flipped
    widths_result = peak_widths(y_work, [peak_index], rel_height=rel_height)
    return _widths_cm1(x, widths_result)[0]


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
    finite = np.isfinite(y)
    if not finite.any():
        raise ValueError("The spectrum has no finite values to normalize.")

    def scaled(offset, divisor, what):
        if not np.isfinite(divisor) or divisor == 0:
            raise ValueError(f"Cannot {what}-normalize this spectrum: it is flat or zero.")
        return (y - offset) / divisor

    if method == "max":
        return scaled(0.0, np.nanmax(np.abs(y)), "max")
    elif method == "minmax":
        return scaled(np.nanmin(y), np.nanmax(y) - np.nanmin(y), "minmax")
    elif method == "area":
        if x is None:
            raise ValueError("Area normalization requires x-axis values.")
        from scipy.integrate import trapezoid

        xs = np.asarray(x, dtype=float)
        ok = finite & np.isfinite(xs)
        return scaled(0.0, abs(trapezoid(np.abs(y[ok]), xs[ok])) if ok.sum() > 1 else 0.0, "area")
    elif method == "vector":
        return scaled(0.0, float(np.sqrt(np.nansum(y ** 2))), "vector")
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
