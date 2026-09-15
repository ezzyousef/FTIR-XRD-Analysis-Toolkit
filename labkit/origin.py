"""Send FigureSpecs to OriginLab, styled the way a journal wants them.

Three entry points, all rendering the same `FigureSpec` with the same styles as the
on-screen matplotlib figure:

`OriginSession`
    A live session that accumulates: every `send()` adds a workbook and its graphs to the
    same running Origin, so a whole working session builds one project. Save and close
    when finished. Keep all calls on one thread (see `OriginSession`).

`export_to_origin()`
    One call: start Origin, build everything, save a .opju and PNGs, close Origin. Falls
    back to the script package when Origin is not installed.

`write_labtalk_package()`
    No Origin needed. Origin-ready CSVs plus a LabTalk script that rebuilds the identical
    project on a machine that has Origin.

Everything below was verified against a live Origin 2026b installation, and several of
the rules are not what originpro's documentation says. Each is noted where it applies.
"""
from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from . import style as S
from .figure import FigureSpec, free_corners, resolve_styles

__all__ = [
    "OriginBook", "OriginResult", "OriginNotAvailable", "OriginSession", "origin_available",
    "export_to_origin", "write_labtalk_package",
]

MAX_LONG_NAME = 60


class OriginNotAvailable(RuntimeError):
    """originpro is not installed, or Origin itself cannot be reached."""


@dataclass
class OriginBook:
    """One workbook for Origin: its graphs, plus optional extra columns and results."""
    name: str
    figures: list[FigureSpec] = field(default_factory=list)
    table: dict[str, Sequence[Any]] | None = None       # extra columns, e.g. raw data
    results: list[tuple[str, Any, str]] | None = None   # (quantity, value, unit)
    note: str = ""

    @property
    def safe_id(self) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "_", self.name).strip("_")[:40] or "book"


@dataclass
class OriginResult:
    mode: str                                   # live | script
    folder: Path | None = None
    project: Path | None = None
    images: list[Path] = field(default_factory=list)
    books: int = 0
    graphs: int = 0
    messages: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.mode == "live":
            text = f"{self.books} workbook(s) and {self.graphs} graph(s) in Origin"
            if self.project:
                text += f", saved to {self.project.name}"
            if self.images:
                text += f", {len(self.images)} image(s) exported"
            return text
        return (f"Origin script package written to {self.folder} ({self.books} workbook(s), "
                f"{self.graphs} graph(s)) — open AeroLab_build.ogs in Origin")


# ---------------------------------------------------------------------------
# availability
# ---------------------------------------------------------------------------
def origin_available() -> tuple[bool, str]:
    """(usable, reason). Checks the Python package and the COM registration, without
    launching Origin — starting it takes ten seconds and is not a question to ask lightly."""
    try:
        import originpro                                    # noqa: F401
    except ImportError:
        return False, "The 'originpro' package is not installed (pip install originpro pywin32)."
    try:
        import win32com.client                              # noqa: F401
    except ImportError:
        return False, "pywin32 is not installed, so Origin's automation server cannot be reached."
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Origin.ApplicationSI"))
    except OSError:
        return False, "OriginLab is not installed, or its automation server is not registered."
    return True, "OriginLab automation is available."


# ---------------------------------------------------------------------------
# column layout — shared by the live path and the script package
# ---------------------------------------------------------------------------
@dataclass
class _Column:
    long_name: str
    units: str
    comment: str
    values: np.ndarray
    kind: str                                   # x | y | yerr | n


def _book_columns(book: OriginBook) -> tuple[list[_Column], list[list[tuple[int, int, int | None]]]]:
    """Columns for a book, and for each figure the (x, y, yerr) column indices of its traces.

    Every trace gets its own X and Y column. Sharing one X across traces saves a few
    columns but breaks the moment two traces have different lengths — a fit sampled on a
    fine grid against measured points — so it is not worth the fragility.
    The Comments row carries the trace label, because Origin's default legend is built
    from the Comments of each Y column.
    """
    columns: list[_Column] = []
    plots: list[list[tuple[int, int, int | None]]] = []
    for spec in book.figures:
        refs = []
        for s in spec.drawable:
            xi = len(columns)
            columns.append(_Column(spec.x_label, spec.x_unit, s.label, s.x, "x"))
            yi = len(columns)
            columns.append(_Column(spec.y_label, spec.y_unit, s.label, s.y, "y"))
            ei = None
            if s.y_err is not None:
                ei = len(columns)
                columns.append(_Column(f"{spec.y_label} error", spec.y_unit, s.label, s.y_err, "yerr"))
            refs.append((xi, yi, ei))
        plots.append(refs)
    if book.table:
        from .units import split_label
        for name, values in book.table.items():
            arr = np.asarray(list(values), dtype=object)
            label, unit = split_label(name)
            columns.append(_Column(label, unit, str(name), arr, "n"))
    return columns, plots


def _clean(value: Any) -> Any:
    """What a worksheet cell should hold: finite floats, strings, or blank."""
    if value is None:
        return ""
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else ""
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    return value if isinstance(value, str) else str(value)


# ---------------------------------------------------------------------------
# live automation
# ---------------------------------------------------------------------------
class OriginSession:
    """A live Origin session that accumulates workbooks and graphs across sends.

    COM is apartment-threaded: the originpro objects created on one thread must be used on
    that thread. The session records the thread that started it and refuses calls from any
    other, turning an obscure COM failure into a clear message. In a Qt application run
    every call on one long-lived worker (see `labkit.qt.origin_worker`).
    """

    def __init__(self, visible: bool = True) -> None:
        self.visible = visible
        self._op: Any = None
        self._thread_id: int | None = None
        self.books_sent = 0
        self.graphs_sent = 0
        self.workbooks: list[Any] = []                      # originpro WBook per send()

    # -- lifecycle -----------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self._op is not None

    def start(self) -> None:
        if self._op is not None:
            self._check_thread()
            return
        ok, why = origin_available()
        if not ok:
            raise OriginNotAvailable(why)
        try:
            import originpro as op
            op.set_show(self.visible)
        except Exception as exc:                            # noqa: BLE001
            raise OriginNotAvailable(f"Could not start or connect to Origin: {exc}") from exc
        self._op = op
        self._thread_id = threading.get_ident()

    def _check_thread(self) -> None:
        if self._thread_id is not None and threading.get_ident() != self._thread_id:
            raise RuntimeError("This Origin session belongs to another thread. COM objects "
                               "cannot cross threads; run every Origin call on one worker.")

    def save(self, path: str | Path) -> Path:
        self._require()
        p = Path(path)
        if p.suffix.lower() not in (".opju", ".opj"):
            p = p.with_suffix(".opju")
        p.parent.mkdir(parents=True, exist_ok=True)
        result = self._op.save(str(p))
        if result is False:
            raise RuntimeError(f"Origin did not confirm the save to {p}")
        return p

    def close(self, save_to: str | Path | None = None) -> None:
        """Close Origin. Safe to call when nothing is open."""
        if self._op is None:
            return
        self._check_thread()
        try:
            if save_to:
                try:
                    self.save(save_to)
                except Exception:                           # noqa: BLE001 - still close
                    pass
            self._op.exit()
        finally:
            # A half-closed COM handle must never be reused by a later send.
            self._op = None
            self._thread_id = None
            self.workbooks = []

    def _require(self) -> None:
        if self._op is None:
            raise RuntimeError("No Origin session is open — send something first.")
        self._check_thread()

    # -- building ------------------------------------------------------------
    def send(self, book: OriginBook, *, theme: str = "light",
             palette_name: str | None = None) -> list[Any]:
        """Add one workbook and its graphs. Returns the originpro graph pages."""
        self.start()
        self._check_thread()
        op = self._op
        columns, plots = _book_columns(book)
        if not columns and not book.results:
            raise ValueError(f"{book.name}: nothing to send")

        wb = op.new_book("w", lname=book.name[:MAX_LONG_NAME])
        wks = wb[0]
        for i, col in enumerate(columns):
            wks.from_list(i, [_clean(v) for v in col.values])
        if columns:
            wks.set_labels([c.long_name for c in columns], "L")
            wks.set_labels([c.units for c in columns], "U")
            wks.set_labels([c.comment for c in columns], "C")
            wks.cols_axis("".join({"x": "x", "y": "y", "yerr": "e", "n": "n"}[c.kind] for c in columns))
        if book.results:
            self._write_results(wb, book.results)
        if book.note:
            try:
                wb.comments = book.note
            except Exception:                               # noqa: BLE001 - cosmetic
                pass

        pages = []
        for spec, refs in zip(book.figures, plots):
            if refs:
                pages.append(self._graph(spec, refs, wks, theme, palette_name))
        self.workbooks.append(wb)
        self.books_sent += 1
        self.graphs_sent += len(pages)
        return pages

    def _write_results(self, wb, results) -> None:
        try:
            sheet = wb.add_sheet("Results")
        except Exception:                                   # noqa: BLE001 - older originpro
            sheet = self._op.new_sheet("w", lname="Results")
        sheet.from_list(0, [str(r[0]) for r in results])
        sheet.from_list(1, [_clean(r[1]) for r in results])
        sheet.from_list(2, [str(r[2]) if len(r) > 2 and r[2] else "" for r in results])
        sheet.set_labels(["Quantity", "Value", "Unit"], "L")
        sheet.cols_axis("nyn")
        try:
            sheet.lname = "Results"                         # add_sheet() leaves it blank
        except Exception:                                   # noqa: BLE001 - cosmetic
            pass

    def _graph(self, spec: FigureSpec, refs, wks, theme, palette_name):
        op = self._op
        page = op.new_graph(lname=(spec.title or spec.name or "Graph")[:MAX_LONG_NAME],
                            template="scatter")
        layer = page[0]
        for (xi, yi, ei), st in zip(refs, resolve_styles(spec, theme=theme, palette_name=palette_name)):
            if ei is not None:
                dp = layer.add_plot(wks, coly=yi, colx=xi, colyerr=ei, type=st.origin_plot_type)
            else:
                dp = layer.add_plot(wks, coly=yi, colx=xi, type=st.origin_plot_type)
            if dp is not None:
                _style_data_plot(dp, st)
                if ei is not None:
                    _style_error_bars(layer, dp, st)

        layer.axis("x").title = spec.x_axis
        layer.axis("y").title = spec.y_axis
        if spec.effective_scale("x") == "log":
            layer.axis("x").scale = "log10"
        if spec.effective_scale("y") == "log":
            layer.axis("y").scale = "log10"
        layer.rescale()
        _reverse_axes(layer, spec)
        try:
            # Plain legendupdate builds entries from each Y column's Comments. Passing
            # mode:=/update:= switches to a text form that prints raw column ranges.
            layer.lt_exec("legendupdate;")
        except Exception:                                   # noqa: BLE001 - cosmetic
            pass
        if len(spec.drawable) > 1:
            try:
                page.activate()                             # legend.* resolves in the active graph
                op.lt_exec(legend_placement_labtalk(free_corners(spec)[0]))
            except Exception:                               # noqa: BLE001 - cosmetic
                pass
        return page

    def export_images(self, pages: Sequence[Any], folder: str | Path, *, fmt: str = "png",
                      width: int = 1800, names: Sequence[str] | None = None) -> list[Path]:
        self._require()
        out: list[Path] = []
        target = Path(folder)
        target.mkdir(parents=True, exist_ok=True)
        for i, page in enumerate(pages):
            stem = names[i] if names and i < len(names) else f"graph_{i + 1}"
            dest = target / f"{re.sub(r'[^A-Za-z0-9_-]+', '_', stem)[:60]}.{fmt}"
            try:
                page.save_fig(str(dest), type=fmt, replace=True, width=width)
            except Exception:                               # noqa: BLE001 - reported by count
                continue
            if dest.exists():
                out.append(dest)
        return out


def legend_placement_labtalk(corner: str, margin: float = 0.03) -> str:
    """LabTalk that moves the active graph's legend into `corner`, clear of the data.

    Origin puts the legend top-right, over whatever data is there. The same script runs
    in both paths, so a live export and the script package place it identically.

    Verified against Origin 2026b: `legend.x/y` is the legend's centre in data units, and
    `legend.dx/dy` its size in data units *at its current position* — on a log axis dx
    changes as the legend moves, but its width in log space does not. The placement is
    therefore computed in normalised axis coordinates, measured from the axis `from`
    (left/bottom on screen) to `to`, which also keeps it right on a reversed axis.
    """
    left = "left" in corner
    lower = "lower" in corner
    cx = f"({margin} + abs(__lw)/2)" if left else f"(1 - {margin} - abs(__lw)/2)"
    cy = f"({margin} + abs(__lh)/2)" if lower else f"(1 - {margin} - abs(__lh)/2)"
    return (
        "double __lx = legend.x; double __ldx = legend.dx; double __ly = legend.y; double __ldy = legend.dy; "
        "double __a1 = layer.x.from; double __a2 = layer.x.to; double __b1 = layer.y.from; double __b2 = layer.y.to; "
        "double __lw; double __lh; "
        "if (layer.x.type == 2) {__lw = (log(__lx + __ldx/2) - log(__lx - __ldx/2)) / (log(__a2) - log(__a1));} "
        "else {__lw = __ldx / (__a2 - __a1);} "
        "if (layer.y.type == 2) {__lh = (log(__ly + __ldy/2) - log(__ly - __ldy/2)) / (log(__b2) - log(__b1));} "
        "else {__lh = __ldy / (__b2 - __b1);} "
        f"double __cx = {cx}; double __cy = {cy}; "
        "if (layer.x.type == 2) {legend.x = 10^(log(__a1) + __cx * (log(__a2) - log(__a1)));} "
        "else {legend.x = __a1 + __cx * (__a2 - __a1);} "
        "if (layer.y.type == 2) {legend.y = 10^(log(__b1) + __cy * (log(__b2) - log(__b1)));} "
        "else {legend.y = __b1 + __cy * (__b2 - __b1);}"
    )


def _style_data_plot(dp, st: S.SeriesStyle) -> None:
    """Apply one style to a data plot.

    Symbol shape, size and interior go through originpro's properties, which set
    `plotN.symbol.*` directly and were verified to take effect. Colours go through
    `set_cmd`, which targets this plot by its own range — `set %C` in a script only ever
    reaches the first plot of a layer.
    """
    try:
        dp.color = st.colour
    except Exception:                                       # noqa: BLE001
        pass
    try:
        if st.has_symbol:
            dp.symbol_kind = st.origin_symbol
            dp.symbol_size = float(st.symbol_size)
            dp.symbol_interior = st.origin_symbol_interior
    except Exception:                                       # noqa: BLE001
        pass
    try:
        dp.set_cmd(*st.labtalk_set_options())
    except Exception:                                       # noqa: BLE001 - styling is best effort
        pass


def _style_error_bars(layer, dp, st: S.SeriesStyle) -> None:
    """Colour the error bars of `dp` to match it.

    Verified: error bars are a separate data plot placed directly after their parent
    (index + 1), drawn in Origin's default black until styled.
    """
    try:
        plots = layer.plot_list()
        bars = plots[dp.index() + 1]
        bars.set_cmd(*error_bar_options(st))
    except Exception:                                       # noqa: BLE001 - cosmetic
        pass


def error_bar_options(st: S.SeriesStyle) -> list[str]:
    return [f"-c {S.labtalk_colour(st.colour)}", f"-w {int(round(0.9 * S.LABTALK_LINE_WIDTH_UNITS))}"]


def _reverse_axes(layer, spec: FigureSpec) -> None:
    """Run an axis high-to-low (FTIR wavenumber) by swapping its limits after rescale."""
    for axis, wanted in (("x", spec.invert_x), ("y", spec.invert_y)):
        if not wanted:
            continue
        try:
            lo, hi = layer.axis(axis).limits[:2]
            if lo < hi:
                layer.axis(axis).set_limits(hi, lo)
        except Exception:                                   # noqa: BLE001
            try:
                layer.lt_exec(f"layer.{axis}.reverse = 1;")
            except Exception:                               # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# one call
# ---------------------------------------------------------------------------
def export_to_origin(books: Sequence[OriginBook], destination: str | Path, *,
                     project_name: str = "Project", theme: str = "light",
                     palette_name: str | None = None, save_images: bool = True,
                     visible: bool = False, keep_open: bool = False,
                     force_script: bool = False) -> OriginResult:
    """Build every book in Origin and save a project, or write the script package.

    Starting Origin takes ten to twenty seconds, so call this off the UI thread.
    """
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    if not books:
        return OriginResult(mode="script", folder=dest, messages=["Nothing to export."])

    ok, why = origin_available()
    if force_script or not ok:
        result = write_labtalk_package(books, dest, project_name=project_name, theme=theme,
                                       palette_name=palette_name)
        if not ok:
            result.messages.insert(0, why)
        return result

    session = OriginSession(visible=visible)
    try:
        pages, names = [], []
        for book in books:
            new = session.send(book, theme=theme, palette_name=palette_name)
            pages += new
            names += [f"{book.safe_id}_{spec.slug()}" for spec in book.figures if spec.drawable][:len(new)]
        project = session.save(dest / f"{_file_stem(project_name)}.opju")
        images = session.export_images(pages, dest / "figures", names=names) if save_images else []
        return OriginResult(mode="live", folder=dest, project=project, images=images,
                            books=session.books_sent, graphs=session.graphs_sent)
    finally:
        if not keep_open:
            session.close()


def _file_stem(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_") or "Project"


# ---------------------------------------------------------------------------
# script package
# ---------------------------------------------------------------------------
SCRIPT_NAME = "AeroLab_build.ogs"


def write_labtalk_package(books: Sequence[OriginBook], folder: str | Path, *,
                          project_name: str = "Project", theme: str = "light",
                          palette_name: str | None = None) -> OriginResult:
    """Origin-ready CSVs plus a LabTalk script that rebuilds the same project.

    The generated script follows rules found by running it inside Origin:
    - no [Main] section, or Origin will not execute the file when it is opened
    - a bare `impasc`; explicit options.names.* make the import return zero rows
    - the book short name is read after import, because the import renames the book
    - `page.longname$` is reset, because the import sets it to the file path
    - each plot is styled through its own `[Graph]1!n` range; `set %C` reaches only the first
    """
    out = Path(folder)
    data_dir = out / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "// ---------------------------------------------------------------",
        f"// {project_name} — Origin project rebuilt from exported data",
        "//",
        "// In Origin:  File > Open, choose this file (file type: LabTalk Script *.ogs)",
        '//        or:  run.file("<full path to this file>");   in the Script Window',
        "// ---------------------------------------------------------------",
        "string gpath$ = %X;",
        'if (gpath$ == "") { type "Set gpath$ to the folder of this script, then run it again."; }',
        "",
    ]
    graphs = 0
    for bi, book in enumerate(books):
        columns, plots = _book_columns(book)
        if not columns:
            continue
        csv_name = f"{bi + 1:02d}_{book.safe_id}.csv"
        _write_origin_csv(columns, data_dir / csv_name)
        bvar = f"bk{bi + 1}"
        lines += [
            f"// ---- {book.name}",
            f'newbook name:="{_lt(book.name[:MAX_LONG_NAME])}" sheet:=1 option:=lsname;',
            f'impasc fname:="%(gpath$)data\\{csv_name}";',
            f"string {bvar}$ = %H;",
            f'page.longname$ = "{_lt(book.name[:MAX_LONG_NAME])}";',
        ]
        for ci, col in enumerate(columns, start=1):
            lines.append(f"wks.col{ci}.type = {_LT_COL_TYPE[col.kind]};")

        for gi, (spec, refs) in enumerate(zip(book.figures, plots)):
            if not refs:
                continue
            gvar = f"gr{bi + 1}_{gi + 1}"
            lines += ["win -t plot;", f"string {gvar}$ = %H;"]
            styles = resolve_styles(spec, theme=theme, palette_name=palette_name)
            pi = 0          # layer plot index; an error bar is its own plot after its parent
            for (xi, yi, ei), st in zip(refs, styles):
                err = f",{ei + 1}" if ei is not None else ""
                lines.append(f"plotxy iy:=[%({bvar}$)]1!({xi + 1},{yi + 1}{err}) "
                             f"plot:={st.labtalk_plot_type} ogl:=<active>;")
                pi += 1
                lines.append(f"range rr{pi} = [%({gvar}$)]1!{pi};")
                lines += [f"set rr{pi} {opt};" for opt in st.labtalk_set_options()]
                if ei is not None:
                    pi += 1
                    lines.append(f"range rr{pi} = [%({gvar}$)]1!{pi};")
                    lines += [f"set rr{pi} {opt};" for opt in error_bar_options(st)]
            lines.append(f'win -r %H "{_ascii_name(f"{book.safe_id}_{spec.slug()}", 30)}";')
            lines.append(f'label -xb "{_lt(spec.x_axis)}";')
            lines.append(f'label -yl "{_lt(spec.y_axis)}";')
            if spec.effective_scale("x") == "log":
                lines.append("layer.x.type = 2;")
            if spec.effective_scale("y") == "log":
                lines.append("layer.y.type = 2;")
            lines.append("rescale;")
            if spec.invert_x:
                lines.append("double xa = layer.x.from; layer.x.from = layer.x.to; layer.x.to = xa;")
            if spec.invert_y:
                lines.append("double ya = layer.y.from; layer.y.from = layer.y.to; layer.y.to = ya;")
            lines.append("legendupdate;")
            if len(spec.drawable) > 1:
                lines.append(legend_placement_labtalk(free_corners(spec)[0]))
            lines.append("")
            graphs += 1

    stem = _file_stem(project_name)
    lines += [f'save -i "%(gpath$){stem}.opju";',
              f'type "{_lt(project_name)}: {len(books)} workbook(s), {graphs} graph(s) built.";', ""]
    script = out / SCRIPT_NAME
    script.write_text("\n".join(lines), encoding="utf-8")
    _write_readme(out, books, project_name, stem)
    return OriginResult(mode="script", folder=out, books=len(books), graphs=graphs,
                        messages=[f"Open {SCRIPT_NAME} in Origin to rebuild the project."])


# LabTalk wks.col.type: 1 Y, 2 disregard, 3 Y error, 4 X, 5 label, 6 Z, 7 X error
_LT_COL_TYPE = {"x": 4, "y": 1, "yerr": 3, "n": 2}


def _write_origin_csv(columns: list[_Column], path: Path) -> None:
    """Origin's own import layout: Long Name, Units, Comments, then the values."""
    height = max((c.values.size for c in columns), default=0)
    rows = [",".join(_csv(c.long_name) for c in columns),
            ",".join(_csv(c.units) for c in columns),
            ",".join(_csv(c.comment) for c in columns)]
    for r in range(height):
        cells = []
        for c in columns:
            if r >= c.values.size:
                cells.append("")
                continue
            v = _clean(c.values[r])
            cells.append(f"{v:.10g}" if isinstance(v, float) else _csv(str(v)))
        rows.append(",".join(cells))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_readme(folder: Path, books, project_name: str, stem: str) -> None:
    lines = [
        f"{project_name} — Origin export package", "=" * 48, "",
        "Everything needed to rebuild this project in OriginLab is in this folder.", "",
        "To rebuild:",
        "  1. Copy this whole folder to a machine with OriginLab.",
        f"  2. In Origin: File > Open, set the type to LabTalk Script (*.ogs), choose {SCRIPT_NAME}.",
        f"  3. Origin builds every workbook and graph and saves {stem}.opju next to the script.",
        "",
        "The CSVs in .\\data are Origin-ready on their own: row 1 is the Long Name, row 2 the",
        "Units and row 3 the Comments, so File > Import > Single ASCII also works by hand.",
        "", "Workbooks:",
    ]
    lines += [f"  - {b.name} ({len([f for f in b.figures if f.drawable])} graph(s))" for b in books]
    (folder / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _lt(text: str) -> str:
    """Text safe inside a LabTalk string literal.

    Verified in Origin: a lone % stays literal and %% is NOT an escape (it renders as two
    percent signs). Only % followed by a letter or "(" substitutes, so only those are defused.
    """
    text = str(text).replace('"', "'").replace("\n", " ")
    return re.sub(r"%(?=[A-Za-z(])", "%\u2009", text)


def _ascii_name(text: str, limit: int) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(text)).strip("_")[:limit] or "Graph"


def _csv(text: str) -> str:
    text = str(text or "")
    return f'"{text.replace(chr(34), chr(34) * 2)}"' if any(c in text for c in ',"\n') else text
