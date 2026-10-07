# FTIR matching upgrade — plan

Status: implemented on branch `claude/intelligent-planck-3addcx`, then revised after four independent
reviews (spectroscopy, UX/UI, code, lab user) — see section 9.

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

## 3. Matching algorithm ("Weighted evidence", the default) — as implemented after review

Code: `modules/ftir_matching.py`. For each candidate material:

1. **Measured range.** Bands lying wholly outside the measured range (e.g. below 650 cm⁻¹ on a
   diamond ATR) are marked *outside* and left out of every score.
2. **Band weights (P1).** From the intensity label: very strong / strong 1.0, medium-strong 0.8,
   medium 0.6, weak-medium 0.45, weak 0.3, unlabelled 0.5. IR-inactive `[0, 0]` entries are skipped.
3. **Position score (P2, P7).** d = distance from the peak to the nearest edge of the band range;
   s = exp(−½(d/σ)²), σ = tol/2, 0 beyond the tolerance. Broad bands get twice the tolerance, but
   a sharp peak (FWHM < 40 cm⁻¹) counts only 0.3 for a broad band.
4. **Intensity agreement.** A strong band matched only by a weak peak (< 15 % of the strongest)
   counts 0.6.
5. **One-to-one assignment (P3)** by the Hungarian algorithm (`scipy.optimize.linear_sum_assignment`).
6. **Forward score** F = Σ w·s·f (found bands) / Σ w (bands in range).
7. **Reverse score (P5)** R = prominence of the peaks it explains / prominence of all peaks in its
   band region (lowest band − 50 to highest band + 50 cm⁻¹).
8. **Unexplained strong peaks elsewhere** U = 1 − 0.5·u, u = share of the sample's strong peaks
   (≥ 50 % of the strongest) that lie outside the material's region and stay unexplained.
9. **Chance (P4).** For each band, the background density is the number of peaks the material does
   *not* claim within ±150 cm⁻¹ (+1), per cm⁻¹; p_i = 1 − exp(−ρ_i·(width_i + 2 tol_i)). Hits are
   counted softly — a peak counts min(1, rel. prominence / 0.05) — and the Poisson-binomial tail
   P(X ≥ k) is interpolated for fractional k. Family-wise: P_f = 1 − (1 − P)^min(M, 20).
   S = min(1, −log₁₀P_f / 2).
10. **Match score** C = F^0.6 · R^0.4 · S · U. Tiers: **Strong** ≥ 0.60, **Moderate** ≥ 0.40,
    **Weak** ≥ 0.20, otherwise **Poor**. Strong additionally needs no missing strong band, more
    than two bands, and a margin of 0.10 over every other candidate; otherwise it is shown as
    Moderate with the reason ("close call with …").
11. **Look-alikes.** Pairs of database entries whose weighted bands overlap ≥ 80 % in both
    directions (129 pairs, e.g. PA11/PA12, Na₂CO₃/K₂CO₃, EPR/EPDM, stearic/palmitic acid) are
    listed with every top result: a peak list cannot separate them.
12. **Artefacts.** Peaks in the CO₂ region (2280–2400 cm⁻¹) and lines narrower than 4 cm⁻¹ in the
    water-vapour regions (1350–1950, 3550–3950 cm⁻¹) are ignored. Detection itself can skip the
    CO₂ region and applies a noise floor of 5 σ (σ from the median absolute point-to-point
    difference).
13. **Storage.** Results with no meaningful evidence are dropped; only the best 30 keep their
    band-by-band detail (the rest are re-scored on demand), which keeps sessions and undo small.

The legacy fraction-of-bands method stays available as **Coverage (legacy)**.

## 4. Mixture analysis (P6)

Greedy, but without stealing shared bands: after a component is accepted (C ≥ 0.35) its peaks
are marked *explained*. Later candidates may still use them as support for their own bands
(blends share bands, e.g. CH₂ rocking), but their reverse score, outside penalty and "newly
explained" peaks only count still-unexplained peaks, and intensity classes are relative to the
strongest unexplained peak so a minor component is not judged against the major one. Up to 3
components. *Share of peak intensity* is the fraction of summed prominence a component newly
explains — not a concentration.

## 5. Synthetic reference spectrum

One Gaussian per band (height = weight, FWHM = range width, min 12 cm⁻¹, 60 cm⁻¹ for broad
bands), drawn on the plot, and a Pearson correlation with the measured spectrum (converted to
absorbance in %T mode) reported as *Pattern r* — informational only.

## 6. Validation (`python tools/benchmark_ftir_matching.py`)

Spectra are simulated (pseudo-Voigt bands at random positions inside each literature range,
random heights and widths, sloping baseline, noise) and pass through the app's own peak
detection before matching. Scenarios: clean, noisy, atmospheric artefacts, ATR-like shifts;
plus a leave-one-out null (true material removed from the database), confusable pairs and
two-material blends. Results of the run on this commit are in section 10. The simulation is
built from the same band tables the matcher uses, so it is optimistic; it is **not** a
validation on lab spectra, which is still needed.

## 7. UX / UI (FTIR page)

- Cards numbered in workflow order: **1 · Processing**, **2 · Peak detection** (noise floor, skip
  CO₂, shoulders), **3 · Database screening** (search scope, tolerance with ATR guidance,
  scoring, *Hide scores below*, Match (Ctrl+M), Analyse as mixture).
- **Database matches** tab: filter (Ctrl+F, Enter selects the first row), Match button, Copy
  evidence, reference-band CSV, clear overlay; a one-line summary ("Screening: … listed, …
  hidden, best: …"); table # · Material · Match score (tier, colour + text) · Bands found ·
  Peaks explained · Chance p · Missing strong · Verdict, with header tooltips; an HTML evidence
  panel (verdict, warnings, band table with ✓ ≈ ✗ –); **Confirm… / Reject… / Clear verdict**.
- **Mixture** tab: Analyse and *Show all components* (each component's found bands in its own
  colour), summary, table with *Share of peak intensity* (tooltip: not a concentration) and the
  strong unexplained peaks (with a hint when 3200–3500 + ~1640 suggest absorbed water).
- Plot: detected peaks as short neutral ticks, only the strongest 15 labelled (25 cm⁻¹ apart) or,
  with an overlay, only the matched ones; bands in Okabe-Ito colours (found blue, edge orange,
  missing vermillion dashed) with a marker above each band and a real legend; title in the theme
  colour.
- Routine confirmations go to the status bar; toasts only for warnings and errors.
- Stale results are impossible to see: processing or re-detection clears matches, functional
  groups, mixture and overlay; background results arriving after undo are discarded.
- Exports: PDF gets *Method & parameters*, the match table, the evidence of the selected (or top)
  match, mixture evidence and analyst verdicts; Excel gets a settings sheet and verdict,
  look-alike and "listed in app" columns. Parameters are captured when matching runs.

## 8. Out of scope / future work

- Full-spectrum HQI against measured library spectra (needs a spectral library).
- Joint re-scoring of candidate pairs and a spectrum-level NNLS fit for mixtures (suggested by
  the science review; the greedy method with shared bands is the current compromise).
- Using baseline-corrected height or band area instead of prominence as the intensity measure.
- Validation on measured spectra of known materials, and curating weak/unreliable database bands.

## 9. Review log

Four independent reviewers (spectroscopy/chemometrics, UX/UI, code correctness, lab user) read
the first implementation. Every finding and what was done:

| Reviewer | Finding | Resolution |
|---|---|---|
| Science C1 | "Strong" when the true material is absent (41 % in leave-one-out) | Margin/missing-band/few-band gates on Strong; database look-alikes shown; leave-one-out added to the benchmark and reported honestly (section 10) |
| Science C2 | Hard 5 % significance cut makes the score jump | Soft hit counting, interpolated tail |
| Science C3 | Uniform density, uncapped M, 2-band entries unwinnable | Local background density, M capped at 20, few-band entries capped at Moderate instead |
| Science M1 | Noise peaks | 5σ noise floor in detection; warning above 60 peaks |
| Science M2 | CO₂ / water vapour / moisture | CO₂ skipped in detection, artefact peaks ignored in matching, absorbed-water hint |
| Science M3 | Window-limited R hides strong unexplained peaks | Outside-region penalty U |
| Science M4 | Minor components judged against the major one | Intensity relative to the strongest unexplained peak in mixture rounds |
| Science M5 | Greedy removal steals shared bands | Explained peaks stay available as support |
| Science M6 | Circular benchmark | Rebuilt at spectrum level through detection, with null, artefacts, pairs, blends, per-tier precision |
| Science m1 | Sharp peaks accepted for broad bands | FWHM < 40 cm⁻¹ counts 0.3 |
| Science m3/m4 | −0.0 scores; pattern r on %T | Clamped; converted to absorbance, min FWHM 12 |
| Code 1 | Out-of-range bands counted as missing | *Outside* status, excluded from scores and overlay |
| Code 2 | Result lost on undo but history recorded | Results for a replaced trace are discarded with a warning, no history entry |
| Code 3 | Stale matches / pattern r / current match | Cleared on processing, detection, revert, undo; pattern r not cached |
| Code 4 | 1 MB sessions, 60 MB undo | Zero-evidence results dropped, detail kept for top 30 only |
| Code 5/6 | Mixture ids relative to sub-list; NaN prominence | Ids index the full list; NaN-safe prominences |
| Code 7 | Weak tests | Tests for session round-trip, undo during a job, stale state, out-of-range, NaN, artefacts, look-alikes, verdicts, PDF/Excel |
| UX 1/2 | Peak markers in the "missing" red; overlapping labels | Neutral ticks; top-15 / matched-only labels with spacing |
| UX 3 | Toasts over results | Status bar for routine messages |
| UX 4/7/11 | Small-window mixture table, clipped toolbar and controls | Minimum heights, shorter toolbar, controls fitted to content on first show, column widths |
| UX 5/6 | Truncated title legend, red/green | Legend handles, theme title, Okabe-Ito + markers + line styles |
| UX 8 | Mono text evidence | HTML evidence panel with band table |
| UX 9 | Overstated certainty | "Match score" + tiers Strong/Moderate/Weak/Poor; "Share of peak intensity"; "Screening:" prefixes |
| UX 10 | Hard-to-find actions | Match/Mixture buttons in the tabs, Ctrl+M, empty-state hints |
| UX 12–19 | Header jargon, wording, curve visibility, stale overlay, keyboard, legacy text, combined mixture view | Header tooltips; consistent *bands* (reference) / *peaks* (sample); visible synthetic curve with legend; trace name in title and overlay cleared on trace switch; Ctrl+F/Enter; "n/a (coverage mode)"; *Show all components* |
| User C1 | Stale matches after processing | As Code 3 |
| User C2 | Settings not recorded | Parameters captured at match time; PDF and Excel sections |
| User C3/C4 | "Confidence 96 %", "Share of sample" | Renamed (see UX 9) |
| User M1 | README out of date, workflow order | README rewritten; cards numbered in workflow order |
| User M2/M3 | 2 % threshold picks up noise; tolerance guidance; hidden-count wording | Noise floor, tolerance tooltip, "N scoring below X hidden" |
| User M4 | Demo file named "Polyethylene.csv" | Screenshots regenerated with honest names |
| User M5/M6 | ⓘ written for programmers; plan ≠ code | Plain-language ⓘ; this document rewritten |
| User M7 | Evidence not exported | PDF evidence sections, Copy evidence |
| User minor | Verdicts, no-match guidance, legacy threshold, mixture tooltip | Confirm/Reject with note; guidance toast; threshold disabled for legacy; mixture tooltip |

Not done (recorded in section 8): pair re-scoring/NNLS for mixtures, height/area intensity,
comparing two traces' rankings side by side.

## 10. Benchmark results (this commit)

```
201 materials x 1 spectra per scenario, tolerance 10 cm-1, range 600-4000 cm-1

scenario   method      top-1  top-3   right answer tier (weighted)
clean      coverage    92.5%  98.5%   
clean      weighted    95.5%  97.5%   Strong 78%, Moderate 13%, Poor 5%, Weak 3%
noisy      coverage    91.5%  97.0%   
noisy      weighted    93.5%  96.5%   Strong 81%, Moderate 10%, Poor 5%, Weak 4%
artefacts  coverage    73.1%  81.6%   
artefacts  weighted    92.0%  94.0%   Strong 79%, Moderate 11%, Poor 7%, Weak 3%
atr-like   coverage    94.0%  98.0%   
atr-like   weighted    96.0%  98.0%   Strong 79%, Moderate 13%, Poor 5%, Weak 3%

Precision by tier of the top hit (all scenarios above, weighted):
  Strong    right 100.0%  (633 top hits)
  Moderate  right  91.8%  (97 top hits)
  Weak      right  72.7%  (33 top hits)
  Poor      right  29.3%  (41 top hits)

Leave-one-out null (true material removed from the library), tier of the top hit:
  Poor 35%, Moderate 23%, Weak 22%, Strong 20%

Two-material blends (80, minor component 40-100 %): both found 70%, one 26%, none 4%; 17 wrong components reported in total
```

Confusable pairs (5 spectra each): PE, PP, PET, PBT 5/5 correct and not flagged; PA6, PA66,
PA11 5/5 and PA12 4/5 correct, all 5/5 flagged as look-alikes (their band tables nearly
coincide in the database).

Reading these numbers: on simulated spectra the weighted method beats the legacy method in
every scenario, most clearly with atmospheric artefacts (92 % vs 73 % top-1); a top hit rated
Strong was right every time *when the material was in the database*. When it was not, the top
hit was still Strong 20 % of the time — almost always a chemical relative — which is why the
tier is a screening statement and look-alikes are shown. All of this is simulation from the
same band tables; lab validation is still needed.

