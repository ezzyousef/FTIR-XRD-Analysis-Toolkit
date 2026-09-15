"""FigureSpec: a plot described once, as data, and rendered by matplotlib.

The Origin bridge (`labkit.origin`) and the Excel writer (`labkit.excel`) read the same
spec and call the same `resolve_styles`, so the colour, symbol and legend of every trace
agree across the screen, the Origin project and the workbook.

No Qt imports: figures render headlessly for tests, batch export and CI.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from . import style as S

__all__ = [
    "SeriesSpec", "FigureSpec", "resolve_styles", "render", "save", "annotate",
    "free_corners", "CORNERS",
]

LEGEND_INSIDE_MAX = 4           # above this many traces the legend moves outside the axes
_ROLE_WORDS = {"fit", "fitted", "data", "measured", "raw", "curve", "points", "plot",
               "branch", "model", "simulated", "calc", "calculated"}


@dataclass
class SeriesSpec:
    """One trace."""
    label: str
    x: Sequence[float]
    y: Sequence[float]
    role: str = "data"                  # data | fit | guide | reference
    style: str = "scatter"              # scatter | line | scatter+line
    parent: str | None = None           # label of the data series a fit belongs to
    y_err: Sequence[float] | None = None
    colour: str | None = None           # override the palette (use sparingly)

    def __post_init__(self) -> None:
        self.x = np.asarray(self.x, dtype=float).ravel()
        self.y = np.asarray(self.y, dtype=float).ravel()
        if self.x.size != self.y.size:
            raise ValueError(f"series {self.label!r}: x has {self.x.size} points, y has {self.y.size}")
        if self.y_err is not None:
            self.y_err = np.asarray(self.y_err, dtype=float).ravel()
            if self.y_err.size != self.y.size:
                raise ValueError(f"series {self.label!r}: y_err length does not match y")

    @property
    def is_empty(self) -> bool:
        return self.x.size == 0 or not np.isfinite(self.x).any() or not np.isfinite(self.y).any()


@dataclass
class FigureSpec:
    """A whole plot: axes, scales and traces."""
    title: str
    x_label: str
    y_label: str
    series: list[SeriesSpec] = field(default_factory=list)
    x_unit: str = ""
    y_unit: str = ""
    xscale: str = "linear"              # linear | log
    yscale: str = "linear"
    invert_x: bool = False              # FTIR wavenumber axes run high to low
    invert_y: bool = False
    equal_aspect: bool = False          # Nyquist plots
    note: str = ""
    name: str = ""                      # short identifier for file and sheet names

    def add(self, label: str, x, y, **kwargs) -> "FigureSpec":
        self.series.append(SeriesSpec(label, x, y, **kwargs))
        return self

    @property
    def x_axis(self) -> str:
        return axis_title(self.x_label, self.x_unit)

    @property
    def y_axis(self) -> str:
        return axis_title(self.y_label, self.y_unit)

    @property
    def drawable(self) -> list[SeriesSpec]:
        return [s for s in self.series if not s.is_empty]

    @property
    def is_empty(self) -> bool:
        return not self.drawable

    def effective_scale(self, axis: str) -> str:
        """A log axis cannot show zero or negative values, so fall back to linear."""
        requested = self.xscale if axis == "x" else self.yscale
        if requested != "log":
            return requested
        for s in self.drawable:
            values = s.x if axis == "x" else s.y
            finite = values[np.isfinite(values)]
            if finite.size and finite.min() <= 0:
                return "linear"
        return "log"

    def slug(self) -> str:
        text = self.name or self.title or "figure"
        return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:48] or "figure"


def axis_title(label: str, unit: str) -> str:
    return f"{label} ({unit})" if unit and unit != "-" else label


# ---------------------------------------------------------------------------
# style assignment — shared by every renderer
# ---------------------------------------------------------------------------
def _stem(label: str) -> str:
    words = [w for w in re.split(r"[\s_\-·:]+", label.lower()) if w and w not in _ROLE_WORDS]
    return " ".join(words) or label.lower()


def resolve_styles(spec: FigureSpec, *, theme: str = "light",
                   palette_name: str | None = None) -> list[S.SeriesStyle]:
    """The style of every drawable series, in order.

    Data series take palette slots in turn. A fit takes the slot of the data it belongs
    to: its explicit `parent`, else the data series whose label shares its stem ("elastic
    fit" belongs to "elastic data"), else the only data series if there is just one.
    A fit that belongs to nothing gets a slot of its own rather than borrowing a colour
    that would mislabel it.
    """
    drawable = spec.drawable
    slots: dict[str, int] = {}
    stems: dict[str, int] = {}
    next_slot = 0
    for s in drawable:
        if s.role == "data":
            slots[s.label] = next_slot
            stems.setdefault(_stem(s.label), next_slot)
            next_slot += 1

    styles: list[S.SeriesStyle] = []
    for s in drawable:
        if s.role == "data":
            slot = slots[s.label]
        elif s.role == "fit":
            if s.parent is not None and s.parent in slots:
                slot = slots[s.parent]
            elif _stem(s.label) in stems:
                slot = stems[_stem(s.label)]
            elif len(slots) == 1:
                slot = next(iter(slots.values()))
            else:
                slot = next_slot
                next_slot += 1
        else:
            slot = 0
        styles.append(S.style_for(slot, s.role, palette_name=palette_name, label=s.label,
                                  theme=theme, style_hint=s.style, colour=s.colour))
    return styles


# ---------------------------------------------------------------------------
# matplotlib
# ---------------------------------------------------------------------------
def render(spec: FigureSpec, *, theme: str = "light", size: str = "screen", figure=None,
           palette_name: str | None = None, legend: bool = True, show_note: bool = True,
           metrics: Iterable[tuple[str, float, str]] | None = None):
    """Draw `spec` onto a new or supplied matplotlib Figure and return it."""
    import matplotlib
    from matplotlib.figure import Figure

    rc = S.matplotlib_rc(theme, size)
    t = S.THEMES.get(theme, S.THEMES["light"])
    with matplotlib.rc_context(rc):
        if figure is None:
            figure = Figure(figsize=rc["figure.figsize"], dpi=rc["figure.dpi"])
        figure.clear()
        figure.patch.set_facecolor(t.background)
        ax = figure.add_subplot(111)
        _style_axes(ax, t)

        drawable = spec.drawable
        if not drawable:
            ax.text(0.5, 0.5, "No data to plot", ha="center", va="center",
                    transform=ax.transAxes, color=t.muted, fontsize=11)
            ax.set_axis_off()
            return figure

        for s, st in zip(drawable, resolve_styles(spec, theme=theme, palette_name=palette_name)):
            ok = np.isfinite(s.x) & np.isfinite(s.y)
            kw = st.mpl_kwargs(background=t.background)
            if s.y_err is not None:
                ax.errorbar(s.x[ok], s.y[ok], yerr=s.y_err[ok], capsize=2.5, elinewidth=0.9,
                            ecolor=st.colour, **kw)
            else:
                ax.plot(s.x[ok], s.y[ok], **kw)

        if spec.title:
            ax.set_title(spec.title)
        ax.set_xlabel(spec.x_axis)
        ax.set_ylabel(spec.y_axis)
        if spec.effective_scale("x") == "log":
            ax.set_xscale("log")
        if spec.effective_scale("y") == "log":
            ax.set_yscale("log")
        if spec.invert_x:
            ax.invert_xaxis()
        if spec.invert_y:
            ax.invert_yaxis()
        if spec.equal_aspect:
            ax.set_aspect("equal", adjustable="datalim")
        ax.grid(True, which="major", color=t.grid, linewidth=0.7, alpha=0.9)
        if "log" in (spec.effective_scale("x"), spec.effective_scale("y")):
            ax.grid(True, which="minor", color=t.grid, linewidth=0.45, alpha=0.5)

        corners = free_corners(spec)
        if legend and len(drawable) > 1:
            if len(drawable) > LEGEND_INSIDE_MAX:
                leg = ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1.0), borderaxespad=0.0)
            else:
                leg = ax.legend(loc=corners[1] if metrics else corners[0])
            leg.get_frame().set_facecolor(t.background)
            leg.get_frame().set_edgecolor(t.grid)
            leg.get_frame().set_linewidth(0.8)
            for text in leg.get_texts():
                text.set_color(t.foreground)
        if metrics:
            annotate(figure, metrics, theme=theme, corner=corners[0])
        if show_note and spec.note:
            figure.text(0.012, 0.012, spec.note, fontsize=7.6, color=t.muted,
                        ha="left", va="bottom", style="italic")
        try:
            figure.tight_layout(pad=0.9, rect=(0, 0.035 if spec.note else 0, 1, 1))
        except Exception:                                   # noqa: BLE001 - layout is best effort
            pass
    return figure


def _style_axes(ax, theme: S.Theme) -> None:
    ax.set_facecolor(theme.background)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme.foreground)
    ax.tick_params(colors=theme.foreground, which="both")


CORNERS = ("upper left", "upper right", "lower left", "lower right")


def free_corners(spec: FigureSpec) -> list[str]:
    """The four corners, emptiest first, so the legend and results box land clear of data.

    Beats matplotlib's `loc="best"` because the legend and the results box can agree on
    who gets which corner instead of both choosing the same one.
    """
    drawable = spec.drawable
    if not drawable:
        return list(CORNERS)
    xs = np.concatenate([s.x[np.isfinite(s.x) & np.isfinite(s.y)] for s in drawable])
    ys = np.concatenate([s.y[np.isfinite(s.x) & np.isfinite(s.y)] for s in drawable])
    if xs.size == 0 or np.ptp(xs) == 0 or np.ptp(ys) == 0:
        return list(CORNERS)
    log_x = spec.effective_scale("x") == "log"
    log_y = spec.effective_scale("y") == "log"
    u = _normalise(xs, log_x)
    v = _normalise(ys, log_y)
    if spec.invert_x:
        u = 1.0 - u
    if spec.invert_y:
        v = 1.0 - v
    counts = {
        "upper left": int(((u < 0.45) & (v > 0.55)).sum()),
        "upper right": int(((u > 0.55) & (v > 0.55)).sum()),
        "lower left": int(((u < 0.45) & (v < 0.45)).sum()),
        "lower right": int(((u > 0.55) & (v < 0.45)).sum()),
    }
    return sorted(CORNERS, key=lambda c: (counts[c], CORNERS.index(c)))


def _normalise(values: np.ndarray, log: bool) -> np.ndarray:
    if log:
        values = np.log10(np.clip(values, 1e-300, None))
    lo, hi = float(values.min()), float(values.max())
    return (values - lo) / (hi - lo) if hi > lo else np.zeros_like(values)


def annotate(figure, metrics: Iterable[tuple[str, float, str]], *, theme: str = "light",
             corner: str = "upper left", maximum: int = 4) -> None:
    """A small results box: `metrics` is (name, value, unit) triples."""
    t = S.THEMES.get(theme, S.THEMES["light"])
    width_in = figure.get_size_inches()[0]
    maximum = min(maximum, 4 if width_in >= 6.0 else (3 if width_in >= 4.5 else 2))
    lines = []
    for name, value, unit in metrics:
        if len(lines) >= maximum:
            break
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            continue
        suffix = f" {unit}" if unit and unit != "-" else ""
        lines.append(f"{name} = {format_number(value)}{suffix}")
    if not lines or not figure.axes:
        return
    budget = max(18, int(width_in * 72 * 0.52 / (8.2 * 0.54)))
    lines = [ln if len(ln) <= budget else ln[:budget - 1].rstrip() + "…" for ln in lines]
    pad = 0.028
    figure.axes[0].text(
        pad if "left" in corner else 1.0 - pad, 1.0 - pad if "upper" in corner else pad,
        "\n".join(lines), transform=figure.axes[0].transAxes,
        ha="right" if "right" in corner else "left", va="bottom" if "lower" in corner else "top",
        fontsize=8.2, color=t.foreground, linespacing=1.45, zorder=5,
        bbox={"boxstyle": "round,pad=0.45", "facecolor": t.panel, "edgecolor": t.grid,
              "alpha": 0.94, "linewidth": 0.8})


def format_number(value: float, digits: int = 4) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(v):
        return "n/a"
    if v == 0:
        return "0"
    return f"{v:.{digits}g}"


def save(figure, path: str | Path, *, dpi: str | int = "print", transparent: bool = False) -> Path:
    """Write PNG / PDF / SVG / EPS / TIFF, choosing the format from the suffix."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    resolution = S.EXPORT_DPI.get(dpi, 300) if isinstance(dpi, str) else int(dpi)
    figure.savefig(p, dpi=resolution, transparent=transparent,
                   facecolor="none" if transparent else figure.get_facecolor(),
                   bbox_inches="tight", pad_inches=0.06)
    return p
