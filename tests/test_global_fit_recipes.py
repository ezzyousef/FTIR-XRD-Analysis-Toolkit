"""Global constrained/robust fitting, uncertainty bands, recipes and batch processing."""
import csv
import json
import math

import numpy as np
import pytest

import global_fit as gf
import recipes

LN2 = math.log(2.0)


def gauss(x, h, c, w):
    return h * np.exp(-4 * LN2 * ((x - c) / w) ** 2)


X = np.arange(1500.0, 1800.0, 0.5)
TRUTH = [(0.8, 1640.0, 18.0), (0.5, 1662.0, 14.0)]       # two overlapping bands


def two_bands(noise=0.0, seed=0, spikes=False):
    y = 0.05 + 1e-4 * (X - 1650.0) + sum(gauss(X, *t) for t in TRUTH)
    rng = np.random.default_rng(seed)
    y = y + rng.normal(0, noise, len(X)) if noise else y
    if spikes:
        y = y.copy()
        y[rng.choice(len(X), 12, replace=False)] += 0.6           # cosmic-ray-like outliers
    return y


def test_global_fit_recovers_overlapping_bands_exactly():
    fit = gf.fit_peaks_global(X, two_bands(), [1638.0, 1665.0], x_range=(1560, 1740), max_shift=8)
    for got, (h, c, w) in zip(fit["peaks"], TRUTH):
        assert (got["height"], got["center"], got["fwhm"]) == pytest.approx((h, c, w), rel=1e-6)
        assert got["area"] == pytest.approx(h * w * math.sqrt(math.pi / (4 * LN2)), rel=1e-6)
    b0, b1, xm = fit["baseline"]
    assert b0 + b1 * (1650.0 - xm) == pytest.approx(0.05, abs=1e-6) and b1 == pytest.approx(1e-4, rel=1e-4)


def test_centre_constraint_is_respected():
    fit = gf.fit_peaks_global(X, two_bands(), [1630.0, 1665.0], x_range=(1560, 1740), max_shift=3)
    assert 1627.0 - 1e-9 <= fit["peaks"][0]["center"] <= 1633.0 + 1e-9
    assert fit["peaks"][0]["at_bound"]


def test_shared_width_gives_one_width():
    fit = gf.fit_peaks_global(X, two_bands(), [1638.0, 1665.0], x_range=(1560, 1740), shared_fwhm=True)
    assert fit["peaks"][0]["fwhm"] == fit["peaks"][1]["fwhm"]


def test_robust_loss_resists_spikes_better_than_least_squares():
    y = two_bands(noise=0.003, seed=3, spikes=True)
    plain = gf.fit_peaks_global(X, y, [1638.0, 1665.0], x_range=(1560, 1740), max_shift=8)
    robust = gf.fit_peaks_global(X, y, [1638.0, 1665.0], x_range=(1560, 1740), max_shift=8, loss="soft_l1")
    err = lambda f: sum(abs(p["height"] - t[0]) / t[0] for p, t in zip(f["peaks"], TRUTH))
    assert err(robust) < err(plain)
    assert err(robust) < 0.05


def test_standard_errors_match_the_scatter_of_repeated_fits():
    # Monte Carlo: the spread of the fitted centre over 60 noise realisations agrees with the
    # reported standard error to within the sampling uncertainty of a standard deviation.
    centres, ses = [], []
    for seed in range(60):
        f = gf.fit_peaks_global(X, two_bands(noise=0.01, seed=seed), [1638.0, 1665.0], x_range=(1560, 1740))
        centres.append(f["peaks"][0]["center"])
        ses.append(f["peaks"][0]["stderr"]["center"])
    assert np.std(centres, ddof=1) == pytest.approx(np.mean(ses), rel=0.3)


def test_confidence_band_brackets_the_truth_most_of_the_time():
    truth = two_bands()
    f = gf.fit_peaks_global(X, two_bands(noise=0.01, seed=11), [1638.0, 1665.0], x_range=(1560, 1740))
    xs = X[(X >= 1560) & (X <= 1740)]
    curve, lo, hi = gf.confidence_band(f, xs, k=2.0)
    inside = np.mean((truth[(X >= 1560) & (X <= 1740)] >= lo) & (truth[(X >= 1560) & (X <= 1740)] <= hi))
    assert inside > 0.8 and np.all(hi >= lo)
    assert np.allclose(curve, gf.evaluate(f, xs))


def test_baseline_uncertainty_shrinks_with_less_noise():
    x = np.arange(400.0, 4000.0, 2.0)
    rng = np.random.default_rng(0)
    for noise in (0.01, 0.001):
        y = 0.1 + 1e-5 * x + rng.normal(0, noise, len(x))
        base, sigma = gf.baseline_uncertainty(x, y, (500.0, 3800.0), half_window_pts=10)
        # standard error of a mean of 21 points: noise / sqrt(21) at the anchors
        i = int(np.argmin(abs(x - 500.0)))
        assert sigma[i] == pytest.approx(noise / math.sqrt(21), rel=0.4)
        assert np.max(np.abs(base - (0.1 + 1e-5 * x))) < 5 * noise


def test_global_fit_refuses_bad_input():
    with pytest.raises(ValueError):
        gf.fit_peaks_global(X, two_bands(), [])
    with pytest.raises(ValueError):
        gf.fit_peaks_global(X, two_bands(), [1640.0], shape="triangle")


# ------------------------------------------------------------------ recipes and batch
def write_spectrum(path, shift=0.0, pct_t=False):
    x = np.arange(4000.0, 399.0, -2.0)
    a = 0.02 + gauss(x, 0.8, 1720.0 + shift, 16.0) + gauss(x, 0.5, 2920.0 + shift, 20.0)
    y = 100 * 10 ** (-a) if pct_t else a
    with open(path, "w", encoding="utf-8") as f:
        f.write("wavenumber,y\n" + "".join(f"{p:.1f},{q:.6f}\n" for p, q in zip(x, y)))
    return str(path)


def test_recipe_round_trip_and_validation(tmp_path):
    r = recipes.make_recipe("std", [("crop", {"low": 600, "high": 3800}), ("smooth", {"window_length": 9}),
                                    ("baseline", {}), ("normalize", {"method": "max"})])
    p = tmp_path / "r.json"
    recipes.save_recipe(r, p)
    assert recipes.load_recipe(p) == r
    with pytest.raises(ValueError, match="Unknown recipe step"):
        recipes.make_recipe("bad", [("explode", {})])
    with pytest.raises(ValueError, match="unknown parameter"):
        recipes.make_recipe("bad", [("smooth", {"window": 9})])
    (tmp_path / "x.json").write_text(json.dumps({"format": "other"}), encoding="utf-8")
    with pytest.raises(ValueError, match="Not a recipe"):
        recipes.load_recipe(tmp_path / "x.json")


def test_apply_recipe_is_the_same_as_the_steps_by_hand(tmp_path):
    import ftir_analysis as fa
    x = np.arange(4000.0, 399.0, -2.0)
    y = 0.02 + gauss(x, 0.8, 1720.0, 16.0)
    r = recipes.make_recipe("s", [("smooth", {"window_length": 11, "polyorder": 3}), ("baseline", {}),
                                  ("normalize", {"method": "vector"})])
    x2, y2, log = recipes.apply_recipe(x, y, r)
    by_hand = fa.normalize_spectrum(fa.baseline_correct(x, fa.smooth_spectrum(y, 11, 3))[0], "vector", x=x)
    assert np.allclose(y2, by_hand) and len(log) == 3 and "Savitzky" in log[0]
    assert np.allclose(y, 0.02 + gauss(x, 0.8, 1720.0, 16.0))          # input untouched


def test_batch_processes_files_and_records_failures_and_provenance(tmp_path):
    files = [write_spectrum(tmp_path / f"s{i}.csv", shift=2 * i) for i in range(3)]
    files.append(write_spectrum(tmp_path / "t.csv", pct_t=True))
    bad = tmp_path / "bad.csv"
    bad.write_text("not a spectrum\n", encoding="utf-8")
    files.append(str(bad))
    r = recipes.make_recipe("b", [("crop", {"low": 600, "high": 3800})])
    out = tmp_path / "batch.csv"
    res = recipes.run_batch(files, r, str(out), app_version="test")
    rows = list(csv.reader(open(out, encoding="utf-8")))
    assert rows[0][0] == "File" and any(row[1].startswith("FAILED") and row[0] == "bad.csv" for row in rows)
    peaks_s1 = sorted(float(row[2]) for row in rows if row[0] == "s1.csv")
    assert peaks_s1 == pytest.approx([1722.0, 2922.0], abs=2.0)
    assert len([x for x in res if not x.get("error")]) == 4
