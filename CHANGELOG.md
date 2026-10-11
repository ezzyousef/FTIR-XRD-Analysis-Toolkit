# Changelog

## 3.2.0

From user testing, then five independent reviews (spectroscopy, usability, state and undo, edge cases, references) and a Codex review; every finding was reproduced before it was fixed.

- **Normalization:**
  - Applying normalization again, or with another method, replaces the previous one instead of stacking on it.
  - **Remove normalization** restores the curve before normalizing. Later steps are kept, and it still works after reloading a saved session.
  - An "Applied:" line lists the processing in effect.
  - When the spectrum is normalized, the y axis says so (the curve itself keeps its shape).
  - Normalizing %T data now asks first.
  - Flat or all-zero data gives an error instead of an all-NaN spectrum.
- **Peaks by hand:**
  - **Pick peaks on the graph**: left-click adds a peak, right-click removes one, Esc stops.
  - A click snaps to a real maximum within 10 cm⁻¹, found on a lightly smoothed copy so noise does not pull it off-centre. Otherwise it stays where you clicked, marked as a shoulder.
  - The zoom is kept while picking.
  - Hand-picked peaks get an open circle and a Source column, also in the PDF.
  - Detect peaks asks whether to keep them.
  - The report records how the peaks were made.
- **Detection:**
  - "Sensitivity" is renamed **Minimum peak size (higher = fewer)**.
  - New: **Minimum separation** in cm⁻¹, and **Keep at most** N peaks.
  - In %T mode, peak heights and widths are measured on absorbance.
  - The second-derivative detector no longer reports peaks between side lobes.
- **Check a suspected material:**
  - Pick any of the 237 cards: its bands are drawn on your spectrum and marked found / not found as you add peaks.
  - The card stays on screen when peaks change.
  - Bands outside your data are not drawn.
  - IR-inactive materials are explained.
- **References:**
  - Each card shows its full citations, in the evidence panel, Copy evidence, the PDF and the reference-bands CSV.
  - The 24 cards that cited only "IR literature" now cite checked papers (22). Dextran and grey selenium keep the general tables, with a note.
  - The PDF uses a Unicode font.
- **Database 4.4 corrections:**
  - PLA 921 cm⁻¹ crystalline band added (955 cm⁻¹ is amorphous).
  - PVA 1141 cm⁻¹ crystallinity band.
  - Gypsum ν₁ moved to 1005 cm⁻¹, and the ν₂ band relabelled.
  - NaHCO₃ 835 cm⁻¹ band added; the 3430 cm⁻¹ band is relabelled as adsorbed water.
  - Graphite, MoS₂ and Si IR-active modes.
  - h-BN range widened; six hydrogel ranges widened to their sources.
  - The audit tool now rejects any reference that does not resolve.
- **Fixes:**
  - Baseline correction keeps an earlier ATR correction.
  - A verdict can no longer land on the wrong spectrum.
  - Background results are discarded after any peak edit.
  - Peak widths are correct on uneven grids.
  - A double-click no longer acts twice.

## 3.1.0

- FTIR matching uses weighted evidence. Bands count by strength. The score combines forward and reverse coverage and estimates the chance of a coincidental match. Each match gets a tier: Strong, Moderate, Weak or Poor.
- Materials that a peak list cannot tell apart ("look-alikes") are shown next to a strong match.
- Reference database 4.3:
  - 237 materials with provenance;
  - additions from online sources are marked where they still need checking against a measured spectrum;
  - `tools/audit_ftir_database.py` checks structure and citations.
- XRD:
  - Kα2 stripping;
  - instrumental broadening correction (Caglioti U, V, W);
  - Williamson–Hall standard errors;
  - peak detection against the local noise.
- Windows build on GitHub Actions: the installer and portable zip are downloadable from each run.
- Details: `docs/FTIR_MATCHING_PLAN.md`, `docs/XRD_REVIEW.md`, `docs/FTIR_DATABASE_AUDIT.md`.
