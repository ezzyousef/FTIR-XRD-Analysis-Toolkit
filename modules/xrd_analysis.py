"""
xrd_analysis.py
XRD pattern peak detection and standard calculations:
Bragg's law (d-spacing), Scherrer equation (crystallite size),
approximate % crystallinity, and basic cubic lattice parameter estimation.

Wavelength reference values (Angstrom) are standard, widely published
characteristic X-ray wavelengths (e.g. Cu Ka1 = 1.540562 A). Cross-check
against your instrument's actual tube/monochromator setting -- some setups
use the Ka1/Ka2-weighted average (~1.5418 A) instead of Ka1 alone.
"""
import csv
import json
import os
import numpy as np
# scipy is imported lazily inside the functions that need it (see
# detect_xrd_peaks/percent_crystallinity below) -- see the matching comment
# in ftir_analysis.py for why (keeps the startup splash screen short).

try:
    from signal_utils import smooth_savgol
    from app_config import get_config_dir
except ImportError:
    from modules.signal_utils import smooth_savgol
    from modules.app_config import get_config_dir

USER_PHASES_FILENAME = "user_xrd_phases.json"

# Common X-ray source wavelengths in Angstrom
WAVELENGTHS = {
    "Cu Ka1": 1.540562,
    "Cu Ka (weighted avg)": 1.541838,
    "Cu Ka2": 1.544390,
    "Co Ka1": 1.788965,
    "Cr Ka1": 2.289760,
    "Fe Ka1": 1.936042,
    "Mo Ka1": 0.709300,
    "Ag Ka1": 0.559420,
}


def detect_xrd_peaks(two_theta, intensity, prominence_frac=0.02, min_distance_pts=5):
    from scipy.signal import find_peaks, peak_widths

    two_theta = np.asarray(two_theta, dtype=float)
    intensity = np.asarray(intensity, dtype=float)
    y_range = intensity.max() - intensity.min()
    prominence = max(prominence_frac * y_range, 1e-9)

    idx, props = find_peaks(intensity, prominence=prominence, distance=min_distance_pts)
    widths_result = peak_widths(intensity, idx, rel_height=0.5)

    peaks = []
    for i, pk in enumerate(idx):
        # FWHM in points -> convert to 2theta units using local spacing
        if pk + 1 < len(two_theta):
            dx = abs(two_theta[pk + 1] - two_theta[pk])
        else:
            dx = abs(two_theta[pk] - two_theta[pk - 1])
        fwhm_deg = widths_result[0][i] * dx
        peaks.append({
            "index": int(pk),
            "two_theta": float(two_theta[pk]),
            "intensity": float(intensity[pk]),
            "prominence": float(props["prominences"][i]),
            "fwhm_deg": float(fwhm_deg),
        })
    peaks.sort(key=lambda p: -p["intensity"])
    return peaks


def bragg_d_spacing(two_theta_deg, wavelength_a, n=1):
    """
    Bragg's Law: n*lambda = 2*d*sin(theta)  ->  d = n*lambda / (2*sin(theta))
    two_theta_deg: the 2theta peak position in degrees.
    wavelength_a: X-ray wavelength in Angstrom.
    Returns d-spacing in Angstrom.
    """
    theta_rad = np.radians(np.asarray(two_theta_deg, dtype=float) / 2.0)
    sin_theta = np.sin(theta_rad)
    if np.any(sin_theta <= 0):
        raise ValueError("2theta must be > 0 degrees.")
    return (n * wavelength_a) / (2 * sin_theta)


def two_theta_from_d(d_spacing_a, wavelength_a, n=1):
    """
    Inverse of bragg_d_spacing: 2theta (degrees) from a d-spacing and
    wavelength. Returns None (rather than raising) if that reflection isn't
    observable at this wavelength -- i.e. d is too small for sin(theta) <= 1
    -- which is a normal, expected case (not every reference line of a phase
    is reachable at every X-ray source), not an error condition.
    """
    ratio = (n * wavelength_a) / (2 * d_spacing_a)
    if not (0 < ratio <= 1):
        return None
    return float(2 * np.degrees(np.arcsin(ratio)))


def scherrer_crystallite_size(fwhm_deg, two_theta_deg, wavelength_a, K=0.9):
    """
    Scherrer equation: tau = K*lambda / (beta*cos(theta))
    fwhm_deg: peak full width at half maximum, in degrees 2theta.
    K: shape factor (0.9 is a common default for roughly spherical crystallites;
       varies 0.62-2.08 depending on assumed crystallite shape).
    Returns crystallite size in nanometers.

    Note: this reports apparent crystallite size from peak broadening alone. It
    does not separate strain broadening from size broadening (that requires a
    Williamson-Hall analysis using multiple peaks) and does NOT correct for
    instrumental broadening (which should be subtracted in quadrature using a
    standard reference sample for rigorous work).
    """
    beta_rad = np.radians(fwhm_deg)
    theta_rad = np.radians(np.asarray(two_theta_deg, dtype=float) / 2.0)
    wavelength_nm = wavelength_a * 0.1  # Angstrom -> nm
    tau_nm = (K * wavelength_nm) / (beta_rad * np.cos(theta_rad))
    return float(tau_nm)


def williamson_hall(two_theta_list, fwhm_list, wavelength_a, K=0.9):
    """
    Williamson-Hall analysis across multiple peaks to separate size and strain
    broadening: beta*cos(theta) = K*lambda/D + 4*epsilon*sin(theta)
    Returns dict with crystallite size D (nm), microstrain (dimensionless), and
    the linear fit used, from a straight-line fit of
    y = beta*cos(theta) vs x = 4*sin(theta).
    Requires at least 3 peaks for a meaningful fit.
    """
    two_theta = np.radians(np.asarray(two_theta_list, dtype=float))
    fwhm = np.radians(np.asarray(fwhm_list, dtype=float))
    theta = two_theta / 2.0
    wavelength_nm = wavelength_a * 0.1

    x = 4 * np.sin(theta)
    y = fwhm * np.cos(theta)

    if len(x) < 3:
        raise ValueError("Williamson-Hall analysis needs at least 3 peaks for a reliable fit.")

    slope, intercept = np.polyfit(x, y, 1)
    strain = slope / 4.0
    if intercept <= 0:
        D_nm = None  # non-physical intercept; size term not resolvable from this data
    else:
        D_nm = (K * wavelength_nm) / intercept
    return {"crystallite_size_nm": D_nm, "microstrain": float(strain),
            "slope": float(slope), "intercept": float(intercept)}


def percent_crystallinity(two_theta, intensity, crystalline_regions, amorphous_regions):
    """
    Approximate % crystallinity via area-under-curve method:
    %Xc = Area(crystalline peaks) / [Area(crystalline peaks) + Area(amorphous halo)] * 100

    crystalline_regions / amorphous_regions: lists of (start, end) 2theta tuples
    defining where to integrate. This is an approximate, method-dependent metric --
    results are sensitive to the chosen regions and baseline; report the method
    alongside the number, and expect different software to give somewhat
    different values for the same raw pattern.
    """
    from scipy import integrate

    two_theta = np.asarray(two_theta, dtype=float)
    intensity = np.asarray(intensity, dtype=float)

    def region_area(regions):
        total = 0.0
        for lo, hi in regions:
            mask = (two_theta >= lo) & (two_theta <= hi)
            if mask.sum() < 2:
                continue
            xs, ys = two_theta[mask], intensity[mask]
            order = np.argsort(xs)
            total += integrate.trapezoid(ys[order], xs[order])
        return total

    crys_area = region_area(crystalline_regions)
    amorph_area = region_area(amorphous_regions)
    denom = crys_area + amorph_area
    if denom <= 0:
        raise ValueError("Selected regions contain no usable area; check your 2theta ranges.")
    return float(100 * crys_area / denom)


def cubic_lattice_parameter(d_spacing_a, h, k, l):
    """
    For a cubic crystal system: 1/d^2 = (h^2+k^2+l^2)/a^2  ->  a = d * sqrt(h^2+k^2+l^2)
    Only valid for cubic systems -- for other symmetries (tetragonal, hexagonal,
    etc.) a different formula is required.
    """
    hkl_sum = h**2 + k**2 + l**2
    if hkl_sum == 0:
        raise ValueError("h, k, l cannot all be zero.")
    return float(d_spacing_a * np.sqrt(hkl_sum))


def smooth_pattern(intensity, window_length=11, polyorder=3):
    """Savitzky-Golay smoothing wrapper (see signal_utils.smooth_savgol)."""
    return smooth_savgol(intensity, window_length=window_length, polyorder=polyorder)


# ---------------- Iterative multi-peak unit-cell refinement ----------------

def parse_hkl(hkl_str):
    """
    Parses a database hkl string into an (h, k, l) int tuple. The reference
    database stores hkl as a plain 3-digit concatenation ("111", "200") or,
    when any index needs 2+ digits, comma-separated ("1,0,10"). Returns None
    if the string can't be parsed (e.g. empty).
    """
    s = (hkl_str or "").strip()
    if not s:
        return None
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        return tuple(int(p) for p in parts)
    if len(s) == 3 and s.isdigit():
        return tuple(int(c) for c in s)
    raise ValueError(f"Cannot parse hkl string {hkl_str!r}")


LATTICE_SYSTEMS = {
    "cubic": ("a",),
    "tetragonal": ("a", "c"),
    "hexagonal": ("a", "c"),
    "orthorhombic": ("a", "b", "c"),
}


def _q_calc(hkl, params, crystal_system):
    """Q = 1/d^2 as a function of (h,k,l) and lattice parameter(s), per crystal system."""
    h, k, l = hkl[:, 0], hkl[:, 1], hkl[:, 2]
    if crystal_system == "cubic":
        (a,) = params
        return (h ** 2 + k ** 2 + l ** 2) / a ** 2
    elif crystal_system == "tetragonal":
        a, c = params
        return (h ** 2 + k ** 2) / a ** 2 + l ** 2 / c ** 2
    elif crystal_system == "hexagonal":
        a, c = params
        return (4.0 / 3.0) * (h ** 2 + h * k + k ** 2) / a ** 2 + l ** 2 / c ** 2
    elif crystal_system == "orthorhombic":
        a, b, c = params
        return h ** 2 / a ** 2 + k ** 2 / b ** 2 + l ** 2 / c ** 2
    raise ValueError(f"Unsupported crystal system '{crystal_system}'. Supported: {list(LATTICE_SYSTEMS)}")


def refine_lattice_parameters(peaks, wavelength_a, crystal_system="cubic",
                               initial_params=None, outlier_sigma=3.0, max_outlier_rounds=4):
    """
    Iterative least-squares unit-cell (lattice parameter) refinement from
    multiple indexed peaks -- the standard crystallographic technique for
    getting an accurate lattice parameter (Cullity & Stock, 2001, Ch. 11),
    rather than the single-peak a = d*sqrt(h^2+k^2+l^2) estimate (which has
    no way to detect a misindexed peak or average out measurement noise).

    peaks: list of dicts, each {"two_theta": float, "h": int, "k": int, "l": int}
    crystal_system: one of LATTICE_SYSTEMS ("cubic", "tetragonal", "hexagonal", "orthorhombic")
    outlier_sigma: after each fit, peaks whose residual exceeds this many
        standard deviations of the residual distribution are excluded and
        the fit is redone -- repeated (up to max_outlier_rounds times) until
        no further peaks are excluded ("reiterative" refinement). This is
        what catches a peak that was assigned the wrong hkl index.

    Returns a dict:
        params: {"a": ..., ["b":...], ["c":...]}  (Angstrom)
        param_errors: 1-sigma parameter uncertainties from the fit covariance
        r_squared, reduced_chi_square: goodness of fit (on Q = 1/d^2)
        n_peaks_used / n_peaks_excluded, excluded_indices
        per_peak: list of {two_theta_obs, two_theta_calc, delta_two_theta,
                   h, k, l, used} for every input peak, for inspection
        rounds: number of outlier-rejection rounds actually performed
        converged: bool
    """
    from scipy.optimize import least_squares

    if crystal_system not in LATTICE_SYSTEMS:
        raise ValueError(f"Unsupported crystal system '{crystal_system}'. Supported: {list(LATTICE_SYSTEMS)}")
    param_names = LATTICE_SYSTEMS[crystal_system]
    n = len(peaks)
    if n < len(param_names) + 1:
        raise ValueError(f"Need at least {len(param_names) + 1} indexed peaks for a {crystal_system} refinement "
                          f"({len(param_names)} parameter(s) + 1 degree of freedom), got {n}.")

    hkl = np.array([[p["h"], p["k"], p["l"]] for p in peaks], dtype=float)
    two_theta_obs = np.array([p["two_theta"] for p in peaks], dtype=float)
    theta_obs = np.radians(two_theta_obs / 2.0)
    d_obs = wavelength_a / (2 * np.sin(theta_obs))
    q_obs = 1.0 / d_obs ** 2

    if initial_params is None:
        # rough starting guess from the single-peak formula, averaged over all peaks
        guesses = {name: [] for name in param_names}
        for i in range(n):
            h, k, l = hkl[i]
            if crystal_system in ("cubic",):
                guesses["a"].append(d_obs[i] * np.sqrt(h ** 2 + k ** 2 + l ** 2))
            elif crystal_system in ("tetragonal", "hexagonal"):
                # crude decoupled guess: use l=0 peaks for 'a', h=k=0 peaks for 'c' if available,
                # else fall back to a single shared rough estimate for both.
                guesses["a"].append(d_obs[i] * np.sqrt(h ** 2 + k ** 2 + l ** 2))
                guesses["c"].append(d_obs[i] * np.sqrt(h ** 2 + k ** 2 + l ** 2))
            else:
                guesses["a"].append(d_obs[i] * np.sqrt(h ** 2 + k ** 2 + l ** 2))
                guesses["b"].append(d_obs[i] * np.sqrt(h ** 2 + k ** 2 + l ** 2))
                guesses["c"].append(d_obs[i] * np.sqrt(h ** 2 + k ** 2 + l ** 2))
        initial_params = [float(np.mean(guesses[name])) for name in param_names]

    active = np.ones(n, dtype=bool)
    params = np.array(initial_params, dtype=float)
    rounds_done = 0
    result = None

    for round_idx in range(max_outlier_rounds + 1):
        rounds_done = round_idx + 1

        def residuals(p, active_mask=active):
            return q_obs[active_mask] - _q_calc(hkl[active_mask], p, crystal_system)

        if active.sum() <= len(param_names):
            break  # not enough peaks left to fit; stop refining further
        result = least_squares(residuals, x0=params, method="lm", max_nfev=10000)
        params = result.x

        q_calc_all = _q_calc(hkl, params, crystal_system)
        resid_all = q_obs - q_calc_all
        active_resid = resid_all[active]
        # Median absolute deviation (scaled to be a consistent estimator of
        # sigma for normally-distributed residuals) rather than plain std:
        # a single badly-misindexed peak inflates its OWN std so much that a
        # std-based threshold never flags it as an outlier relative to
        # itself. MAD is robust to exactly this one-bad-point case.
        median_resid = float(np.median(active_resid))
        mad = float(np.median(np.abs(active_resid - median_resid)))
        sigma = 1.4826 * mad if active.sum() > 2 else float(np.std(active_resid)) if active.sum() > 1 else 0.0
        # Numerical floor: with near-perfect data (e.g. synthetic test peaks,
        # or a very clean pattern) most residuals cluster at ~0 and MAD can
        # itself be ~0, which would make the threshold so tight that
        # floating-point-level noise gets flagged as an "outlier". Floor
        # sigma at a tiny fraction of the typical Q scale so only genuinely
        # discrepant peaks (a real misindex) get excluded.
        sigma = max(sigma, 1e-8 * float(np.median(np.abs(q_obs[active]))))
        if sigma <= 0:
            new_active = active.copy()
        else:
            new_active = np.abs(resid_all - median_resid) <= outlier_sigma * sigma
        if np.array_equal(new_active, active) or new_active.sum() < len(param_names) + 1:
            break
        active = new_active

    if result is None:
        raise ValueError("Refinement failed to run (not enough usable peaks).")

    q_calc_all = _q_calc(hkl, params, crystal_system)
    # convert calculated Q back to two-theta for human-readable residuals
    d_calc_all = 1.0 / np.sqrt(np.clip(q_calc_all, 1e-12, None))
    with np.errstate(invalid="ignore"):
        sin_theta_calc = np.clip(wavelength_a / (2 * d_calc_all), -1.0, 1.0)
        two_theta_calc_all = 2 * np.degrees(np.arcsin(sin_theta_calc))

    resid_all = q_obs - q_calc_all
    active_resid = resid_all[active]
    ss_res = float(np.sum(active_resid ** 2))
    ss_tot = float(np.sum((q_obs[active] - np.mean(q_obs[active])) ** 2))
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    dof = max(active.sum() - len(param_names), 1)
    reduced_chi_square = ss_res / dof

    # parameter uncertainties from the linearized covariance at the solution
    try:
        jac = result.jac
        cov = np.linalg.inv(jac.T @ jac) * reduced_chi_square
        param_errors = {name: float(np.sqrt(max(cov[i, i], 0))) for i, name in enumerate(param_names)}
    except Exception:
        param_errors = {name: float("nan") for name in param_names}

    per_peak = []
    for i in range(n):
        per_peak.append({
            "two_theta_obs": float(two_theta_obs[i]),
            "two_theta_calc": float(two_theta_calc_all[i]) if np.isfinite(two_theta_calc_all[i]) else None,
            "delta_two_theta": float(two_theta_obs[i] - two_theta_calc_all[i]) if np.isfinite(two_theta_calc_all[i]) else None,
            "h": int(hkl[i, 0]), "k": int(hkl[i, 1]), "l": int(hkl[i, 2]),
            "used": bool(active[i]),
        })

    return {
        "crystal_system": crystal_system,
        "params": {name: float(params[i]) for i, name in enumerate(param_names)},
        "param_errors": param_errors,
        "r_squared": r_squared,
        "reduced_chi_square": float(reduced_chi_square),
        "n_peaks_used": int(active.sum()),
        "n_peaks_excluded": int((~active).sum()),
        "per_peak": per_peak,
        "rounds": rounds_done,
        "converged": bool(result.success),
    }


# ---------------- Reference phase database (d-spacing matching) ----------------

def load_xrd_database(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_references(database):
    """Return the bibliography list ({id, citation}) embedded in the database's _meta."""
    return database.get("_meta", {}).get("references", [])


def search_xrd_database(database, query=""):
    """Search phase entries by name substring (case-insensitive). For the Database Viewer UI."""
    query = (query or "").strip().lower()
    return [p for p in database.get("phases", []) if not query or query in p["name"].lower()]


def find_phase(database, name):
    """
    Looks up a single phase entry by exact name. Used to fetch a phase
    match's full reference d-spacing list for the "overlay this phase's
    reference lines on my pattern" comparison feature.
    """
    for p in database.get("phases", []):
        if p["name"] == name:
            return p
    return None


PHASE_CATEGORY_LABELS = {
    "metal": "Metals",
    "oxide": "Oxides",
    "mineral": "Minerals",
    "salt": "Salts",
    "semiconductor": "Semiconductors",
    "carbon": "Carbon Allotropes",
}
ALL_CATEGORIES_LABEL = "All Categories"


def match_xrd_phases(peaks, wavelength_a, database, d_tolerance_pct=1.5, top_n_ref_peaks=10, categories=None):
    """
    Match detected XRD peaks against the reference phase database by comparing
    d-spacings (wavelength-independent), so it works regardless of which X-ray
    source/wavelength was used to collect the pattern.

    categories: optional list of phase-category keys (see PHASE_CATEGORY_LABELS)
    to restrict the search to -- e.g. ["salt"] if you already know the sample
    isn't a metal/oxide/mineral. None or empty searches every category.

    For each phase, only the top_n_ref_peaks strongest reference lines are
    considered (weaker/rare reflections are dropped to reduce false positives
    from an over-long reference peak list). A reference line counts as matched
    if an observed peak's d-spacing falls within +/- d_tolerance_pct percent of it.

    Scoring is intensity-weighted coverage: sum of rel_intensity of matched
    reference lines / sum of rel_intensity of all considered reference lines.
    This is a heuristic screening tool, not definitive phase identification --
    always confirm against a certified ICDD PDF card for anything consequential.
    """
    observed = []
    for p in peaks:
        try:
            d = bragg_d_spacing(p["two_theta"], wavelength_a)
            observed.append({"d_A": float(d), "peak": p})
        except Exception:
            continue

    search_categories = set(categories) if categories else None

    results = []
    for phase in database.get("phases", []):
        if search_categories and phase.get("category") not in search_categories:
            continue
        ref_peaks = sorted(phase["peaks"], key=lambda r: -r.get("rel_intensity", 0))[:top_n_ref_peaks]
        if not ref_peaks:
            continue
        matched = []
        for rp in ref_peaks:
            tol = rp["d_A"] * (d_tolerance_pct / 100.0)
            hit = None
            best_dist = None
            for obs in observed:
                dist = abs(obs["d_A"] - rp["d_A"])
                if dist <= tol and (best_dist is None or dist < best_dist):
                    best_dist = dist
                    hit = obs
            if hit:
                matched.append({
                    "reference": rp, "observed": hit["peak"],
                    "observed_d_A": hit["d_A"],
                    "delta_d_A": hit["d_A"] - rp["d_A"],
                })
        total_weight = sum(rp.get("rel_intensity", 1) for rp in ref_peaks)
        matched_weight = sum(m["reference"].get("rel_intensity", 1) for m in matched)
        if matched and total_weight > 0:
            results.append({
                "name": phase["name"],
                "category": phase.get("category", ""),
                "crystal_system": phase.get("crystal_system", ""),
                "source": phase.get("source", ""),
                "score": matched_weight / total_weight,
                "matched_count": len(matched),
                "total_reference_peaks": len(ref_peaks),
                "matches": matched,
            })

    # Same reasoning as the FTIR matcher: rank by absolute evidence (number
    # of matched reference lines) before the intensity-weighted fractional
    # score, so a phase with one lucky strong-line match can't outrank a
    # phase with many corroborating matched lines.
    results.sort(key=lambda r: (r["matched_count"], r["score"]), reverse=True)
    return results


def import_phases_from_csv(path):
    """
    Import user-supplied reference phase(s) from a CSV file, for extending the
    XRD phase database with data the user has legitimate access to (e.g.
    transcribed from a licensed ICDD PDF card in their own diffraction software).

    Expected columns (header row required, case-insensitive):
        name, d_A, hkl, rel_intensity[, category, crystal_system, source]
    Multiple rows with the same 'name' are grouped into one phase entry.
    Returns a list of phase dicts in the same schema as the built-in database.
    """
    phases = {}
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV file has no header row. Expected columns: name, d_A, hkl, rel_intensity")
        fields = {k.lower().strip(): k for k in reader.fieldnames}
        required = ["name", "d_a"]
        for req in required:
            if req not in fields:
                raise ValueError(f"CSV is missing required column '{req}' (expected: name, d_A, hkl, rel_intensity)")
        for row in reader:
            name = row[fields["name"]].strip()
            if not name:
                continue
            d_a = float(row[fields["d_a"]])
            hkl = row[fields["hkl"]].strip() if "hkl" in fields and row.get(fields["hkl"]) else ""
            rel_intensity = float(row[fields["rel_intensity"]]) if "rel_intensity" in fields and row.get(fields["rel_intensity"]) else 100.0
            entry = phases.setdefault(name, {
                "name": name,
                "category": row.get(fields.get("category", ""), "user-imported") or "user-imported",
                "crystal_system": row.get(fields.get("crystal_system", ""), "") or "",
                "source": row.get(fields.get("source", ""), "") or "User-imported (transcribed by user from their own reference source)",
                "peaks": [],
            })
            entry["peaks"].append({"d_A": d_a, "hkl": hkl, "rel_intensity": rel_intensity})
    if not phases:
        raise ValueError("No usable rows found in CSV file.")
    return list(phases.values())


def _user_phases_path():
    return os.path.join(get_config_dir(), USER_PHASES_FILENAME)


def load_user_phases():
    """User-imported custom phases persisted across sessions (see import_phases_from_csv)."""
    path = _user_phases_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("phases", [])
    except (json.JSONDecodeError, OSError):
        return []


def save_user_phases(phases):
    with open(_user_phases_path(), "w", encoding="utf-8") as f:
        json.dump({"phases": phases}, f, indent=2)


def add_user_phases(new_phases):
    """Merge new_phases into the persisted user-phase list (by name) and save."""
    existing = {p["name"]: p for p in load_user_phases()}
    for p in new_phases:
        existing[p["name"]] = p
    save_user_phases(list(existing.values()))
    return list(existing.values())


def remove_user_phase(name):
    existing = [p for p in load_user_phases() if p["name"] != name]
    save_user_phases(existing)
    return existing


def merged_database(builtin_db):
    """Built-in phase database + any persisted user-imported phases, ready for match_xrd_phases()."""
    merged = {"_meta": builtin_db.get("_meta", {}), "phases": list(builtin_db.get("phases", [])) + load_user_phases()}
    return merged
