# Upgrade audit: FTIR & XRD Analysis Toolkit (repository 04)

Local path `E:\Lab Apps\FTIR_XRD_Toolkit`. Audited at `feature/licensing` `6654389` (3.3.1 plus licensing groundwork); upgraded on `upgrade/04-ftir`.

Baseline: 170 tests (132 non-GUI + 38 GUI), all passing. The GUI file took 27 min because closed windows were never deleted, so each fixture setup grew from about 50 s to 190 s.

## Before the upgrade: the brief's targets against the code

| # | Target | State at 3.3.1 | Evidence |
|---|---|---|---|
| A | Equations checked with independent numbers | **PARTIAL**: unit tests existed, but no first-principles oracles | `tests/test_xrd_analysis.py`, `test_ftir_analysis.py` |
| A | Hostile and malformed files | **PARTIAL**: decimal comma and header lines were handled; UTF-16, ragged rows, NaN and binary files were not | probe of 14 files, then 41 tests (37 failed on 3.3.1) |
| 1 | Validation laboratory (measured test sets, confusion matrix, precision/recall, OOD, sensitivity) | **MISSING**: only a synthetic benchmark (`tools/benchmark_ftir_matching.py`) | |
| 2 | Matched-peak comparison, overlays | **DONE** (band-by-band found/missing/edge, card overlay) | `ftir_matching.score_entry` "bands"; "Check a suspected material" |
| 2 | Manual peaks with undo | **DONE** (3.2.0); assignment labels **MISSING** | |
| 2 | Uncertainty bands, robust constrained global fitting | **MISSING**: single-peak fits only, no errors | `peak_fitting.fit_peak` |
| 2 | Processing recipes, batch reports | **MISSING**: a processing log only | `metadata["processing"]` |
| 2 | Trace provenance | **PARTIAL**: Excel provenance sheet | `exports.excel_report` |
| 3 | Diffractometer import tests | **PARTIAL**: synthetic UXD/RAS/XRDML tests; no real files | `tests/test_file_readers.py` |
| 3 | Calibration with certified standards | **MISSING**: Caglioti U, V, W existed (instrument width), no position calibration | `xrd_analysis.fit_caglioti` |
| 3 | Preferred-orientation and amorphous warnings | **MISSING** | |
| 3 | Instrument-broadening propagation | **PARTIAL**: correction existed, no uncertainty | `correct_instrumental` |
| 3 | Peak indexing helpers | **PARTIAL**: single-peak cubic a and extinction note | `cubic_lattice_parameter` |
| 3 | Licensed / user-supplied phase cards | **MISSING** | |
| 4 | External refinement adapter | **MISSING** | |
| 5 | FTIR + XRD evidence workspace | **MISSING** | |
| 6 | Large spectra, crosshair, zoom, shortcuts, batch queue, preferences, labels, colour-blind plots, strict parsing, no hidden transmission | **PARTIAL**: zoom/pan toolbar, shortcuts, cursor x/y, house palette (no CVD option), no network code, but no display thinning, preferences or batch | `ui_common`, `labkit/qt` |

## Defects found (all reproduced by a failing test first)

| Defect | Where | Effect |
|---|---|---|
| Linear baseline wrong on descending axes | `modules/ftir_analysis.py` `baseline_correct` (np.interp with decreasing anchors) | The **Baseline correct** button on 4000 → 400 cm⁻¹ files left a 0.072 error at the ends in the test case |
| First derivative sign inverted on descending axes | `derivative_spectrum` (`mean(abs(dx))`) | 1st-derivative plots of normal FTIR exports were upside down |
| Fitted peak area truncated to the fit window | `modules/peak_fitting.py` `fit_peak` | Lorentzian −10.6 %, pseudo-Voigt −2.5 % in the tests |
| A row wider than the others became a data point | `file_readers._try_parse_two_column_text` | `x,y` then `1,2,3,4,5` gave a point at x = 1 that is not in the spectrum |
| NaN/inf rows silently truncated the file | same | 6 of 20 rows lost, reported only in an unshown "note" |
| UTF-16 exports refused | every text reader (`open(..., errors="ignore")`) | Common Windows instrument exports could not be loaded |
| JCAMP-DX DIF Y-check value counted twice | `read_jcampdx` | Valid compressed files refused (NPOINTS mismatch) |
| JCAMP-DX FIRSTX multiplied by XFACTOR | `read_jcampdx` | X axis wrong when XFACTOR ≠ 1 (FIRSTX is an actual value) |
| JCAMP-DX µm/nm axes treated as cm⁻¹ | `read_jcampdx` | Wavelength-axis files plotted on the wrong axis |
| Malformed XRDML raised `ParseError`, not `ValueError` | `read_xrdml` | Inconsistent error contract (the UI caught it anyway) |

## Risks

- **False identification** remains the main scientific risk. The FTIR score is a screening score, and generic XRD matching cannot prove a phase. Both are stated in the README, in every new report and in the evidence report.
- No measured reference data exist in the repository, so the matcher's real accuracy is unknown. The validation laboratory measures it once the owner supplies spectra.
- Bruker `.raw` parsing is still reverse-engineered and low confidence.
