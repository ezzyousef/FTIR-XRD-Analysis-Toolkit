"""
Synthetic benchmark for FTIR database matching: legacy coverage vs weighted evidence.

Spectra are simulated, then go through the same peak detection the app uses (noise floor,
CO2 region skipped) before matching, so detection, band overlap and artefacts are part of
the test. For each material with >= 3 bands in the measured range:

  * each band becomes a pseudo-Voigt line at a random position inside its literature range
    (not the centre), with a random height (0.4-1.6 x its label weight) and width
    (8-25 cm-1, 80-200 cm-1 for broad bands), on a sloping baseline with Gaussian noise;
  * scenarios: clean (noise 0.3 %), noisy (1 %), artefacts (CO2 doublet, water-vapour lines,
    absorbed water), ATR-like (strong bands shifted -6 cm-1, high-wavenumber bands damped);
  * leave-one-out null: the same spectrum matched against the database WITHOUT that
    material -- what a user sees when the sample is not in the library;
  * confusable pairs (PE/PP, PET/PBT, nylons...) and random two-material blends.

Reported: top-1 / top-3 retrieval, the tier given to the right answer, and how often each
tier is given to a wrong answer (precision per tier, and the leave-one-out false "Strong"
rate). These are still simulations built from the same band tables the matcher uses, so
they are optimistic: they show how the scoring behaves, not how accurately it identifies
real samples. Validate on measured spectra of known materials.

    python tools/benchmark_ftir_matching.py [--per-material 1] [--seed 0] [--quick]
"""
import argparse
import copy
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "modules"))

import ftir_analysis  # noqa: E402
import ftir_matching  # noqa: E402

DB_PATH = os.path.join(HERE, "..", "database", "ftir_reference_db.json")
X = np.arange(4000.0, 599.0, -2.0)          # diamond-ATR-like range, 2 cm-1 spacing
RANGE = (600.0, 4000.0)
SCENARIOS = {
    "clean": {"noise": 0.003},
    "noisy": {"noise": 0.010},
    "artefacts": {"noise": 0.004, "artefacts": True},
    "atr-like": {"noise": 0.004, "atr": True},
}
CONFUSABLE = [
    ("Polyethylene (PE)", "Polypropylene (PP)"),
    ("Polyethylene Terephthalate (PET)", "Polybutylene Terephthalate (PBT)"),
    ("Nylon 6 / Polyamide (PA6)", "Nylon 6,6 (PA66)"),
    ("Polyamide 11 (PA11)", "Polyamide 12 (PA12)"),
    ("Poly(methyl methacrylate) (PMMA)", "Poly(vinyl acetate) (PVAc)"),
]


def pseudo_voigt(x, c, fwhm, h, eta=0.5):
    g = np.exp(-4 * np.log(2) * ((x - c) / fwhm) ** 2)
    lor = 1.0 / (1 + 4 * ((x - c) / fwhm) ** 2)
    return h * (eta * lor + (1 - eta) * g)


def simulate_spectrum(entries, rng, noise=0.003, artefacts=False, atr=False, scales=None):
    y = 0.02 + 0.01 * (X - X.min()) / (X.max() - X.min())         # sloping baseline
    for k, entry in enumerate(entries):
        scale = (scales or [1.0] * len(entries))[k]
        for rp in entry["peaks"]:
            if not ftir_matching.is_matchable(rp):
                continue
            w, broad = ftir_matching.parse_intensity(rp.get("intensity"))
            lo, hi = sorted(rp["range"])
            c = rng.uniform(lo, hi) if hi > lo else lo
            fwhm = rng.uniform(80, 200) if broad else rng.uniform(8, 25)
            h = scale * w * rng.uniform(0.4, 1.6)
            if atr:
                if w >= 0.8:
                    c -= 6.0
                h *= 1000.0 / max(c, 400.0) * 1.2                     # ATR damps high wavenumbers
            y = y + pseudo_voigt(X, c, fwhm, h)
    if artefacts:
        y = y + pseudo_voigt(X, 2360, 10, 0.25) + pseudo_voigt(X, 2340, 10, 0.2)        # CO2
        for c in rng.sample(range(1400, 1900, 7), 8) + rng.sample(range(3600, 3900, 7), 6):
            y = y + pseudo_voigt(X, c, 2.0, 0.05)                                            # vapour
        y = y + pseudo_voigt(X, 3400, 250, 0.15) + pseudo_voigt(X, 1640, 40, 0.06)          # water
    y = y + np.asarray([rng.gauss(0, noise) for _ in X])
    return y


def detect(y):
    return ftir_analysis.detect_peaks(X, y, prominence_frac=0.02, noise_floor=True,
                                      exclude_regions=[ftir_analysis.CO2_REGION])


def without(db, name):
    out = copy.copy(db)
    for cat in ftir_analysis.MATERIAL_CATEGORIES:
        out[cat] = [e for e in db.get(cat, []) if e["name"] != name]
    return out


def rank_of(results, name):
    for i, r in enumerate(results, 1):
        if r["name"] == name:
            return i
    return None


def in_range_bands(entry):
    return [p for p in entry["peaks"] if ftir_matching.is_matchable(p) and max(p["range"]) >= RANGE[0]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-material", type=int, default=1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tolerance", type=float, default=10.0)
    ap.add_argument("--quick", action="store_true", help="every 4th material only")
    args = ap.parse_args()
    t0 = time.time()

    with open(DB_PATH, encoding="utf-8") as f:
        db = json.load(f)
    entries = [e for c in ftir_analysis.MATERIAL_CATEGORIES for e in db.get(c, []) if len(in_range_bands(e)) >= 3]
    if args.quick:
        entries = entries[::4]
    rng = random.Random(args.seed)
    tol = args.tolerance

    print(f"{len(entries)} materials x {args.per_material} spectra per scenario, tolerance {tol:g} cm-1, "
          f"range {RANGE[0]:.0f}-{RANGE[1]:.0f} cm-1\n")
    print(f"{'scenario':<11}{'method':<10}{'top-1':>7}{'top-3':>7}   right answer tier (weighted)")
    tier_wrong = Counter()          # tier of a wrong top hit
    tier_right = Counter()          # tier of a right top hit
    for scen, opts in SCENARIOS.items():
        stats = {m: [0, 0, 0] for m in ("coverage", "weighted")}
        right_tiers = Counter()
        for entry in entries:
            for _ in range(args.per_material):
                peaks = detect(simulate_spectrum([entry], rng, **opts))
                for method in stats:
                    res = ftir_analysis.match_peaks_to_database(peaks, db, tolerance=tol, method=method,
                                                                spectral_range=RANGE)
                    r = rank_of(res, entry["name"])
                    stats[method][0] += 1
                    stats[method][1] += int(r == 1)
                    stats[method][2] += int(r is not None and r <= 3)
                    if method == "weighted":
                        hit = res[r - 1] if r else None
                        right_tiers[hit["tier"] if hit else "not listed"] += 1
                        if res:
                            (tier_right if r == 1 else tier_wrong)[res[0]["tier"]] += 1
        for method, (n, t1, t3) in stats.items():
            tiers = ", ".join(f"{k} {100 * v / n:.0f}%" for k, v in right_tiers.most_common()) if method == "weighted" else ""
            print(f"{scen:<11}{method:<10}{100 * t1 / n:6.1f}%{100 * t3 / n:6.1f}%   {tiers}")

    print("\nPrecision by tier of the top hit (all scenarios above, weighted):")
    for tier, _thr in ftir_matching.TIERS:
        n = tier_right[tier] + tier_wrong[tier]
        if n:
            print(f"  {tier:<9} right {100 * tier_right[tier] / n:5.1f}%  ({n} top hits)")

    loo = Counter()
    for entry in entries:
        peaks = detect(simulate_spectrum([entry], rng, noise=0.004))
        res = ftir_analysis.match_peaks_to_database(peaks, without(db, entry["name"]), tolerance=tol,
                                                    spectral_range=RANGE)
        loo[res[0]["tier"] if res else "none"] += 1
    n = sum(loo.values())
    print("\nLeave-one-out null (true material removed from the library), tier of the top hit:")
    print("  " + ", ".join(f"{k} {100 * v / n:.0f}%" for k, v in loo.most_common()))

    print("\nConfusable pairs (5 spectra each, weighted): top-1 right, and flagged as ambiguous")
    by_name = {e["name"]: e for c in ftir_analysis.MATERIAL_CATEGORIES for e in db.get(c, [])}
    for a, b in CONFUSABLE:
        for name in (a, b):
            if name not in by_name:
                print(f"  {name}: not in database, skipped")
                continue
            right = close = 0
            for _ in range(5):
                res = ftir_analysis.match_peaks_to_database(detect(simulate_spectrum([by_name[name]], rng)), db,
                                                            tolerance=tol, spectral_range=RANGE)
                right += int(bool(res) and res[0]["name"] == name)
                close += int(bool(res) and bool(res[0].get("ambiguous_with") or res[0].get("look_alikes")))
            print(f"  {name:<40} right {right}/5   flagged as close call / look-alike {close}/5")

    mrng = random.Random(args.seed + 2)
    found = defaultdict(int)
    n_mix = 40 if args.quick else 80
    for _ in range(n_mix):
        a, b = mrng.sample(entries, 2)
        peaks = detect(simulate_spectrum([a, b], rng, noise=0.004, scales=[1.0, mrng.uniform(0.4, 1.0)]))
        mix = ftir_analysis.analyse_mixture(peaks, db, tolerance=tol, spectral_range=RANGE)
        names = {c["name"] for c in mix["components"]}
        k = int(a["name"] in names) + int(b["name"] in names)
        found[k] += 1
        found["false"] += len(names - {a["name"], b["name"]})
    print(f"\nTwo-material blends ({n_mix}, minor component 40-100 %): both found {100 * found[2] / n_mix:.0f}%, "
          f"one {100 * found[1] / n_mix:.0f}%, none {100 * found[0] / n_mix:.0f}%; "
          f"{found['false']} wrong components reported in total")
    print(f"\n({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
