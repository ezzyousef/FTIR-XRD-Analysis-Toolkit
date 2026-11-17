# Handoff: FTIR & XRD Analysis Toolkit upgrade (repository 04)

| | |
|---|---|
| Local path | `E:\Lab Apps\FTIR_XRD_Toolkit` |
| Branch | `upgrade/04-ftir`, from `feature/licensing` at `6654389` (pushed to origin, verified 170/170) |
| Version | 3.3.1 → 3.4.0 (`modules/app_info.py`, `installer/FTIR_XRD_Toolkit.iss`) |
| Tests | `py -3 -m pytest -q -p no:cacheprovider` with `QT_QPA_PLATFORM=offscreen`: **303 passed** (170 at baseline; 291 before the Codex fixes) |
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

## Codex review (independent, read-only)

The report is `AI_Engineering_Knowledge_Base/reports/codex/04-ftir-upgrade-review.md`, reviewing 6654389..9ad6ace. All 7 findings reproduced. Each has a regression test built from Codex's input (`tests/test_codex_review.py`), written to fail on 9ad6ace, then fixed.

| Severity | Finding | Reproduced | Fix | Test |
|---|---|---|---|---|
| High | JCAMP-DX line X values not checked (`9999 A4KK` loaded as 1003) | yes | `file_readers.read_jcampdx`: every line's X × XFACTOR must sit within half a step of its point's abscissa, counting the DIF overlap point | `test_jcamp_corrupt_line_x_is_refused`, `test_jcamp_correct_line_x_with_dif_overlap_and_plain_lines_load` |
| Medium | XYPOINTS scaled the already-physical FIRSTX/LASTX; only the span was compared | yes | Scaled data endpoints are compared with FIRSTX/LASTX by position (raw-stored endpoints still accepted) | `test_jcamp_xypoints_with_xfactor_and_physical_firstx`, `test_jcamp_xypoints_at_the_wrong_position_is_refused` |
| Medium | Multi-digit DUP counts (`T0` = 20) decoded as DUP 2 plus a stray 0 | yes (pre-existing) | `_jcamp_decode_asdf_line_ex` reads the whole DUP integer | `test_jcamp_multi_digit_dup_count` |
| Medium | Row width from the modal row, not the header; short rows passed | yes | Record widths as in supercap's `_clean_table`: a delimited header fixes the width, otherwise all rows must match; any mismatch refused with the line | `test_rows_wider_than_the_header_are_refused`, `test_rows_narrower_than_the_rest_are_refused` (guard: `test_header_and_rows_of_equal_width_still_load`) |
| Medium | Derivatives assumed even spacing | yes | `ftir_analysis.derivative_spectrum`: uneven axes use local polynomial fits on the actual x (Savitzky–Golay on even grids). `derivative_method()` text goes into the processing log | `test_derivative_on_a_micrometre_converted_axis`, `test_derivative_across_a_gap_from_dropped_rows` |
| Medium | Displacement calibration accepted single-angle designs | yes | `xrd_tools.calibrate`: rank-deficient designs refused; narrow cos θ spread (< 0.1) and two-angle exact fits give warnings, shown in the dialog | `test_displacement_calibration_rejects_a_single_angle`, `test_displacement_calibration_warns_on_narrow_coverage` |
| Low | Equation report claimed "every equation and algorithm" | yes | Scope wording and "Scope"/"Input domains not verified" sections | n/a (docs) |

Tests after the fixes: **303 passed** (291 before; 170 at baseline).

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
