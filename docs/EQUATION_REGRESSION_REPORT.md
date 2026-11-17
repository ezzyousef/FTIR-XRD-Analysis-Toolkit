# Equation regression report

The equations and algorithms listed in the tables below, each checked on the specific synthetic cases shown. The expected values are worked out from first principles (the `math` module), or the test signal's truth is known by construction. The code under test never computes its own expected value.

This report does **not** cover every equation, input domain or algorithm in the app. Passing these cases shows that the listed calculations reproduce the expected numbers on these inputs. It does not prove the algorithms correct in general. See "Scope" at the end.

Tests: `tests/test_oracle_equations.py` (36 tests). Run: `py -3 -m pytest -q -p no:cacheprovider tests/test_oracle_equations.py`. Last run 2026-11-15: **36 passed**. Against the 3.3.1 code the same file gave **5 failed, 31 passed**. The five failures were three real defects (fixed below) and one missing conversion (added).

Constants: Cu Kα1 λ = 1.5406 Å, as the brief asks. The app's own table uses 1.540562 Å; both are tested. Angles are in degrees unless stated. Every FWHM goes into Scherrer and Williamson–Hall in **radians**.

## XRD

| Quantity | Synthetic input (known truth) | Expected, worked from first principles | App |
|---|---|---|---|
| Bragg, d = nλ / (2 sin θ) | 2θ = 30°, λ = 1.5406 Å | 1.5406 / (2 · sin 15°) = **2.976211 Å** | equal to 1e-12 |
| Bragg round trip | d = 4, 3, 2, 1.2, 0.9 Å → 2θ = 22.2062°, 29.7566°, 45.3061°, 79.8698°, 117.7161° | the same d back | equal to 1e-12 (both directions) |
| Second order, unreachable line | n = 2; d < λ/2 | d doubles; `None` | as expected |
| Scattering vector | Q = 4π sin θ / λ at 10°, 44.5°, 120° | Q · d = 2π | equal to 1e-12 |
| σ(d) | 2θ = 38°, σ(2θ) = 0.01° | central-difference derivative of Bragg × σ | equal to 1e-6 |
| Cubic a | a = 4.0 Å, (111), (200), (220), (311) | a = d √(h²+k²+l²) = 4.0 Å | equal to 1e-12 |
| Peak position | Gaussian at 2θ(d = 2.5 Å) = **35.8919°**, FWHM 0.20°, step 0.01° | detection within half a step; fit centre exact | detected ±0.005°, fitted 1e-6°, d = 2.5 Å to 1e-6 |
| Scherrer, τ = Kλ / (β cos θ) | K = 0.9, β = 0.5° = 0.0087266 rad, 2θ = 40° | 0.9 × 0.15406 nm / (0.0087266 × cos 20°) = **16.9083 nm** | equal to 1e-12; K enters linearly |
| Scherrer from a simulated peak | D = 20 nm at 2θ = 35° → β = **0.41649°** | fitted FWHM, then 20 nm | FWHM 1e-6 rel., D 1e-5 rel.; detection FWHM within one step |
| Instrument broadening, Gaussian | D = 30 nm at 50° (β = 0.29219°), instrument b = 0.08° → B = √(β² + b²) = 0.30294° | β back, then 30 nm | equal to 1e-12 |
| Instrument broadening, Lorentzian | B = β + b = 0.37219° | β back | equal to 1e-12 |
| Width not above the instrument | B = 1.02 b | no size | `None` |
| Quadrature rule itself | numerical convolution of 0.3 and 0.4 Gaussians | 0.5 | 0.5 to 1e-3 |
| Caglioti U, V, W | H² = U tan²θ + V tanθ + W with U = 0.004, V = −0.002, W = 0.003 at six angles | the same U, V, W | equal to 1e-12 |
| Williamson–Hall | β cos θ = Kλ/D + 4ε sin θ, D = 25 nm, ε = 2×10⁻³, six peaks | 25 nm, 2×10⁻³, R² = 1 | equal to 1e-9 |
| Kα2 stripping | doublet at 2θ₁ = 70°, 2θ₂ from exact Bragg = **70.1995°**, ratio 0.5 | the Kα1 peak alone | within 2 % of peak height everywhere |
| Kα2 offset, small-angle formula | same angle | exact separation 0.19950° | 0.19938° (0.06 % low; stripping uses the exact angle) |
| Crystallinity | crystalline Gaussian h = 800, FWHM 0.5° plus amorphous halo h = 100, FWHM 6° (area = h·FWHM·1.0645) | **40.0 %** | 40.0 % (1e-3 rel.) |
| SNIP background | flat 200 counts plus a 2000-count, 0.2° peak, 2° window | 200 under the peak | within 2 % |

## FTIR

| Quantity | Synthetic input | Expected | App |
|---|---|---|---|
| A = −log10 T = 2 − log10 %T | %T = 100, 50, 10, 1 | 0, **0.30103**, 1, 2 | equal to 1e-12; inverse equal; the peak-measuring signal gives the same A from %T and from 0–1 T |
| Wavenumber ↔ wavelength | λ(µm) = 10⁴ / ν̃(cm⁻¹) | 1000 cm⁻¹ = 10 µm, 4000 cm⁻¹ = 2.5 µm | **added in 3.4** (was missing); a JCAMP-DX file in µm or nm is now converted on import |
| Linear baseline | Gaussian band + 0.05 + 2×10⁻⁵·ν̃ on a 4000 → 400 cm⁻¹ axis | the band alone | **was wrong on descending axes (error 0.072 at the ends); fixed**, now 1e-9 |
| Peak area | Gaussian h = 0.6, FWHM 16 cm⁻¹ | h·FWHM·√(π/(4 ln 2)) = **10.2189** | 1e-6 rel., either axis direction |
| FWHM, absorbance and %T | Gaussian FWHM 24 cm⁻¹; %T = 100·10^(−A) | 24 cm⁻¹ in both modes | 0.2 % |
| Beer–Lambert, c = A / (εl) | A = 0.45, ε = 150 L mol⁻¹ cm⁻¹, l = 0.01 cm | 0.3 mol/L | equal |
| Normalisation | max, min-max, vector, area | max = 1; range 0–1; ‖y‖₂ = 1; ∫\|y\|dν̃ = 1 | equal |
| ATR correction | A_ATR = A · d_p(ν̃)/d_p(1000), d_p = λ / (2π n₁ √(sin²θ − (n₂/n₁)²)), diamond n₁ = 2.4, n₂ = 1.5, 45° | A back | equal to 1e-12 |
| Savitzky–Golay derivative | y = 3×10⁻⁶ ν̃³ − 2×10⁻³ ν̃² on ascending and descending axes | dy/dν̃ = 9×10⁻⁶ ν̃² − 4×10⁻³ ν̃; d²y/dν̃² = 1.8×10⁻⁵ ν̃ − 4×10⁻³ | **first derivative had the wrong sign on descending axes; fixed**, now 1e-6 rel. |

## Peak fitting

| Quantity | Synthetic input | Expected | App |
|---|---|---|---|
| Gaussian parameters and area | h = 0.7, ν̃₀ = 1650, FWHM 12 cm⁻¹, offset 0.02 | area = h·FWHM·1.0645 = 8.9415 | 1e-6 rel. |
| Lorentzian area | same parameters | area = π·h·FWHM/2 = **13.1947** | **was 11.80 (−10.6 %), the part inside the fit window only; fixed** |
| Pseudo-Voigt area | h = 1, FWHM 0.4, η = 0.3 | h·FWHM·(η·π/2 + (1−η)·1.0645) = **0.48655** | **was 0.47458 (−2.5 %); fixed** |

The window-limited area is still returned as `area_in_window` for anyone who needs it. Fitted parameters now also carry 1σ standard errors (`stderr`) from the fit covariance.

## Global fit and uncertainty (new in 3.4, `tests/test_global_fit_recipes.py`)

| Check | Result |
|---|---|
| Two overlapping Gaussians (1640/18 and 1662/14 cm⁻¹) on a sloping baseline | heights, centres, widths and baseline recovered to 1e-6 |
| Reported σ(centre) against the spread of 60 noisy repeats | agree within 30 % (the sampling error of a standard deviation from 60 values is about 9 %) |
| 2σ delta-method band | brackets the true curve at more than 80 % of points |
| Robust (soft-L1) against plain least squares, 12 spikes of +0.6 | robust height error < 5 %, smaller than plain least squares |
| XRD size uncertainty with instrument broadening | analytic propagation within 5 % of a 200 000-draw Monte Carlo |

## Defects found and fixed

1. **Linear baseline on descending axes** (`modules/ftir_analysis.py`, `baseline_correct`). With the default end-point anchors and a 4000 → 400 cm⁻¹ axis, `np.interp` got decreasing anchor positions and returned a wrong baseline. This is the path behind the **Baseline correct (linear)** button, so every FTIR file stored high-to-low wavenumber, which is the usual export order, was affected. Fixed by sorting the anchors.
2. **First derivative sign on descending axes** (`derivative_spectrum`). The step was taken as `mean(|Δx|)`, so d/dν̃ on a 4000 → 400 axis came out negated. The second derivative was unaffected. Fixed with the signed step.
3. **Fitted peak areas** (`modules/peak_fitting.py`, `fit_peak`). The area was integrated only inside the fit window, so Lorentzian areas were about 10 % low at a ±3 FWHM window, and pseudo-Voigt areas were low in proportion to η. The area is now the analytic area of the whole fitted profile.

Each fix has a test that failed on 3.3.1 and passes now.

## Observed, not changed

- `baseline_correct` with anchors *inside* the spectrum holds the baseline flat beyond the outermost anchors (np.interp). The app's button always uses the end points, so this path is not reachable from the UI. The behaviour is documented in the test.
- Synthetic PTFE (four bands) only reaches the Weak tier in the matcher. This is by design: cards with few bands cannot reach Strong.

## Scope: what kind of check each row is

- **Equation checks**: closed-form identities evaluated at stated inputs. Bragg, Q, σ(d), cubic a, Scherrer, broadening rules, A = −log10 T, ν̃ = 10⁴/λ, Beer–Lambert, normalisation, ATR, analytic peak areas, Caglioti.
- **Recovery checks**: a synthetic signal built from known parameters, then the app must recover them. Peak position, Scherrer from a simulated peak, Williamson–Hall, Kα2 stripping, crystallinity, SNIP, baseline, derivatives, all fits. These hold only for the shapes, noise levels and grids tested.
- **Consistency checks**: errors and bands against Monte Carlo spread, robust against plain fits. They show agreement, not exactness.
- **Implementation regressions** from the independent Codex review (`tests/test_codex_review.py`, 12 tests):
  - derivatives on uneven axes, as after a µm→cm⁻¹ import or dropped NaN rows; the method is stated in the processing log;
  - JCAMP-DX per-line X checks, XYPOINTS endpoints and multi-digit DUP counts;
  - record-width checks in the text reader;
  - the identifiability of zero-shift + displacement calibration.

## Input domains not verified

- Real instrument files of any format; vendor JCAMP-DX variants beyond the spec cases written here.
- Very noisy or strongly overlapped spectra, non-Gaussian instrument profiles, and asymmetric peaks. Fits assume symmetric profiles.
- Lattices other than cubic for indexing; textured samples beyond the intensity-ratio warning.
- Matcher accuracy on measured spectra (see the validation laboratory).

## What this does not cover

- Measured spectra and patterns: none were supplied, so every check uses synthetic data. These checks show that the arithmetic is right. They do not show that the band tables, the matcher or a real instrument's output are right.
- The Bruker .raw reader: no sample files, so it stays "best effort" with a low-confidence flag, as before.
- Literature values (certified d-spacings, reference spectra) were not added or checked. The new calibration and phase-card tools take them from the user's own licensed sources.
