import numpy as np

import signal_utils as su


def test_smooth_savgol_reduces_noise():
    rng = np.random.default_rng(42)
    x = np.linspace(0, 10, 400)
    clean = np.sin(x)
    noisy = clean + rng.normal(scale=0.1, size=len(x))
    smoothed = su.smooth_savgol(noisy, window_length=15, polyorder=3)
    assert np.std(smoothed - clean) < np.std(noisy - clean)
    assert len(smoothed) == len(noisy)


def test_smooth_savgol_handles_short_arrays_without_raising():
    y = np.array([1.0, 2.0, 3.0])
    result = su.smooth_savgol(y, window_length=11, polyorder=3)
    assert len(result) == len(y)


def test_smooth_savgol_clamps_even_window_to_odd():
    y = np.sin(np.linspace(0, 10, 100))
    # even window_length should not raise (gets clamped to odd internally)
    result = su.smooth_savgol(y, window_length=10, polyorder=2)
    assert len(result) == len(y)


def test_moving_average_basic():
    y = np.array([1.0, 1.0, 1.0, 10.0, 1.0, 1.0, 1.0])
    smoothed = su.moving_average(y, window=3)
    assert smoothed[3] < 10.0  # the spike gets averaged down
    assert len(smoothed) == len(y)


def test_moving_average_passthrough_for_window_one():
    y = np.array([1.0, 5.0, 2.0])
    result = su.moving_average(y, window=1)
    assert np.allclose(result, y)
