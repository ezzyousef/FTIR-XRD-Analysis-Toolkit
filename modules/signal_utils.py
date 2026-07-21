"""
signal_utils.py
Shared signal-processing helpers used by both FTIR and XRD analysis modules.
"""
import numpy as np
# scipy is imported lazily below -- see the matching comment in
# ftir_analysis.py for why (keeps the startup splash screen short).


def smooth_savgol(y, window_length=11, polyorder=3):
    """
    Savitzky-Golay smoothing. Automatically clamps window_length to a valid
    odd value <= len(y), and polyorder to < window_length, so it never raises
    on short or noisy arrays.
    """
    from scipy.signal import savgol_filter

    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 5:
        return y.copy()

    wl = int(window_length)
    if wl % 2 == 0:
        wl += 1
    wl = max(5, min(wl, n if n % 2 == 1 else n - 1))

    po = int(polyorder)
    if po >= wl:
        po = wl - 2
    po = max(1, po)

    return savgol_filter(y, window_length=wl, polyorder=po)


def moving_average(y, window=5):
    """Simple centered moving-average smoothing (fallback / alternative to Savitzky-Golay)."""
    y = np.asarray(y, dtype=float)
    window = max(1, int(window))
    if window <= 1 or window >= len(y):
        return y.copy()
    kernel = np.ones(window) / window
    return np.convolve(y, kernel, mode="same")
