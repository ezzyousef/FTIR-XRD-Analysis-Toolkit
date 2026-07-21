import os
import numpy as np
import pytest

import xrd_analysis
from conftest import DB_DIR


@pytest.fixture(scope="module")
def db():
    return xrd_analysis.load_xrd_database(os.path.join(DB_DIR, "xrd_reference_db.json"))


def test_database_schema(db):
    assert "_meta" in db and "references" in db["_meta"]
    assert len(db["phases"]) > 0
    for phase in db["phases"]:
        assert phase["name"]
        assert phase.get("source")
        assert phase["peaks"]
        for p in phase["peaks"]:
            assert p["d_A"] > 0
            assert 0 <= p["rel_intensity"] <= 100


def test_bragg_d_spacing_known_value():
    # Cu Ka1, 2theta=26.6 deg is the well-known quartz (101) line, d ~ 3.34 A
    d = xrd_analysis.bragg_d_spacing(26.6, xrd_analysis.WAVELENGTHS["Cu Ka1"])
    assert d == pytest.approx(3.35, abs=0.02)


def test_bragg_d_spacing_round_trips_with_scherrer_inputs():
    wl = xrd_analysis.WAVELENGTHS["Cu Ka1"]
    d = xrd_analysis.bragg_d_spacing(30.0, wl)
    # recompute 2theta from d and confirm it comes back to 30 degrees
    theta_rad = np.arcsin(wl / (2 * d))
    two_theta_back = np.degrees(theta_rad) * 2
    assert two_theta_back == pytest.approx(30.0, abs=1e-6)


def test_bragg_d_spacing_rejects_non_positive_two_theta():
    with pytest.raises(ValueError):
        xrd_analysis.bragg_d_spacing(0.0, 1.54)


def test_scherrer_crystallite_size_sanity():
    # narrower FWHM -> larger apparent crystallite size
    size_narrow = xrd_analysis.scherrer_crystallite_size(0.1, 30.0, 1.5406)
    size_wide = xrd_analysis.scherrer_crystallite_size(0.5, 30.0, 1.5406)
    assert size_narrow > size_wide > 0


def test_williamson_hall_recovers_pure_size_broadening():
    # beta*cos(theta) = K*lambda/D  (strain = 0) for a set of synthetic peaks
    wl = 1.5406
    two_theta = np.array([20.0, 30.0, 40.0, 50.0, 60.0])
    theta = np.radians(two_theta / 2.0)
    K, D_nm = 0.9, 20.0
    beta_rad = (K * wl * 0.1) / (D_nm * np.cos(theta))  # no strain term
    fwhm_deg = np.degrees(beta_rad)
    res = xrd_analysis.williamson_hall(two_theta, fwhm_deg, wl)
    assert res["crystallite_size_nm"] == pytest.approx(D_nm, rel=0.05)
    assert res["microstrain"] == pytest.approx(0.0, abs=1e-6)


def test_williamson_hall_requires_three_peaks():
    with pytest.raises(ValueError):
        xrd_analysis.williamson_hall([20.0, 30.0], [0.2, 0.2], 1.5406)


def test_percent_crystallinity_all_crystalline():
    x = np.linspace(10, 30, 500)
    y = np.exp(-0.5 * ((x - 20) / 1.0) ** 2)  # sharp crystalline peak, no halo
    pct = xrd_analysis.percent_crystallinity(x, y, [(18, 22)], [(12, 16)])
    assert pct > 95


def test_cubic_lattice_parameter():
    d = 2.088  # Cu (111) d-spacing
    a = xrd_analysis.cubic_lattice_parameter(d, 1, 1, 1)
    assert a == pytest.approx(3.615, abs=0.01)  # known Cu lattice parameter
    with pytest.raises(ValueError):
        xrd_analysis.cubic_lattice_parameter(d, 0, 0, 0)


def test_detect_xrd_peaks_sorted_by_intensity():
    two_theta = np.linspace(10, 80, 3000)
    intensity = (100 * np.exp(-0.5 * ((two_theta - 26.6) / 0.1) ** 2)
                 + 40 * np.exp(-0.5 * ((two_theta - 36.5) / 0.1) ** 2))
    peaks = xrd_analysis.detect_xrd_peaks(two_theta, intensity, prominence_frac=0.05)
    assert len(peaks) == 2
    assert peaks[0]["intensity"] >= peaks[1]["intensity"]


def test_match_xrd_phases_identifies_quartz_self_pattern(db):
    wl = xrd_analysis.WAVELENGTHS["Cu Ka1"]
    quartz = next(p for p in db["phases"] if p["name"].startswith("Quartz"))
    d = np.array([p["d_A"] for p in quartz["peaks"]])
    inten = np.array([p["rel_intensity"] for p in quartz["peaks"]], dtype=float)
    two_theta = 2 * np.degrees(np.arcsin(wl / (2 * d)))

    x = np.linspace(10, 80, 4000)
    y = np.zeros_like(x)
    for c, h in zip(two_theta, inten):
        y += h * np.exp(-0.5 * ((x - c) / 0.08) ** 2)

    peaks = xrd_analysis.detect_xrd_peaks(x, y, prominence_frac=0.02)
    matches = xrd_analysis.match_xrd_phases(peaks, wl, db, d_tolerance_pct=1.5)
    assert matches
    assert matches[0]["name"] == "Quartz, alpha (SiO2)"
    assert matches[0]["score"] > 0.95

    # restricting the search to "mineral" should still find it (quartz is a mineral)
    mineral_only = xrd_analysis.match_xrd_phases(peaks, wl, db, d_tolerance_pct=1.5, categories=["mineral"])
    assert mineral_only and mineral_only[0]["name"] == "Quartz, alpha (SiO2)"
    assert all(m["category"] == "mineral" for m in mineral_only)

    # restricting the search to "metal" should exclude quartz entirely
    metal_only = xrd_analysis.match_xrd_phases(peaks, wl, db, d_tolerance_pct=1.5, categories=["metal"])
    assert all(m["name"] != "Quartz, alpha (SiO2)" for m in metal_only)
    assert all(m["category"] == "metal" for m in metal_only)


def test_phase_category_labels_cover_every_phase_category(db):
    used_categories = {p["category"] for p in db["phases"]}
    for cat in used_categories:
        assert cat in xrd_analysis.PHASE_CATEGORY_LABELS


def test_import_and_persist_user_phases(tmp_path, monkeypatch):
    monkeypatch.setattr(xrd_analysis, "get_config_dir", lambda: str(tmp_path))
    csv_path = tmp_path / "custom_phase.csv"
    csv_path.write_text("name,d_A,hkl,rel_intensity\nMy Phase,2.500,111,100\nMy Phase,1.800,200,50\n", encoding="utf-8")

    phases = xrd_analysis.import_phases_from_csv(str(csv_path))
    assert len(phases) == 1
    assert len(phases[0]["peaks"]) == 2

    xrd_analysis.add_user_phases(phases)
    loaded = xrd_analysis.load_user_phases()
    assert len(loaded) == 1
    assert loaded[0]["name"] == "My Phase"

    xrd_analysis.remove_user_phase("My Phase")
    assert xrd_analysis.load_user_phases() == []


def test_import_phases_from_csv_missing_column_raises(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        xrd_analysis.import_phases_from_csv(str(csv_path))


def _synthetic_peaks(system, params, hkls, wl):
    peaks = []
    for h, k, l in hkls:
        if system == "cubic":
            (a,) = params
            q = (h ** 2 + k ** 2 + l ** 2) / a ** 2
        elif system == "tetragonal":
            a, c = params
            q = (h ** 2 + k ** 2) / a ** 2 + l ** 2 / c ** 2
        elif system == "hexagonal":
            a, c = params
            q = (4.0 / 3.0) * (h ** 2 + h * k + k ** 2) / a ** 2 + l ** 2 / c ** 2
        elif system == "orthorhombic":
            a, b, c = params
            q = h ** 2 / a ** 2 + k ** 2 / b ** 2 + l ** 2 / c ** 2
        d = 1.0 / np.sqrt(q)
        two_theta = 2 * np.degrees(np.arcsin(wl / (2 * d)))
        peaks.append({"two_theta": two_theta, "h": h, "k": k, "l": l})
    return peaks


def test_refine_lattice_parameters_cubic_recovers_known_value():
    wl = xrd_analysis.WAVELENGTHS["Cu Ka1"]
    true_a = 3.6150  # Cu
    hkls = [(1, 1, 1), (2, 0, 0), (2, 2, 0), (3, 1, 1), (2, 2, 2), (4, 0, 0)]
    peaks = _synthetic_peaks("cubic", (true_a,), hkls, wl)
    res = xrd_analysis.refine_lattice_parameters(peaks, wl, crystal_system="cubic")
    assert res["params"]["a"] == pytest.approx(true_a, abs=1e-4)
    assert res["r_squared"] > 0.999
    assert res["n_peaks_used"] == 6
    assert res["n_peaks_excluded"] == 0
    assert res["converged"]


def test_refine_lattice_parameters_rejects_misindexed_outlier():
    wl = xrd_analysis.WAVELENGTHS["Cu Ka1"]
    true_a = 3.6150
    hkls = [(1, 1, 1), (2, 0, 0), (2, 2, 0), (3, 1, 1), (2, 2, 2), (4, 0, 0)]
    peaks = _synthetic_peaks("cubic", (true_a,), hkls, wl)
    peaks_with_outlier = peaks + [{"two_theta": 50.0, "h": 1, "k": 1, "l": 1}]  # garbage 2theta

    res = xrd_analysis.refine_lattice_parameters(peaks_with_outlier, wl, crystal_system="cubic", outlier_sigma=3.0)
    assert res["params"]["a"] == pytest.approx(true_a, abs=1e-3)
    assert res["n_peaks_excluded"] == 1
    assert res["n_peaks_used"] == 6
    assert res["per_peak"][-1]["used"] is False  # the injected garbage peak


def test_refine_lattice_parameters_averages_down_noise():
    wl = xrd_analysis.WAVELENGTHS["Cu Ka1"]
    true_a = 3.6150
    hkls = [(1, 1, 1), (2, 0, 0), (2, 2, 0), (3, 1, 1), (2, 2, 2), (4, 0, 0)]
    rng = np.random.default_rng(0)
    peaks = _synthetic_peaks("cubic", (true_a,), hkls, wl)
    for p in peaks:
        p["two_theta"] += rng.normal(scale=0.02)

    res = xrd_analysis.refine_lattice_parameters(peaks, wl, crystal_system="cubic")
    assert res["params"]["a"] == pytest.approx(true_a, abs=0.01)
    assert res["n_peaks_excluded"] == 0
    assert res["param_errors"]["a"] > 0  # a real, nonzero uncertainty estimate


def test_refine_lattice_parameters_tetragonal_and_hexagonal_and_orthorhombic():
    wl = xrd_analysis.WAVELENGTHS["Cu Ka1"]

    tet_hkls = [(1, 1, 0), (1, 0, 1), (2, 0, 0), (1, 1, 1), (2, 1, 0), (2, 1, 1), (2, 2, 0), (0, 0, 2)]
    peaks = _synthetic_peaks("tetragonal", (4.594, 2.959), tet_hkls, wl)
    res = xrd_analysis.refine_lattice_parameters(peaks, wl, crystal_system="tetragonal")
    assert res["params"]["a"] == pytest.approx(4.594, abs=1e-3)
    assert res["params"]["c"] == pytest.approx(2.959, abs=1e-3)

    hex_hkls = [(1, 0, 0), (1, 0, 1), (1, 1, 0), (1, 0, 2), (1, 1, 1), (2, 0, 0), (2, 0, 1), (0, 0, 3)]
    peaks = _synthetic_peaks("hexagonal", (4.913, 5.405), hex_hkls, wl)
    res = xrd_analysis.refine_lattice_parameters(peaks, wl, crystal_system="hexagonal")
    assert res["params"]["a"] == pytest.approx(4.913, abs=1e-3)
    assert res["params"]["c"] == pytest.approx(5.405, abs=1e-3)

    orth_hkls = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1), (1, 1, 1), (2, 0, 0)]
    peaks = _synthetic_peaks("orthorhombic", (5.0, 6.0, 7.0), orth_hkls, wl)
    res = xrd_analysis.refine_lattice_parameters(peaks, wl, crystal_system="orthorhombic")
    assert res["params"]["a"] == pytest.approx(5.0, abs=1e-3)
    assert res["params"]["b"] == pytest.approx(6.0, abs=1e-3)
    assert res["params"]["c"] == pytest.approx(7.0, abs=1e-3)


def test_refine_lattice_parameters_requires_enough_peaks():
    wl = xrd_analysis.WAVELENGTHS["Cu Ka1"]
    peaks = _synthetic_peaks("cubic", (3.615,), [(1, 1, 1)], wl)
    with pytest.raises(ValueError):
        xrd_analysis.refine_lattice_parameters(peaks, wl, crystal_system="cubic")


def test_refine_lattice_parameters_rejects_unsupported_system():
    wl = xrd_analysis.WAVELENGTHS["Cu Ka1"]
    peaks = _synthetic_peaks("cubic", (3.615,), [(1, 1, 1), (2, 0, 0), (2, 2, 0)], wl)
    with pytest.raises(ValueError):
        xrd_analysis.refine_lattice_parameters(peaks, wl, crystal_system="monoclinic")


def test_find_phase_returns_full_peak_list_for_overlay(db):
    phase = xrd_analysis.find_phase(db, "Quartz, alpha (SiO2)")
    assert phase is not None
    assert len(phase["peaks"]) >= 10
    assert xrd_analysis.find_phase(db, "Not A Real Phase") is None


def test_two_theta_from_d_round_trips_with_bragg_d_spacing():
    wl = xrd_analysis.WAVELENGTHS["Cu Ka1"]
    two_theta = 26.6
    d = xrd_analysis.bragg_d_spacing(two_theta, wl)
    back = xrd_analysis.two_theta_from_d(d, wl)
    assert back == pytest.approx(two_theta, abs=1e-6)


def test_two_theta_from_d_returns_none_when_unreachable():
    wl = xrd_analysis.WAVELENGTHS["Cu Ka1"]
    # a d-spacing smaller than wavelength/2 is not reachable at this wavelength (sin(theta) > 1)
    assert xrd_analysis.two_theta_from_d(0.1, wl) is None
