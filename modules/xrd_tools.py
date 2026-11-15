"""
xrd_tools.py
XRD helpers beyond single-peak calculations:

  * calibration against a standard whose d-spacings the USER enters from its certificate
    (zero shift, optionally sample displacement), and applying the correction;
  * instrument-broadening propagation into the Scherrer size uncertainty;
  * pattern warnings: amorphous background / halo, and preferred orientation against a
    user-supplied card's relative intensities;
  * cubic indexing helper (ratio method) that lists candidates, never a single "answer";
  * cross-check of observed peaks against a user-supplied, legally obtained phase card
    (CSV of d or 2theta and relative intensity). The result says whether the peaks are
    CONSISTENT with the card; it does not identify a phase.

No reference values are built in: certificate values and phase cards come from the user's own
licensed sources, and their file name / source note travels with the result.
"""
import csv
import math

import numpy as np

try:
    import xrd_analysis
except ImportError:  # pragma: no cover
    from modules import xrd_analysis


# ------------------------------------------------------------------------------- calibration
def calibrate(observed_two_theta, certified_d, wavelength_a, displacement=False):
    """Least-squares correction 2theta_true = 2theta_obs - delta, with
    delta = z (zero shift), or delta = z + s*cos(theta) (zero shift and sample displacement,
    the usual Bragg-Brentano form, s = -2 h cos(theta)/R expressed in degrees).
    certified_d: the standard's d-spacings from its certificate (Angstrom), one per observed peak.
    Returns {"zero_shift_deg", "displacement_deg", "residuals_deg", "rms_deg", "n", "model"}."""
    obs = np.asarray(observed_two_theta, dtype=float)
    d = np.asarray(certified_d, dtype=float)
    if obs.shape != d.shape or len(obs) < (2 if displacement else 1):
        raise ValueError("Give one certified d-spacing per observed peak (at least 2 peaks for displacement).")
    true_tt = np.array([xrd_analysis.two_theta_from_d(v, wavelength_a) or np.nan for v in d])
    if np.any(~np.isfinite(true_tt)):
        raise ValueError("A certified d-spacing is not reachable at this wavelength.")
    delta = obs - true_tt
    if displacement:
        A = np.vstack([np.ones_like(obs), np.cos(np.radians(true_tt / 2.0))]).T
        (z, s), *_ = np.linalg.lstsq(A, delta, rcond=None)
    else:
        z, s = float(np.mean(delta)), 0.0
    model = z + s * np.cos(np.radians(true_tt / 2.0))
    resid = delta - model
    return {"zero_shift_deg": float(z), "displacement_deg": float(s), "residuals_deg": resid.tolist(),
            "rms_deg": float(np.sqrt(np.mean(resid ** 2))), "n": int(len(obs)),
            "model": "zero shift + displacement" if displacement else "zero shift"}


def apply_calibration(two_theta, cal):
    """Corrected 2theta for a pattern: 2theta - (z + s cos(theta)). theta of the correction is
    taken from the observed angle (the difference is second order)."""
    tt = np.asarray(two_theta, dtype=float)
    return tt - (cal["zero_shift_deg"] + cal["displacement_deg"] * np.cos(np.radians(tt / 2.0)))


# ------------------------------------------------------------------------------- uncertainty
def scherrer_with_uncertainty(B_deg, sigma_B_deg, two_theta_deg, wavelength_a, K=0.9, b_deg=0.0,
                              sigma_b_deg=0.0, mode="gaussian", sigma_two_theta_deg=0.0):
    """Scherrer size and its 1-sigma uncertainty with the instrument width b removed.
    Gaussian: beta = sqrt(B^2 - b^2), sigma_beta^2 = (B sB)^2/beta^2 + (b sb)^2/beta^2.
    Lorentzian: beta = B - b, sigma_beta^2 = sB^2 + sb^2.
    sigma_D/D = sqrt((sigma_beta/beta)^2 + (tan(theta) sigma_theta)^2), theta in radians.
    Returns None when the peak is not measurably broader than the instrument."""
    beta = xrd_analysis.correct_instrumental(B_deg, b_deg, mode=mode)
    if beta is None:
        return None
    if b_deg <= 0:
        s_beta = sigma_B_deg
    elif mode == "lorentzian":
        s_beta = math.hypot(sigma_B_deg, sigma_b_deg)
    else:
        s_beta = math.hypot(B_deg * sigma_B_deg, b_deg * sigma_b_deg) / beta
    D = xrd_analysis.scherrer_crystallite_size(beta, two_theta_deg, wavelength_a, K=K)
    theta = math.radians(two_theta_deg / 2.0)
    rel = math.hypot(s_beta / beta, math.tan(theta) * math.radians(sigma_two_theta_deg / 2.0))
    return {"size_nm": D, "sigma_nm": D * rel, "beta_deg": beta, "sigma_beta_deg": s_beta, "K": K, "mode": mode}


# ------------------------------------------------------------------------------- warnings
def amorphous_background_warning(two_theta, intensity, background, threshold=0.5, hump_ratio=1.3):
    """Warn when the background holds most of the signal or rises in a hump (a halo) above the
    straight line joining its ends. Returns {"background_fraction", "hump_ratio", "warnings"}."""
    from scipy.integrate import trapezoid

    x = np.asarray(two_theta, dtype=float)
    y = np.asarray(intensity, dtype=float)
    bg = np.asarray(background, dtype=float)
    o = np.argsort(x)
    x, y, bg = x[o], y[o], bg[o]
    total = trapezoid(np.clip(y, 0, None), x)
    frac = float(trapezoid(np.clip(bg, 0, None), x) / total) if total > 0 else float("nan")
    n = max(len(x) // 50, 3)
    line = np.interp(x, [x[:n].mean(), x[-n:].mean()], [bg[:n].mean(), bg[-n:].mean()])
    ratio = float(np.max(bg / np.where(line > 0, line, np.nan))) if np.any(line > 0) else float("nan")
    warnings = []
    if frac > threshold:
        warnings.append(f"The background holds {100 * frac:.0f} % of the integrated intensity: the sample may be "
                        "largely amorphous, or the background estimate is too high. Sizes and crystallinity from "
                        "this pattern are uncertain.")
    if np.isfinite(ratio) and ratio > hump_ratio:
        i = int(np.nanargmax(bg / np.where(line > 0, line, np.nan)))
        warnings.append(f"The background rises in a broad hump (×{ratio:.1f} over a straight line, near "
                        f"2θ = {x[i]:.1f}°): an amorphous halo or a sample holder contribution.")
    return {"background_fraction": frac, "hump_ratio": ratio, "warnings": warnings}


def preferred_orientation_warning(matched, factor=2.0):
    """matched: [(two_theta, observed_relative_I, card_relative_I)], intensities on any scale.
    Both sets are scaled to their strongest matched line; a reflection off by more than
    `factor` either way is listed. Strong texture (or a wrong card) gives such ratios."""
    if len(matched) < 2:
        return {"ratios": [], "warnings": []}
    tt, obs, card = (np.array(v, dtype=float) for v in zip(*matched))
    obs = obs / obs.max()
    card = card / card.max()
    ratios = obs / np.where(card > 0, card, np.nan)
    flagged = [(float(t), float(r)) for t, r in zip(tt, ratios) if np.isfinite(r) and (r > factor or r < 1 / factor)]
    warnings = []
    if flagged:
        warnings.append("Relative intensities differ from the card by more than ×{:g} at {}: preferred orientation "
                        "(texture), coarse grains, or a different phase. Peak positions are still usable; "
                        "intensity-based conclusions are not.".format(
                            factor, ", ".join(f"{t:.2f}° (×{r:.2f})" for t, r in flagged)))
    return {"ratios": [(float(t), float(r)) for t, r in zip(tt, ratios)], "warnings": warnings}


# ------------------------------------------------------------------------------- indexing
def index_cubic(two_theta, wavelength_a, max_hkl_sum=40, tolerance=0.02):
    """Ratio method for cubic patterns: sin^2(theta) = (lambda^2 / 4a^2) N, N = h^2+k^2+l^2.
    Tries the first reflection as N1 in {1, 2, 3, 4} and keeps every trial whose ratios fall on
    integers within `tolerance` (relative). Returns candidates sorted by fit quality, each with
    a, the N and (hkl) of every peak, the allowed lattices, and the rms misfit. These are
    candidates for checking, not an indexing result."""
    tt = np.sort(np.asarray(two_theta, dtype=float))
    s2 = np.sin(np.radians(tt / 2.0)) ** 2
    allowed_N = {h * h + k * k + l * l: (h, k, l) for h in range(7) for k in range(h + 1) for l in range(k + 1)
                 if 0 < h * h + k * k + l * l <= max_hkl_sum}
    candidates = []
    for n1 in (1, 2, 3, 4):
        N = s2 / s2[0] * n1
        Nr = np.rint(N).astype(int)
        rel = np.abs(N - Nr) / np.maximum(Nr, 1)
        if np.any(rel > tolerance) or any(n not in allowed_N for n in Nr):
            continue
        a_each = wavelength_a / (2.0 * np.sqrt(s2 / Nr))
        hkl = [allowed_N[n] for n in Nr]
        lattices = []
        if all((sum(h) % 2 == 0) for h in hkl):
            lattices.append("I")
        if all(len({v % 2 for v in h}) == 1 for h in hkl):
            lattices.append("F")
        lattices.insert(0, "P")
        candidates.append({"a": float(np.mean(a_each)), "a_sd": float(np.std(a_each, ddof=1)) if len(tt) > 1 else 0.0,
                           "N": Nr.tolist(), "hkl": hkl, "lattices_consistent": lattices,
                           "rms_misfit": float(np.sqrt(np.mean((N - Nr) ** 2))), "two_theta": tt.tolist()})
    candidates.sort(key=lambda c: (c["rms_misfit"], len(c["lattices_consistent"]) == 1))
    return candidates


# ------------------------------------------------------------------------------- phase cards
def load_phase_card(path):
    """User-supplied card CSV with a header: 'd' (Angstrom) or 'two_theta' (deg, with a
    'wavelength' column or a '# wavelength=' line), 'intensity' (relative), optional 'hkl'.
    Lines starting with '#' are notes ('# name=...', '# source=...', '# licence=...').
    Strict: ragged rows and non-numeric values are refused with the line number."""
    meta, rows = {}, []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        lines = f.read().splitlines()
    data_lines = []
    for lineno, ln in enumerate(lines, start=1):
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#"):
            k, _, v = s[1:].partition("=")
            if v:
                meta[k.strip().lower()] = v.strip()
            continue
        data_lines.append((lineno, s))
    if not data_lines:
        raise ValueError("The phase card has no data rows.")
    header = [h.strip().lower() for h in next(csv.reader([data_lines[0][1]]))]
    if "intensity" not in header or not ({"d", "two_theta"} & set(header)):
        raise ValueError("The phase card needs columns 'd' or 'two_theta', and 'intensity'.")
    for lineno, s in data_lines[1:]:
        vals = next(csv.reader([s]))
        if len(vals) != len(header):
            raise ValueError(f"Phase card line {lineno} has {len(vals)} values; the header has {len(header)}.")
        rec = dict(zip(header, [v.strip() for v in vals]))
        try:
            row = {"intensity": float(rec["intensity"])}
            if "d" in rec and rec["d"]:
                row["d"] = float(rec["d"])
            if "two_theta" in rec and rec["two_theta"]:
                row["two_theta"] = float(rec["two_theta"])
        except ValueError:
            raise ValueError(f"Phase card line {lineno}: a value is not a number.") from None
        if not all(math.isfinite(v) for v in row.values()):
            raise ValueError(f"Phase card line {lineno}: non-finite value.")
        row["hkl"] = rec.get("hkl", "")
        rows.append(row)
    wl = meta.get("wavelength")
    for r in rows:
        if "d" not in r:
            if not wl:
                raise ValueError("A card given in 2θ needs '# wavelength=<Angstrom>' so it can be converted to d.")
            r["d"] = float(xrd_analysis.bragg_d_spacing(r["two_theta"], float(wl)))
    return {"name": meta.get("name", ""), "source": meta.get("source", ""), "licence": meta.get("licence", ""),
            "lines": rows, "path": str(path)}


def cross_check_card(peaks_two_theta, peak_intensities, card, wavelength_a, tol_deg=0.10, min_rel_intensity=10.0,
                     measured_range=None):
    """Which card lines (relative intensity >= min_rel_intensity % of the strongest) have an observed
    peak within tol_deg, and which observed peaks the card does not explain. Returns the
    matched pairs, missing strong lines, unexplained peaks, the fraction of strong lines
    found, the mean |delta 2theta|, and a verdict that is at most "consistent with the card"."""
    obs = np.asarray(peaks_two_theta, dtype=float)
    inten = np.asarray(peak_intensities, dtype=float)
    imax = max(r["intensity"] for r in card["lines"]) or 1.0
    if measured_range is not None:
        rng = (min(measured_range), max(measured_range))
    else:                                 # the pattern's range should be given; peaks +/- 1 deg otherwise
        rng = (float(obs.min()) - 1.0, float(obs.max()) + 1.0) if obs.size else None
    strong = []
    for r in card["lines"]:
        tt = xrd_analysis.two_theta_from_d(r["d"], wavelength_a)
        if tt is None or r["intensity"] / imax * 100 < min_rel_intensity:
            continue
        if rng is not None and not (rng[0] <= tt <= rng[1]):
            continue                     # outside the measured range
        strong.append((tt, r))
    used, matched, missing = set(), [], []
    for tt, r in sorted(strong, key=lambda t: -t[1]["intensity"]):
        if obs.size:
            j = int(np.argmin(np.abs(obs - tt)))
            if abs(obs[j] - tt) <= tol_deg and j not in used:
                used.add(j)
                matched.append({"card_two_theta": tt, "observed_two_theta": float(obs[j]), "delta_deg": float(obs[j] - tt),
                                "card_intensity": r["intensity"], "observed_intensity": float(inten[j]), "hkl": r["hkl"]})
                continue
        missing.append({"card_two_theta": tt, "card_intensity": r["intensity"], "hkl": r["hkl"]})
    unexplained = [float(obs[j]) for j in range(len(obs)) if j not in used]
    frac = len(matched) / len(strong) if strong else 0.0
    mean_delta = float(np.mean([abs(m["delta_deg"]) for m in matched])) if matched else float("nan")
    if not strong:
        verdict = "no card lines in the measured range"
    elif frac >= 0.8 and not any(m["card_intensity"] / imax >= 0.5 for m in missing):
        verdict = "consistent with the card (not an identification)"
    elif frac >= 0.5:
        verdict = "partly consistent: some strong card lines are missing"
    else:
        verdict = "not consistent with the card"
    po = preferred_orientation_warning([(m["observed_two_theta"], m["observed_intensity"], m["card_intensity"])
                                        for m in matched])
    return {"card": card.get("name", ""), "source": card.get("source", ""), "licence": card.get("licence", ""),
            "matched": matched, "missing_strong": missing, "unexplained_peaks": unexplained,
            "fraction_found": frac, "mean_abs_delta_deg": mean_delta, "verdict": verdict,
            "warnings": po["warnings"],
            "caveat": "Generic peak matching cannot establish phase identity; confirm with composition, other "
                      "techniques or a full-pattern refinement."}
