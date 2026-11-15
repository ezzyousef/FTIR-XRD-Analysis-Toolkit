"""Independent numerical oracles for the app's equations and algorithms.

Every expected value here is computed from first principles with the `math` module (or from a
synthetic signal whose truth is known by construction), never by calling the code under test.
docs/EQUATION_REGRESSION_REPORT.md lists the worked numbers.
"""
import math

import numpy as np
import pytest

import ftir_analysis as fa
import peak_fitting as pf
import xrd_analysis as xa

CU_KA1 = 1.5406          # Angstrom, the value the upgrade brief asks for
LN2 = math.log(2.0)


def gauss(x, h, c, fwhm):
    s = fwhm / (2.0 * math.sqrt(2.0 * LN2))
    return h * np.exp(-0.5 * ((x - c) / s) ** 2)


def lorentz(x, h, c, fwhm):
    g = fwhm / 2.0
    return h * g * g / ((x - c) ** 2 + g * g)


# ------------------------------------------------------------------------------- XRD: Bragg
def test_bragg_worked_example_cu_ka1():
    # d = lambda / (2 sin theta); 2theta = 30 deg -> theta = 15 deg
    expected = CU_KA1 / (2.0 * math.sin(math.radians(15.0)))
    assert expected == pytest.approx(2.976211, abs=1e-6)
    assert float(xa.bragg_d_spacing(30.0, CU_KA1)) == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("d", [4.0, 3.0, 2.0, 1.2, 0.9])
def test_bragg_round_trip_from_known_d(d):
    two_theta = 2.0 * math.degrees(math.asin(CU_KA1 / (2.0 * d)))
    assert float(xa.bragg_d_spacing(two_theta, CU_KA1)) == pytest.approx(d, rel=1e-12)
    assert xa.two_theta_from_d(d, CU_KA1) == pytest.approx(two_theta, rel=1e-12)


def test_bragg_second_order_and_unreachable():
    assert float(xa.bragg_d_spacing(30.0, CU_KA1, n=2)) == pytest.approx(
        2 * CU_KA1 / (2.0 * math.sin(math.radians(15.0))), rel=1e-12)
    assert xa.two_theta_from_d(CU_KA1 / 2.0 * 0.99, CU_KA1) is None   # sin(theta) would exceed 1


def test_q_identity_q_times_d_is_two_pi():
    for tt in (10.0, 44.5, 120.0):
        q = xa.q_from_two_theta(tt, CU_KA1)
        assert q == pytest.approx(4 * math.pi * math.sin(math.radians(tt / 2)) / CU_KA1, rel=1e-12)
        assert q * float(xa.bragg_d_spacing(tt, CU_KA1)) == pytest.approx(2 * math.pi, rel=1e-12)
    conv = xa.convert_xrd_units(2.5, "d", CU_KA1)
    assert conv["q_inv_a"] == pytest.approx(2 * math.pi / 2.5, rel=1e-12)


def test_d_spacing_uncertainty_equals_numerical_derivative():
    tt, sigma = 38.0, 0.01
    d = lambda t: CU_KA1 / (2.0 * math.sin(math.radians(t / 2.0)))
    numeric = abs(d(tt + 1e-5) - d(tt - 1e-5)) / 2e-5 * sigma
    assert xa.d_spacing_uncertainty(tt, CU_KA1, sigma) == pytest.approx(numeric, rel=1e-6)


def test_cubic_lattice_parameter_from_synthetic_reflection():
    a = 4.0
    for hkl in ((1, 1, 1), (2, 0, 0), (2, 2, 0), (3, 1, 1)):
        d = a / math.sqrt(sum(i * i for i in hkl))
        tt = 2.0 * math.degrees(math.asin(CU_KA1 / (2.0 * d)))
        assert xa.cubic_lattice_parameter(float(xa.bragg_d_spacing(tt, CU_KA1)), *hkl) == pytest.approx(a, rel=1e-12)


def test_peak_position_on_a_synthetic_pattern():
    # A Gaussian reflection placed at the 2theta of d = 2.5 A; detection and fitting find it.
    true_tt = 2.0 * math.degrees(math.asin(CU_KA1 / (2.0 * 2.5)))
    x = np.arange(20.0, 60.0, 0.01)
    y = 50.0 + gauss(x, 1000.0, true_tt, 0.20)
    peaks = xa.detect_xrd_peaks(x, y)
    assert len(peaks) == 1 and abs(peaks[0]["two_theta"] - true_tt) <= 0.005 + 1e-9
    fit = pf.fit_peak(x, y, peaks[0]["two_theta"], 1.0, shape="gaussian")
    assert fit["center"] == pytest.approx(true_tt, abs=1e-6)
    assert float(xa.bragg_d_spacing(fit["center"], CU_KA1)) == pytest.approx(2.5, abs=1e-6)


# ------------------------------------------------------------------------------- XRD: Scherrer
def test_scherrer_worked_example():
    # tau = K lambda / (beta cos theta), beta in radians; K = 0.9, beta = 0.5 deg, 2theta = 40 deg
    expected_nm = 0.9 * (CU_KA1 / 10.0) / (math.radians(0.5) * math.cos(math.radians(20.0)))
    assert expected_nm == pytest.approx(16.9083, abs=1e-4)
    assert xa.scherrer_crystallite_size(0.5, 40.0, CU_KA1, K=0.9) == pytest.approx(expected_nm, rel=1e-12)
    # K enters linearly
    assert xa.scherrer_crystallite_size(0.5, 40.0, CU_KA1, K=1.0) == pytest.approx(expected_nm / 0.9, rel=1e-12)


def _fwhm_deg_for_size(D_nm, two_theta, K=0.9, lam=CU_KA1):
    return math.degrees(K * lam / 10.0 / (D_nm * math.cos(math.radians(two_theta / 2.0))))


def test_scherrer_recovers_size_from_a_simulated_peak():
    D, tt = 20.0, 35.0
    beta = _fwhm_deg_for_size(D, tt)
    x = np.arange(30.0, 40.0, 0.002)
    y = gauss(x, 500.0, tt, beta)
    fit = pf.fit_peak(x, y, tt, 2.0, shape="gaussian")
    assert fit["fwhm"] == pytest.approx(beta, rel=1e-6)
    assert xa.scherrer_crystallite_size(fit["fwhm"], fit["center"], CU_KA1) == pytest.approx(D, rel=1e-5)
    # Detection measures FWHM from the raw points: within one step of the truth.
    pk = xa.detect_xrd_peaks(x, y)[0]
    assert abs(pk["fwhm_deg"] - beta) < 0.002


def test_instrument_broadening_gaussian_and_lorentzian():
    D, tt, b = 30.0, 50.0, 0.08          # instrument FWHM 0.08 deg
    beta = _fwhm_deg_for_size(D, tt)
    B_gauss = math.sqrt(beta ** 2 + b ** 2)     # Gaussian widths add in quadrature
    B_lor = beta + b                            # Lorentzian widths add linearly
    corrected_g = xa.correct_instrumental(B_gauss, b, mode="gaussian")
    corrected_l = xa.correct_instrumental(B_lor, b, mode="lorentzian")
    assert corrected_g == pytest.approx(beta, rel=1e-12) and corrected_l == pytest.approx(beta, rel=1e-12)
    assert xa.scherrer_crystallite_size(corrected_g, tt, CU_KA1) == pytest.approx(D, rel=1e-12)
    # Width not measurably above the instrument: no size
    assert xa.correct_instrumental(1.02 * b, b) is None


def test_simulated_convolution_supports_quadrature_rule():
    # Convolve two Gaussians numerically: the result's FWHM is sqrt(B1^2 + B2^2).
    x = np.arange(-5.0, 5.0, 0.001)
    g = np.convolve(gauss(x, 1.0, 0.0, 0.3), gauss(x, 1.0, 0.0, 0.4), mode="same")
    fit = pf.fit_peak(x, g, 0.0, 2.0, shape="gaussian")
    assert fit["fwhm"] == pytest.approx(0.5, rel=1e-3)


def test_caglioti_fit_recovers_uvw():
    U, V, W = 0.004, -0.002, 0.003
    tt = np.array([20.0, 35.0, 50.0, 65.0, 80.0, 95.0])
    t = np.tan(np.radians(tt / 2.0))
    h = np.sqrt(U * t ** 2 + V * t + W)
    r = xa.fit_caglioti(tt, h)
    assert (r["U"], r["V"], r["W"]) == pytest.approx((U, V, W), abs=1e-12)
    assert xa.caglioti_fwhm(50.0, U, V, W) == pytest.approx(math.sqrt(U * math.tan(math.radians(25)) ** 2
                                                                      + V * math.tan(math.radians(25)) + W))


def test_williamson_hall_recovers_size_and_strain():
    D, eps, K = 25.0, 2.0e-3, 0.9
    tt = np.array([28.0, 33.0, 47.0, 56.0, 69.0, 76.0])
    th = np.radians(tt / 2.0)
    beta_rad = (K * CU_KA1 / 10.0 / D + 4.0 * eps * np.sin(th)) / np.cos(th)
    r = xa.williamson_hall(tt, np.degrees(beta_rad), CU_KA1, K=K)
    assert r["crystallite_size_nm"] == pytest.approx(D, rel=1e-9)
    assert r["microstrain"] == pytest.approx(eps, rel=1e-9)
    assert r["r_squared"] == pytest.approx(1.0)


def test_kalpha2_stripping_removes_the_exact_bragg_doublet():
    lam1, lam2 = 1.540562, 1.544390
    tt1 = 70.0
    tt2 = 2.0 * math.degrees(math.asin(math.sin(math.radians(tt1 / 2.0)) * lam2 / lam1))
    x = np.arange(65.0, 75.0, 0.005)
    y = gauss(x, 1000.0, tt1, 0.08) + 0.5 * gauss(x, 1000.0, tt2, 0.08)
    stripped = xa.strip_kalpha2(x, y, lam1, lam2, ratio=0.5)
    truth = gauss(x, 1000.0, tt1, 0.08)
    assert np.max(np.abs(stripped - truth)) < 0.02 * 1000.0
    # The small-angle offset formula is close to the exact separation at this angle
    assert float(xa.kalpha2_offset_deg(tt1, lam1, lam2)) == pytest.approx(tt2 - tt1, rel=2e-3)


def test_crystallinity_of_two_known_areas():
    x = np.arange(5.0, 60.0, 0.01)
    # narrow crystalline peak (area h*fwhm*sqrt(pi/(4 ln2))) and a broad amorphous halo
    area = lambda h, w: h * w * math.sqrt(math.pi / (4 * LN2))
    y = gauss(x, 800.0, 40.0, 0.5) + gauss(x, 100.0, 20.0, 6.0)
    expected = 100.0 * area(800, 0.5) / (area(800, 0.5) + area(100, 6.0))
    got = xa.percent_crystallinity(x, y, [(37.0, 43.0)], [(5.0, 35.0)])
    assert got == pytest.approx(expected, rel=1e-3)


def test_snip_background_under_a_narrow_peak_on_a_flat_background():
    x = np.arange(10.0, 80.0, 0.02)
    y = 200.0 + gauss(x, 2000.0, 45.0, 0.2)
    bg = xa.snip_background(y, iterations=xa.snip_iterations(x, 2.0))
    assert np.max(np.abs(bg - 200.0)) < 0.02 * 200.0


# ------------------------------------------------------------------------------- FTIR
@pytest.mark.parametrize("pct_t, absorbance", [(100.0, 0.0), (50.0, -math.log10(0.5)), (10.0, 1.0), (1.0, 2.0)])
def test_transmittance_absorbance(pct_t, absorbance):
    assert float(fa.transmittance_to_absorbance(pct_t)) == pytest.approx(absorbance, abs=1e-12)
    assert float(fa.absorbance_to_transmittance(absorbance)) == pytest.approx(pct_t, rel=1e-12)
    # the peak-measuring signal gives the same A from %T and from 0-1 transmittance
    pct = np.array([pct_t, 100.0, 80.0])
    assert fa.absorbance_like(pct, "transmittance")[0] == pytest.approx(absorbance, abs=1e-12)
    assert fa.absorbance_like(pct / 100.0, "transmittance")[0] == pytest.approx(absorbance, abs=1e-12)


def test_wavenumber_wavelength_conversion():
    # lambda (um) = 10^4 / nu (cm-1)
    assert fa.wavenumber_to_wavelength_um(1000.0) == pytest.approx(10.0)
    assert fa.wavenumber_to_wavelength_um(4000.0) == pytest.approx(2.5)
    assert fa.wavelength_um_to_wavenumber(2.5) == pytest.approx(4000.0)
    assert np.allclose(fa.wavelength_um_to_wavenumber(fa.wavenumber_to_wavelength_um(np.array([400.0, 1650.0]))),
                       [400.0, 1650.0])
    with pytest.raises(ValueError):
        fa.wavenumber_to_wavelength_um(0.0)


def test_linear_baseline_correction_recovers_the_band():
    x = np.arange(4000.0, 399.0, -1.0)
    band = gauss(x, 0.8, 1700.0, 20.0)
    y = band + 0.05 + 2e-5 * x
    # What the app's button does: a straight line through the first and last points.
    corrected, baseline = fa.baseline_correct(x, y)
    assert np.max(np.abs(corrected - band)) < 1e-9
    assert np.allclose(baseline, 0.05 + 2e-5 * x)
    # Anchors inside the spectrum: exact between them; outside them the line is held flat
    # (np.interp), which the report documents. The app's button does not pass anchors.
    corrected, baseline = fa.baseline_correct(x, y, anchor_points=[3800.0, 600.0])
    inside = (x >= 600.0) & (x <= 3800.0)
    assert np.max(np.abs(corrected - band)[inside]) < 1e-9
    assert baseline[0] == pytest.approx(0.05 + 2e-5 * 3800.0)


def test_peak_area_of_a_gaussian_band():
    x = np.arange(1500.0, 1900.0, 0.5)
    y = gauss(x, 0.6, 1700.0, 16.0)
    expected = 0.6 * 16.0 * math.sqrt(math.pi / (4 * LN2))
    assert fa.peak_area(x, y, 1600.0, 1800.0) == pytest.approx(expected, rel=1e-6)
    assert fa.peak_area(x[::-1], y[::-1], 1800.0, 1600.0) == pytest.approx(expected, rel=1e-6)


def test_fwhm_in_absorbance_and_transmittance_modes():
    x = np.arange(4000.0, 400.0, -0.25)
    a = gauss(x, 0.9, 1100.0, 24.0)
    i = int(np.argmax(a))
    assert fa.fwhm_from_peak(x, a, i) == pytest.approx(24.0, rel=2e-3)
    pct_t = 100.0 * 10.0 ** (-a)
    assert fa.fwhm_from_peak(x, pct_t, i, mode="transmittance") == pytest.approx(24.0, rel=2e-3)


def test_beer_lambert():
    # c = A / (epsilon l): A = 0.45, epsilon = 150 L/(mol cm), l = 0.01 cm -> 0.3 mol/L
    assert fa.beer_lambert_concentration(0.45, 150.0, 0.01) == pytest.approx(0.3)


def test_normalization_definitions():
    x = np.linspace(400.0, 4000.0, 901)
    y = gauss(x, 2.0, 1700.0, 30.0) + 0.1
    assert np.nanmax(np.abs(fa.normalize_spectrum(y, "max"))) == pytest.approx(1.0)
    mm = fa.normalize_spectrum(y, "minmax")
    assert (mm.min(), mm.max()) == pytest.approx((0.0, 1.0))
    v = fa.normalize_spectrum(y, "vector")
    assert math.sqrt(float(np.sum(v ** 2))) == pytest.approx(1.0)
    ar = fa.normalize_spectrum(y, "area", x=x)
    assert float(np.sum((np.abs(ar[1:]) + np.abs(ar[:-1])) / 2 * np.diff(x))) == pytest.approx(1.0)


def test_atr_correction_undoes_penetration_depth():
    # d_p = lambda / (2 pi n1 sqrt(sin^2 theta - (n2/n1)^2)), lambda = 1/nu: d_p is proportional to 1/nu.
    n1, n2, theta = 2.4, 1.5, math.radians(45.0)
    dp = lambda nu: (1.0 / nu) / (2 * math.pi * n1 * math.sqrt(math.sin(theta) ** 2 - (n2 / n1) ** 2))
    x = np.array([3000.0, 1700.0, 1000.0, 700.0])
    true_a = np.full_like(x, 0.5)
    atr_a = true_a * np.array([dp(v) for v in x]) / dp(1000.0)
    corrected = fa.atr_correction(x, atr_a, crystal="diamond", angle_deg=45.0, n_sample=n2, reference_wavenumber=1000.0)
    assert np.allclose(corrected, true_a, rtol=1e-12)


@pytest.mark.parametrize("descending", [False, True])
def test_first_and_second_derivative_against_the_analytic_derivative(descending):
    # y = 3e-6 x^3 - 2e-3 x^2: dy/dx = 9e-6 x^2 - 4e-3 x, d2y/dx2 = 1.8e-5 x - 4e-3
    x = np.arange(400.0, 4000.5, 2.0)
    if descending:
        x = x[::-1]                     # FTIR exports usually run from 4000 down to 400
    y = 3e-6 * x ** 3 - 2e-3 * x ** 2
    d1 = fa.derivative_spectrum(x, y, order=1, window_length=15, polyorder=3)
    d2 = fa.derivative_spectrum(x, y, order=2, window_length=15, polyorder=3)
    inner = slice(10, -10)
    assert np.allclose(d1[inner], (9e-6 * x ** 2 - 4e-3 * x)[inner], rtol=1e-6, atol=1e-9)
    assert np.allclose(d2[inner], (1.8e-5 * x - 4e-3)[inner], rtol=1e-6, atol=1e-9)


# ------------------------------------------------------------------------------- peak fitting
@pytest.mark.parametrize("shape, func, area_factor", [
    ("gaussian", gauss, math.sqrt(math.pi / (4 * LN2))),     # area = h * FWHM * 1.0645
    ("lorentzian", lorentz, math.pi / 2.0),                 # area = pi * h * gamma = h * FWHM * pi/2
])
def test_fitted_parameters_and_full_profile_area(shape, func, area_factor):
    h, c, w = 0.7, 1650.0, 12.0
    x = np.arange(1600.0, 1700.0, 0.1)
    y = func(x, h, c, w) + 0.02
    fit = pf.fit_peak(x, y, 1648.0, 36.0, shape=shape)
    assert (fit["height"], fit["center"], fit["fwhm"]) == pytest.approx((h, c, w), rel=1e-6)
    assert fit["offset"] == pytest.approx(0.02, abs=1e-6)
    # The area of a fitted peak is the area of the whole fitted profile, not the part
    # that happens to lie inside the fit window (a Lorentzian has long tails).
    assert fit["area"] == pytest.approx(h * w * area_factor, rel=1e-6)


def test_pseudo_voigt_area_is_the_weighted_sum():
    h, c, w, eta = 1.0, 30.0, 0.4, 0.3
    x = np.arange(27.0, 33.0, 0.002)
    y = eta * lorentz(x, h, c, w) + (1 - eta) * gauss(x, h, c, w)
    fit = pf.fit_peak(x, y, 30.0, 2.0, shape="pseudo_voigt")
    assert fit["eta"] == pytest.approx(eta, abs=1e-6)
    expected = h * w * (eta * math.pi / 2 + (1 - eta) * math.sqrt(math.pi / (4 * LN2)))
    assert fit["area"] == pytest.approx(expected, rel=1e-6)
