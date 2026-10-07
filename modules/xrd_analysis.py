"""
xrd_analysis.py
XRD pattern peak detection and standard calculations:
Bragg's law (d-spacing), Scherrer equation (crystallite size),
Williamson-Hall size/strain, approximate % crystallinity, SNIP background
subtraction, 2theta/d/Q conversion and a single-peak cubic lattice parameter.

Wavelength reference values (Angstrom) are standard, widely published
characteristic X-ray wavelengths (e.g. Cu Ka1 = 1.540562 A). Cross-check
against your instrument's actual tube/monochromator setting -- some setups
use the Ka1/Ka2-weighted average (~1.5418 A) instead of Ka1 alone.
"""
import os
import numpy as np
# scipy is imported lazily inside the functions that need it (see
# detect_xrd_peaks/percent_crystallinity below) -- see the matching comment
# in ftir_analysis.py for why (keeps the startup splash screen short).

try:
    from signal_utils import smooth_savgol
except ImportError:
    from modules.signal_utils import smooth_savgol

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


# Kalpha2 wavelengths offered for stripping. Only Cu is pre-filled (the values above);
# for other anodes the user enters Kalpha2 from the instrument documentation.
KALPHA_PAIRS = {"Cu Ka1": (1.540562, 1.544390)}
KALPHA2_RATIO = 0.5                 # I(Ka2)/I(Ka1), the usual value for Cu
NOISE_FLOOR_SIGMAS = 7.0              # chosen on simulated patterns: 5 sigma let ~1 noise peak per 800 points through
MIN_WIDTH_POINTS = 3.0              # narrower "peaks" are spikes, not reflections


def estimate_noise_sigma(intensity):
    """Robust noise standard deviation from point-to-point differences (MAD)."""
    d = np.diff(np.asarray(intensity, dtype=float))
    d = d[np.isfinite(d)]
    if len(d) < 3:
        return 0.0
    return float(1.4826 * np.median(np.abs(d - np.median(d))) / np.sqrt(2.0))


def detect_xrd_peaks(two_theta, intensity, prominence_frac=0.02, min_distance_pts=5, noise_floor=False):
    """
    Peaks of a diffraction pattern, sorted by 2theta. Each peak carries its width from the
    raw points ("fwhm_deg", "fwhm_pts") and "usable": False for spikes narrower than
    MIN_WIDTH_POINTS data points, which must not enter size/strain analysis.
    noise_floor: keep only peaks whose prominence is >= NOISE_FLOOR_SIGMAS x the noise around
    them, drop weaker maxima inside a stronger peak's half-maximum width, and drop spikes.
    """
    from scipy.signal import find_peaks, peak_widths

    two_theta = np.asarray(two_theta, dtype=float)
    intensity = np.asarray(intensity, dtype=float)
    y_range = intensity.max() - intensity.min()
    prominence = max(prominence_frac * y_range, 1e-9)
    if noise_floor:
        prominence = max(prominence, NOISE_FLOOR_SIGMAS * estimate_noise_sigma(intensity))

    idx, props = find_peaks(intensity, prominence=prominence, distance=min_distance_pts)
    widths_result = peak_widths(intensity, idx, rel_height=0.5)
    keep = np.ones(len(idx), dtype=bool)
    if noise_floor and len(idx):
        # Counting noise grows with intensity (Poisson), so judge each peak against the noise
        # measured around it, not one global value dominated by the background.
        for i, pk in enumerate(idx):
            half = max(int(5 * widths_result[0][i]), 25)
            local = estimate_noise_sigma(intensity[max(pk - half, 0):pk + half + 1])
            if props["prominences"][i] < NOISE_FLOOR_SIGMAS * local:
                keep[i] = False
        # A weaker maximum inside a stronger peak's half-maximum width is noise on that peak.
        order = np.argsort(-props["prominences"])
        for rank, i in enumerate(order):
            if not keep[i]:
                continue
            left, right = widths_result[2][i], widths_result[3][i]
            for j in order[rank + 1:]:
                if keep[j] and left <= idx[j] <= right:
                    keep[j] = False
        keep &= widths_result[0] >= MIN_WIDTH_POINTS

    peaks = []
    for i, pk in enumerate(idx):
        if not keep[i]:
            continue
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
            "fwhm_pts": float(widths_result[0][i]),
            "usable": bool(widths_result[0][i] >= MIN_WIDTH_POINTS),
        })
    peaks.sort(key=lambda p: p["two_theta"])
    return peaks


# ---------------------------------------------------------------- Kalpha2 and instrument
def kalpha2_offset_deg(two_theta_deg, lambda1, lambda2):
    """Separation 2theta(Ka2) - 2theta(Ka1) in degrees: 2*tan(theta)*(l2 - l1)/l1 (radians)."""
    theta = np.radians(np.asarray(two_theta_deg, dtype=float) / 2.0)
    return np.degrees(2.0 * np.tan(theta) * (lambda2 - lambda1) / lambda1)


def strip_kalpha2(two_theta, intensity, lambda1, lambda2, ratio=KALPHA2_RATIO):
    """
    Rachinger correction: remove the Ka2 component, point by point from low angle,
    I1(2t) = I(2t) - ratio * I1(2t - offset(2t)). Works on any 2theta order and returns the
    Ka1-only pattern in the input order. The input should be background-free or nearly so
    near the peaks; noise is carried through (it is not amplified by more than 1 + ratio).
    """
    x = np.asarray(two_theta, dtype=float)
    y = np.asarray(intensity, dtype=float)
    order = np.argsort(x)
    xs, ys = x[order], y[order]
    out = np.empty_like(ys)
    shift = kalpha2_offset_deg(xs, lambda1, lambda2)
    for i in range(len(xs)):
        target = xs[i] - shift[i]
        if i == 0 or target <= xs[0]:
            out[i] = ys[i]
            continue
        j = int(np.searchsorted(xs, target))           # xs[j-1] < target <= xs[j], j <= i
        if j >= i:                                       # inside the current step: solve for out[i]
            w = (xs[i] - target) / (xs[i] - xs[i - 1])
            out[i] = (ys[i] - ratio * w * out[i - 1]) / (1.0 + ratio * (1.0 - w))
            continue
        w = (target - xs[j - 1]) / (xs[j] - xs[j - 1])
        out[i] = ys[i] - ratio * ((1.0 - w) * out[j - 1] + w * out[j])
    result = np.empty_like(out)
    result[order] = out
    return result


def caglioti_fwhm(two_theta_deg, U, V, W):
    """Instrument FWHM (degrees 2theta): H^2 = U tan^2(theta) + V tan(theta) + W."""
    t = np.tan(np.radians(np.asarray(two_theta_deg, dtype=float) / 2.0))
    h2 = U * t ** 2 + V * t + W
    h = np.sqrt(np.clip(h2, 0.0, None))
    return float(h) if np.ndim(h) == 0 else h


def fit_caglioti(two_theta_deg, fwhm_deg):
    """Least-squares U, V, W from the peak widths of a line-profile standard (>= 3 peaks).
    Returns {"U", "V", "W", "r_squared", "n_peaks"}."""
    tt = np.asarray(two_theta_deg, dtype=float)
    h2 = np.asarray(fwhm_deg, dtype=float) ** 2
    if len(tt) < 3:
        raise ValueError("Refining U, V, W needs at least 3 peaks of the standard.")
    t = np.tan(np.radians(tt / 2.0))
    A = np.vstack([t ** 2, t, np.ones_like(t)]).T
    (U, V, W), *_ = np.linalg.lstsq(A, h2, rcond=None)
    pred = A @ np.array([U, V, W])
    ss_tot = float(np.sum((h2 - h2.mean()) ** 2))
    r2 = 1.0 - float(np.sum((h2 - pred) ** 2)) / ss_tot if ss_tot > 0 else float("nan")
    return {"U": float(U), "V": float(V), "W": float(W), "r_squared": r2, "n_peaks": int(len(tt))}


def correct_instrumental(fwhm_deg, instrument_fwhm_deg, mode="gaussian", min_ratio=1.05):
    """
    Sample broadening from the measured width B and the instrument width b (both degrees):
    Gaussian profiles add in quadrature, beta = sqrt(B^2 - b^2); Lorentzian profiles add
    linearly, beta = B - b. Returns None when B <= min_ratio * b: the peak is not
    measurably broader than the instrument, so no size can be derived from it.
    """
    B, b = float(fwhm_deg), float(instrument_fwhm_deg or 0.0)
    if b <= 0:
        return B
    if B <= min_ratio * b:
        return None
    if mode == "lorentzian":
        return B - b
    return float(np.sqrt(B * B - b * b))


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


def q_from_two_theta(two_theta_deg, wavelength_a):
    """
    Scattering-vector magnitude Q = 4*pi*sin(theta)/lambda (A^-1), the
    diffraction-angle-independent axis used by PDF/total-scattering software
    and to compare data collected at different wavelengths on a common scale.
    """
    two_theta_deg = np.asarray(two_theta_deg, dtype=float)
    theta_rad = np.radians(two_theta_deg / 2.0)
    q = 4 * np.pi * np.sin(theta_rad) / wavelength_a
    return float(q) if q.ndim == 0 else q


def two_theta_from_q(q, wavelength_a, n=1):
    """Inverse of q_from_two_theta. Returns None if unreachable at this wavelength."""
    ratio = (q * wavelength_a) / (4 * np.pi)
    if not (0 < ratio <= 1):
        return None
    return float(2 * np.degrees(np.arcsin(ratio)))


def convert_xrd_units(value, from_unit, wavelength_a, n=1):
    """
    Convert a single diffraction-axis value between '2theta' (degrees),
    'd' (d-spacing, Angstrom), and 'q' (scattering vector, A^-1). Returns a
    dict with all three, or None for entries unreachable at this wavelength.
    """
    from_unit = from_unit.lower()
    if from_unit == "2theta":
        two_theta = float(value)
        d = float(bragg_d_spacing(two_theta, wavelength_a, n=n)) if two_theta > 0 else None
        q = q_from_two_theta(two_theta, wavelength_a)
    elif from_unit == "d":
        d = float(value)
        two_theta = two_theta_from_d(d, wavelength_a, n=n)
        q = q_from_two_theta(two_theta, wavelength_a) if two_theta is not None else None
    elif from_unit == "q":
        q = float(value)
        two_theta = two_theta_from_q(q, wavelength_a, n=n)
        d = float(bragg_d_spacing(two_theta, wavelength_a, n=n)) if two_theta is not None else None
    else:
        raise ValueError("from_unit must be '2theta', 'd', or 'q'.")
    return {"two_theta_deg": two_theta, "d_spacing_a": d, "q_inv_a": q}


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
    y = beta*cos(theta) vs x = 4*sin(theta) -- since x already has the factor
    of 4 folded in, the fitted slope IS the microstrain directly (epsilon),
    not epsilon divided by another 4.
    Requires at least 3 peaks for a meaningful fit.

    A negative fitted microstrain is mathematically possible (it is just an
    unconstrained least-squares slope) but has no direct physical meaning --
    true strain broadening can only add width to a peak, never subtract it.
    In practice a negative or near-zero slope means the data doesn't show a
    resolvable strain contribution (it's within noise / uncorrected
    instrumental broadening), not a real "negative strain". The returned
    "strain_physical" flag is False whenever microstrain < 0, so callers can
    surface that caveat instead of reporting the bare number at face value.
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
    strain = slope
    pred = slope * x + intercept
    resid = y - pred
    n = len(x)
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1.0 - float(np.sum(resid ** 2)) / ss_tot if ss_tot > 0 else float("nan")
    # standard errors of an ordinary least-squares line
    s2 = float(np.sum(resid ** 2)) / (n - 2)
    sxx = float(np.sum((x - x.mean()) ** 2))
    se_slope = float(np.sqrt(s2 / sxx)) if sxx > 0 else float("nan")
    se_intercept = float(np.sqrt(s2 * (1.0 / n + x.mean() ** 2 / sxx))) if sxx > 0 else float("nan")
    if intercept <= 0:
        D_nm, se_D = None, None  # non-physical intercept; size term not resolvable from this data
    else:
        D_nm = (K * wavelength_nm) / intercept
        se_D = float(D_nm * se_intercept / intercept)
    return {"crystallite_size_nm": D_nm, "crystallite_size_se_nm": se_D, "microstrain": float(strain),
            "microstrain_se": se_slope, "strain_physical": bool(strain >= 0),
            "slope": float(slope), "intercept": float(intercept), "intercept_se": se_intercept,
            "r_squared": r_squared, "K": float(K), "wavelength_a": float(wavelength_a),
            "x": [float(v) for v in x], "y": [float(v) for v in y],
            "two_theta": [float(v) for v in np.degrees(two_theta)]}


def percent_crystallinity(two_theta, intensity, crystalline_regions, amorphous_regions, linear_baseline=False):
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
    if linear_baseline:
        intensity = intensity - span_baseline(two_theta, intensity, list(crystalline_regions) + list(amorphous_regions))

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


def span_baseline(two_theta, intensity, regions, edge_points=5):
    """Straight line through the pattern at the outer ends of all regions (each end averaged
    over a few points), so instrument background is not counted as crystalline or amorphous."""
    two_theta = np.asarray(two_theta, dtype=float)
    intensity = np.asarray(intensity, dtype=float)
    lo = min(min(r) for r in regions)
    hi = max(max(r) for r in regions)
    order = np.argsort(two_theta)
    xs, ys = two_theta[order], intensity[order]
    i_lo = int(np.searchsorted(xs, lo))
    i_hi = int(np.searchsorted(xs, hi))
    y_lo = float(np.mean(ys[max(i_lo - edge_points // 2, 0):i_lo + edge_points // 2 + 1]))
    y_hi = float(np.mean(ys[max(i_hi - edge_points // 2, 0):i_hi + edge_points // 2 + 1]))
    base = np.interp(two_theta, [lo, hi], [y_lo, y_hi])
    return np.where((two_theta >= lo) & (two_theta <= hi), base, 0.0)


def snip_iterations(two_theta, window_deg):
    """SNIP clipping half-width in data points for a window given in degrees 2theta, so the
    result does not depend on the step size."""
    x = np.sort(np.asarray(two_theta, dtype=float))
    step = float(np.median(np.diff(x))) if len(x) > 1 else 1.0
    return max(1, int(np.ceil(float(window_deg) / max(step, 1e-9))))


def d_spacing_uncertainty(two_theta_deg, wavelength_a, sigma_two_theta_deg):
    """sigma_d = d * cot(theta) * sigma_theta, with sigma_theta = sigma(2theta)/2 in radians."""
    d = float(bragg_d_spacing(two_theta_deg, wavelength_a))
    theta = np.radians(float(two_theta_deg) / 2.0)
    return float(d / np.tan(theta) * np.radians(float(sigma_two_theta_deg) / 2.0))


def cubic_lattice_parameter(d_spacing_a, h, k, l):
    """
    For a cubic crystal system: 1/d^2 = (h^2+k^2+l^2)/a^2  ->  a = d * sqrt(h^2+k^2+l^2)
    Only valid for cubic systems -- for other symmetries (tetragonal, hexagonal,
    etc.) a different formula is required.
    """
    if any(float(v) != int(v) for v in (h, k, l)):
        raise ValueError("h, k and l must be whole numbers.")
    hkl_sum = h**2 + k**2 + l**2
    if hkl_sum == 0:
        raise ValueError("h, k, l cannot all be zero.")
    return float(d_spacing_a * np.sqrt(hkl_sum))


def cubic_extinction_note(h, k, l):
    """Which cubic lattices allow this reflection (simple rules for P, I, F)."""
    h, k, l = int(h), int(k), int(l)
    allowed = ["primitive (P)"]
    if (h + k + l) % 2 == 0:
        allowed.append("body-centred (I)")
    if len({h % 2, k % 2, l % 2}) == 1:
        allowed.append("face-centred (F)")
    return "allowed for " + ", ".join(allowed)


def smooth_pattern(intensity, window_length=11, polyorder=3):
    """Savitzky-Golay smoothing wrapper (see signal_utils.smooth_savgol)."""
    return smooth_savgol(intensity, window_length=window_length, polyorder=polyorder)


def snip_background(intensity, iterations=40):
    """
    SNIP (Statistics-sensitive Non-linear Iterative Peak-clipping) background
    estimation (Ryan et al., Nucl. Instrum. Methods B 34, 1988; Morhac et al.,
    Nucl. Instrum. Methods A 401, 1997). This is the standard automatic
    background-estimation algorithm used by commercial XRD software (e.g.
    PANalytical HighScore, Bruker DIFFRAC.EVA) -- it needs no user-selected
    "background-only" regions, working directly on the raw pattern.

    Method: the pattern is transformed with the LLS (log-log-sqrt) operator,
    which compresses peak amplitudes far more than the background level, then
    repeatedly clipped -- at each point, replaced by the local two-point
    average (window m) if that average is smaller -- for increasing window
    widths m = 1..iterations. Because peaks are narrow, they get clipped down
    to the background; because the background varies slowly, it survives.
    The result is inverse-transformed back to intensity units.

    Returns the estimated background curve (same length as intensity); the
    caller subtracts it: `intensity_corrected = intensity - background`.
    """
    y = np.clip(np.asarray(intensity, dtype=float), 0, None)
    v = np.log(np.log(np.sqrt(y + 1.0) + 1.0) + 1.0)
    n = len(v)
    for m in range(1, int(iterations) + 1):
        if 2 * m >= n:
            break
        avg = 0.5 * (v[: n - 2 * m] + v[2 * m:])
        segment = v[m:n - m]
        v = v.copy()
        v[m:n - m] = np.minimum(segment, avg)
    background = (np.exp(np.exp(v) - 1.0) - 1.0) ** 2 - 1.0
    return np.clip(background, 0, None)
