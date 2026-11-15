# Test report: repository 04

Environment: Windows 11, Python 3.14.5, `QT_QPA_PLATFORM=offscreen`, `MPLBACKEND=Agg`. Date 2026-11-15.

## Commands and results

| Step | Command | Result |
|---|---|---|
| Verify `feature/licensing` (non-GUI) | `py -3 -m pytest -q -p no:cacheprovider --ignore=tests/test_qt_app.py` | **132 passed** (26 s) |
| Verify `feature/licensing` (GUI) | `py -3 -m pytest -q -p no:cacheprovider tests/test_qt_app.py --durations=10` | **38 passed in 27 min 2 s**. Slowest were fixture *setups*, 51–188 s each, growing through the run |
| Same GUI file after the fixture fix | same | **38 passed in 50.6 s** |
| labkit sync | `py -3 sync.py --apply --test --only FTIR_XRD_Toolkit` (from `E:\Lab Apps\labkit`) | 1.1.0 → 1.2.0, +5 ~3 files, **288 passed** |
| Oracles against 3.3.1 code | `tests/test_oracle_equations.py` with the old modules first on `sys.path` | **5 failed, 31 passed** (3 defects + 1 missing conversion; area failures ×2) |
| Hostile files against 3.3.1 reader | `tests/test_hostile_inputs.py`, old `file_readers.py` | **37 failed, 4 passed** |
| Each milestone commit in a clean worktree | `py -3 -m pytest -q -p no:cacheprovider` | A `c01f789`: 247; B `0300f92`: 254; C `5f45a53`: 265; D `7923f4a`: 282; all passed |
| Milestone E `00fc221` | same | 289 passed |
| Full suite, final | `py -3 -m pytest -q -p no:cacheprovider` | **291 passed** (about 75 s) |
| Packaged-build self-test, from source | `py -3 main.py --selftest` | SELF-TEST PASSED |
| Version | `py -3 main.py --version` | FTIR & XRD Analysis Toolkit 3.4.0 |

## Counts

Before: 170 tests. After: 291. The 121 new tests are oracle 36, hostile files 41, validation lab 7, global fit and recipes 12, XRD tools 8, refinement/evidence/no-network 9, GUI workbench 8. No test was skipped, deleted or weakened. One existing test file changed: `tests/test_qt_app.py`, fixture teardown only.

## Why the GUI file was slow

Each test built a `MainWindow` and only closed it. Closed windows stayed alive in the session-wide `QApplication`, so every later setup did more work: 51 s, then 69 s, 110 s, up to 188 s. Teardown now processes pending events, then deletes the window. Run time fell from 27 min to 51 s, with the same 38 assertions.

## Not run or not verifiable here

| Item | Status | Reason |
|---|---|---|
| Real instrument exports (Bruker .raw, PANalytical .xrdml, Rigaku .ras, OPUS/OMNIC CSV, JCAMP-DX from vendors) | **UNVERIFIED** | No sample files were supplied; every importer test uses files written to the documented formats |
| Matcher accuracy on measured spectra | **UNVERIFIED** | No measured reference set exists. The validation laboratory is ready for one |
| GSAS-II / FullProf reading the `.xye` export | **UNVERIFIED** | Neither is installed (`find_spec('GSASII')` is None) |
| Installer build and installed-app smoke test | **NOT RUN** | The installer was not rebuilt this round. Source self-test passed |
| Screen reader and high-DPI pass on the new dialogs | **NOT RUN** | The new dialogs use the existing labelled form and text widgets; no manual AT test |
| Independent review by another assistant | **NOT RUN** | |
