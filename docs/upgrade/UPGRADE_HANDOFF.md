# Handoff: FTIR & XRD Analysis Toolkit upgrade (repository 04)

| | |
|---|---|
| Local path | `E:\Lab Apps\FTIR_XRD_Toolkit` |
| Branch | `upgrade/04-ftir`, from `feature/licensing` at `6654389` (pushed to origin, verified 170/170) |
| Version | 3.3.1 → 3.4.0 (`modules/app_info.py`, `installer/FTIR_XRD_Toolkit.iss`) |
| Tests | `py -3 -m pytest -q -p no:cacheprovider` with `QT_QPA_PLATFORM=offscreen`: **291 passed** (170 at baseline) |
| Installer | Not rebuilt this round |
| Merge | **Not merged** into `master`; owner decision |

## Feature matrix (brief → state now)

| # | Target | Now | Notes / blocker |
|---|---|---|---|
| A | Equation oracles + report | **DONE** | `docs/EQUATION_REGRESSION_REPORT.md`; 3 defects fixed |
| A | Hostile files for every importer | **DONE** | 41 tests; 7 reader defects fixed |
| 1 | Validation laboratory | **DONE (software)**, **BLOCKED (data)** | Manifest, leak check, train-only tuning, confusion matrix, P/R/F1, OOD false positives, tolerance and shift sensitivity, CLI and menu. **Blocker:** no measured spectra of known materials were supplied; the matcher's real accuracy is still unknown. Inorganic and organic standards "tested separately" needs those spectra |
| 2 | Matched-peak comparison, overlays | **DONE** (before) | |
| 2 | Manual assignments with undo | **DONE** | Peaks table, peak CSV and evidence report. Excel/Origin peak sheets do not carry the label yet (**PARTIAL**) |
| 2 | Uncertainty bands, robust constrained global fit | **DONE** | Fit table with 1σ errors; the fitted curve and its 2σ band are drawn on the FTIR plot and saved in sessions |
| 2 | Recipes, batch reports | **DONE** | Synchronous batch with a log dialog; no background queue with progress (**PARTIAL**) |
| 2 | Trace provenance | **PARTIAL** | `.provenance.json` beside peak-list CSVs (both pages), batch summaries and `.xye` exports; the Excel provenance sheet as before. Not yet beside Origin packages, graphs or PDF reports |
| 3 | Diffractometer import tests | **PARTIAL** | Synthetic files to the documented formats only. **Blocker:** no real instrument files |
| 3 | Calibration with certified standards | **DONE** | The user enters certificate d-values; none are built in |
| 3 | Preferred orientation / amorphous warnings | **DONE** | |
| 3 | Instrument-broadening propagation | **DONE** | Monte Carlo checked |
| 3 | Indexing helpers | **DONE (cubic)** | Lower symmetries not attempted: they need a real indexing algorithm (e.g. DICVOL-type) and validation data |
| 3 | Licensed / user phase cards | **DONE** | CSV cards; verdict capped at "consistent"; no ICDD scraping |
| 4 | External refinement adapter | **PARTIAL** | `.xye` + provenance export and a GSAS-II presence check. **Blocker:** GSAS-II/FullProf are not installed; their licences and environment could not be verified offline; there is no benchmark refinement to compare against. No engine is run or claimed |
| 5 | FTIR + XRD evidence workspace | **DONE** | JSON record + escaped HTML report with caveats first. Opening a saved record back into the workspace UI is not built (**PARTIAL**) |
| 6 | Large spectra | **DONE** | Min/max thinning for drawing; data and exports untouched |
| 6 | Synchronised hover/crosshair | **PARTIAL** | Status bar shows cursor, active-trace value and d; no drawn crosshair line |
| 6 | Zoom/ROI, shortcuts | **DONE** | Existing toolbar; new shortcuts Ctrl+G, Ctrl+B, Ctrl+Shift+A, Ctrl+Shift+R, Ctrl+, (no clashes) |
| 6 | Preferences, custom labels, colour-blind plots | **DONE** | QSettings; Okabe–Ito palette |
| 6 | Strict parsing, no hidden transmission | **DONE** | Reader hardening; AST and socket tests |

## Rollback

- Whole upgrade: `git switch feature/licensing` (the branch is unchanged and pushed).
- One milestone: `git revert <commit>` (see the plan for hashes).
- labkit only: `py -3 sync.py --restore FTIR_XRD_Toolkit` from `E:\Lab Apps\labkit` (backup in `.labkit-backup/20261115-122203`).

## Next steps

1. The owner supplies measured spectra of known materials (organic and inorganic separately) and runs `tools/validate_ftir_matching.py`. Then decide whether the tier thresholds hold.
2. Supply real exports from each diffractometer for import tests.
3. Add assignments to the Excel/Origin peak sheets; add Provenance beside Origin, graph and PDF exports; a drawn crosshair; a background batch queue.
4. Rebuild the installer (`build_installer.ps1`) and smoke-test the installed app.
5. Next repository in the queue: 05 `brookfield-dv1-logger`.
