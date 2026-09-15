"""One formatted Excel workbook for a whole session — meant to be handed on as-is.

    Summary      every result of every analysis, one row each, filterable
    <analysis>   its results, the settings used, then its curves as columns
    Charts       native Excel charts built from the same FigureSpecs (real, editable charts)
    <extras>     any extra tables an application adds (validation, calculations, …)
    Provenance   application, versions, sources and settings — enough to retrace a number

Written with xlsxwriter, the only writer that creates native charts.
"""
from __future__ import annotations

import math
import platform
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from . import style as S
from .figure import FigureSpec, resolve_styles

__all__ = ["ExcelAnalysis", "ExcelTable", "ExcelReport", "write_workbook"]

MAX_CHART_POINTS = 4000             # beyond this Excel charts crawl; the columns keep every point
SHEET_NAME_LIMIT = 31
_INVALID_SHEET = re.compile(r"[\[\]:*?/\\]")


@dataclass
class ExcelAnalysis:
    """One analysed dataset."""
    title: str
    results: list[tuple] = field(default_factory=list)      # (quantity, value, unit[, note])
    figures: list[FigureSpec] = field(default_factory=list)
    table: dict[str, Sequence[Any]] | None = None             # extra raw columns
    settings: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    group: str = ""                                            # e.g. the measurement type


@dataclass
class ExcelTable:
    """A plain table sheet an application wants to include."""
    name: str
    headers: list[str]
    rows: list[Sequence[Any]]
    subtitle: str = ""


@dataclass
class ExcelReport:
    app_name: str
    app_version: str = ""
    project: str = "Session"
    author: str = ""
    analyses: list[ExcelAnalysis] = field(default_factory=list)
    tables: list[ExcelTable] = field(default_factory=list)
    include_curves: bool = True
    include_charts: bool = True
    theme: str = "light"
    extra_provenance: dict[str, str] = field(default_factory=dict)


def write_workbook(report: ExcelReport, path: str | Path) -> Path:
    import xlsxwriter

    p = Path(path)
    if p.suffix.lower() != ".xlsx":
        p = p.with_suffix(".xlsx")
    p.parent.mkdir(parents=True, exist_ok=True)
    book = xlsxwriter.Workbook(str(p), {"nan_inf_to_errors": True})
    try:
        fmt = _formats(book, report.theme)
        used: set[str] = {"summary", "charts", "provenance"}
        _summary_sheet(book, fmt, report)
        chart_jobs = []
        for analysis in report.analyses:
            name = _unique_sheet_name(analysis.title, used)
            layout = _analysis_sheet(book, fmt, analysis, name, report.include_curves)
            chart_jobs.append((name, analysis, layout))
        for table in report.tables:
            _table_sheet(book, fmt, table, _unique_sheet_name(table.name, used))
        if report.include_charts and report.include_curves:
            _charts_sheet(book, fmt, report, chart_jobs)
        _provenance_sheet(book, fmt, report)
    finally:
        book.close()
    return p


# ---------------------------------------------------------------------------
def _formats(book, theme: str) -> dict:
    accent = S.THEMES.get(theme, S.THEMES["light"]).accent
    base = {"font_name": "Calibri", "font_size": 11}
    border = {"border": 1, "border_color": "#E3E6EA"}
    alt = {"bg_color": "#F6F7F9"}
    return {
        "title": book.add_format({**base, "font_size": 16, "bold": True, "font_color": "#1B1F24"}),
        "subtitle": book.add_format({**base, "font_size": 10, "italic": True, "font_color": "#6A7280"}),
        "h2": book.add_format({**base, "font_size": 12, "bold": True, "font_color": accent,
                               "bottom": 1, "border_color": "#C9CED6"}),
        "header": book.add_format({**base, "bold": True, "font_color": "#FFFFFF", "bg_color": accent,
                                   "valign": "vcenter", "text_wrap": True, "border": 1,
                                   "border_color": "#FFFFFF"}),
        "cell": book.add_format({**base, **border}),
        "cell_alt": book.add_format({**base, **border, **alt}),
        "num": book.add_format({**base, **border, "num_format": "0.0000"}),
        "num_alt": book.add_format({**base, **border, **alt, "num_format": "0.0000"}),
        "sci": book.add_format({**base, **border, "num_format": "0.000E+00"}),
        "sci_alt": book.add_format({**base, **border, **alt, "num_format": "0.000E+00"}),
        "data": book.add_format({**base, "num_format": "General"}),
        "bold": book.add_format({**base, "bold": True}),
        "muted": book.add_format({**base, "font_color": "#6A7280"}),
        "wrap": book.add_format({**base, "text_wrap": True, "valign": "top"}),
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool)


def _value_format(fmt: dict, value: Any, alt: bool):
    if not _is_number(value) or not math.isfinite(float(value)):
        return fmt["cell_alt" if alt else "cell"]
    v = abs(float(value))
    if v != 0 and (v >= 1e6 or v < 1e-3):
        return fmt["sci_alt" if alt else "sci"]
    if float(value).is_integer() and v < 1e6:
        return fmt["cell_alt" if alt else "cell"]
    return fmt["num_alt" if alt else "num"]


def _cell(value: Any) -> Any:
    if value is None:
        return ""
    if _is_number(value):
        f = float(value)
        return f if math.isfinite(f) else "n/a"
    return str(value)


def _result_row(r: Sequence) -> tuple[str, Any, str, str]:
    quantity = str(r[0]) if len(r) > 0 else ""
    value = r[1] if len(r) > 1 else ""
    unit = str(r[2]) if len(r) > 2 and r[2] not in (None, "-") else ""
    note = str(r[3]) if len(r) > 3 and r[3] else ""
    return quantity, value, unit, note


# ---------------------------------------------------------------------------
def _summary_sheet(book, fmt, report: ExcelReport) -> None:
    ws = book.add_worksheet("Summary")
    ws.hide_gridlines(2)
    for col, width in zip("ABCDEF", (28, 24, 36, 16, 14, 48)):
        ws.set_column(f"{col}:{col}", width)
    ws.write(0, 0, report.project, fmt["title"])
    who = f"  ·  {report.author}" if report.author else ""
    ws.write(1, 0, f"{report.app_name} {report.app_version}  ·  exported "
                   f"{datetime.now():%Y-%m-%d %H:%M}{who}".replace("  ", " "), fmt["subtitle"])
    ws.write(2, 0, f"{len(report.analyses)} analysis/analyses", fmt["subtitle"])
    headers = ["Analysis", "Type", "Quantity", "Value", "Unit", "Note"]
    for c, h in enumerate(headers):
        ws.write(4, c, h, fmt["header"])
    ws.autofilter(4, 0, 4, len(headers) - 1)
    ws.freeze_panes(5, 0)
    row = 5
    for i, analysis in enumerate(report.analyses):
        alt = i % 2 == 1
        cell = fmt["cell_alt" if alt else "cell"]
        for r in analysis.results:
            q, v, u, n = _result_row(r)
            ws.write(row, 0, analysis.title, cell)
            ws.write(row, 1, analysis.group, cell)
            ws.write(row, 2, q, cell)
            ws.write(row, 3, _cell(v), _value_format(fmt, v, alt))
            ws.write(row, 4, u, cell)
            ws.write(row, 5, n, cell)
            row += 1
    if row == 5:
        ws.write(5, 0, "No results in this session.", fmt["muted"])


def _analysis_sheet(book, fmt, analysis: ExcelAnalysis, name: str, include_curves: bool):
    """Write one analysis. Returns, per figure, [(x_col, y_col, first_row, n)] for charts."""
    ws = book.add_worksheet(name)
    ws.hide_gridlines(2)
    ws.set_column("A:A", 34)
    ws.set_column("B:C", 15)
    ws.set_column("D:D", 44)
    ws.write(0, 0, analysis.title, fmt["title"])
    subtitle = analysis.group
    if analysis.source:
        subtitle = f"{subtitle}  ·  source: {Path(analysis.source).name}".strip(" ·")
    if subtitle:
        ws.write(1, 0, subtitle, fmt["subtitle"])

    row = 3
    if analysis.results:
        ws.write(row, 0, "Results", fmt["h2"])
        row += 1
        for c, h in enumerate(["Quantity", "Value", "Unit", "Note"]):
            ws.write(row, c, h, fmt["header"])
        row += 1
        for i, r in enumerate(analysis.results):
            alt = i % 2 == 1
            cell = fmt["cell_alt" if alt else "cell"]
            q, v, u, n = _result_row(r)
            ws.write(row, 0, q, cell)
            ws.write(row, 1, _cell(v), _value_format(fmt, v, alt))
            ws.write(row, 2, u or "-", cell)
            ws.write(row, 3, n, cell)
            row += 1
    if analysis.settings:
        row += 1
        ws.write(row, 0, "Settings used", fmt["h2"])
        row += 1
        for key, value in analysis.settings.items():
            ws.write(row, 0, str(key), fmt["cell"])
            ws.write(row, 1, str(value), fmt["cell"])
            row += 1

    layouts: list[list[tuple[int, int, int, int]]] = []
    if not include_curves:
        return layouts
    col = 5
    header_row = 3
    first_data = header_row + 1
    for spec in analysis.figures:
        refs = []
        for s in spec.drawable:
            n = int(s.x.size)
            ws.set_column(col, col + 1, 14)
            ws.write(header_row - 1, col, spec.title[:40], fmt["muted"])
            ws.write(header_row, col, f"{s.label} · {spec.x_axis}", fmt["header"])
            ws.write(header_row, col + 1, f"{s.label} · {spec.y_axis}", fmt["header"])
            ws.write_column(first_data, col, [_cell(v) for v in s.x], fmt["data"])
            ws.write_column(first_data, col + 1, [_cell(v) for v in s.y], fmt["data"])
            refs.append((col, col + 1, first_data, n))
            col += 2
        layouts.append(refs)
        col += 1                                            # a gap between figures
    if analysis.table:
        for key, values in analysis.table.items():
            vals = list(values)
            ws.set_column(col, col, 14)
            ws.write(header_row, col, str(key), fmt["header"])
            ws.write_column(first_data, col, [_cell(v) for v in vals], fmt["data"])
            col += 1
    ws.freeze_panes(first_data, 0)
    return layouts


def _table_sheet(book, fmt, table: ExcelTable, name: str) -> None:
    ws = book.add_worksheet(name)
    ws.hide_gridlines(2)
    ws.write(0, 0, table.name, fmt["title"])
    if table.subtitle:
        ws.write(1, 0, table.subtitle, fmt["subtitle"])
    for c, h in enumerate(table.headers):
        ws.write(3, c, h, fmt["header"])
        ws.set_column(c, c, max(12, min(48, len(str(h)) + 6)))
    for r, values in enumerate(table.rows):
        alt = r % 2 == 1
        for c, v in enumerate(values):
            ws.write(4 + r, c, _cell(v), _value_format(fmt, v, alt))
    if table.headers:
        ws.autofilter(3, 0, 3 + max(len(table.rows), 1), len(table.headers) - 1)
    ws.freeze_panes(4, 0)


def _charts_sheet(book, fmt, report: ExcelReport, jobs) -> None:
    ws = book.add_worksheet("Charts")
    ws.hide_gridlines(2)
    ws.write(0, 0, "Charts", fmt["title"])
    ws.write(1, 0, "Native Excel charts linked to the analysis sheets. The Origin export carries "
                   "the full publication styling.", fmt["subtitle"])
    anchor = 3
    for sheet_name, analysis, layouts in jobs:
        for spec, refs in zip(analysis.figures, layouts):
            chart = _chart(book, sheet_name, analysis, spec, refs, report.theme)
            if chart is None:
                continue
            ws.insert_chart(anchor, 0, chart, {"x_offset": 8, "y_offset": 8})
            anchor += 18
    if anchor == 3:
        ws.write(3, 0, "No curves to chart in this session.", fmt["muted"])


def _chart(book, sheet_name: str, analysis: ExcelAnalysis, spec: FigureSpec, refs, theme: str):
    if not refs:
        return None
    chart = book.add_chart({"type": "scatter", "subtype": "straight_with_markers"})
    for (xc, yc, first, n), st in zip(refs, resolve_styles(spec, theme=theme)):
        if n < 1:
            continue
        last = first + min(n, MAX_CHART_POINTS) - 1
        series: dict[str, Any] = {
            "name": st.label,
            "categories": [sheet_name, first, xc, last, xc],
            "values": [sheet_name, first, yc, last, yc],
            "line": ({"none": True} if not st.has_line else
                     {"color": st.colour, "width": max(st.line_width, 0.75), "dash_type": st.excel_dash}),
            "marker": ({"type": "none"} if not st.has_symbol else
                       {"type": st.excel_marker, "size": max(3, int(round(st.symbol_size))),
                        "border": {"color": st.colour},
                        "fill": {"color": st.colour} if st.filled else {"none": True}}),
        }
        chart.add_series(series)
    x_axis: dict[str, Any] = {"name": spec.x_axis, "major_gridlines": {"visible": False}}
    y_axis: dict[str, Any] = {"name": spec.y_axis,
                              "major_gridlines": {"visible": True, "line": {"color": "#E3E6EA"}}}
    if spec.effective_scale("x") == "log":
        x_axis["log_base"] = 10
    if spec.effective_scale("y") == "log":
        y_axis["log_base"] = 10
    if spec.invert_x:
        x_axis["reverse"] = True
    if spec.invert_y:
        y_axis["reverse"] = True
    chart.set_title({"name": f"{analysis.title} — {spec.title}"[:120], "name_font": {"size": 12}})
    chart.set_x_axis(x_axis)
    chart.set_y_axis(y_axis)
    chart.set_legend({"position": "bottom" if len(refs) > 3 else "right"})
    chart.set_size({"width": 680, "height": 340})
    return chart


def _provenance_sheet(book, fmt, report: ExcelReport) -> None:
    ws = book.add_worksheet("Provenance")
    ws.hide_gridlines(2)
    ws.set_column("A:A", 28)
    ws.set_column("B:B", 96)
    ws.write(0, 0, "Provenance", fmt["title"])
    ws.write(1, 0, "What produced these numbers, and from what.", fmt["subtitle"])
    rows: list[tuple[str, str]] = [
        ("Exported", f"{datetime.now():%Y-%m-%d %H:%M:%S}"),
        ("Application", f"{report.app_name} {report.app_version}".strip()),
        ("Project", report.project),
        ("Author", report.author or "-"),
        ("Python", sys.version.split()[0]),
        ("Platform", f"{platform.system()} {platform.release()}"),
    ]
    for module in ("numpy", "scipy", "pandas", "matplotlib", "xlsxwriter"):
        try:
            rows.append((module, __import__(module).__version__))
        except Exception:                                   # noqa: BLE001 - optional
            continue
    rows += list(report.extra_provenance.items())
    r = 3
    for label, value in rows:
        ws.write(r, 0, label, fmt["bold"])
        ws.write(r, 1, str(value), fmt["cell"])
        r += 1
    r += 1
    ws.write(r, 0, "Analyses", fmt["h2"])
    r += 1
    for analysis in report.analyses:
        settings = ", ".join(f"{k}={v}" for k, v in analysis.settings.items()) or "defaults"
        ws.write(r, 0, analysis.title, fmt["cell"])
        ws.write(r, 1, f"{analysis.group} — {analysis.source or 'in-app data'} — {settings}", fmt["wrap"])
        r += 1


def _unique_sheet_name(title: str, used: set[str]) -> str:
    base = (_INVALID_SHEET.sub("-", str(title)).strip().strip("'") or "Sheet")[:SHEET_NAME_LIMIT]
    name, n = base, 2
    while name.lower() in used:
        suffix = f" ({n})"
        name = base[:SHEET_NAME_LIMIT - len(suffix)] + suffix
        n += 1
    used.add(name.lower())
    return name
