import numpy as np
import pytest

import peak_fitting as pf


def test_fit_peak_gaussian_recovers_known_parameters():
    x = np.linspace(-50, 50, 2000)
    true_center, true_height, true_fwhm = 5.0, 3.0, 8.0
    y = pf.gaussian(x, true_height, true_center, true_fwhm, offset=0.1)
    result = pf.fit_peak(x, y, center_guess=4.0, window=30, shape="gaussian")
    assert result["center"] == pytest.approx(true_center, abs=0.1)
    assert result["height"] == pytest.approx(true_height, abs=0.1)
    assert result["fwhm"] == pytest.approx(true_fwhm, abs=0.2)
    assert result["r_squared"] > 0.999


def test_fit_peak_lorentzian_recovers_known_parameters():
    x = np.linspace(-50, 50, 2000)
    true_center, true_height, true_fwhm = -3.0, 2.0, 6.0
    y = pf.lorentzian(x, true_height, true_center, true_fwhm)
    result = pf.fit_peak(x, y, center_guess=-2.5, window=30, shape="lorentzian")
    assert result["center"] == pytest.approx(true_center, abs=0.15)
    assert result["fwhm"] == pytest.approx(true_fwhm, abs=0.3)
    assert result["r_squared"] > 0.999


def test_fit_peak_pseudo_voigt_recovers_known_parameters():
    x = np.linspace(-50, 50, 2000)
    y = pf.pseudo_voigt(x, 4.0, 2.0, 10.0, 0.4)
    result = pf.fit_peak(x, y, center_guess=2.5, window=30, shape="pseudo_voigt")
    assert result["center"] == pytest.approx(2.0, abs=0.2)
    assert 0.99 < result["r_squared"] <= 1.0001


def test_fit_peak_raises_with_too_few_points():
    x = np.array([1.0, 2.0, 3.0])
    y = np.array([1.0, 2.0, 1.0])
    with pytest.raises(ValueError):
        pf.fit_peak(x, y, center_guess=2.0, window=0.1, shape="gaussian")


def test_fit_peaks_batch_fits_multiple_isolated_peaks():
    x = np.linspace(0, 200, 4000)
    centers = [40.0, 100.0, 160.0]
    y = sum(pf.gaussian(x, 2.0, c, 5.0) for c in centers)
    seed_peaks = [{"x": c + 1.0} for c in centers]  # slightly off-center seeds
    fits, errors = pf.fit_peaks_batch(x, y, seed_peaks, window=20, shape="gaussian")
    assert len(fits) == 3
    assert not errors
    fitted_centers = sorted(f["center"] for f in fits)
    for expected, actual in zip(sorted(centers), fitted_centers):
        assert actual == pytest.approx(expected, abs=0.2)


def test_gaussian_and_lorentzian_peak_at_center():
    assert pf.gaussian(np.array([0.0]), 5.0, 0.0, 4.0)[0] == pytest.approx(5.0)
    assert pf.lorentzian(np.array([0.0]), 5.0, 0.0, 4.0)[0] == pytest.approx(5.0)
