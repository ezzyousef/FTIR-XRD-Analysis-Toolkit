# FTIR & XRD Analysis Toolkit

A Windows desktop application (PySide6) for FTIR spectra and X-ray diffraction patterns,
built on the lab's shared **labkit** interface — the same one as AeroLab Studio, the DV1
Viscosity Logger and Supercap Suite: a navigation rail, light and dark themes, a Ctrl+K
command palette, undo/redo, styled OriginLab graphs, Excel workbooks and PDF reports.

Made by Ezzeldien Yousef (ezzyousef@aucegypt.edu), Energy Materials Laboratory (EML).
A step-by-step user guide with screenshots is in `FTIR_XRD_Toolkit_User_Guide.docx` (this folder).

- **FTIR**: multi-spectrum overlay, smoothing, baseline correction, ATR correction,
  derivatives, normalization, automatic peak detection (with optional second-derivative
  shoulder resolution), Gaussian/Lorentzian/pseudo-Voigt peak fitting, and screening against
  a **237-material reference database** plus **99 functional-group correlations**, optionally
  restricted to one category. Calculators: %T ↔ absorbance, peak area, FWHM, Beer–Lambert.
- **XRD**: several diffractometer file formats, peak detection, d-spacing (Bragg), crystallite
  size (Scherrer), Williamson–Hall size/strain, approximate % crystallinity, SNIP background
  subtraction, 2θ/d/Q conversion, single-peak cubic lattice parameter and peak fitting.
  Phase identification against reference cards is out of scope — use your diffractometer's
  search/match software for that, then bring the pattern here for the quantitative work.

Every database entry and every calculation carries a **literature citation** — the ⓘ button
next to each tool, or **Library › Sources & references** in the app.

## Getting the Windows app

### Installer (recommended)
```
.\build.ps1
```
Runs the tests, builds `dist\FTIR_XRD_Toolkit\` with PyInstaller, runs the built exe's
`--selftest`, packs a portable zip and compiles `installer\output\FTIR_XRD_ToolkitSetup-<version>.exe`
with [Inno Setup 6](https://jrsoftware.org/isdl.php) (`winget install JRSoftware.InnoSetup`).
Copy the setup file to any Windows PC — nothing else needs to be installed there.
(`build_installer.ps1` and `build_exe.bat` still work and call the same build.)

The build is **onedir**, not onefile: onefile re-extracts its whole runtime to a temp folder on
every launch, a well-known cause of slow, flaky startup as antivirus rescans it.

### Run from source
`pip install -r requirements.txt`, then `python main.py` (Python 3.11+).
`python main.py file1.csv pattern.xrdml` opens files at start-up;
`python main.py --selftest` checks the whole application without a window.

## Using the app

The rail on the left has **Analyse** (FTIR spectra, XRD patterns), **Library** (reference
database, sources & references) and **Help** (About).

### FTIR spectra
1. **Load spectra…** (Ctrl+O) or drop files anywhere on the page — `.csv .txt .dat .xy .dpt .jdx`.
   Load several to overlay them; click a row in *Loaded traces* to make it the active trace,
   untick *Show* to hide it.
2. **Process first** (the *Processing* card): ATR correction, then baseline correction, then
   smoothing. Baseline correction always starts again from the raw data, so do it before
   smoothing. Any processing step clears the detected peaks and the match results, because
   they no longer describe the spectrum.
3. Choose **Absorbance** or **%Transmittance**, set the sensitivity and **Detect peaks**.
   Peaks are picked above an automatic noise floor, and the atmospheric CO₂ region
   (2280–2400 cm⁻¹) is skipped unless you untick it.
4. **Match to database** (Ctrl+M) — screens the detected peaks against the reference database
   and functional groups in the background. The default *Weighted evidence* scoring asks three
   questions for each material:
   - Are its bands, especially the strong ones, present close to the expected positions?
   - Does it explain most of your strong peaks in its region?
   - Could this many hits happen by luck, given how crowded the peak list is and how many
     materials were searched?

   Results are ranked by **match score** with a tier: Strong, Moderate, Weak or Poor. The score
   is a screening score, **not the probability that the identification is correct**.

   Click a row to see the evidence band by band (✓ found, ≈ at the tolerance edge, ✗ missing,
   ⚠ for a missing strong band) and to overlay the bands on the plot. *Hide matches below* and
   the filter box only change what is listed. *Coverage (legacy)* reproduces the scoring used
   by earlier versions.
5. **Analyse as mixture** — when no single material explains the spectrum, screens for up to
   three components and lists the peaks left unexplained. *Share of peak intensity* is not a
   concentration.
6. **Check, then confirm.** Mark a candidate *Confirmed* or *Rejected* (with a note) once you
   have compared it with a certified reference spectrum (NIST WebBook, SDBS) or an expert. The
   PDF and Excel exports record the method, every parameter, the database version and the
   band-by-band evidence, so others can reproduce the result.
   The scoring was tested on synthetic peak lists only
   (`python tools/benchmark_ftir_matching.py`). It has not yet been validated on lab spectra of
   known materials. Design notes are in `docs/FTIR_MATCHING_PLAN.md`.
7. **Fit all detected peaks** — the fitted peaks are drawn as one model curve in the
   spectrum's colour and listed in *Peak fits*.
8. **Calculations** with ⓘ formula/source buttons.

### XRD patterns
1. **Load patterns…** — format detected from the extension:
   `.xy .txt .dat .csv` (generic two-column ASCII; header lines and decimal commas handled),
   `.uxd` (Siemens/Bruker, pair or counts-only blocks), `.ras` (Rigaku, attenuation applied),
   `.xrdml` (PANalytical/Malvern, list or start/end positions, attenuation applied) — high
   confidence; `.raw` (legacy Bruker binary) — best effort, export ASCII if it fails. Files with
   several scans load the first and say so; a wavelength stored in the file that differs from
   the selected one is flagged.
2. **1 · Instrument** — wavelength, Scherrer K, and the **instrument profile** (a constant FWHM
   or Caglioti U, V, W; *Refine profile from this pattern* fits them from a line-profile
   standard such as LaB6 or Si). Without a profile, sizes are not corrected for instrumental
   broadening. Changing any of these clears results computed with the old values.
3. **2 · Processing** — in this order: **SNIP background** (window in degrees 2θ), **strip Kα2**
   (Rachinger; Cu pre-filled — leaving Kα2 in widens peaks with angle and mimics strain), then
   smoothing only if needed.
4. **3 · Peak detection** — peaks are judged against the local counting noise (7σ); noise
   maxima on top of a stronger peak and spikes are dropped.
5. **6 · Peak fitting** (pseudo-Voigt by default, window ±3 × each peak's width), then
   **4 · Size & strain**: d-spacing and Scherrer size per peak from the fitted, instrument-
   corrected width; **Williamson–Hall** with standard errors, R² and its plot. Untick a peak in
   the Peaks table to leave it out. Sizes are *apparent* sizes.
6. **5 · Crystallinity** — area method on the raw pattern minus a straight baseline (SNIP would
   remove the amorphous halo); the regions are drawn on the plot.
7. **Tools** — cubic lattice parameter (whole-number hkl, P/I/F extinction note, precision per
   0.01° in 2θ) and the 2θ/d/Q converter; results are kept in the *Calculations* tab and the PDF.

Every result keeps the wavelength, K, instrument profile, width source and processing it was
computed with; the PDF, Excel and peak CSV print those stored values.

### Exports (both pages)
- **Send to Origin** (button under the plot, or Ctrl+Shift+O) — a workbook with every visible
  trace, the peak table and a Results sheet, and a styled graph (colour-blind-safe palette,
  FTIR axis running high to low, fits in their spectrum's colour, legend clear of the data).
  Each send adds to the same Origin project; the arrow menu saves or closes it. Without Origin,
  **Write LabTalk package** builds the same project on any PC with Origin.
- **Export to Excel** (Ctrl+Shift+E) — a summary, one sheet and native chart per trace, match
  and fit tables, and a provenance sheet.
- **Save figures** (300 dpi PNG), **Export graph** (SVG/EPS/PDF/PNG), **Export PDF report**
  (Ctrl+E), **Export peak list (CSV)**, **Export for OriginLab (CSV)**.
- **Save / load session** (Ctrl+S / Ctrl+L) — `.ftirxrd` project files, compatible with
  earlier versions.

### Keyboard
| Keys | Action |
|---|---|
| Ctrl+O | Open data files |
| Ctrl+Z / Ctrl+Y | Undo / redo (loading, processing, detection, matching, fitting, calculations) |
| Ctrl+S / Ctrl+L | Save / load session |
| Ctrl+E | PDF report |
| Ctrl+Shift+O / Ctrl+Shift+E | Send to Origin / export to Excel |
| Ctrl+M | Match the active FTIR spectrum to the database |
| Ctrl+D | FTIR reference database |
| Ctrl+T | Light / dark theme |
| Ctrl+K | Command palette |
| Ctrl+1 … Ctrl+5 | Go to a page |

## Important accuracy notes
- FTIR reference peak positions are compiled from published literature (see the in-app
  citations), not certified measurements of a specific sample. Treat matches as a starting
  point, not a certificate of identity.
- Scherrer crystallite sizes are **apparent** sizes from broadening alone — not corrected for
  instrumental broadening, and they mix size and strain unless you use Williamson–Hall.
- % crystallinity by area under the curve depends on the method and the regions chosen —
  report the regions with the number.
- Bruker `.raw` parsing is best effort (undocumented format) — cross-check against an ASCII export.

## Project structure
```
ftir_xrd_toolkit/
  main.py                          entry point (splash, --selftest, --version, files to open)
  selftest.py                      headless check used on packaged builds
  app.spec, build.ps1              PyInstaller spec and the full build
  installer/FTIR_XRD_Toolkit.iss   Inno Setup script
  database/ftir_reference_db.json  237 materials + 99 functional groups, cited (v4.3; additions in docs/FTIR_DATABASE_ADDITIONS.md)
  tools/audit_ftir_database.py     database audit -> docs/FTIR_DATABASE_AUDIT.md
  tools/benchmark_ftir_matching.py simulated-spectrum benchmark of the matcher
  labkit/                          vendored shared interface — edit ..\..\labkit and run sync.py
  modules/
    app_window.py                  the window: pages, menus, recent files, undo/redo, Origin
    ui_common.py                   shared page scaffolding: traces, plot, tables, dialogs, sessions
    ftir_tab.py / xrd_tab.py       the two analysis pages
    exports.py                     figures, Origin workbooks and Excel reports (no Qt)
    file_readers.py                FTIR/XRD file format readers
    ftir_analysis.py               peak detection, database matching, calculations
    xrd_analysis.py                Bragg/Scherrer/W-H/crystallinity/SNIP/conversions
    peak_fitting.py                Gaussian/Lorentzian/pseudo-Voigt fitting
    signal_utils.py, report_export.py, session_io.py, app_config.py, trace_model.py,
    workers.py, formula_sources.py, app_info.py
  tests/                           pytest suite (analysis, readers, exports, the Qt pages)
  assets/                          icon, EML logo
```

Extend the FTIR database by editing its JSON file — no code changes needed.
Run the tests with `python -m pytest tests`.
