# FTIR & XRD Analysis Toolkit 3.4.0: release notes

## Please read: three results change

1. **Linear baseline.** If your FTIR files run from high to low wavenumber (most do), **Baseline correct (linear)** used to subtract a wrong baseline. Re-run it on those spectra and redo anything that depends on it, such as peak heights after baseline correction.
2. **First derivative.** On those files the first-derivative curve was upside down. Second-derivative results are unchanged.
3. **Fitted peak areas** now include the whole fitted peak. Lorentzian areas go up by about 10 %, and pseudo-Voigt areas by a smaller amount. Centres, widths and heights do not change.

Sessions saved with earlier versions open as before. Results stored in them keep their old values until you re-run the step.

## Files load more reliably and never silently lose data

- UTF-16 files (common from Windows instrument software) now load.
- Empty and binary files are refused with a clear message.
- A row with more values than the others is refused, with its line number.
- Rows with NaN or inf are dropped, and you are told which lines.
- You are warned when extra columns or other blocks of numbers in a file were not used.
- JCAMP-DX:
  - DIF-compressed files now load;
  - files with an XFACTOR get the right x axis;
  - files in micrometres or nanometres are converted to cm⁻¹.

## New in the Tools menu

- Global peak fitting with error bars.
- Labels for peaks.
- Processing recipes and batch runs.
- A **validation laboratory** to measure how often the database matcher is right on your own measured spectra.
- XRD calibration against a standard, cubic indexing candidates, phase-card cross-checks against your own licensed cards, warnings for amorphous background and texture, and export for GSAS-II/FullProf.
- A one-page **evidence report** that puts a sample's FTIR and XRD results side by side.
- A colour-blind-safe palette and Preferences.

## What it does not do

- It does not identify materials or phases. A "Strong" FTIR match or a "consistent" XRD card is a lead to confirm, not a result.
- It ships no reference spectra and no phase cards.
- It does not run Rietveld refinements.

## Privacy

Nothing is sent anywhere. A test checks that no module imports a network library and that loading and matching open no connection.
