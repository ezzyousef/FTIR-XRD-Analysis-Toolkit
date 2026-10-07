# XRD page — review and revision

Two independent reviewers (an XRD scientist/code reviewer who ran simulations, and a UX
designer who is a daily XRD user) read the XRD page. This is what they found and what was done.

## Validation of the revised analysis (simulated CeO₂-like patterns)

Pseudo-Voigt reflections of a = 5.411 Å, Gaussian instrument width 0.08°, Kα1 + Kα2 (ratio 0.5),
Poisson noise, 0.01° step, background 50 counts. Pipeline: SNIP (2°) → Kα2 strip → detect (7σ
local noise) → pseudo-Voigt fit (±3 FWHM) → instrument correction (Gaussian) → Scherrer / W–H.

| Truth | Before (raw, no correction) | After |
|---|---|---|
| D = 80 nm, ε = 0 | Scherrer 16–96 nm (median ≈ 54); W–H 37 ± 22 nm, ε < 0, R² 0.01 | Scherrer median ≈ 79 nm; W–H 78–85 ± 2–3 nm, ε ≈ 0 |
| D = 20 nm, ε = 0 | W–H 21.9 nm with a spurious ε = 0.7×10⁻³ (R² 0.96) from Kα2 | W–H 20.1–20.2 ± 0.2 nm, ε ≈ 0 |
| D = 20 nm, ε = 3×10⁻³ | many noise "peaks" (27 for 10 reflections) | W–H 17–18 ± 4 nm, ε ≈ 2.0–2.1 ± 0.9 ×10⁻³ |

These are simulations; check against a measured standard on your instrument.

## Findings and resolutions

| Source | Finding | Resolution |
|---|---|---|
| Science C1 | Kα2 ignored | Rachinger stripping (Cu pre-filled; other anodes: enter Kα2); W–H panel warns if not stripped |
| Science C2 | Noise spikes and raw-point widths fed into size/strain | Local-noise (7σ) detection, sub-peak and spike removal, per-peak *Use* ticks, fitted widths used when available, peaks narrower than the instrument excluded with a note |
| Science C3 | No instrumental correction | Instrument profile (constant or Caglioti U, V, W), refinement from a standard, Gaussian/Lorentzian subtraction, no size when B ≤ 1.05 b, > 150 nm flagged |
| Science M4 | Fixed ±0.5° fit window | Default ±3 × each peak's width |
| Science M5 | SNIP window in points | Window in degrees, converted from the step |
| Science M6 / UX 2 | Crystallinity after SNIP meaningless; stale | Always on raw data minus a straight baseline; regions on the plot; own results tab |
| Science M7 / UX 1 | Results stale after λ change; Custom cancel fell back silently | λ, K or profile changes clear derived results; cancel restores the previous choice; file wavelength flagged; exports print the stored λ |
| Science M8 / UX 5 | W–H without uncertainty or plot | SE of D and ε, R², plot, peaks used, parameters and warnings |
| Science M9 | Readers returning wrong data silently | UXD counts blocks/ranges, header-proof text parsing, decimal commas, RAS intensity block + attenuation + header, xrdml list positions + attenuation + counting time, multi-scan warnings; tests for each |
| Science m10 | Peaks sorted by intensity | Sorted by 2θ |
| Science m11/m12 | No d precision; non-integer hkl | Precision per 0.01° in the lattice tool; whole-number hkl with extinction note |
| Science m13 | SNIP discarded smoothing; smoothing broadens | Processing works on the current pattern and is logged; smoothing warns |
| Science m15 | Unverifiable SNIP software claim | Removed |
| Science m16 | Converter message for Q/d ≤ 0 | Positive values required |
| UX 3 | Fit could land on changed data | Results for a replaced or changed pattern are discarded |
| UX 4 | Workflow order | Numbered cards 1 Instrument → 6 Fitting, plus Tools |
| UX 6/9 | Hidden assumptions, overclaiming | K, profile, width source and processing recorded and shown; "apparent size", 3 significant figures |
| UX 8 | Peak lines looked like gridlines | ▼ markers with 2θ labels; hollow for excluded peaks |
| UX 10/11 | Tables; modal-only results | I/I₀, use, β, note columns; fits with shape; *Calculations* tab |
| UX 13 | PDF/Excel provenance | Method & parameters, fits, W–H statistics, formatted regions, calculations; Excel settings from the stored parameters |

## Not done (needs data or a larger change)

- Bruker `.raw` binary: the layout is undocumented and no sample file was available; the reader
  still refuses files it cannot parse rather than guessing. Export ASCII instead.
- Interactive region selection on the plot (SpanSelector); regions are typed and then drawn.
- Doublet-aware fitting, multi-peak simultaneous fitting, size–strain plot, multi-peak lattice
  refinement (Nelson–Riley), batch processing, stick-pattern overlays.
- Kα2 wavelengths for anodes other than Cu are not pre-filled (values must come from the
  instrument documentation). The Cr Kα1 and Ag Kα1 entries in the wavelength table could not be
  confirmed to the last digit by the reviewer; check them against a primary table.
