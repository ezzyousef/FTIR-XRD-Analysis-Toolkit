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
    if intercept <= 0:
        D_nm = None  # non-physical intercept; size term not resolvable from this data
    else:
        D_nm = (K * wavelength_nm) / intercept
    return {"crystallite_size_nm": D_nm, "microstrain": float(strain),
            "strain_physical": bool(strain >= 0),
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
