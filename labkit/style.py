"""One definition of "publishable", shared by matplotlib, OriginLab and Excel.

Colours are the Okabe–Ito colourblind-safe set, ordered so the first three also separate
in greyscale. Symbols are ordered so neighbouring series never share a shape, and filled
and open symbols alternate after the first cycle.

The Origin codes in this module were verified against a live Origin 2026b installation,
and two of them contradict originpro's own documentation — see
`SeriesStyle.origin_symbol_interior` and `labtalk_colour`.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "PALETTES", "DEFAULT_PALETTE", "SYMBOLS", "MPL_MARKER", "ORIGIN_SYMBOL", "LINE_STYLES",
    "ORIGIN_LINE_STYLE", "SeriesStyle", "Theme", "THEMES", "FIGURE_SIZES", "EXPORT_DPI",
    "palette", "style_for", "matplotlib_rc", "labtalk_colour", "hex_to_rgb",
]

# ---------------------------------------------------------------------------
# colour
# ---------------------------------------------------------------------------
PALETTES: dict[str, list[str]] = {
    # Okabe–Ito, reordered so the first three are also the most distinct in greyscale.
    "publication": ["#0072B2", "#D55E00", "#009E73", "#CC79A7",
                    "#E69F00", "#56B4E9", "#7F3F98", "#333333"],
    # Higher contrast for dark backgrounds and projected slides.
    "vivid": ["#3987E5", "#FF7A45", "#1FC28C", "#FF6FB5",
              "#FFC24B", "#7DD3FC", "#A78BFA", "#E5E7EB"],
    # A series ordered by a parameter: scan rate, cycle number, temperature.
    "sequential": ["#08306B", "#12508F", "#2171B5", "#4292C6",
                   "#6BAED6", "#9ECAE1", "#C6DBEF", "#DEEBF7"],
    # Signed quantities.
    "diverging": ["#B2182B", "#D6604D", "#F4A582", "#FDDBC7",
                  "#D1E5F0", "#92C5DE", "#4393C3", "#2166AC"],
    # One accent against a graded grey ramp, when a single series is the point.
    "focus": ["#0072B2", "#2F343B", "#4A5058", "#656C75",
              "#828992", "#9EA5AD", "#B9BFC6", "#D4D9DE"],
}
DEFAULT_PALETTE = "publication"

GUIDE_COLOUR = {"light": "#333333", "dark": "#D5D8DD"}

# ---------------------------------------------------------------------------
# symbols and lines
# ---------------------------------------------------------------------------
SYMBOLS: list[str] = ["circle", "square", "triangle_up", "diamond",
                      "triangle_down", "hexagon", "star", "cross"]

MPL_MARKER: dict[str, str] = {
    "circle": "o", "square": "s", "triangle_up": "^", "diamond": "D",
    "triangle_down": "v", "hexagon": "h", "star": "*", "cross": "X",
    "plus": "P", "none": "",
}

# Origin symbol shape codes (`set -k n` / plot.symbol_kind).
ORIGIN_SYMBOL: dict[str, int] = {
    "circle": 2, "square": 3, "triangle_up": 7, "diamond": 5,
    "triangle_down": 8, "hexagon": 12, "star": 10, "cross": 15,
    "plus": 14, "none": 0,
}

LINE_STYLES: dict[str, tuple[float, ...] | None] = {
    "solid": None, "dash": (6, 3), "dot": (1.5, 2.5),
    "dashdot": (7, 2.5, 1.5, 2.5), "longdash": (11, 4),
}

# Origin line style codes (`set -d n`).
ORIGIN_LINE_STYLE: dict[str, int] = {"solid": 0, "dash": 1, "dot": 2, "dashdot": 3, "longdash": 5}

LABTALK_LINE_WIDTH_UNITS = 500      # `set -w` counts in 1/500 pt


def hex_to_rgb(colour: str) -> tuple[int, int, int]:
    h = colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def labtalk_colour(colour: str) -> str:
    """LabTalk colour literal.

    Verified: the `color(r,g,b)` form parses; `color(#RRGGBB)` is silently ignored.
    """
    r, g, b = hex_to_rgb(colour)
    return f"color({r},{g},{b})"


@dataclass(frozen=True)
class SeriesStyle:
    """Everything needed to draw one trace, in matplotlib, Origin or Excel."""
    colour: str
    symbol: str
    line_style: str
    line_width: float
    symbol_size: float
    filled: bool
    label: str = ""

    @property
    def has_symbol(self) -> bool:
        return self.symbol != "none" and self.symbol_size > 0

    @property
    def has_line(self) -> bool:
        return self.line_style != "none" and self.line_width > 0

    # -- matplotlib ----------------------------------------------------------
    def mpl_kwargs(self, background: str = "#FFFFFF") -> dict:
        kw: dict = {
            "color": self.colour, "linewidth": self.line_width,
            "markersize": self.symbol_size, "markeredgecolor": self.colour,
            "markerfacecolor": self.colour if self.filled else background,
            "markeredgewidth": 1.1, "label": self.label,
            "marker": MPL_MARKER.get(self.symbol, "o") if self.has_symbol else "",
        }
        if not self.has_line:
            kw["linestyle"] = "none"
        else:
            dashes = LINE_STYLES.get(self.line_style)
            kw["linestyle"] = (0, dashes) if dashes else "-"
        return kw

    # -- Origin --------------------------------------------------------------
    @property
    def origin_symbol(self) -> int:
        return ORIGIN_SYMBOL.get(self.symbol, 2)

    @property
    def origin_line_style(self) -> int:
        return ORIGIN_LINE_STYLE.get(self.line_style, 0)

    @property
    def origin_symbol_interior(self) -> int:
        """Origin's `plotN.symbol.interior`: 0 fills with the plot colour, 1 leaves it open.

        Verified against Origin 2026b by rendering. originpro's docstring has these the
        other way round, and setting 1 there produces a hollow symbol.
        """
        return 0 if self.filled else 1

    @property
    def origin_plot_type(self) -> str:
        """originpro `add_plot(type=)`: line, line+symbol, or scatter."""
        if not self.has_symbol:
            return "l"
        return "y" if self.has_line else "s"

    @property
    def labtalk_plot_type(self) -> int:
        """LabTalk `plotxy plot:=` code: 200 line, 201 line+symbol, 202 scatter."""
        if not self.has_symbol:
            return 200
        return 201 if self.has_line else 202

    def labtalk_set_options(self) -> list[str]:
        """The `set <range>` options that apply this style to one data plot.

        `-c` is always sent: it sets the plot's own colour, which is what a line-only
        plot reports and what its legend swatch uses. `-cl` only reaches the line
        segment, and on a line+symbol plot `plot.color` only reaches the line, leaving
        the symbol Origin's default black — so symbol colour is set explicitly too.
        """
        options = [f"-c {labtalk_colour(self.colour)}"]
        if self.has_symbol:
            options += [f"-k {self.origin_symbol}",
                        f"-z {max(1, int(round(self.symbol_size)))}",
                        f"-kf {self.origin_symbol_interior}"]
        else:
            options.append("-k 0")
        if self.has_line:
            options += [f"-w {int(round(self.line_width * LABTALK_LINE_WIDTH_UNITS))}",
                        f"-d {self.origin_line_style}",
                        f"-cl {labtalk_colour(self.colour)}"]
        return options

    # -- Excel ---------------------------------------------------------------
    @property
    def excel_marker(self) -> str:
        return {"circle": "circle", "square": "square", "triangle_up": "triangle",
                "triangle_down": "triangle", "diamond": "diamond", "hexagon": "diamond",
                "star": "star", "cross": "x", "plus": "plus"}.get(self.symbol, "circle")

    @property
    def excel_dash(self) -> str:
        return {"solid": "solid", "dash": "dash", "dot": "round_dot",
                "dashdot": "dash_dot", "longdash": "long_dash"}.get(self.line_style, "solid")


# ---------------------------------------------------------------------------
# themes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Theme:
    name: str
    background: str
    panel: str
    foreground: str
    muted: str
    grid: str
    accent: str
    palette: str = DEFAULT_PALETTE


THEMES: dict[str, Theme] = {
    "light": Theme("light", "#FFFFFF", "#F6F7F9", "#1B1F24", "#6A7280", "#DDE1E6", "#0072B2",
                   "publication"),
    "dark": Theme("dark", "#15181D", "#1E2228", "#E8EAED", "#9AA1AB", "#2C313A", "#3987E5",
                  "vivid"),
}

FIGURE_SIZES: dict[str, tuple[float, float]] = {
    "single_column": (3.35, 2.6),       # 85 mm, the usual single-column width
    "double_column": (6.9, 4.2),        # 175 mm
    "square": (4.2, 4.2),
    "presentation": (8.0, 4.5),
    "screen": (7.2, 4.6),
}

EXPORT_DPI: dict[str, int] = {"screen": 110, "print": 300, "poster": 600}


# ---------------------------------------------------------------------------
# assignment
# ---------------------------------------------------------------------------
def palette(name: str | None = None) -> list[str]:
    return PALETTES.get(name or DEFAULT_PALETTE, PALETTES[DEFAULT_PALETTE])


def style_for(slot: int, role: str = "data", *, palette_name: str | None = None,
              label: str = "", theme: str = "light", style_hint: str = "scatter",
              colour: str | None = None) -> SeriesStyle:
    """The style for the series in palette `slot`.

    `role` is what the series is for: measured data, a fitted line, a guide or a
    reference marker. A fit is drawn dashed in its slot's colour, so passing the slot of
    the data it fits is what makes a figure with several fits readable.
    """
    colours = palette(palette_name)
    c = colour or colours[slot % len(colours)]
    symbol = SYMBOLS[slot % len(SYMBOLS)]
    filled = (slot // len(SYMBOLS)) % 2 == 0

    if role == "fit":
        return SeriesStyle(c, "none", "dash", 1.6, 0.0, False, label)
    if role in ("guide", "reference"):
        return SeriesStyle(colour or GUIDE_COLOUR.get(theme, GUIDE_COLOUR["light"]),
                           "none", "dot", 1.2, 0.0, False, label)
    if style_hint == "line":
        return SeriesStyle(c, "none", "solid", 1.9, 0.0, True, label)
    if style_hint == "scatter+line":
        return SeriesStyle(c, symbol, "solid", 1.4, 5.4, filled, label)
    return SeriesStyle(c, symbol, "none", 0.0, 6.0, filled, label)


def matplotlib_rc(theme: str = "light", size: str = "screen") -> dict:
    """rcParams for a figure that already looks like a journal figure."""
    t = THEMES.get(theme, THEMES["light"])
    from cycler import cycler

    return {
        "figure.figsize": FIGURE_SIZES.get(size, FIGURE_SIZES["screen"]),
        "figure.facecolor": t.background, "figure.dpi": 110,
        "savefig.facecolor": t.background, "savefig.bbox": "tight", "savefig.pad_inches": 0.06,
        "axes.facecolor": t.background, "axes.edgecolor": t.foreground,
        "axes.labelcolor": t.foreground, "axes.titlecolor": t.foreground,
        "axes.linewidth": 1.0, "axes.grid": True, "axes.axisbelow": True,
        "axes.titlesize": 11, "axes.titleweight": "semibold", "axes.titlepad": 9,
        "axes.labelsize": 10, "axes.labelpad": 5,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.prop_cycle": cycler(color=palette(t.palette)),
        "grid.color": t.grid, "grid.linewidth": 0.7, "grid.alpha": 0.9,
        "xtick.color": t.foreground, "ytick.color": t.foreground,
        "xtick.labelsize": 9, "ytick.labelsize": 9,
        "xtick.direction": "out", "ytick.direction": "out",
        "xtick.minor.visible": True, "ytick.minor.visible": True,
        "legend.frameon": True, "legend.framealpha": 0.92, "legend.facecolor": t.background,
        "legend.edgecolor": t.grid, "legend.fontsize": 9, "legend.labelcolor": t.foreground,
        "text.color": t.foreground, "font.size": 10, "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "Arial", "Helvetica", "DejaVu Sans"],
        "mathtext.fontset": "dejavusans", "lines.solid_capstyle": "round",
    }
