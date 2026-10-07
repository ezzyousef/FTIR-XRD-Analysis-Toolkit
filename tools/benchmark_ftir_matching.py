"""
Synthetic retrieval benchmark for FTIR database matching: legacy coverage vs weighted evidence.

For every database material with >= 3 matchable bands, a peak list is simulated from its
band centres (Gaussian jitter, some weak bands dropped, random spurious peaks) and both
methods are asked to rank the database. It also runs a null test (pure random peak lists)
and a two-material mixture test.

These are idealised, self-referential data: they show how the scoring behaves, NOT how
accurately it identifies real samples. Validate on measured spectra of known materials.

    python tools/benchmark_ftir_matching.py [--trials 3] [--seed 0]
"""
import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "modules"))

import ftir_analysis  # noqa: E402
import ftir_matching  # noqa: E402

DB_PATH = os.path.join(HERE, "..", "database", "ftir_reference_db.json")


def simulate(entry, rng, jitter=3.0, drop_weak=0.3, spurious=5, lo=400.0, hi=4000.0):
    peaks = []
    for rp in entry["peaks"]:
        if not ftir_matching.is_matchable(rp):
            continue
        w, _b = ftir_matching.parse_intensity(rp.get("intensity"))
        if w <= 0.45 and rng.random() < drop_weak:
            continue
        c = (rp["range"][0] + rp["range"][1]) / 2 + rng.gauss(0, jitter)
        peaks.append({"x": c, "y": w, "prominence": w * rng.uniform(0.7, 1.3)})
    for _ in range(spurious):
        peaks.append({"x": rng.uniform(lo, hi), "y": 0.2, "prominence": rng.uniform(0.05, 0.4)})
    peaks.sort(key=lambda p: p["x"])
    return peaks


def rank_of(results, name):
    for i, r in enumerate(results, 1):
        if r["name"] == name:
            return i
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tolerance", type=float, default=10.0)
    args = ap.parse_args()

    with open(DB_PATH, encoding="utf-8") as f:
        db = json.load(f)
    entries = [e for c in ftir_analysis.MATERIAL_CATEGORIES for e in db.get(c, [])
               if sum(ftir_matching.is_matchable(p) for p in e["peaks"]) >= 3]

    stats = {m: {"top1": 0, "top3": 0, "n": 0} for m in ("coverage", "weighted")}
    rng = random.Random(args.seed)
    for entry in entries:
        for _ in range(args.trials):
            peaks = simulate(entry, rng)
            for method in stats:
                res = ftir_analysis.match_peaks_to_database(peaks, db, tolerance=args.tolerance, method=method)
                r = rank_of(res, entry["name"])
                stats[method]["n"] += 1
                stats[method]["top1"] += int(r == 1)
                stats[method]["top3"] += int(r is not None and r <= 3)

    print(f"Self-retrieval, {len(entries)} materials x {args.trials} simulated peak lists "
          f"(jitter 3 cm-1, 30% weak bands dropped, 5 spurious peaks, tol {args.tolerance:g}):")
    for method, s in stats.items():
        print(f"  {method:9s} top-1 {100 * s['top1'] / s['n']:5.1f}%   top-3 {100 * s['top3'] / s['n']:5.1f}%")

    tiers = {}
    nrng = random.Random(args.seed + 1)
    for _ in range(200):
        n = nrng.randint(8, 40)
        peaks = [{"x": nrng.uniform(400, 4000), "y": 1, "prominence": nrng.random()} for _ in range(n)]
        res = ftir_analysis.match_peaks_to_database(peaks, db, tolerance=args.tolerance)
        tier = res[0]["tier"] if res else "none"
        tiers[tier] = tiers.get(tier, 0) + 1
    print("Null test, 200 random peak lists (8-40 peaks): tier of the top weighted hit:", tiers)

    mrng = random.Random(args.seed + 2)
    both, n_mix = 0, 100
    for _ in range(n_mix):
        a, b = mrng.sample(entries, 2)
        peaks = simulate(a, mrng, spurious=0) + simulate(b, mrng, spurious=3)
        mix = ftir_analysis.analyse_mixture(peaks, db, tolerance=args.tolerance)
        found = {c["name"] for c in mix["components"]}
        both += int(a["name"] in found and b["name"] in found)
    print(f"Mixture test, {n_mix} random two-material blends: both components found in {both}%")


if __name__ == "__main__":
    main()
