"""
peak_fitting.py
Single- and multi-peak deconvolution (Gaussian / Lorentzian / pseudo-Voigt)
for FTIR and XRD peaks, used to refine center/height/width/area beyond what
simple prominence-based peak picking gives you.
"""
import numpy as np
# scipy is imported lazily inside fit_peak() below -- see the matching
# comment in ftir_analysis.py for why (keeps the startup splash screen short).


def gaussian(x, height, center, fwhm, offset=0.0):
    sigma = fwhm / (2 * np.sqrt(2 * np.log(2)))
    return offset + height * np.exp(-0.5 * ((x - center) / sigma) ** 2)


def lorentzian(x, height, center, fwhm, offset=0.0):
    gamma = fwhm / 2.0
    return offset + height * (gamma ** 2) / ((x - center) ** 2 + gamma ** 2)


def pseudo_voigt(x, height, center, fwhm, eta, offset=0.0):
    """eta in [0,1]: 0 = pure Gaussian, 1 = pure Lorentzian."""
    eta = np.clip(eta, 0.0, 1.0)
    g = gaussian(x, height, center, fwhm, 0.0)
    l = lorentzian(x, height, center, fwhm, 0.0)
    return offset + eta * l + (1 - eta) * g


SHAPES = {"gaussian": gaussian, "lorentzian": lorentzian}


def fit_peak(x, y, center_guess, window, shape="gaussian"):
    """
    Fit a single isolated peak within +/- window of center_guess.
    Returns dict: {center, height, fwhm, area, offset, r_squared, shape} or raises
    ValueError if the fit fails / too few points in the window.
    """
    from scipy.optimize import curve_fit
    from scipy import integrate

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = (x >= center_guess - window) & (x <= center_guess + window)
    if mask.sum() < 5:
        raise ValueError(f"Not enough points within +/-{window} of {center_guess} to fit a peak (need >= 5).")
    xs, ys = x[mask], y[mask]
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]

    height_guess = float(ys.max() - ys.min())
    offset_guess = float(ys.min())
    fwhm_guess = max(window / 3.0, 1e-3)

    if shape == "pseudo_voigt":
        func = pseudo_voigt
        p0 = [height_guess, center_guess, fwhm_guess, 0.5, offset_guess]
        bounds = ([0, xs.min(), 1e-6, 0, -np.inf], [np.inf, xs.max(), (xs.max() - xs.min()) * 2, 1, np.inf])
    else:
        func = SHAPES.get(shape, gaussian)
        p0 = [height_guess, center_guess, fwhm_guess, offset_guess]
        bounds = ([0, xs.min(), 1e-6, -np.inf], [np.inf, xs.max(), (xs.max() - xs.min()) * 2, np.inf])

    try:
        popt, _ = curve_fit(func, xs, ys, p0=p0, bounds=bounds, maxfev=10000)
    except Exception as e:
        raise ValueError(f"Peak fit did not converge: {e}")

    y_fit = func(xs, *popt)
    ss_res = np.sum((ys - y_fit) ** 2)
    ss_tot = np.sum((ys - ys.mean()) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    if shape == "pseudo_voigt":
        height, center, fwhm, eta, offset = popt
        area = float(integrate.trapezoid(func(xs, *popt) - offset, xs))
        result = {"shape": shape, "height": float(height), "center": float(center),
                  "fwhm": float(fwhm), "eta": float(eta), "offset": float(offset),
                  "area": area, "r_squared": float(r_squared)}
    else:
        height, center, fwhm, offset = popt
        area = float(integrate.trapezoid(func(xs, *popt) - offset, xs))
        result = {"shape": shape, "height": float(height), "center": float(center),
                  "fwhm": float(fwhm), "offset": float(offset),
                  "area": area, "r_squared": float(r_squared)}
    return result


def fit_peaks_batch(x, y, peak_list, window, shape="gaussian"):
    """
    Fit every peak in peak_list (each a dict with an 'x' key giving the initial
    center guess). Returns a list of successful fit-result dicts (each also
    carrying the original peak's 'x' as 'seed_x'); peaks that fail to fit are
    skipped with their reason recorded in 'errors'.
    """
    fits = []
    errors = []
    for p in peak_list:
        try:
            r = fit_peak(x, y, p["x"], window, shape=shape)
            r["seed_x"] = p["x"]
            fits.append(r)
        except ValueError as e:
            errors.append({"seed_x": p["x"], "error": str(e)})
    return fits, errors
