# FTIR & XRD Analysis Toolkit — Professional Edition

A professional Windows desktop application (Tkinter/ttkbootstrap) for:
- **FTIR**: multi-spectrum overlay, smoothing, baseline correction, automatic
  peak detection, Gaussian/Lorentzian/pseudo-Voigt peak fitting, and matching
  against a **224-material reference database** (polymers, hydrogels, salts,
  inorganic oxides/minerals, organic/biomolecules, elements & allotropes) plus
  **67 generic functional-group correlations** — covering common calculations
  (%T ↔ Absorbance, peak area, FWHM, Beer-Lambert concentration). The search
  can be **restricted to a single category** (e.g. just Organic/Biomolecules,
  or just Salts) when you already know roughly what the sample is, for more
  accurate and faster matching.
- **XRD**: reading multiple diffractometer file formats, peak detection,
  d-spacing (Bragg's law), crystallite size (Scherrer equation),
  Williamson-Hall size/strain analysis, approximate % crystallinity, cubic
  lattice parameter estimation, and matching against a **23-phase reference
  database** (metals, oxides, minerals, salts, semiconductors, carbon
  allotropes) by wavelength-independent d-spacing — also restrictable by
  category, and extensible via CSV import of your own reference cards.

Every database entry and every calculation carries a **literature citation**
— click the ⓘ button next to a tool, or open **Help → Data Sources &
References** inside the app.

## Getting the Windows app

This app is built and tested on Windows. Three ways to get it:

### 1. Windows installer (recommended)
Run `build_installer.ps1` (needs [Inno Setup 6](https://jrsoftware.org/isdl.php)
installed, free) — produces `installer\output\FTIR_XRD_ToolkitSetup.exe`, a
normal double-click Windows installer (Start Menu shortcut, optional Desktop
shortcut, uninstaller). Copy that one file to any Windows PC and run it —
nothing else needs to be installed there.

### 2. Standalone folder (no installer)
Double-click `build_exe.bat` (or run it from a terminal). When it finishes,
your app is at `dist\FTIR_XRD_Toolkit\FTIR_XRD_Toolkit.exe`. Copy the **whole**
`dist\FTIR_XRD_Toolkit\` folder anywhere — it needs every file alongside it,
not just the exe.

(Both use an **onedir** PyInstaller build rather than onefile — onefile
re-extracts its entire bundled runtime to a fresh temp folder on every launch,
which is a well-documented cause of flaky/slow startup as antivirus
real-time-scans the new payload each time. onedir extracts once.)

### 3. Run from source
`pip install -r requirements.txt`, then `python main.py` — no packaging
needed, works on any OS with Python 3.10+.

## Using the app

### FTIR tab
1. **Load Spectrum** (or drag & drop a file onto the plot) — accepts
   two-column `.csv/.txt/.dat/.xy` files (wavenumber, intensity/%T/absorbance).
   Load multiple files to overlay them; click a trace in "Loaded Traces" to
   make it active, click its ● to hide/show it.
2. Choose **Absorbance** or **%Transmittance** mode, adjust the sensitivity
   slider, and **Detect Peaks**.
3. **Smooth / Baseline Correct / Normalize / Revert to Raw** as needed.
4. **Match to Database** — screens detected peaks against the 224-material
   database and 67 functional groups, ranked by corroborating peak count
   then coverage score. Pick a category (Polymers, Hydrogels, Salts,
   Inorganic, Organic/Biomolecules, Elements/Allotropes, or All) to narrow
   the search when you already know roughly what the sample is. This is a
   **heuristic screening tool, not definitive identification** — always
   confirm anything important against a certified
   reference spectrum (NIST WebBook, SDBS) or an expert.
5. **Fit All Detected Peaks** for Gaussian/Lorentzian/pseudo-Voigt refinement.
6. Calculation tools (with ⓘ formula/source buttons): %T↔A converter,
   peak-area integration, FWHM, Beer-Lambert concentration.
7. **Export Peak List (CSV)**, **Export PDF Report**, or **Save/Load Session**
   (`.ftirxrd` project files).

### XRD tab
1. **Load XRD File** (or drag & drop) — auto-detects format from the extension:
   - `.xy` `.txt` `.dat` `.csv` — generic two-column ASCII (high confidence)
   - `.uxd` — Siemens/Bruker text (high confidence)
   - `.ras` — Rigaku text (high confidence)
   - `.xrdml` — PANalytical/Malvern XML (high confidence)
   - `.raw` — legacy Bruker binary (**best-effort** — undocumented format;
     export ASCII from your instrument software if it fails to parse)
2. Select the **X-ray wavelength**, **Detect Peaks**, then **Run All
   Calculations** for d-spacing and Scherrer crystallite size per peak.
3. **Williamson-Hall** separates size vs. strain broadening (needs 3+ peaks).
4. **% Crystallinity** — specify crystalline vs. amorphous-halo 2θ regions.
5. **Cubic Lattice Parameter** — a quick single-peak estimate (cubic only).
   For an accurate result, use **Iterative Lattice Refinement** instead: index
   several detected peaks with their (h,k,l) (use **Auto-fill hkl from Top
   Phase Match** for a starting guess after running phase ID, then verify
   them), pick a crystal system (cubic/tetragonal/hexagonal/orthorhombic),
   and it refines the lattice parameter(s) by nonlinear least squares across
   **all** of them at once — with automatic outlier rejection that repeats
   the fit, dropping any peak whose residual is inconsistent with the rest
   (catches a wrong hkl assignment), until it converges. Reports each
   parameter with a real uncertainty, R², and a per-peak residual table.
6. **Match to Phase Database** — screens detected peaks (as wavelength-
   independent d-spacings) against the 23-phase database. **Open Database
   Viewer / Import CSV** lets you add your own phases (e.g. transcribed from
   a certified ICDD PDF card in your own diffraction software) — they persist
   across sessions.
7. **Fit All Detected Peaks**, **Export Peak List (CSV)**, **Export PDF
   Report**, or **Save/Load Session**.

### Everywhere
- **Tools → Reference Database Viewer** browses every material/phase entry,
  its peaks, and its literature source.
- **Help → Data Sources & References** lists the full bibliography.
- **View → Light/Dark Themes** — 18 ttkbootstrap themes, persisted across runs.
- Long-running matches/fits run on a background thread so the window stays
  responsive.

## Important accuracy notes
- All reference-database peak positions/d-spacings are compiled from standard,
  published literature (see in-app citations), not certified measurements of
  a specific sample batch. Treat matches as a starting point, not a
  certificate of identity.
- Scherrer crystallite sizes are **apparent** sizes from peak broadening
  alone — not corrected for instrumental broadening, and conflate size/strain
  effects unless you use Williamson-Hall.
- % Crystallinity by area-under-curve is inherently method- and
  region-choice-dependent. Always report which regions you used.
- Bruker `.raw` binary parsing is best-effort (undocumented format) — cross-
  check against an ASCII export when it matters.

## Project structure
```
ftir_xrd_toolkit/
  main.py                          # App shell: menu, theming, tabs, status bar
  app.spec                         # PyInstaller build spec (onedir)
  build_exe.bat                    # Standalone-folder build
  build_installer.ps1              # Full Setup.exe build (PyInstaller + Inno Setup)
  installer/FTIR_XRD_Toolkit.iss   # Inno Setup script
  requirements.txt
  database/
    ftir_reference_db.json         # 224 materials + 67 functional groups, cited
    xrd_reference_db.json          # 23 phases, cited
  modules/
    file_readers.py                # FTIR/XRD file format readers
    ftir_analysis.py               # Peak detection, DB matching, calculations
    xrd_analysis.py                # Bragg/Scherrer/W-H/crystallinity, phase matching
    peak_fitting.py                # Gaussian/Lorentzian/pseudo-Voigt fitting
    signal_utils.py                # Shared smoothing helpers
    report_export.py               # PDF report generation
    session_io.py                  # Session save/load
    app_config.py                  # Persisted user settings
    trace_model.py                 # Multi-trace data model
    workers.py                     # Background-thread helper
    formula_sources.py             # Formula/citation text for the ⓘ buttons
    ui_common.py                   # Shared UI scaffolding (trace panel, tables,
                                    #   dialogs, database viewer)
    ftir_tab.py / xrd_tab.py       # The two analysis tabs
  tests/                           # pytest suite for the core analysis modules
  assets/                          # App icon, EML logo
```

You can extend either database by editing its JSON file directly, or (for
XRD) via the in-app **Import Phases from CSV** — no code changes needed.

Run the test suite with `pytest tests/`.
