import os
import random

import numpy as np
import pytest

import ftir_analysis
import ftir_matching
from conftest import DB_DIR

PET = "Polyethylene Terephthalate (PET)"


@pytest.fixture(scope="module")
def db():
    return ftir_analysis.load_database(os.path.join(DB_DIR, "ftir_reference_db.json"))


def _peak(x, prominence=0.5):
    return {"index": 0, "x": float(x), "y": prominence, "prominence": prominence}


def _from_entry(entry, skip=()):
    peaks = []
    for rp in entry["peaks"]:
        if not ftir_matching.is_matchable(rp) or rp["range"] in skip:
            continue
        w, _b = ftir_matching.parse_intensity(rp["intensity"])
        peaks.append(_peak(sum(rp["range"]) / 2, w))
    return peaks


PET_PEAKS = [_peak(x, p) for x, p in [(1716, .5), (1250, .4), (1095, .3), (1125, .25), (1017, .2),
                                       (1342, .2), (972, .15), (872, .15), (725, .2)]]


def test_parse_intensity_labels():
    assert ftir_matching.parse_intensity("strong") == (1.0, False)
    assert ftir_matching.parse_intensity("broad, strong") == (1.0, True)
    assert ftir_matching.parse_intensity("weak-medium")[0] == 0.45
    assert ftir_matching.parse_intensity("medium-strong")[0] == 0.8
    assert ftir_matching.parse_intensity("weak")[0] == 0.3
    assert ftir_matching.parse_intensity("n/a")[0] == ftir_matching.DEFAULT_WEIGHT


def test_position_score_inside_edge_and_outside():
    assert ftir_matching.position_score(1715, 1710, 1720, 10) == 1.0
    edge = ftir_matching.position_score(1730, 1710, 1720, 10)
    assert 0.1 < edge < 0.2
    assert ftir_matching.position_score(1731, 1710, 1720, 10) == 0.0


def test_poisson_binomial_tail_matches_binomial():
    from math import comb
    p, n = 0.3, 6
    exact = sum(comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(3, n + 1))
    assert ftir_matching.poisson_binomial_tail([p] * n, 3) == pytest.approx(exact)
    assert ftir_matching.poisson_binomial_tail([0.2, 0.5], 0) == 1.0


def test_family_wise_correction_grows_with_search_size():
    assert ftir_matching.family_wise(0.01, 1) == pytest.approx(0.01)
    assert ftir_matching.family_wise(0.01, 224) > 0.85
    assert ftir_matching.chance_significance(1e-6) == 1.0
    assert ftir_matching.chance_significance(1.0) == 0.0


def test_weighted_ranks_pet_first_with_high_confidence(db):
    matches = ftir_analysis.match_peaks_to_database(PET_PEAKS, db, tolerance=8.0)
    best = matches[0]
    assert best["name"] == PET
    assert best["tier"] == "High" and best["confidence"] > 0.8
    assert best["method"] == ftir_matching.METHOD_WEIGHTED
    # backwards-compatible keys used by exports and sessions
    for key in ("score", "matched_count", "total_reference_peaks", "matches", "source", "category"):
        assert key in best
    confidences = [m["confidence"] for m in matches]
    assert confidences == sorted(confidences, reverse=True)


def test_random_peak_lists_never_reach_high_confidence(db):
    rng = random.Random(7)
    for _ in range(40):
        peaks = [_peak(rng.uniform(400, 4000), rng.random()) for _ in range(rng.randint(8, 40))]
        matches = ftir_analysis.match_peaks_to_database(peaks, db)
        assert not matches or matches[0]["tier"] != "High"


def test_missing_strong_band_costs_more_than_missing_weak_band(db):
    entry = ftir_analysis.find_entry(db, PET)
    bands = [rp for rp in entry["peaks"] if ftir_matching.is_matchable(rp)]
    strong = next(rp for rp in bands if ftir_matching.parse_intensity(rp["intensity"])[0] >= 1.0)
    weak = min(bands, key=lambda rp: ftir_matching.parse_intensity(rp["intensity"])[0])
    no_strong = ftir_matching.score_entry(entry, _from_entry(entry, skip=[strong["range"]]))
    no_weak = ftir_matching.score_entry(entry, _from_entry(entry, skip=[weak["range"]]))
    assert no_strong["forward_score"] < no_weak["forward_score"]
    assert strong in no_strong["missing_strong"]
    assert not no_weak["missing_strong"]


def test_one_observed_peak_supports_only_one_band():
    entry = {"name": "Twin", "category": "test", "peaks": [
        {"range": [1000, 1004], "intensity": "strong", "assignment": "a"},
        {"range": [1008, 1012], "intensity": "strong", "assignment": "b"}]}
    one = ftir_matching.score_entry(entry, [_peak(1006)], tolerance=10)
    assert one["matched_count"] == 1
    two = ftir_matching.score_entry(entry, [_peak(1002), _peak(1010)], tolerance=10)
    assert two["matched_count"] == 2


def test_chance_probability_rises_with_peak_density(db):
    entry = ftir_analysis.find_entry(db, PET)
    peaks = _from_entry(entry)
    sparse = ftir_matching.score_entry(entry, peaks, density=0.002)
    crowded = ftir_matching.score_entry(entry, peaks, density=0.05)
    assert crowded["chance_probability"] > sparse["chance_probability"]


def test_broad_bands_get_a_wider_tolerance():
    entry = {"name": "Broad", "category": "test", "peaks": [
        {"range": [3200, 3400], "intensity": "broad, strong", "assignment": "O-H"}]}
    assert ftir_matching.score_entry(entry, [_peak(3415)], tolerance=10) is not None
    sharp = {"name": "Sharp", "category": "test", "peaks": [
        {"range": [3200, 3400], "intensity": "strong", "assignment": "O-H"}]}
    assert ftir_matching.score_entry(sharp, [_peak(3415)], tolerance=10) is None


def test_legacy_coverage_method_is_unchanged(db):
    matches = ftir_analysis.match_peaks_to_database(PET_PEAKS, db, tolerance=8.0, method="coverage")
    assert matches[0]["name"] == PET
    assert matches[0]["score"] == pytest.approx(0.9)
    assert matches[0]["method"] == ftir_matching.METHOD_COVERAGE
    keys = [(m["matched_count"], m["score"]) for m in matches]
    assert keys == sorted(keys, reverse=True)


def test_mixture_finds_both_components(db):
    pet = ftir_analysis.find_entry(db, PET)
    other = next(e for e in db["inorganics_minerals"] if "Calcite" in e["name"] or "Calcium Carbonate" in e["name"])
    peaks = sorted(_from_entry(pet) + _from_entry(other), key=lambda p: p["x"])
    result = ftir_analysis.analyse_mixture(peaks, db, tolerance=8.0)
    names = [c["name"] for c in result["components"]]
    assert PET in names and other["name"] in names
    assert result["explained_share"] > 0.8
    assert all(0 < c["share"] <= 1 for c in result["components"])


def test_mixture_on_noise_finds_nothing_confident(db):
    rng = random.Random(3)
    peaks = [_peak(rng.uniform(400, 4000), rng.random()) for _ in range(20)]
    result = ftir_analysis.analyse_mixture(peaks, db)
    assert len(result["components"]) <= 1


def test_synthetic_spectrum_and_pattern_correlation(db):
    entry = ftir_analysis.find_entry(db, PET)
    x = np.linspace(600, 1900, 1301)
    y = ftir_matching.synthetic_reference_spectrum(entry, x)
    assert y.max() > 0
    noisy = y + np.random.default_rng(0).normal(0, 0.02, len(x))
    r = ftir_matching.pattern_correlation(entry, x, noisy)
    assert r is not None and r > 0.9
    r_t = ftir_matching.pattern_correlation(entry, x, 100 - 50 * noisy, mode="transmittance")
    assert r_t > 0.9


def test_old_format_matches_still_export(db):
    import exports
    from trace_model import Trace
    t = Trace("old.csv", [1, 2], [1, 2], "#0072B2")
    t.matches = [{"name": "Poly(x)", "category": "polymer", "score": 0.5, "matched_count": 1,
                  "total_reference_peaks": 2, "source": "ref", "matches": []}]
    rows = exports.match_rows(t)
    assert len(rows[0]) == len(exports.MATCH_HEADERS)
    t.matches = ftir_analysis.match_peaks_to_database(PET_PEAKS, db, tolerance=8.0)[:3]
    rows = exports.match_rows(t)
    assert rows[0][1] == PET and rows[0][3] == "High"
