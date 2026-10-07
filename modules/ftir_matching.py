"""
ftir_matching.py
Weighted-evidence matching of a detected FTIR peak list against the reference database,
multi-component (mixture) screening, and a synthetic reference spectrum for visual checks.

The database stores literature band *ranges* with intensity labels, not measured spectra, so
full-spectrum correlation (a Hit Quality Index) cannot be computed. This module scores the
peak list instead. For each material:

  F  forward:   intensity-weighted share of its reference bands found, each scaled by how
                close the peak sits to the band (one peak supports at most one band)
  R  reverse:   share of the sample's peak prominence in the material's band region that
                it accounts for
  P  chance:    probability of at least this many hits by coincidence, from the density of
                the peaks the material does not claim, near each band (Poisson-binomial;
                hits are counted softly by peak strength); Pf = 1-(1-P)^min(M, 20)
  S  = min(1, -log10(Pf)/2)
  U  = 1 - 0.5 * (share of the sample's strong peaks left unexplained outside its region)

  match score C = F^0.6 * R^0.4 * S * U       (a screening score, not a probability)

A Strong tier also needs no missing strong band, more than two bands, and a margin of 0.10
over every other candidate. The weights and thresholds are engineering choices for this
database, revised after an independent review; docs/FTIR_MATCHING_PLAN.md explains them and
their limits. Checking both directions follows forward/backward library searching (Lavine et
al., Talanta 2016). This is screening, not identification.
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

# Tier names describe the match, not a probability of being right.
TIERS = (("Strong", 0.60), ("Moderate", 0.40), ("Weak", 0.20), ("Poor", 0.0))
DETAIL_TOP = 30                     # results beyond this keep only their summary (see match_weighted)
CLOSE_CALL_MARGIN = 0.10            # a Strong tier needs this margin over the next candidate
FEW_BANDS = 2                       # entries with this many bands or fewer cannot reach Strong
FAMILY_SIZE_CAP = 20                # effective number of independent alternatives in a search
COINCIDENCE_FLAG_P = 0.05           # family-wise chance above this is flagged in the UI
LOCAL_HALF_WINDOW = 150.0           # cm-1 either side of a band for the local peak density
OUTSIDE_STRONG_PENALTY = 0.5        # score x (1 - 0.5 u), u = share of strong peaks unexplained
                                    # outside the material's band region
BROAD_MIN_FWHM = 40.0               # cm-1; sharper peaks are weak evidence for a broad band
SHARP_ON_BROAD_FACTOR = 0.3
CO2_REGION = (2280.0, 2400.0)
VAPOUR_REGIONS = ((1350.0, 1950.0), (3550.0, 3950.0))
VAPOUR_MAX_FWHM = 4.0               # cm-1; narrower lines there are treated as water vapour

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


def _prominences(peaks):
    prom = np.array([float(p.get("prominence", 1.0) or 0.0) for p in peaks], dtype=float)
    return np.nan_to_num(prom, nan=0.0, posinf=0.0, neginf=0.0)


def _relative_prominences(peaks, reference_max=None):
    prom = _prominences(peaks)
    top = reference_max if reference_max else (float(prom.max()) if len(prom) else 1.0)
    if not top or top <= 0 or not np.isfinite(top):
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
    """Probability that at least one of n_searched materials matches this well by chance.
    The count is capped at FAMILY_SIZE_CAP: library entries are far from independent (many
    share functional groups), and an uncapped count made materials with few bands unwinnable
    and made scores depend strongly on the category filter."""
    p = min(max(float(p_chance), 0.0), 1.0)
    n = min(max(int(n_searched), 1), FAMILY_SIZE_CAP)
    return -math.expm1(n * math.log1p(-p)) if p < 1.0 else 1.0


def chance_significance(p_chance):
    """0..1 credit for how unlikely the band hits are by coincidence."""
    p = min(max(float(p_chance), 1e-12), 1.0)
    return max(0.0, min(1.0, -math.log10(p) / SIGNIFICANCE_FULL_LOG10))


def soft_tail(probs, k_eff):
    """poisson_binomial_tail for a non-integer number of hits, interpolated linearly, so a
    peak sliding across the significance threshold changes the score smoothly."""
    lo = int(math.floor(k_eff))
    frac = k_eff - lo
    p_lo = poisson_binomial_tail(probs, lo)
    if frac <= 1e-9:
        return p_lo
    return p_lo + frac * (poisson_binomial_tail(probs, lo + 1) - p_lo)


def hit_strength(rel):
    """How much a peak of this relative prominence counts as evidence (0..1): full credit at
    CHANCE_MIN_REL_PROMINENCE and above, proportionally less below, so noise-level peaks
    count for little without a hard cut-off."""
    return np.clip(np.asarray(rel, dtype=float) / CHANCE_MIN_REL_PROMINENCE, 0.0, 1.0)


def peak_density(peaks, spectral_range=None, rel_prom=None):
    """Average peaks per cm-1 over the measured range, each peak weighted by hit_strength
    when relative prominences are given."""
    xs = [p["x"] for p in peaks]
    lo, hi = spectral_range or DEFAULT_SPECTRAL_RANGE
    if xs:
        lo, hi = min(lo, min(xs)), max(hi, max(xs))
    span = max(hi - lo, 1.0)
    if rel_prom is None:
        return len(peaks) / span
    return float(hit_strength(rel_prom).sum()) / span


def artefact_mask(peaks):
    """True for peaks that look like atmospheric artefacts rather than sample bands: anything
    in the CO2 region, and very narrow lines (FWHM < 4 cm-1) in the water-vapour regions.
    Peaks without a measured FWHM are only judged by position."""
    flags = []
    for p in peaks:
        x = p["x"]
        fwhm = p.get("fwhm_cm1")
        bad = CO2_REGION[0] <= x <= CO2_REGION[1]
        if fwhm is not None and fwhm < VAPOUR_MAX_FWHM and any(lo <= x <= hi for lo, hi in VAPOUR_REGIONS):
            bad = True
        flags.append(bad)
    return np.array(flags, dtype=bool)


# ---------------------------------------------------------------- one material
def score_entry(entry, peaks, tolerance=10.0, rel_prom=None, density=None, n_searched=1, spectral_range=None,
                usable=None, explained=None):
    """
    Weighted-evidence score of one database entry against a peak list. Returns None when the
    entry has no band in the measured range or no meaningful hit.

    rel_prom    relative prominence of each peak (computed if omitted)
    density     if given, one uniform peak density (peaks per cm-1) for the chance test;
                otherwise a local density around each band is used
    n_searched  number of materials in the search (family-wise correction, capped)
    spectral_range  (low, high) measured cm-1; bands wholly outside it are "outside", unscored
    usable      bool per peak; False peaks (artefacts) are ignored entirely
    explained   bool per peak; True peaks were already explained by an accepted mixture
                component: they still support this material's bands, but not its reverse
                score, outside-window penalty or "newly explained" list
    """
    from scipy.optimize import linear_sum_assignment

    all_bands = [rp for rp in entry.get("peaks", []) if is_matchable(rp)]
    outside = []
    if spectral_range is not None:
        r_lo, r_hi = min(spectral_range), max(spectral_range)
        outside = [rp for rp in all_bands if max(rp["range"]) < r_lo or min(rp["range"]) > r_hi]
    bands = [rp for rp in all_bands if not any(rp is o for o in outside)]
    if not bands or not peaks:
        return None
    n = len(peaks)
    if rel_prom is None:
        rel_prom = _relative_prominences(peaks)
    usable = np.ones(n, dtype=bool) if usable is None else np.asarray(usable, dtype=bool)
    explained = np.zeros(n, dtype=bool) if explained is None else np.asarray(explained, dtype=bool)
    strength = hit_strength(rel_prom) * usable

    weights, tols, broads = [], [], []
    for rp in bands:
        w, broad = parse_intensity(rp.get("intensity"))
        weights.append(w)
        broads.append(broad)
        tols.append(band_tolerance(rp, tolerance))

    xs = np.array([p["x"] for p in peaks], dtype=float)
    cand = set()
    for rp, tol in zip(bands, tols):
        lo, hi = min(rp["range"]), max(rp["range"])
        cand.update(np.nonzero(usable & (xs >= lo - tol) & (xs <= hi + tol))[0].tolist())
    if not cand:
        return None
    cand = sorted(cand)

    value = np.zeros((len(bands), len(cand)))
    pos = np.zeros_like(value)
    factor = np.ones_like(value)
    for i, (rp, tol, w, broad) in enumerate(zip(bands, tols, weights, broads)):
        lo, hi = rp["range"]
        for j, pi in enumerate(cand):
            s = position_score(xs[pi], lo, hi, tol)
            if s > 0:
                f = _intensity_factor(w, rel_prom[pi])
                fwhm = peaks[pi].get("fwhm_cm1")
                if broad and fwhm is not None and fwhm < BROAD_MIN_FWHM:
                    f *= SHARP_ON_BROAD_FACTOR      # a sharp peak is weak evidence for a broad band
                pos[i, j], factor[i, j] = s, f
                value[i, j] = w * s * f
    rows, cols = linear_sum_assignment(-value)

    assigned = {}
    for i, j in zip(rows, cols):
        if value[i, j] > 0:
            assigned[i] = (cand[j], pos[i, j], factor[i, j])
    if not assigned:
        return None
    assigned_ids = {pi for pi, _s, _f in assigned.values()}
    k_eff = float(sum(strength[pi] for pi in assigned_ids))
    if k_eff < 0.5:
        return None                             # only noise-level peaks hit: no evidence

    total_w = float(sum(weights))
    forward = sum(weights[i] * s * f for i, (_pi, s, f) in assigned.items()) / total_w

    # reverse score over the peaks not yet explained by someone else, inside the band window
    lows = [min(rp["range"]) for rp in bands]
    highs = [max(rp["range"]) for rp in bands]
    w_lo, w_hi = min(lows) - WINDOW_MARGIN_CM1, max(highs) + WINDOW_MARGIN_CM1
    open_peaks = usable & ~explained
    in_window = open_peaks & (xs >= w_lo) & (xs <= w_hi)
    window_prom = float(rel_prom[in_window].sum())
    new_ids = sorted(pi for pi in assigned_ids if open_peaks[pi])
    explained_prom = float(sum(rel_prom[pi] for pi in new_ids))
    reverse = explained_prom / window_prom if window_prom > 0 else 0.0

    # strong peaks of the sample that lie outside this material's region and stay unexplained
    strong_open = open_peaks & (rel_prom >= OBS_STRONG)
    strong_total = float(rel_prom[strong_open].sum())
    strong_outside = float(sum(rel_prom[i] for i in np.nonzero(strong_open & ~((xs >= w_lo) & (xs <= w_hi)))[0]
                               if i not in assigned_ids))
    unexplained_strong = strong_outside / strong_total if strong_total > 0 else 0.0
    outside_penalty = 1.0 - OUTSIDE_STRONG_PENALTY * unexplained_strong

    # chance: background density from the peaks this material does NOT claim, near each band
    chance_probs = []
    background = strength.copy()
    background[list(assigned_ids)] = 0.0
    r_lo, r_hi = (min(spectral_range), max(spectral_range)) if spectral_range else (
        min(DEFAULT_SPECTRAL_RANGE[0], xs.min()), max(DEFAULT_SPECTRAL_RANGE[1], xs.max()))
    for rp, tol in zip(bands, tols):
        width = (max(rp["range"]) - min(rp["range"])) + 2 * tol
        if density is not None:
            rho = density
        else:
            c = (rp["range"][0] + rp["range"][1]) / 2
            a, b = max(c - LOCAL_HALF_WINDOW, r_lo), min(c + LOCAL_HALF_WINDOW, r_hi)
            span = max(b - a, 2 * tol, 1.0)
            near = (xs >= a) & (xs <= b)
            rho = (float(background[near].sum()) + 1.0) / span
        chance_probs.append(1.0 - math.exp(-rho * width))
    p_chance = soft_tail(chance_probs, k_eff)
    p_family = family_wise(p_chance, n_searched)
    significance = chance_significance(p_family)
    confidence = (forward ** FORWARD_EXP) * (reverse ** REVERSE_EXP) * significance * outside_penalty
    confidence = max(0.0, float(confidence))

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
    for rp in outside:
        band_rows.append({"reference": rp, "status": "outside", "weight": parse_intensity(rp.get("intensity"))[0],
                          "match": None})
    band_rows.sort(key=lambda b: min(b["reference"]["range"]))

    tier = confidence_tier(confidence)
    caps = []
    few_bands = len(bands) <= FEW_BANDS
    if tier == "Strong" and missing_strong:
        caps.append("a strong band is missing")
    if tier == "Strong" and few_bands:
        caps.append("only one or two bands to compare")
    if caps:
        tier = "Moderate"

    return {
        "name": entry["name"],
        "category": entry.get("category", ""),
        "source": entry.get("source", ""),
        "method": METHOD_WEIGHTED,
        "score": confidence,
        "confidence": confidence,
        "tier": tier,
        "tier_capped_because": caps,
        "forward_score": forward,
        "reverse_score": reverse,
        "outside_penalty": outside_penalty,
        "chance_probability": p_chance,
        "family_chance_probability": p_family,
        "could_be_coincidence": p_family > COINCIDENCE_FLAG_P,
        "significance": significance,
        "few_bands": few_bands,
        "coverage": len(assigned) / len(bands),
        "matched_count": len(assigned),
        "total_reference_peaks": len(bands),
        "outside_count": len(outside),
        "n_searched": int(n_searched),
        "detail": True,
        "missing_strong": missing_strong,
        "explained_peak_ids": new_ids,
        "bands": band_rows,
        "matches": sorted(matches, key=lambda m: m["reference"]["range"][0]),
    }


LOOK_ALIKE_OVERLAP = 0.80           # two entries whose weighted bands overlap this much both ways
_LOOK_ALIKE_CACHE = {}


def _band_overlap(a, b, tol):
    """Weighted share of a's bands that overlap some band of b (ranges widened by tol)."""
    total = sum(w for _lo, _hi, w in a)
    if not total:
        return 0.0
    hit = sum(w for lo, hi, w in a if any(lo2 - tol <= hi and hi2 + tol >= lo for lo2, hi2, _w in b))
    return hit / total


def look_alikes(entries, tolerance=10.0):
    """{name: [names]} of database entries whose band tables nearly coincide (>= 80 % weighted
    overlap in both directions, both with >= 3 bands). A peak list cannot tell such materials
    apart, so a strong match to one is also consistent with the others -- including when the
    true material is not in the database at all. Cached per set of entries."""
    entries = list(entries)
    key = (tuple(e["name"] for e in entries), float(tolerance))
    if key in _LOOK_ALIKE_CACHE:
        return _LOOK_ALIKE_CACHE[key]
    bands = []
    for e in entries:
        bl = []
        for rp in e.get("peaks", []):
            if is_matchable(rp):
                bl.append((min(rp["range"]), max(rp["range"]), parse_intensity(rp.get("intensity"))[0]))
        bands.append(bl)
    out = {e["name"]: [] for e in entries}
    for i in range(len(entries)):
        if len(bands[i]) < 3:
            continue
        for j in range(i + 1, len(entries)):
            if len(bands[j]) < 3:
                continue
            if min(_band_overlap(bands[i], bands[j], tolerance),
                   _band_overlap(bands[j], bands[i], tolerance)) >= LOOK_ALIKE_OVERLAP:
                out[entries[i]["name"]].append(entries[j]["name"])
                out[entries[j]["name"]].append(entries[i]["name"])
    _LOOK_ALIKE_CACHE[key] = out
    return out


def _flag_close_calls(results):
    """A Strong tier needs a clear margin over every other candidate: within CLOSE_CALL_MARGIN
    the bands do not separate them, so both are shown as Moderate with a 'close call' note."""
    for i, r in enumerate(results[:DETAIL_TOP]):
        if r["confidence"] < 0.40:
            break
        close = [o["name"] for o in results[:DETAIL_TOP]
                 if o is not r and abs(o["confidence"] - r["confidence"]) < CLOSE_CALL_MARGIN]
        r["ambiguous_with"] = close
        if close and r["tier"] == "Strong":
            r["tier"] = "Moderate"
            r["tier_capped_because"] = list(r.get("tier_capped_because", [])) + ["close call with " + close[0]]


def match_weighted(peaks, entries, tolerance=10.0, spectral_range=None, prominence_max=None,
                   detail_top=DETAIL_TOP, explained=None, all_entries=None):
    """Score every entry and return them ranked by confidence (best first). Entries with no
    meaningful evidence are left out. Only the best `detail_top` keep their band-by-band
    detail; the rest keep the summary ("detail": False) and can be re-scored with score_entry
    on demand, which keeps sessions and undo snapshots small. Atmospheric artefact peaks
    (artefact_mask) are ignored. Look-alikes are looked up in `all_entries` (default: the
    searched entries), so a category-restricted search still warns about other classes."""
    if not peaks:
        return []
    usable = ~artefact_mask(peaks)
    if not usable.any():
        return []
    explained = np.zeros(len(peaks), dtype=bool) if explained is None else np.asarray(explained, dtype=bool)
    if prominence_max is None:
        prom = _prominences(peaks)
        open_prom = prom[usable & ~explained]
        prominence_max = float(open_prom.max()) if len(open_prom) and open_prom.max() > 0 else None
    rel = _relative_prominences(peaks, prominence_max)
    entries = list(entries)
    results = []
    for entry in entries:
        r = score_entry(entry, peaks, tolerance=tolerance, rel_prom=rel, n_searched=len(entries),
                        spectral_range=spectral_range, usable=usable, explained=explained)
        if r is not None and r["confidence"] > 0:
            results.append(r)
    results.sort(key=lambda r: (r["confidence"], r["forward_score"], r["matched_count"]), reverse=True)
    _flag_close_calls(results)
    twins = look_alikes(all_entries if all_entries is not None else entries, tolerance)
    for r in results[:DETAIL_TOP]:
        r["look_alikes"] = list(twins.get(r["name"], []))
    if detail_top is not None:
        for r in results[detail_top:]:
            r.pop("bands", None)
            r["matches"] = []
            r["explained_peak_ids"] = []
            r["detail"] = False
    return results


# ---------------------------------------------------------------- mixtures
def analyse_mixture(peaks, entries, tolerance=10.0, spectral_range=None, max_components=3,
                    min_confidence=0.35):
    """
    Greedy multi-component screening. Accept the best-scoring material, mark the peaks it
    explains, and rank again: later candidates may still use already-explained peaks as
    support for their own bands (blends share bands, e.g. CH2 rocking), but are judged on how
    much of the still-unexplained spectrum they account for. Intensity classes are relative to
    the strongest unexplained peak, so a minor component is not judged against the major one.
    Returns {"components", "unexplained", "explained_share", "min_confidence"}; each component
    is a score_entry() result plus "share" (fraction of total peak prominence it newly
    explains -- not a concentration) and "explained_peak_ids" (indices into `peaks`).
    """
    result = {"components": [], "unexplained": [], "explained_share": 0.0, "min_confidence": min_confidence}
    if not peaks:
        return result
    usable = ~artefact_mask(peaks)
    rel_all = _relative_prominences(peaks)
    total = float(rel_all[usable].sum()) or 1.0
    explained = np.zeros(len(peaks), dtype=bool)
    entries = list(entries)
    used_names = set()
    components = []
    for _ in range(max_components):
        if not (usable & ~explained).any():
            break
        ranked = [r for r in match_weighted(peaks, entries, tolerance, spectral_range, explained=explained)
                  if r["name"] not in used_names]
        if not ranked or ranked[0]["confidence"] < min_confidence or not ranked[0]["explained_peak_ids"]:
            break
        best = ranked[0]
        ids = best["explained_peak_ids"]
        best["share"] = float(sum(rel_all[i] for i in ids)) / total
        components.append(best)
        used_names.add(best["name"])
        explained[ids] = True
    result["components"] = components
    result["unexplained"] = [peaks[i] for i in range(len(peaks)) if usable[i] and not explained[i]]
    result["artefacts"] = [peaks[i] for i in range(len(peaks)) if not usable[i]]
    result["explained_share"] = float(rel_all[explained & usable].sum()) / total
    return result


# ---------------------------------------------------------------- synthetic spectrum
def synthetic_reference_spectrum(entry, x):
    """One Gaussian per reference band: height = band weight, FWHM = range width (min 12 cm-1,
    60 cm-1 for broad bands). For drawing and for the informational pattern correlation only."""
    x = np.asarray(x, dtype=float)
    y = np.zeros_like(x)
    for rp in entry.get("peaks", []):
        if not is_matchable(rp):
            continue
        w, broad = parse_intensity(rp.get("intensity"))
        lo, hi = min(rp["range"]), max(rp["range"])
        fwhm = max(hi - lo, 60.0 if broad else 12.0)
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
        # to absorbance (A = -log10 T), so band heights are comparable with the reference
        t = sample / 100.0 if np.nanmax(sample) > 1.5 else sample
        sample = -np.log10(np.clip(t, 1e-4, None))
    ref = synthetic_reference_spectrum(entry, x[mask])
    if np.std(sample) == 0 or np.std(ref) == 0:
        return None
    return float(np.corrcoef(sample, ref)[0, 1])
