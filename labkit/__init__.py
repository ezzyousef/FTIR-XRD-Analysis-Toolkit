"""labkit — the shared publication-figure, OriginLab, Excel and Qt-interface layer.

One source of truth for how the lab's desktop tools look and export. Each application
vendors a copy of this package (see sync.py) so it keeps building on its own, but the
look, the Origin styling and the Excel layout stay identical across all of them.

The common currency is `labkit.figure.FigureSpec`: a plot described once, as data.
matplotlib, OriginLab and Excel all render from the same spec, so a figure cannot look
one way on screen and another way in Origin.

Nothing outside `labkit.qt` imports Qt, so the figure, Origin and Excel layers can be
used and tested without a display.
"""

__version__ = "1.0.0"

__all__ = ["__version__"]
