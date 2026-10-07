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


def test_family_wise_correction_grows_with_search_size_up_to_the_cap():
    assert ftir_matching.family_wise(0.01, 1) == pytest.approx(0.01)
    assert ftir_matching.family_wise(0.01, 10) > ftir_matching.family_wise(0.01, 2)
    cap = ftir_matching.FAMILY_SIZE_CAP
    assert ftir_matching.family_wise(0.01, 224) == pytest.approx(ftir_matching.family_wise(0.01, cap))
    assert ftir_matching.chance_significance(1e-6) == 1.0
    assert ftir_matching.chance_significance(1.0) == 0.0
    assert str(ftir_matching.chance_significance(1.0)) == "0.0"          # never -0.0


def test_soft_hits_change_the_chance_smoothly():
    probs = [0.2] * 6
    p3, p4 = ftir_matching.poisson_binomial_tail(probs, 3), ftir_matching.poisson_binomial_tail(probs, 4)
    mid = ftir_matching.soft_tail(probs, 3.5)
    assert p4 < mid < p3


def test_weighted_ranks_pet_first_with_high_confidence(db):
    matches = ftir_analysis.match_peaks_to_database(PET_PEAKS, db, tolerance=8.0)
    best = matches[0]
    assert best["name"] == PET
    assert best["tier"] == "Strong" and best["confidence"] > 0.8
    assert best["method"] == ftir_matching.METHOD_WEIGHTED
    # backwards-compatible keys used by exports and sessions
    for key in ("score", "matched_count", "total_reference_peaks", "matches", "source", "category"):
        assert key in best
    confidences = [m["confidence"] for m in matches]
    assert confidences == sorted(confidences, reverse=True)


def test_random_peak_lists_never_reach_high_confidence(db):
    # measured on 300 lists while tuning: never Strong, 2 % Moderate
    rng = random.Random(7)
    moderate = 0
    for _ in range(40):
        peaks = [_peak(rng.uniform(400, 4000), rng.random()) for _ in range(rng.randint(8, 40))]
        matches = ftir_analysis.match_peaks_to_database(peaks, db)
        assert not matches or matches[0]["tier"] != "Strong"
        moderate += int(bool(matches) and matches[0]["tier"] == "Moderate")
    assert moderate <= 3


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
    # a missing strong band also keeps the tier below Strong
    assert no_strong["tier"] != "Strong" and no_strong["tier_capped_because"] or no_strong["confidence"] < 0.6


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
    # explained_peak_ids index the FULL peak list, for every component
    for c in result["components"]:
        entry = ftir_analysis.find_entry(db, c["name"])
        for i in c["explained_peak_ids"]:
            assert any(ftir_matching.position_score(peaks[i]["x"], *rp["range"], 16) > 0
                       for rp in entry["peaks"] if ftir_matching.is_matchable(rp))
        for mm in c["matches"]:
            assert peaks[mm["peak_id"]] is mm["observed"]


def test_mixture_on_noise_finds_nothing_confident(db):
    rng = random.Random(3)
    peaks = [_peak(rng.uniform(400, 4000), rng.random()) for _ in range(20)]
    result = ftir_analysis.analyse_mixture(peaks, db)
    assert result["components"] == []


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
    assert rows[0][1] == PET and rows[0][3] == "Strong"


def test_bands_outside_the_measured_range_are_not_penalised(db):
    entry = ftir_analysis.find_entry(db, "Polytetrafluoroethylene (PTFE, Teflon)")
    measured = [p for p in _from_entry(entry) if p["x"] >= 650]
    blind = ftir_matching.score_entry(entry, measured)
    aware = ftir_matching.score_entry(entry, measured, spectral_range=(650, 4000))
    assert aware["outside_count"] >= 1
    assert aware["confidence"] > blind["confidence"]
    assert all(b["status"] != "missing" for b in aware["bands"] if max(b["reference"]["range"]) < 650)


def test_nan_and_missing_prominence_do_not_break_ranking(db):
    peaks = [dict(p) for p in PET_PEAKS]
    peaks[1]["prominence"] = float("nan")
    peaks[2]["prominence"] = None
    matches = ftir_analysis.match_peaks_to_database(peaks, db, tolerance=8.0)
    assert matches[0]["name"] == PET and matches[0]["confidence"] > 0.5


def test_artefact_peaks_are_ignored(db):
    co2 = [_peak(2350, 1.0), _peak(2340, 0.9)]
    vapour = [dict(_peak(x, 0.3), fwhm_cm1=2.0) for x in (1507, 1540, 1653, 1700, 3735, 3853)]
    clean = ftir_analysis.match_peaks_to_database(PET_PEAKS, db, tolerance=8.0)[0]
    dirty = ftir_analysis.match_peaks_to_database(PET_PEAKS + co2 + vapour, db, tolerance=8.0)[0]
    assert dirty["name"] == PET
    assert dirty["confidence"] == pytest.approx(clean["confidence"], abs=0.05)
    mask = ftir_matching.artefact_mask(co2 + vapour + [_peak(1716)])
    assert mask.tolist() == [True] * 8 + [False]


def test_sharp_peak_is_weak_evidence_for_a_broad_band():
    entry = {"name": "Acid", "category": "test", "peaks": [
        {"range": [2500, 3300], "intensity": "broad, strong", "assignment": "O-H"},
        {"range": [1700, 1710], "intensity": "strong", "assignment": "C=O"},
        {"range": [1200, 1300], "intensity": "medium", "assignment": "C-O"}]}
    sharp = [dict(_peak(2850), fwhm_cm1=10.0), _peak(1705), _peak(1250)]
    broad = [dict(_peak(2950), fwhm_cm1=300.0), _peak(1705), _peak(1250)]
    assert ftir_matching.score_entry(entry, broad)["forward_score"] > \
        ftir_matching.score_entry(entry, sharp)["forward_score"]


def test_close_calls_are_not_reported_as_strong(db):
    results = [{"name": n, "confidence": c, "tier": ftir_matching.confidence_tier(c)}
               for n, c in (("A", 0.86), ("B", 0.83), ("C", 0.40))]
    ftir_matching._flag_close_calls(results)
    assert results[0]["ambiguous_with"] == ["B"] and results[0]["tier"] == "Moderate"
    assert results[1]["ambiguous_with"] == ["A"]


def test_look_alikes_find_chemically_near_identical_entries(db):
    entries = [e for c in ftir_analysis.MATERIAL_CATEGORIES for e in db[c]]
    twins = ftir_matching.look_alikes(entries)
    assert "Potassium Carbonate (K2CO3)" in twins["Sodium Carbonate (Na2CO3)"]
    assert "Polyamide 12 (PA12)" in twins["Polyamide 11 (PA11)"]
    assert PET not in twins["Polyethylene (PE)"]
    best = ftir_analysis.match_peaks_to_database(PET_PEAKS, db, tolerance=8.0)[0]
    assert "look_alikes" in best


def test_only_the_top_results_keep_band_detail(db):
    rng = random.Random(1)
    peaks = PET_PEAKS + [_peak(rng.uniform(600, 3600), rng.uniform(0.05, 0.3)) for _ in range(25)]
    matches = ftir_analysis.match_peaks_to_database(peaks, db)
    top, rest = matches[:ftir_matching.DETAIL_TOP], matches[ftir_matching.DETAIL_TOP:]
    assert all(m["detail"] and m["bands"] for m in top)
    assert all(not m["detail"] and "bands" not in m for m in rest)
    assert all(m["confidence"] > 0 for m in matches)


def test_noise_floor_and_co2_exclusion_in_detection():
    x = np.linspace(4000, 600, 1701)
    y = 0.8 * np.exp(-0.5 * ((x - 1720) / 8) ** 2) + 0.4 * np.exp(-0.5 * ((x - 2350) / 6) ** 2)
    y = y + np.random.default_rng(0).normal(0, 0.006, len(x))
    plain = ftir_analysis.detect_peaks(x, y, prominence_frac=0.005)
    floored = ftir_analysis.detect_peaks(x, y, prominence_frac=0.005, noise_floor=True,
                                         exclude_regions=[ftir_analysis.CO2_REGION])
    assert len(floored) < len(plain)
    assert any(abs(p["x"] - 1720) < 4 for p in floored)
    assert not any(2280 <= p["x"] <= 2400 for p in floored)
    assert ftir_analysis.estimate_noise_sigma(y) == pytest.approx(0.006, rel=0.3)
    assert all(p["fwhm_cm1"] > 0 for p in floored)


def test_weighted_results_survive_a_json_session_round_trip(db, tmp_path):
    import session_io
    result = ftir_analysis.analyse_mixture(PET_PEAKS, db, tolerance=8.0)
    matches = ftir_analysis.match_peaks_to_database(PET_PEAKS, db, tolerance=8.0)
    path = session_io.save_session(str(tmp_path / "s.ftirxrd"), {"matches": matches, "mixture": result})
    back = session_io.load_session(path)
    assert back["matches"][0]["name"] == PET and back["matches"][0]["bands"]
    assert back["mixture"]["components"][0]["name"] == PET
    assert os.path.getsize(path) < 400_000


def test_database_passes_the_audit(db):
    import importlib.util
    path = os.path.join(DB_DIR, "..", "tools", "audit_ftir_database.py")
    spec = importlib.util.spec_from_file_location("audit_ftir_database", path)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    errors, _notes, pairs, _entries = audit.audit(db)
    assert errors == []
    assert len(pairs) > 50
    assert db["_meta"]["version"] >= "4.2" and "schema" in db["_meta"]


def test_added_entries_are_flagged_for_verification(db):
    added = [e for c in ftir_analysis.MATERIAL_CATEGORIES for e in db[c] if e.get("provenance")]
    assert len(added) >= 13
    assert all(e["provenance"]["verify"] and e["provenance"]["confidence"] in ("low", "medium") for e in added)
    names = {e["name"] for e in added}
    assert "Graphene Oxide (GO)" in names and "Lithium Hexafluorophosphate (LiPF6)" in names
