"""XRD calibration, uncertainty propagation, warnings, cubic indexing and phase-card checks.
All "standards" and "cards" here are synthetic (a made-up cubic a = 4.0 A lattice), not
certificate or database values."""
import math

import numpy as np
import pytest

import xrd_analysis as xa
import xrd_tools as xt

LAM = 1.5406
A = 4.0
FCC = [(1, 1, 1), (2, 0, 0), (2, 2, 0), (3, 1, 1), (2, 2, 2), (4, 0, 0)]


def tt_of(hkl, a=A):
    d = a / math.sqrt(sum(i * i for i in hkl))
    return 2 * math.degrees(math.asin(LAM / (2 * d))), d


def test_zero_shift_and_displacement_are_recovered():
    z, s = 0.05, -0.03
    true = [tt_of(h) for h in FCC]
    obs = [t + z + s * math.cos(math.radians(t / 2)) for t, _ in true]
    cal = xt.calibrate(obs, [d for _, d in true], LAM, displacement=True)
    assert cal["zero_shift_deg"] == pytest.approx(z, abs=1e-9) and cal["displacement_deg"] == pytest.approx(s, abs=1e-9)
    assert cal["rms_deg"] < 1e-9
    corrected = xt.apply_calibration(np.array(obs), cal)
    assert np.allclose(corrected, [t for t, _ in true], atol=1e-4)     # second-order theta difference only
    zero_only = xt.calibrate([t + 0.02 for t, _ in true], [d for _, d in true], LAM)
    assert zero_only["zero_shift_deg"] == pytest.approx(0.02) and zero_only["model"] == "zero shift"


def test_calibration_refuses_mismatched_input():
    with pytest.raises(ValueError):
        xt.calibrate([30.0, 40.0], [3.0], LAM)
    with pytest.raises(ValueError, match="reachable"):
        xt.calibrate([30.0], [0.5], LAM)


def test_scherrer_uncertainty_matches_monte_carlo():
    B, sB, b, sb, tt = 0.30, 0.01, 0.10, 0.005, 40.0
    r = xt.scherrer_with_uncertainty(B, sB, tt, LAM, b_deg=b, sigma_b_deg=sb)
    assert r["size_nm"] == pytest.approx(xa.scherrer_crystallite_size(math.sqrt(B * B - b * b), tt, LAM))
    rng = np.random.default_rng(0)
    Bs, bs = rng.normal(B, sB, 200000), rng.normal(b, sb, 200000)
    D = 0.9 * LAM / 10 / (np.radians(np.sqrt(Bs ** 2 - bs ** 2)) * math.cos(math.radians(tt / 2)))
    assert r["sigma_nm"] == pytest.approx(np.std(D), rel=0.05)
    lor = xt.scherrer_with_uncertainty(B, sB, tt, LAM, b_deg=b, sigma_b_deg=sb, mode="lorentzian")
    assert lor["sigma_beta_deg"] == pytest.approx(math.hypot(sB, sb))
    assert xt.scherrer_with_uncertainty(0.101, 0.01, tt, LAM, b_deg=0.1) is None


def test_amorphous_halo_warning():
    x = np.arange(5.0, 80.0, 0.02)
    halo = 400 * np.exp(-0.5 * ((x - 22) / 5) ** 2) + 50
    peak = 300 * np.exp(-0.5 * ((x - 44) / 0.1) ** 2)
    w = xt.amorphous_background_warning(x, halo + peak, halo)
    assert w["background_fraction"] > 0.5 and len(w["warnings"]) == 2 and "22" in w["warnings"][1]
    flat = xt.amorphous_background_warning(x, 50 + 30000 * np.exp(-0.5 * ((x - 44) / 0.1) ** 2), np.full_like(x, 50.0))
    assert flat["warnings"] == []


def test_preferred_orientation_warning():
    ok = xt.preferred_orientation_warning([(30, 100, 100), (40, 52, 50), (50, 21, 20)])
    assert ok["warnings"] == []
    textured = xt.preferred_orientation_warning([(30, 100, 100), (40, 10, 50), (50, 21, 20)])
    assert "40.00°" in textured["warnings"][0]


def test_cubic_indexing_finds_the_fcc_candidate():
    tts = [tt_of(h)[0] for h in FCC]
    cands = xt.index_cubic(tts, LAM)
    best = [c for c in cands if c["N"] == [3, 4, 8, 11, 12, 16]]
    assert best and best[0]["a"] == pytest.approx(A, rel=1e-9) and "F" in best[0]["lattices_consistent"]


def write_card(tmp_path, lines, header="d,intensity,hkl", notes="# name=Synthetic cubic\n# source=made up for a test\n"):
    p = tmp_path / "card.csv"
    p.write_text(notes + header + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


def test_phase_card_cross_check(tmp_path):
    card_lines = [f"{tt_of(h)[1]:.5f},{I},{''.join(map(str, h))}" for h, I in zip(FCC, (100, 45, 25, 25, 8, 4))]
    card = xt.load_phase_card(write_card(tmp_path, card_lines))
    assert card["name"] == "Synthetic cubic" and len(card["lines"]) == 6
    obs = [tt_of(h)[0] + 0.02 for h in FCC[:4]] + [61.0]
    r = xt.cross_check_card(obs, [100, 45, 25, 25, 30], card, LAM)
    assert r["fraction_found"] == 1.0 and r["verdict"].startswith("consistent") and "not an identification" in r["verdict"]
    assert r["unexplained_peaks"] == [61.0] and r["mean_abs_delta_deg"] == pytest.approx(0.02, abs=1e-3)
    miss = xt.cross_check_card(obs[1:4], [45, 25, 25], card, LAM, measured_range=(20.0, 80.0))
    assert not miss["verdict"].startswith("consistent") and miss["missing_strong"][0]["card_intensity"] == 100


def test_phase_card_is_strict(tmp_path):
    with pytest.raises(ValueError, match="line"):
        xt.load_phase_card(write_card(tmp_path, ["2.3,100,111", "2.0,50,200,extra"]))
    with pytest.raises(ValueError, match="number"):
        xt.load_phase_card(write_card(tmp_path, ["2.3,abc,111"]))
    with pytest.raises(ValueError, match="wavelength"):
        xt.load_phase_card(write_card(tmp_path, ["38.0,100,111"], header="two_theta,intensity,hkl"))
    card = xt.load_phase_card(write_card(tmp_path, ["38.0,100,111"], header="two_theta,intensity,hkl",
                                         notes="# wavelength=1.5406\n"))
    assert card["lines"][0]["d"] == pytest.approx(float(xa.bragg_d_spacing(38.0, 1.5406)))
