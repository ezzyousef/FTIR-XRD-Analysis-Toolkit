"""
report_export.py
Builds a professional PDF analysis report (plot + peak table + database
matches + disclaimer) using reportlab. Used by both the FTIR and XRD tabs.
"""
import datetime

# reportlab is imported lazily, inside build_report() below, rather than here
# at module level -- see the matching comment in ftir_analysis.py for why
# (keeps the startup splash screen short; PDF export is a deliberate,
# infrequent user action, not something needed to show the window).
BRAND_COLOR = None
ACCENT_COLOR = None
FONT, FONT_BOLD = "Helvetica", "Helvetica-Bold"
# Symbols the report fonts lack, written as text so they never print as empty boxes.
SYMBOL_TEXT = {"✓": "+", "✗": "x", "⚠": "(!)"}


def _ensure_imported():
    global colors, letter, getSampleStyleSheet, ParagraphStyle, inch
    global SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
    global BRAND_COLOR, ACCENT_COLOR

    if BRAND_COLOR is not None:
        return
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image,
                                     Table, TableStyle, PageBreak)
    BRAND_COLOR = colors.HexColor("#2453ff")
    ACCENT_COLOR = colors.HexColor("#eef2ff")
    _register_fonts()


def _register_fonts():
    """A Unicode TrueType font (Greek, Delta, approx. signs), since the built-in Helvetica
    only covers Latin-1: Arial on Windows, else the Vera font bundled with reportlab."""
    global FONT, FONT_BOLD
    import os

    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    win = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts")
    bundled = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    for regular, bold in ((os.path.join(win, "arial.ttf"), os.path.join(win, "arialbd.ttf")),
                          (os.path.join(bundled, "Vera.ttf"), os.path.join(bundled, "VeraBd.ttf"))):
        if os.path.exists(regular) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont("ReportSans", regular))
                pdfmetrics.registerFont(TTFont("ReportSans-Bold", bold))
            except Exception:  # noqa: BLE001 - try the next font
                continue
            FONT, FONT_BOLD = "ReportSans", "ReportSans-Bold"
            return


def _text(value):
    s = str(value)
    for symbol, text in SYMBOL_TEXT.items():
        s = s.replace(symbol, text)
    return s


def _styles():
    styles = getSampleStyleSheet()
    styles["Normal"].fontName = FONT
    styles.add(ParagraphStyle(name="ReportTitle", fontSize=20, leading=24,
                               textColor=BRAND_COLOR, spaceAfter=4, fontName=FONT_BOLD))
    styles.add(ParagraphStyle(name="ReportSubtitle", fontSize=10, textColor=colors.grey, spaceAfter=14,
                               fontName=FONT))
    styles.add(ParagraphStyle(name="SectionHeading", fontSize=13, textColor=BRAND_COLOR,
                               spaceBefore=14, spaceAfter=6, fontName=FONT_BOLD))
    styles.add(ParagraphStyle(name="Disclaimer", fontSize=8, textColor=colors.grey, leading=11, fontName=FONT))
    return styles


def _table(rows, col_widths=None):
    rows = [[_text(c) for c in row] for row in rows]
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_COLOR),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ACCENT_COLOR]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def build_report(path, title, subtitle, plot_image_path, sections, disclaimer, source_file=None):
    """
    title: str
    subtitle: str (e.g. instrument mode, wavelength used)
    plot_image_path: path to a PNG snapshot of the analysis plot (or None)
    sections: list of (heading:str, rows: list[list[str]] or None, text: str or None)
              -- if rows is given, renders as a table (first row = header);
                 if text is given (and rows is None), renders as a paragraph.
    disclaimer: str footer text (accuracy / methodology caveats)
    """
    _ensure_imported()
    styles = _styles()
    doc = SimpleDocTemplate(path, pagesize=letter,
                             topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                             leftMargin=0.6 * inch, rightMargin=0.6 * inch)
    story = []

    story.append(Paragraph(title, styles["ReportTitle"]))
    meta_line = f"Generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
    if source_file:
        meta_line += f"  |  Source file: {source_file}"
    if subtitle:
        meta_line += f"  |  {subtitle}"
    story.append(Paragraph(meta_line, styles["ReportSubtitle"]))

    if plot_image_path:
        story.append(Image(plot_image_path, width=6.8 * inch, height=6.8 * inch * 0.56))
        story.append(Spacer(1, 10))

    for heading, rows, text in sections:
        story.append(Paragraph(_text(heading), styles["SectionHeading"]))
        if rows:
            story.append(_table(rows))
        elif text:
            story.append(Paragraph(_text(text).replace("\n", "<br/>"), styles["Normal"]))
        story.append(Spacer(1, 6))

    story.append(Spacer(1, 10))
    story.append(Paragraph(disclaimer, styles["Disclaimer"]))

    doc.build(story)
    return path
