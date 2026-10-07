# FTIR matching upgrade — plan

Status: implemented on branch `claude/intelligent-planck-3addcx` (see "Delivery" at the end).

## 1. What the current matcher does, and where it goes wrong

`ftir_analysis.match_peaks_to_database` compares each detected peak with each reference band
range (± tolerance) and scores a material as

    score = (# reference bands with any peak inside range ± tol) / (# reference bands)

and ranks by the number of matched bands first.

Problems found by reading the code and the database (1,451 reference bands, 224 materials):

| # | Problem | Consequence |
|---|---------|-------------|
| P1 | Every band counts the same. The database labels each band strong / medium / weak / broad, but those labels are not used. | Missing a material's strongest band (e.g. the C=O of PET) costs no more than missing a weak overtone. |
| P2 | A peak 0.5 cm⁻¹ from the band and one at the edge of the tolerance count the same. | No ranking signal from position accuracy. |
| P3 | One observed peak can satisfy several reference bands of the same material. | Double counting inflates the score of materials with closely spaced bands. |
| P4 | Ranking by the number of matched bands favours materials with long band lists. | Large entries get many matches by coincidence, especially in crowded spectra. |
| P5 | Nothing checks the reverse direction: whether the material explains the sample's strong peaks. | A material can rank first while the strongest peaks in the sample are left unexplained. |
| P6 | Only one material is considered at a time. | Blends, composites and contaminated samples are common, and the matcher cannot report "PET + something else". |
| P7 | Broad bands (O–H, N–H, hydrogen-bonded) use the same tolerance as sharp ones. | Real broad-band hits are missed or rejected. |
| P8 | The UI shows a bare percentage. | Users cannot see why a material ranked where it did, or how much to trust it. |

## 2. Literature basis (what was checked, and its limits)

A literature search (Consensus) supports the general direction. These sources do **not**
validate the specific formulas below; they show the problems are recognised in practice:

- Automated library matching can misidentify materials, and a high Hit Quality Index (HQI) did
  not always correspond to a correct identification (Kozloski et al., 2024, *Microplastics and
  Nanoplastics*). → Report more than one number, and show the evidence behind a ranking.
- Searching in both directions (forward and backward) and requiring agreement improved
  confidence in paint library searches (Lavine et al., 2016, *Talanta*). → The forward
  (reference → sample) and reverse (sample → reference) scores below.
- Review of the criteria used to compare IR spectra, including similarity scores and likelihood
  ratios (Lavine et al., 2020, *Forensic Chemistry*). → A probability that a match arose by
  chance, as an addition to the similarity score.
- Pre-filtering by functional group / class before the detailed search (Lavine et al., 2012,
  *Applied Spectroscopy*). → The existing category filter is kept.

The database stores **band ranges, not full spectra**, so full-spectrum HQI (correlation of
two measured spectra) cannot be computed directly. The new scoring is a **peak-list heuristic
designed for this database**. Its weights and thresholds are engineering choices, not published
constants. They are documented, shown in the ⓘ panel, and tested on synthetic data only
(section 6). They should be validated on real lab spectra of known materials before anyone
relies on them.

## 3. New matching algorithm ("weighted evidence", the new default)

For each candidate material:

1. **Band weights (P1).** Each reference band's weight comes from its intensity label: very
   strong 1.0, strong 1.0, medium-strong 0.8, medium 0.6, weak-medium 0.45, weak 0.3, unknown
   0.5. IR-inactive placeholders `[0, 0]` are skipped, as before.
2. **Position score (P2, P7).** d = distance from the observed peak to the nearest edge of the
   band range (0 inside the range). s_pos = exp(−½·(d/σ)²) with σ = tol/2, so a peak inside
   the range scores 1 and a peak at the tolerance edge scores about 0.14. Bands labelled broad
   get twice the tolerance.
3. **Intensity agreement.** Observed peaks are given a strong / medium / weak class from their
   prominence relative to the largest detected peak (≥ 0.5 / ≥ 0.15 / below). If a strong
   reference band is matched only by a weak observed peak, the match is multiplied by 0.6; a
   one-class difference costs nothing.
4. **One-to-one assignment (P3).** Observed peaks are assigned to reference bands with the
   Hungarian algorithm (`scipy.optimize.linear_sum_assignment`), maximising Σ weight·s_pos·s_int.
   Each observed peak supports at most one band per material.
5. **Forward score**, the weighted coverage of the reference:
   F = Σ w·s_pos·s_int (matched) / Σ w (all bands).
6. **Reverse score (P5)**, the share of the sample's peaks that this material accounts for,
   inside the material's own spectral window (lowest band − 50 to highest band + 50 cm⁻¹, because
   reference lists are incomplete outside that window):
   R = Σ prominence(assigned peaks) / Σ prominence(all peaks in the window).
7. **Chance probability (P4).** Peak density ρ = N_peaks / spectral span. The chance that band
   *i* is hit by coincidence is p_i = 1 − exp(−ρ·(width_i + 2·tol_i)). The number of bands hit
   by chance follows a Poisson–binomial distribution, computed exactly by dynamic programming.
   P_chance = P(X ≥ k matched). This is the main fix for large band lists matching noise.
8. **Confidence**:
   C = F^0.6 · R^0.4 · (1 − P_chance), and C = 0 if no band matched.
   Tiers: **High** ≥ 0.60, **Medium** ≥ 0.40, **Low** ≥ 0.20, otherwise **Weak**.
9. **Missing strong bands** are listed explicitly (strong or very strong bands with no
   assigned peak) and shown in the table and detail panel.
10. **Ranking** is by C. The old coverage fraction is kept as `coverage`.

Backward compatibility: the result keeps `name, category, source, score, matched_count,
total_reference_peaks, matches`, so exports, sessions and the selftest keep working. `score`
now holds C. The legacy algorithm stays available as **Coverage (legacy)** in a method selector,
and older sessions whose matches lack the new keys still display.

## 4. Mixture analysis (P6)

`analyse_mixture(peaks, db, …)`:

1. Rank the candidates on the peaks still unexplained.
2. Accept the best candidate if C ≥ 0.35 and it explains at least one peak that no accepted
   component already explains.
3. Remove the peaks it was assigned and repeat, up to 3 components.
4. Report each component (its confidence, the peaks it explains, and its share of the total
   peak prominence), followed by the peaks left unexplained.

This is a greedy, peak-space analogue of residual subtraction. It is a screening aid, and the
UI says so.

## 5. Synthetic reference spectrum (visual check)

`synthetic_reference_spectrum(entry, x)` builds a pseudo-spectrum by placing one Gaussian per
reference band, with height set by the band weight and FWHM equal to the range width, at least
8 cm⁻¹ (or 60 cm⁻¹ for broad bands). It also computes a Pearson correlation with the measured
spectrum over the material's window and reports it as **Pattern r**. Pattern r is informational
only and is not part of C, because the reference band shapes are approximations.

## 6. Validation (synthetic benchmark, `tools/benchmark_ftir_matching.py`)

For every database material with ≥ 3 matchable bands, the benchmark simulates a measurement
from the band centres:

- Gaussian position jitter (σ = 3 cm⁻¹)
- 30 % of weak bands dropped
- 5 spurious peaks added at random positions
- the same random seed for both methods

It then reports top-1 and top-3 retrieval accuracy for the legacy and weighted methods, plus a
two-material mixture test. These results only show behaviour on idealised synthetic data. They
are not a measure of accuracy on real samples.

Unit tests (`tests/test_ftir_matching.py`) cover:

- PET ranks first
- random peaks get Low or Weak confidence
- a missing strong band lowers confidence more than a missing weak band
- one-to-one assignment
- P_chance is monotonic in peak density
- the legacy method still matches the old behaviour
- mixture analysis separates two materials
- old-format matches still display and export

## 7. UX / UI changes (FTIR page)

Principles: show the evidence, not just a number; follow the existing labkit theme tokens in
light and dark mode; colour is never the only signal (tier text plus colour, and ✓ ✗ ≈ marks);
keep the screening disclaimer visible.

- **Database identification card**: a *Scoring* selector (Weighted evidence (recommended) /
  Coverage (legacy)), a *Minimum confidence to list* setting, the existing tolerance and category
  controls, **Match to database** (primary), a new **Analyse as mixture** button, and ⓘ for both.
- **Database matches tab**:
  - a filter box that searches material names
  - columns: Rank · Material · Confidence (tier + %) · Bands (weighted coverage) · Sample
    explained · Chance p · Missing strong · Category
  - confidence cells tinted by tier
- **Match detail**: a summary sentence explaining the rank, then each reference band marked
  ✓ matched (with Δ cm⁻¹ and the observed peak), ≈ edge (position score < 0.5), or ✗ missing
  (flagged ⚠ if strong), followed by the Pattern r note.
- **Plot overlay**: matched bands shaded green, missing bands as red dashed lines, missing strong
  bands drawn heavier, the synthetic reference curve drawn faintly on a secondary axis, and the
  material name and tier in the title row.
- **New "Mixture" tab**: a table of components and a list of unexplained peaks; clicking a
  component overlays its bands.
- **Exports**: the Excel match table, PDF report and reference-peaks CSV gain the new columns,
  with fallbacks for old results.
- **ⓘ text** (`formula_sources`): the full method from section 3, with the honest caveats from
  section 2.

## 8. Out of scope

- Full-spectrum HQI against measured library spectra (needs a spectral library, which this
  database does not contain).
- Machine-learned classifiers (no labelled training spectra).
- Changing the reference database values.

## Delivery

1. Plan (this file).
2. `modules/ftir_matching.py` (new algorithm, mixture analysis, synthetic spectrum), wired in
   through `ftir_analysis.match_peaks_to_database(method=...)`.
3. UI changes in `modules/ftir_tab.py`, plus exports, ⓘ texts and README.
4. Tests and the benchmark. All existing tests must still pass.
