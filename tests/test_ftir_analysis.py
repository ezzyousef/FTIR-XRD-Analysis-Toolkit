import os
import numpy as np
import pytest

import ftir_analysis
from conftest import DB_DIR


@pytest.fixture(scope="module")
def db():
    return ftir_analysis.load_database(os.path.join(DB_DIR, "ftir_reference_db.json"))


def _gaussian(x, c, h, w):
    return h * np.exp(-0.5 * ((x - c) / w) ** 2)


def test_database_schema(db):
    assert "_meta" in db and "references" in db["_meta"]
    ref_ids = {r["id"] for r in db["_meta"]["references"]}
    for cat in ftir_analysis.MATERIAL_CATEGORIES:
        entries = db.get(cat, [])
        assert len(entries) > 0, f"category {cat} is empty"
        for entry in entries:
            assert entry["name"]
            assert entry["category"]
            assert entry["peaks"]
            assert entry.get("source"), f"{entry['name']} missing a source citation"
            for p in entry["peaks"]:
                assert len(p["range"]) == 2
                assert p["range"][0] <= p["range"][1]
                assert "assignment" in p
            # No two reference peaks within the SAME entry may have overlapping
            # ranges: match_peaks_to_database counts each reference peak
            # independently, so one real observed peak landing in an overlap
            # zone would double-count as matching two reference peaks,
            # inflating that material's score (regression: this let PBT
            # outscore PET on a canonical PET spectrum after a database
            # enrichment pass introduced an overlapping duplicate band).
            sorted_peaks = sorted((p for p in entry["peaks"] if not (p["range"][0] == 0 and p["range"][1] == 0)),
                                  key=lambda p: p["range"][0])
            for a, b in zip(sorted_peaks, sorted_peaks[1:]):
                assert a["range"][1] < b["range"][0], (
                    f"{entry['name']}: overlapping reference peak ranges "
                    f"{a['range']} ({a['assignment']}) and {b['range']} ({b['assignment']})"
                )
    for fg in db["functional_groups"]:
        assert fg.get("source")
        assert len(fg["range"]) == 2


def test_detect_peaks_finds_synthetic_peaks():
    x = np.linspace(4000, 400, 1500)
    y = _gaussian(x, 1715, 1.0, 8) + _gaussian(x, 1017, 0.5, 6) + 0.01
    peaks = ftir_analysis.detect_peaks(x, y, prominence_frac=0.05, mode="absorbance")
    xs = sorted(p["x"] for p in peaks)
    assert len(xs) == 2
    assert xs[0] == pytest.approx(1017, abs=15)
    assert xs[1] == pytest.approx(1715, abs=15)


def test_detect_peaks_transmittance_mode_inverts():
    x = np.linspace(4000, 400, 1500)
    # a dip in %T at 1715 should be detected as a peak when mode="transmittance"
    y = 100 - _gaussian(x, 1715, 40, 8)
    peaks = ftir_analysis.detect_peaks(x, y, prominence_frac=0.05, mode="transmittance")
    assert len(peaks) == 1
    assert peaks[0]["x"] == pytest.approx(1715, abs=10)


def test_transmittance_absorbance_round_trip():
    for t_pct in (10, 50, 90, 99):
        a = ftir_analysis.transmittance_to_absorbance(t_pct)
        back = ftir_analysis.absorbance_to_transmittance(a)
        assert back == pytest.approx(t_pct, rel=1e-6)


def test_baseline_correct_flattens_linear_drift():
    x = np.linspace(0, 100, 200)
    drift = 0.01 * x + 2.0
    y = drift + _gaussian(x, 50, 1.0, 3)
    corrected, baseline = ftir_analysis.baseline_correct(x, y)
    assert corrected[0] == pytest.approx(0, abs=1e-6)
    assert corrected[-1] == pytest.approx(0, abs=1e-6)
    assert corrected.max() > 0.9


def test_peak_area_matches_known_gaussian_integral():
    x = np.linspace(-50, 50, 4000)
    height, width = 2.0, 5.0
    y = _gaussian(x, 0, height, width)
    area = ftir_analysis.peak_area(x, y, -30, 30)
    expected = height * width * np.sqrt(2 * np.pi)  # full Gaussian integral
    assert area == pytest.approx(expected, rel=2e-3)


def test_peak_area_rejects_too_narrow_range():
    x = np.array([1.0, 2.0, 3.0])
    y = np.array([1.0, 2.0, 1.0])
    with pytest.raises(ValueError):
        ftir_analysis.peak_area(x, y, 1.0, 1.0)


def test_fwhm_from_peak_matches_known_gaussian():
    x = np.linspace(-50, 50, 4000)
    width = 4.0
    y = _gaussian(x, 0, 1.0, width)
    idx = int(np.argmax(y))
    fwhm = ftir_analysis.fwhm_from_peak(x, y, idx)
    expected_fwhm = 2 * np.sqrt(2 * np.log(2)) * width
    assert fwhm == pytest.approx(expected_fwhm, rel=0.02)


def test_beer_lambert_concentration():
    c = ftir_analysis.beer_lambert_concentration(absorbance=1.0, molar_absorptivity=1000, path_length_cm=1.0)
    assert c == pytest.approx(0.001)
    with pytest.raises(ValueError):
        ftir_analysis.beer_lambert_concentration(1.0, -1, 1.0)


def test_normalize_spectrum_max():
    y = np.array([0.0, 2.0, 4.0, 1.0])
    n = ftir_analysis.normalize_spectrum(y, method="max")
    assert n.max() == pytest.approx(1.0)


def test_match_peaks_to_database_identifies_pet(db):
    # peaks placed at (nearly all of) PET's reference band centers -- a
    # "complete" synthetic PET spectrum, since the reference entry itself
    # now lists 10 characteristic bands rather than a bare-minimum 6.
    peaks = [
        {"index": 0, "x": 1716.0, "y": 1.0, "prominence": 0.5},
        {"index": 1, "x": 1250.0, "y": 0.8, "prominence": 0.4},
        {"index": 2, "x": 1095.0, "y": 0.5, "prominence": 0.3},
        {"index": 3, "x": 1125.0, "y": 0.45, "prominence": 0.25},
        {"index": 4, "x": 1017.0, "y": 0.4, "prominence": 0.2},
        {"index": 5, "x": 1342.0, "y": 0.3, "prominence": 0.2},
        {"index": 6, "x": 972.0, "y": 0.2, "prominence": 0.15},
        {"index": 7, "x": 872.0, "y": 0.2, "prominence": 0.15},
        {"index": 8, "x": 725.0, "y": 0.3, "prominence": 0.2},
    ]
    matches = ftir_analysis.match_peaks_to_database(peaks, db, tolerance=8.0)
    assert matches
    assert matches[0]["name"] == "Polyethylene Terephthalate (PET)"
    assert matches[0]["score"] > 0.7
    assert matches[0]["source"]


def test_match_peaks_to_database_skips_ir_inactive_placeholders(db):
    # a lone peak far from any real band should not match NaCl/KCl/KBr (range [0,0])
    peaks = [{"index": 0, "x": 2500.0, "y": 1.0, "prominence": 0.5}]
    matches = ftir_analysis.match_peaks_to_database(peaks, db, tolerance=5.0)
    assert all(m["name"] not in ("Sodium Chloride (NaCl)", "Potassium Chloride (KCl)", "Potassium Bromide (KBr)")
               for m in matches)


def test_category_filter_restricts_and_excludes_other_categories(db):
    peaks = [
        {"index": 0, "x": 1716.0, "y": 1.0, "prominence": 0.5},
        {"index": 1, "x": 1250.0, "y": 0.8, "prominence": 0.4},
        {"index": 2, "x": 1095.0, "y": 0.5, "prominence": 0.3},
        {"index": 3, "x": 1017.0, "y": 0.4, "prominence": 0.2},
        {"index": 4, "x": 725.0, "y": 0.3, "prominence": 0.2},
    ]
    polymer_only = ftir_analysis.match_peaks_to_database(peaks, db, tolerance=8.0, categories=["polymers"])
    assert polymer_only
    assert all(m["category"] == "polymer" for m in polymer_only)

    salts_only = ftir_analysis.match_peaks_to_database(peaks, db, tolerance=8.0, categories=["salts_inorganic"])
    assert all(m["category"] != "polymer" for m in salts_only)

    # PET must not appear at all when the search is restricted away from polymers
    assert all(m["name"] != "Polyethylene Terephthalate (PET)" for m in salts_only)


def test_category_filter_invalid_key_falls_back_to_all(db):
    peaks = [{"index": 0, "x": 1716.0, "y": 1.0, "prominence": 0.5}]
    all_results = ftir_analysis.match_peaks_to_database(peaks, db, tolerance=8.0, categories=None)
    bogus_results = ftir_analysis.match_peaks_to_database(peaks, db, tolerance=8.0, categories=["not_a_real_category"])
    assert len(bogus_results) == len(all_results)


def test_category_labels_cover_every_material_category():
    for cat in ftir_analysis.MATERIAL_CATEGORIES:
        assert cat in ftir_analysis.CATEGORY_LABELS


def test_match_functional_groups_hits_carbonyl(db):
    peaks = [{"index": 0, "x": 1715.0, "y": 1.0, "prominence": 0.5}]
    hits = ftir_analysis.match_functional_groups(peaks, db, tolerance=10.0)
    assert any("C=O" in h["group"] for h in hits)
    assert all(h.get("source") for h in hits)


def test_smooth_spectrum_reduces_noise_variance():
    rng = np.random.default_rng(0)
    x = np.linspace(0, 100, 500)
    clean = _gaussian(x, 50, 1.0, 10)
    noisy = clean + rng.normal(scale=0.05, size=len(x))
    smoothed = ftir_analysis.smooth_spectrum(noisy, window_length=15, polyorder=3)
    assert np.std(smoothed - clean) < np.std(noisy - clean)


def test_search_database_filters_by_query_and_category(db):
    results = ftir_analysis.search_database(db, "polyethylene")
    assert any("Polyethylene" in r["name"] for r in results)
    poly_only = ftir_analysis.search_database(db, "", category="polymers")
    assert all(r["_db_category"] == "polymers" for r in poly_only)


def test_find_entry_returns_full_peak_list_for_overlay(db):
    entry = ftir_analysis.find_entry(db, "Polyethylene Terephthalate (PET)")
    assert entry is not None
    assert entry["name"] == "Polyethylene Terephthalate (PET)"
    assert len(entry["peaks"]) >= 6  # the full reference list, not a matched subset

    assert ftir_analysis.find_entry(db, "Not A Real Material") is None
