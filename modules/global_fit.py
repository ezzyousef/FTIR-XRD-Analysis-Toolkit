"""
global_fit.py
Constrained, optionally robust, simultaneous fit of several overlapping peaks on a linear
baseline, with 1-sigma parameter errors and a confidence band for the fitted curve, plus the
uncertainty of a two-anchor linear baseline.

  model(x) = b0 + b1 (x - x_mid) + sum_i peak(x; h_i, c_i, w_i[, eta_i])

Constraints: heights >= 0; each centre within +/- max_shift of its seed; widths in
[min_fwhm, max_fwhm]; optionally one shared width for all peaks. Robust loss ("soft_l1" or
"huber", scipy.optimize.least_squares) limits the pull of spikes and outliers.

Errors come from the Jacobian at the solution, J^T J scaled by the residual variance (the
usual least-squares covariance). They assume the model is right and the noise independent;
correlated residuals or a wrong peak count make them too small. The band is the delta-method
1-sigma (or k-sigma) band of the fitted curve, not a prediction interval for new data.
"""
import numpy as np

try:
    import peak_fitting
except ImportError:  # pragma: no cover
    from modules import peak_fitting


def _peak(shape, x, p):
    if shape == "pseudo_voigt":
        return peak_fitting.pseudo_voigt(x, p[0], p[1], p[2], p[3], 0.0)
    if shape == "lorentzian":
        return peak_fitting.lorentzian(x, p[0], p[1], p[2], 0.0)
    return peak_fitting.gaussian(x, p[0], p[1], p[2], 0.0)


def fit_peaks_global(x, y, centers, shape="gaussian", x_range=None, max_shift=None, fwhm_guess=None,
                     min_fwhm=None, max_fwhm=None, shared_fwhm=False, loss="linear", f_scale=None):
    """Fit len(centers) peaks at once. Returns {"peaks": [{height, center, fwhm[, eta], area,
    stderr: {...}}], "baseline": (b0, b1, x_mid), "r_squared", "rmse", "cov", "params", "shape",
    "loss", "x_range", "success", "message"}."""
    from scipy.optimize import least_squares

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    centers = [float(c) for c in centers]
    if not centers:
        raise ValueError("Give at least one peak position.")
    if shape not in ("gaussian", "lorentzian", "pseudo_voigt"):
        raise ValueError("shape must be gaussian, lorentzian or pseudo_voigt.")
    if x_range is None:
        span = (max(centers) - min(centers)) or 1.0
        pad = max(span, fwhm_guess * 4 if fwhm_guess else span)
        x_range = (min(centers) - pad, max(centers) + pad)
    lo, hi = min(x_range), max(x_range)
    m = np.isfinite(x) & np.isfinite(y) & (x >= lo) & (x <= hi)
    xs, ys = x[m], y[m]
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    n_pk = len(centers)
    per = 4 if shape == "pseudo_voigt" else 3
    if len(xs) < n_pk * per + 3:
        raise ValueError("Too few points in the fit range for this many peaks.")
    step = float(np.median(np.diff(xs)))
    width = hi - lo
    fwhm_guess = float(fwhm_guess) if fwhm_guess else width / (4.0 * n_pk)
    min_fwhm = float(min_fwhm) if min_fwhm else 2.0 * step
    max_fwhm = float(max_fwhm) if max_fwhm else width
    max_shift = float(max_shift) if max_shift is not None else max(fwhm_guess, 3 * step)
    x_mid = 0.5 * (lo + hi)
    yspan = float(np.ptp(ys)) or 1.0

    # parameter vector: [b0, b1, (h, c, [eta]) * n, w (shared) | w_i]
    p0, lb, ub = [float(np.min(ys)), 0.0], [-np.inf, -np.inf], [np.inf, np.inf]
    for c in centers:
        h0 = max(float(np.interp(c, xs, ys) - np.min(ys)), 1e-6 * yspan)
        p0 += [h0, c]
        lb += [0.0, c - max_shift]
        ub += [np.inf, c + max_shift]
        if shape == "pseudo_voigt":
            p0.append(0.5)
            lb.append(0.0)
            ub.append(1.0)
    n_w = 1 if shared_fwhm else n_pk
    p0 += [min(max(fwhm_guess, min_fwhm * 1.01), max_fwhm * 0.99)] * n_w
    lb += [min_fwhm] * n_w
    ub += [max_fwhm] * n_w
    p0 = np.clip(np.array(p0), np.array(lb) + 1e-12, np.array(ub) - 1e-12)
    stride = 3 if shape == "pseudo_voigt" else 2

    def unpack(p):
        b0, b1 = p[0], p[1]
        out = []
        for i in range(n_pk):
            q = p[2 + i * stride: 2 + (i + 1) * stride]
            w = p[2 + n_pk * stride + (0 if shared_fwhm else i)]
            out.append((q[0], q[1], w, q[2]) if shape == "pseudo_voigt" else (q[0], q[1], w))
        return b0, b1, out

    def model(p, xx):
        b0, b1, pk = unpack(p)
        yy = b0 + b1 * (xx - x_mid)
        for q in pk:
            yy = yy + _peak(shape, xx, q)
        return yy

    res = least_squares(lambda p: model(p, xs) - ys, p0, bounds=(lb, ub), loss=loss,
                        f_scale=float(f_scale) if f_scale else max(3.0 * _noise(ys), 1e-12), max_nfev=20000)
    p = res.x
    resid = ys - model(p, xs)
    dof = max(len(xs) - len(p), 1)
    J = res.jac
    s2 = float(np.sum(resid ** 2)) / dof
    try:
        cov = np.linalg.pinv(J.T @ J) * s2
    except np.linalg.LinAlgError:
        cov = np.full((len(p), len(p)), np.nan)
    se = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    b0, b1, pk = unpack(p)
    peaks = []
    for i, q in enumerate(pk):
        base = 2 + i * stride
        w_idx = 2 + n_pk * stride + (0 if shared_fwhm else i)
        d = {"height": float(q[0]), "center": float(q[1]), "fwhm": float(q[2]),
             "stderr": {"height": float(se[base]), "center": float(se[base + 1]), "fwhm": float(se[w_idx])}}
        if shape == "pseudo_voigt":
            d["eta"] = float(q[3])
            d["stderr"]["eta"] = float(se[base + 2])
        d["area"] = peak_fitting.profile_area(d["height"], d["fwhm"], shape, d.get("eta", 0.0))
        d["at_bound"] = bool(abs(q[1] - (centers[i] - max_shift)) < 1e-9 or abs(q[1] - (centers[i] + max_shift)) < 1e-9
                             or abs(q[2] - min_fwhm) < 1e-12 or abs(q[2] - max_fwhm) < 1e-12)
        peaks.append(d)
    ss_tot = float(np.sum((ys - ys.mean()) ** 2))
    return {"peaks": peaks, "baseline": (float(b0), float(b1), float(x_mid)), "shape": shape, "loss": loss,
            "shared_fwhm": bool(shared_fwhm), "x_range": (float(lo), float(hi)),
            "r_squared": 1.0 - float(np.sum(resid ** 2)) / ss_tot if ss_tot > 0 else float("nan"),
            "rmse": float(np.sqrt(np.mean(resid ** 2))), "params": p.tolist(), "cov": cov.tolist(),
            "success": bool(res.success), "message": str(res.message),
            "_model": model}


def _noise(y):
    d = np.diff(np.asarray(y, dtype=float))
    if len(d) < 3:
        return 0.0
    return float(1.4826 * np.median(np.abs(d - np.median(d))) / np.sqrt(2.0))


def evaluate(fit, x):
    return fit["_model"](np.asarray(fit["params"], dtype=float), np.asarray(x, dtype=float))


def confidence_band(fit, x, k=1.0):
    """Delta-method band: sigma_f(x)^2 = g(x)^T C g(x), g = d model / d params (numerical).
    Returns (curve, lower, upper) at k sigma."""
    x = np.asarray(x, dtype=float)
    p = np.asarray(fit["params"], dtype=float)
    cov = np.asarray(fit["cov"], dtype=float)
    f0 = fit["_model"](p, x)
    G = np.empty((len(x), len(p)))
    for j in range(len(p)):
        h = 1e-6 * max(abs(p[j]), 1e-3)
        dp = p.copy()
        dp[j] += h
        G[:, j] = (fit["_model"](dp, x) - f0) / h
    sigma = np.sqrt(np.clip(np.einsum("ij,jk,ik->i", G, cov, G), 0.0, None))
    return f0, f0 - k * sigma, f0 + k * sigma


def baseline_uncertainty(x, y, anchors, half_window_pts=5):
    """Straight baseline through the mean of the points around two anchors, and its 1-sigma band
    from the scatter of those points (standard error of each anchor mean, propagated linearly).
    Returns (baseline, sigma) on x."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if len(anchors) != 2:
        raise ValueError("Give two anchor positions.")
    order = np.argsort(x)
    xs, ys = x[order], y[order]
    pts = []
    for a in sorted(anchors):
        i = int(np.clip(np.searchsorted(xs, a), 0, len(xs) - 1))
        sl = slice(max(i - half_window_pts, 0), min(i + half_window_pts + 1, len(xs)))
        seg_x, seg_y = xs[sl], ys[sl]
        n = len(seg_y)
        sem = float(np.std(seg_y, ddof=1) / np.sqrt(n)) if n > 1 else 0.0
        pts.append((float(np.mean(seg_x)), float(np.mean(seg_y)), sem))
    (x1, y1, s1), (x2, y2, s2) = pts
    t = (x - x1) / (x2 - x1)
    base = y1 + t * (y2 - y1)
    sigma = np.sqrt(((1 - t) * s1) ** 2 + (t * s2) ** 2)
    return base, sigma
