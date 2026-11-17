"""
evidence.py
Sample-level FTIR + XRD evidence workspace.

A *sample record* links what was measured on one sample by both techniques -- the FTIR peaks
and screening candidates, the XRD peaks, d-spacings, sizes and phase-card checks -- with the
processing applied, the assumptions made, the software and database versions and the cited
sources. It is saved as JSON ("ftir-xrd-evidence/1") and rendered as a self-contained HTML
report for a lab notebook or a manuscript's supporting information.

The two techniques are kept side by side, never merged into one score: FTIR screening
candidates are band-table matches (a screening score, not a probability), and generic XRD
peak matching cannot establish phase identity. The report says so at the top.
"""
import datetime as _dt
import html
import json
import os

FORMAT = "ftir-xrd-evidence/1"
CAVEATS = (
    "FTIR candidates come from matching a peak list against literature band ranges: the score is a screening "
    "score, not the probability that the identification is correct, and the matcher has not been validated on "
    "measured spectra of this lab's materials.",
    "XRD peak positions and phase-card comparisons can show that a pattern is consistent with a phase; they "
    "cannot establish its identity on their own.",
    "The two techniques are shown side by side as independent evidence; no combined score is computed.",
)


def _peaks_ftir(trace):
    return [{"x_cm1": round(float(p["x"]), 2), "prominence": float(p.get("prominence", 0.0)),
             "fwhm_cm1": float(p.get("fwhm_cm1", 0.0) or 0.0), "manual": bool(p.get("manual", False)),
             "assignment": p.get("assignment", "")} for p in (getattr(trace, "peaks", None) or [])]


def _peaks_xrd(trace, wavelength_a):
    try:
        import xrd_analysis
    except ImportError:  # pragma: no cover
        from modules import xrd_analysis
    out = []
    for p in getattr(trace, "peaks", None) or []:
        tt = float(p.get("two_theta", p.get("x", 0.0)))
        d = float(xrd_analysis.bragg_d_spacing(tt, wavelength_a)) if tt > 0 and wavelength_a else None
        out.append({"two_theta_deg": round(tt, 4), "d_A": None if d is None else round(d, 5),
                    "intensity": float(p.get("intensity", p.get("y", 0.0))), "fwhm_deg": float(p.get("fwhm_deg", 0.0) or 0.0),
                    "assignment": p.get("assignment", "")})
    return out


def _candidates(trace, top=5):
    out = []
    for m in (getattr(trace, "matches", None) or [])[:top]:
        out.append({"name": m.get("name", ""), "tier": m.get("tier", ""),
                    "score": float(m.get("confidence", m.get("score", 0.0)) or 0.0),
                    "bands_found": int(m.get("matched_count", 0)), "bands_in_range": int(m.get("total_reference_peaks", 0)),
                    "source": m.get("source", "")})
    return out


def build_record(sample_id, ftir_trace=None, xrd_trace=None, wavelength_a=None, assumptions=(), notes="",
                 app_version="", database_version="", references=(), xrd_results=None):
    """A sample record from the traces currently loaded. Either technique may be missing."""
    if not str(sample_id).strip():
        raise ValueError("Give the sample an ID.")
    rec = {"format": FORMAT, "sample_id": str(sample_id).strip(), "created": _dt.datetime.now(_dt.timezone.utc)
           .replace(microsecond=0).isoformat(), "app_version": app_version, "database_version": database_version,
           "assumptions": [str(a) for a in assumptions if str(a).strip()], "notes": str(notes),
           "references": [str(r) for r in references], "caveats": list(CAVEATS), "ftir": None, "xrd": None}
    if ftir_trace is not None:
        meta = getattr(ftir_trace, "metadata", {}) or {}
        rec["ftir"] = {"label": ftir_trace.label, "source_file": os.path.basename(str(meta.get("path", ""))),
                       "processing": list(meta.get("processing") or []), "detection": meta.get("detection") or {},
                       "peaks": _peaks_ftir(ftir_trace), "candidates": _candidates(ftir_trace),
                       "match_params": meta.get("match_params") or {}}
    if xrd_trace is not None:
        meta = getattr(xrd_trace, "metadata", {}) or {}
        rec["xrd"] = {"label": xrd_trace.label, "source_file": os.path.basename(str(meta.get("path", ""))),
                      "wavelength_A": wavelength_a, "processing": list(meta.get("processing") or []),
                      "peaks": _peaks_xrd(xrd_trace, wavelength_a), "results": dict(xrd_results or {})}
    if rec["ftir"] is None and rec["xrd"] is None:
        raise ValueError("Load an FTIR spectrum, an XRD pattern, or both.")
    return rec


def save_record(rec, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=2, ensure_ascii=False, allow_nan=False, default=str)


def load_record(path):
    with open(path, "r", encoding="utf-8") as f:
        rec = json.load(f)
    if not isinstance(rec, dict) or rec.get("format") != FORMAT:
        raise ValueError(f"Not an evidence record (expected format {FORMAT!r}).")
    for key in ("sample_id", "caveats"):
        if key not in rec:
            raise ValueError(f"Evidence record is missing {key!r}.")
    return rec


def _table(headers, rows):
    e = html.escape
    head = "".join(f"<th>{e(str(h))}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{e('' if v is None else str(v))}</td>" for v in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>" if rows else "<p>None.</p>"


def render_html(rec):
    """Self-contained HTML (no scripts, no external resources); every value is escaped."""
    e = html.escape
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Evidence — {e(rec['sample_id'])}</title>",
             "<style>body{font-family:'DejaVu Sans',Arial,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;"
             "color:#1a1a1a;background:#fff}table{border-collapse:collapse;margin:.5rem 0 1rem}th,td{border:1px solid #999;"
             "padding:.25rem .5rem;text-align:left}th{background:#eee}.caveat{border-left:4px solid #b35900;padding:.5rem 1rem;"
             "background:#fff4e5}.cols{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem}"
             "@media(max-width:50rem){.cols{grid-template-columns:1fr}}</style></head><body>",
             f"<h1>Sample {e(rec['sample_id'])}: FTIR and XRD evidence</h1>",
             f"<p>Created {e(rec.get('created', ''))} with FTIR &amp; XRD Analysis Toolkit {e(rec.get('app_version', ''))}"
             + (f", FTIR database {e(rec['database_version'])}" if rec.get("database_version") else "") + ".</p>",
             "<div class='caveat'><strong>Read first</strong><ul>"
             + "".join(f"<li>{e(c)}</li>" for c in rec["caveats"]) + "</ul></div>"]
    if rec.get("assumptions"):
        parts.append("<h2>Assumptions</h2><ul>" + "".join(f"<li>{e(a)}</li>" for a in rec["assumptions"]) + "</ul>")
    parts.append("<div class='cols'>")
    f = rec.get("ftir")
    parts.append("<section><h2>FTIR</h2>")
    if f:
        parts.append(f"<p>Spectrum: {e(f['label'])} (file {e(f['source_file'])})</p>")
        parts.append("<h3>Processing</h3>" + ("<ol>" + "".join(f"<li>{e(s)}</li>" for s in f["processing"]) + "</ol>"
                                              if f["processing"] else "<p>Raw data, no processing.</p>"))
        parts.append("<h3>Peaks</h3>" + _table(["cm⁻¹", "FWHM (cm⁻¹)", "Placed", "Assignment"],
                                               [[p["x_cm1"], f"{p['fwhm_cm1']:.1f}", "by hand" if p["manual"] else "detected",
                                                 p["assignment"]] for p in f["peaks"]]))
        parts.append("<h3>Screening candidates (not identifications)</h3>"
                     + _table(["Material", "Tier", "Score", "Bands found", "Source"],
                              [[c["name"], c["tier"], f"{c['score']:.2f}", f"{c['bands_found']}/{c['bands_in_range']}",
                                c["source"]] for c in f["candidates"]]))
    else:
        parts.append("<p>No FTIR spectrum linked.</p>")
    parts.append("</section><section><h2>XRD</h2>")
    x = rec.get("xrd")
    if x:
        parts.append(f"<p>Pattern: {e(x['label'])} (file {e(x['source_file'])}), λ = {e(str(x['wavelength_A']))} Å</p>")
        if x["processing"]:
            parts.append("<h3>Processing</h3><ol>" + "".join(f"<li>{e(s)}</li>" for s in x["processing"]) + "</ol>")
        parts.append("<h3>Peaks</h3>" + _table(["2θ (°)", "d (Å)", "FWHM (°)", "Assignment"],
                                               [[p["two_theta_deg"], p["d_A"], f"{p['fwhm_deg']:.3f}", p["assignment"]]
                                                for p in x["peaks"]]))
        if x.get("results"):
            parts.append("<h3>Results</h3>" + _table(["Quantity", "Value"], [[k, v] for k, v in x["results"].items()]))
    else:
        parts.append("<p>No XRD pattern linked.</p>")
    parts.append("</section></div>")
    if rec.get("notes"):
        parts.append(f"<h2>Notes</h2><p>{e(rec['notes'])}</p>")
    if rec.get("references"):
        parts.append("<h2>Sources</h2><ol>" + "".join(f"<li>{e(r)}</li>" for r in rec["references"]) + "</ol>")
    parts.append("</body></html>")
    return "".join(parts)


def write_report(rec, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(rec))
    return path
