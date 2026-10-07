"""
ftir_matching.py
Weighted-evidence matching of a detected FTIR peak list against the reference database,
multi-component (mixture) screening, and a synthetic reference spectrum for visual checks.

The database stores literature band *ranges* with intensity labels, not measured spectra, so
full-spectrum correlation (a Hit Quality Index) cannot be computed. This module scores the
peak list instead. For each material it combines:

  F  forward score:  intensity-weighted share of the material's reference bands found in the
                     sample, each scaled by how close the peak sits to the band
  R  reverse score:  share of the sample's peak prominence, inside the material's own spectral
                     window, that the material accounts for
  P  chance:         probability that at least that many bands would be hit by coincidence,
                     given how crowded the peak list is (Poisson-binomial)

  Pf family-wise:    1 - (1 - P)^M for M materials searched -- the best of many candidates
                     matches well by coincidence alone (the look-elsewhere effect)
  S  significance:   min(1, -log10(Pf) / 2), so full credit needs Pf <= 0.01

  confidence C = F^0.6 * R^0.4 * S

The weights and thresholds are engineering choices made for this database. They are not
published constants: docs/FTIR_MATCHING_PLAN.md explains them and how they were tested. The
idea of checking both directions follows forward/backward library searching (Lavine et al.,
Talanta 2016), and the chance term follows the likelihood view of spectral comparison reviewed
by Lavine et al. (Forensic Chemistry 2020). This is screening, not identification.
"""
import math

import numpy as np

# ---------------------------------------------------------------- tunable constants
# Weight of a reference band, from its intensity label.
INTENSITY_WEIGHTS = (
    ("very strong", 1.0),
    ("medium-strong", 0.8),
    ("weak-medium", 0.45),
    ("strong", 1.0),
    ("medium", 0.6),
    ("weak", 0.3),
)
DEFAULT_WEIGHT = 0.5
STRONG_WEIGHT = 1.0                 # bands at this weight are reported when missing
BROAD_TOLERANCE_FACTOR = 2.0
STRONG_REF_WEAK_OBS_FACTOR = 0.6    # a strong reference band matched only by a weak peak
OBS_STRONG, OBS_MEDIUM = 0.5, 0.15  # relative prominence classes of observed peaks
# Peaks below this fraction of the largest prominence are treated as possible noise by the
# chance test: they neither raise the peak density nor count as hits there. They still
# contribute (down-weighted) to the forward and reverse scores.
CHANCE_MIN_REL_PROMINENCE = 0.05
WINDOW_MARGIN_CM1 = 50.0
FORWARD_EXP, REVERSE_EXP = 0.6, 0.4
SIGNIFICANCE_FULL_LOG10 = 2.0       # -log10(P_chance) that earns full credit (P <= 0.01)
EDGE_POSITION_SCORE = 0.5           # below this a matched band is shown as "edge"
DEFAULT_SPECTRAL_RANGE = (400.0, 4000.0)

TIERS = (("High", 0.60), ("Medium", 0.40), ("Low", 0.20), ("Weak", 0.0))

METHOD_WEIGHTED = "weighted"
METHOD_COVERAGE = "coverage"
METHOD_LABELS = {METHOD_WEIGHTED: "Weighted evidence (recommended)", METHOD_COVERAGE: "Coverage (legacy)"}


# ---------------------------------------------------------------- band helpers
def parse_intensity(label):
    """(weight, is_broad) from a database intensity label such as 'broad, strong'."""
    text = str(label or "").lower()
    broad = "broad" in text
    for key, weight in INTENSITY_WEIGHTS:
        if key in text:
            return weight, broad
    return DEFAULT_WEIGHT, broad


def is_matchable(ref_peak):
    lo, hi = ref_peak["range"]
    return not (lo == 0 and hi == 0)


def band_tolerance(ref_peak, tolerance):
    _w, broad = parse_intensity(ref_peak.get("intensity"))
    return tolerance * (BROAD_TOLERANCE_FACTOR if broad else 1.0)


def position_score(x, lo, hi, tol):
    """1 inside [lo, hi], Gaussian fall-off outside (sigma = tol/2), 0 beyond the tolerance."""
    lo, hi = min(lo, hi), max(lo, hi)
    d = max(lo - x, 0.0, x - hi)
    if d > tol:
        return 0.0
    sigma = max(tol / 2.0, 1e-9)
    return math.exp(-0.5 * (d / sigma) ** 2)


def confidence_tier(confidence):
    for name, threshold in TIERS:
        if confidence >= threshold:
            return name
    return TIERS[-1][0]


def _relative_prominences(peaks, reference_max=None):
    prom = np.array([float(p.get("prominence", 1.0) or 0.0) for p in peaks], dtype=float)
    top = reference_max if reference_max else (prom.max() if len(prom) else 1.0)
    if not top or top <= 0:
        return np.ones(len(peaks))
    return np.clip(prom / top, 0.0, None)


def _observed_class(rel):
    if rel >= OBS_STRONG:
        return "strong"
    if rel >= OBS_MEDIUM:
        return "medium"
    return "weak"


def _intensity_factor(weight, rel):
    if weight >= 0.8 and _observed_class(rel) == "weak":
        return STRONG_REF_WEAK_OBS_FACTOR
    return 1.0


def poisson_binomial_tail(probs, k):
    """P(X >= k) for X = sum of independent Bernoulli(p_i). Exact, by dynamic programming."""
    if k <= 0:
        return 1.0
    dist = np.zeros(len(probs) + 1)
    dist[0] = 1.0
    for i, p in enumerate(probs):
        p = min(max(float(p), 0.0), 1.0)
        dist[1:i + 2] = dist[1:i + 2] * (1 - p) + dist[0:i + 1] * p
        dist[0] *= (1 - p)
    return float(min(max(dist[k:].sum(), 0.0), 1.0))


def family_wise(p_chance, n_searched):
    """Probability that at least one of n_searched materials matches this well by chance."""
    p = min(max(float(p_chance), 0.0), 1.0)
    n = max(int(n_searched), 1)
    return -math.expm1(n * math.log1p(-p)) if p < 1.0 else 1.0


def chance_significance(p_chance):
    """0..1 credit for how unlikely the band hits are by coincidence."""
    p = min(max(float(p_chance), 1e-12), 1.0)
    return min(1.0, -math.log10(p) / SIGNIFICANCE_FULL_LOG10)


def peak_density(peaks, spectral_range=None, rel_prom=None):
    """Peaks per cm-1 over the measured range, counting only peaks at or above
    CHANCE_MIN_REL_PROMINENCE when relative prominences are given."""
    xs = [p["x"] for p in peaks]
    lo, hi = spectral_range or DEFAULT_SPECTRAL_RANGE
    if xs:
        lo, hi = min(lo, min(xs)), max(hi, max(xs))
    span = max(hi - lo, 1.0)
    if rel_prom is None:
        return len(peaks) / span
    return int(np.sum(np.asarray(rel_prom) >= CHANCE_MIN_REL_PROMINENCE)) / span


# ---------------------------------------------------------------- one material
def score_entry(entry, peaks, tolerance=10.0, rel_prom=None, density=None, n_searched=1):
    """
    Weighted-evidence score of one database entry against a peak list. Returns None when
    the entry has no matchable band or no band was matched. `rel_prom` (relative prominence
    of each peak) and `density` (peaks per cm-1) can be passed in to share work across entries;
    `n_searched` is the number of materials in the search, for the family-wise correction.
    """
    from scipy.optimize import linear_sum_assignment

    bands = [rp for rp in entry.get("peaks", []) if is_matchable(rp)]
    if not bands or not peaks:
        return None
    if rel_prom is None:
        rel_prom = _relative_prominences(peaks)
    if density is None:
        density = peak_density(peaks, rel_prom=rel_prom)

    weights, tols = [], []
    for rp in bands:
        w, _broad = parse_intensity(rp.get("intensity"))
        weights.append(w)
        tols.append(band_tolerance(rp, tolerance))

    # candidate peaks: anything within reach of at least one band
    xs = np.array([p["x"] for p in peaks], dtype=float)
    cand = set()
    for rp, tol in zip(bands, tols):
        lo, hi = min(rp["range"]), max(rp["range"])
        cand.update(np.nonzero((xs >= lo - tol) & (xs <= hi + tol))[0].tolist())
    if not cand:
        return None
    cand = sorted(cand)

    value = np.zeros((len(bands), len(cand)))
    pos = np.zeros_like(value)
    for i, (rp, tol, w) in enumerate(zip(bands, tols, weights)):
        lo, hi = rp["range"]
        for j, pi in enumerate(cand):
            s = position_score(xs[pi], lo, hi, tol)
            if s > 0:
                pos[i, j] = s
                value[i, j] = w * s * _intensity_factor(w, rel_prom[pi])
    rows, cols = linear_sum_assignment(-value)

    assigned = {}
    for i, j in zip(rows, cols):
        if value[i, j] > 0:
            assigned[i] = (cand[j], pos[i, j], value[i, j] / (weights[i] * pos[i, j]))
    if not assigned:
        return None

    total_w = float(sum(weights))
    forward = sum(weights[i] * s * f for i, (_pi, s, f) in assigned.items()) / total_w

    lows = [min(rp["range"]) for rp in bands]
    highs = [max(rp["range"]) for rp in bands]
    w_lo, w_hi = min(lows) - WINDOW_MARGIN_CM1, max(highs) + WINDOW_MARGIN_CM1
    in_window = (xs >= w_lo) & (xs <= w_hi)
    window_prom = float(rel_prom[in_window].sum())
    explained_idx = sorted(pi for pi, _s, _f in assigned.values())
    explained_prom = float(sum(rel_prom[pi] for pi in explained_idx))
    reverse = explained_prom / window_prom if window_prom > 0 else 0.0

    chance_probs = [1.0 - math.exp(-density * ((max(rp["range"]) - min(rp["range"])) + 2 * tol))
                    for rp, tol in zip(bands, tols)]
    significant_hits = sum(1 for pi, _s, _f in assigned.values() if rel_prom[pi] >= CHANCE_MIN_REL_PROMINENCE)
    p_chance = poisson_binomial_tail(chance_probs, significant_hits)

    p_family = family_wise(p_chance, n_searched)
    significance = chance_significance(p_family)
    confidence = (forward ** FORWARD_EXP) * (reverse ** REVERSE_EXP) * significance

    band_rows, matches, missing_strong = [], [], []
    for i, rp in enumerate(bands):
        center = (rp["range"][0] + rp["range"][1]) / 2
        if i in assigned:
            pi, s, f = assigned[i]
            obs = peaks[pi]
            mm = {"reference": rp, "observed": obs, "delta_cm1": obs["x"] - center,
                  "position_score": s, "intensity_factor": f, "weight": weights[i], "peak_id": pi}
            matches.append(mm)
            status = "matched" if s >= EDGE_POSITION_SCORE else "edge"
            band_rows.append({"reference": rp, "status": status, "weight": weights[i], "match": mm})
        else:
            band_rows.append({"reference": rp, "status": "missing", "weight": weights[i], "match": None})
            if weights[i] >= STRONG_WEIGHT:
                missing_strong.append(rp)

    return {
        "name": entry["name"],
        "category": entry.get("category", ""),
        "source": entry.get("source", ""),
        "method": METHOD_WEIGHTED,
        "score": confidence,
        "confidence": confidence,
        "tier": confidence_tier(confidence),
        "forward_score": forward,
        "reverse_score": reverse,
        "chance_probability": p_chance,
        "family_chance_probability": p_family,
        "significance": significance,
        "coverage": len(assigned) / len(bands),
        "matched_count": len(assigned),
        "total_reference_peaks": len(bands),
        "missing_strong": missing_strong,
        "explained_peak_ids": explained_idx,
        "bands": band_rows,
        "matches": sorted(matches, key=lambda m: m["reference"]["range"][0]),
    }


def match_weighted(peaks, entries, tolerance=10.0, spectral_range=None, prominence_max=None):
    """Score every entry and return them ranked by confidence (best first)."""
    if not peaks:
        return []
    rel = _relative_prominences(peaks, prominence_max)
    density = peak_density(peaks, spectral_range, rel_prom=rel)
    entries = list(entries)
    results = []
    for entry in entries:
        r = score_entry(entry, peaks, tolerance=tolerance, rel_prom=rel, density=density,
                        n_searched=len(entries))
        if r is not None:
            results.append(r)
    results.sort(key=lambda r: (r["confidence"], r["forward_score"], r["matched_count"]), reverse=True)
    return results


# ---------------------------------------------------------------- mixtures
def analyse_mixture(peaks, entries, tolerance=10.0, spectral_range=None, max_components=3,
                    min_confidence=0.35):
    """
    Greedy multi-component screening: accept the best-scoring material, remove the peaks it
    explains, re-rank the rest on the remaining peaks, and repeat. Returns
    {"components": [...], "unexplained": [peaks], "explained_share": float}. Each component is
    a score_entry() result plus "share" (its fraction of the total peak prominence) and
    "explained_peaks" (the peak dicts it accounts for).
    """
    if not peaks:
        return {"components": [], "unexplained": [], "explained_share": 0.0}
    rel_all = _relative_prominences(peaks)
    total = float(rel_all.sum()) or 1.0
    prom_max = max(float(p.get("prominence", 1.0) or 0.0) for p in peaks) or None
    remaining = list(range(len(peaks)))
    used_names = set()
    components = []
    for _ in range(max_components):
        sub = [peaks[i] for i in remaining]
        if not sub:
            break
        ranked = [r for r in match_weighted(sub, entries, tolerance, spectral_range, prom_max)
                  if r["name"] not in used_names]
        if not ranked or ranked[0]["confidence"] < min_confidence:
            break
        best = ranked[0]
        ids = [remaining[k] for k in best["explained_peak_ids"]]
        if not ids:
            break
        best["explained_peaks"] = [peaks[i] for i in ids]
        best["share"] = float(sum(rel_all[i] for i in ids)) / total
        components.append(best)
        used_names.add(best["name"])
        remaining = [i for i in remaining if i not in set(ids)]
    unexplained = [peaks[i] for i in remaining]
    explained_share = 1.0 - float(sum(rel_all[i] for i in remaining)) / total
    return {"components": components, "unexplained": unexplained, "explained_share": explained_share}


# ---------------------------------------------------------------- synthetic spectrum
def synthetic_reference_spectrum(entry, x):
    """One Gaussian per reference band: height = band weight, FWHM = range width (min 8 cm-1,
    60 cm-1 for broad bands). For drawing and for the informational pattern correlation only."""
    x = np.asarray(x, dtype=float)
    y = np.zeros_like(x)
    for rp in entry.get("peaks", []):
        if not is_matchable(rp):
            continue
        w, broad = parse_intensity(rp.get("intensity"))
        lo, hi = min(rp["range"]), max(rp["range"])
        fwhm = max(hi - lo, 60.0 if broad else 8.0)
        sigma = fwhm / (2 * math.sqrt(2 * math.log(2)))
        y += w * np.exp(-0.5 * ((x - (lo + hi) / 2) / sigma) ** 2)
    return y


def pattern_correlation(entry, x, y, mode="absorbance"):
    """Pearson r between the measured spectrum and the synthetic reference over the
    material's band window. None when it cannot be computed."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    bands = [rp for rp in entry.get("peaks", []) if is_matchable(rp)]
    if not bands or len(x) < 3:
        return None
    lo = min(min(rp["range"]) for rp in bands) - WINDOW_MARGIN_CM1
    hi = max(max(rp["range"]) for rp in bands) + WINDOW_MARGIN_CM1
    mask = (x >= lo) & (x <= hi)
    if mask.sum() < 3:
        return None
    sample = y[mask]
    if mode == "transmittance":
        sample = sample.max() - sample
    ref = synthetic_reference_spectrum(entry, x[mask])
    if np.std(sample) == 0 or np.std(ref) == 0:
        return None
    return float(np.corrcoef(sample, ref)[0, 1])
