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


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", fontSize=20, leading=24,
                               textColor=BRAND_COLOR, spaceAfter=4, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="ReportSubtitle", fontSize=10, textColor=colors.grey, spaceAfter=14))
    styles.add(ParagraphStyle(name="SectionHeading", fontSize=13, textColor=BRAND_COLOR,
                               spaceBefore=14, spaceAfter=6, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle(name="Disclaimer", fontSize=8, textColor=colors.grey, leading=11))
    return styles


def _table(rows, col_widths=None):
    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_COLOR),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
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
        story.append(Paragraph(heading, styles["SectionHeading"]))
        if rows:
            story.append(_table(rows))
        elif text:
            story.append(Paragraph(text.replace("\n", "<br/>"), styles["Normal"]))
        story.append(Spacer(1, 6))

    story.append(Spacer(1, 10))
    story.append(Paragraph(disclaimer, styles["Disclaimer"]))

    doc.build(story)
    return path
