"""
trace_model.py
A single loaded spectrum/pattern ("Trace") plus the palette used to color
multiple overlaid traces consistently across the FTIR and XRD tabs.
"""
import itertools
import numpy as np

PALETTE = [
    "#2453ff", "#ff6f3c", "#12b886", "#e64980", "#f59f00",
    "#7048e8", "#15aabf", "#82c91e", "#e03131", "#1971c2",
]


class ColorCycle:
    def __init__(self):
        self._cycle = itertools.cycle(PALETTE)

    def next(self):
        return next(self._cycle)


class Trace:
    """One loaded spectrum/pattern, its raw copy, detected peaks, fits, and matches."""

    _next_id = itertools.count(1)

    def __init__(self, label, x, y, color, metadata=None):
        self.id = next(Trace._next_id)
        self.label = label
        self.x = np.asarray(x, dtype=float)
        self.y = np.asarray(y, dtype=float)
        self.y_raw = self.y.copy()
        self.color = color
        self.visible = True
        self.peaks = []
        self.fits = []
        self.matches = []
        self.fg_hits = []
        self.metadata = metadata or {}

    def revert_to_raw(self):
        self.y = self.y_raw.copy()
        self.peaks = []
        self.fits = []
        self.matches = []
        self.fg_hits = []
