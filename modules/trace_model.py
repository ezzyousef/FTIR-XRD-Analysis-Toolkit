"""
trace_model.py
A single loaded spectrum/pattern ("Trace") plus the palette used to color
multiple overlaid traces consistently across the FTIR and XRD tabs.
"""
import itertools
import numpy as np

# Figure Studio's "Review" palette (labkit), the lab's house style, so traces look the same on
# screen, in Origin and in Excel.
from labkit.style import PALETTES

PALETTE = list(PALETTES["review"])


class ColorCycle:
    def __init__(self):
        self._cycle = itertools.cycle(PALETTE)

    def next(self):
        return next(self._cycle)


class Trace:
    """One loaded spectrum/pattern, its raw copy, detected peaks, fits, and matches."""

    _next_id = itertools.count(1)
    y_unnorm = None         # the spectrum before the current normalization (None: not normalized)
    revision = 0            # bumped on every change of the spectrum or its peaks (stale-result guard)

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
        self.y_unnorm = None
        self.peaks = []
        self.fits = []
        self.matches = []
        self.fg_hits = []
        self.metadata.pop("mixture", None)
