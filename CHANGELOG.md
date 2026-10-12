# Changelog

## 3.3.1

- **Foldable left column:** every card has a ▾/▸ toggle (or click its title); the app remembers what you folded. Calculations, Tools and Files & session start folded, so the column is far shorter.
- **Cancel** for background jobs (database matching, mixture screening, peak fitting): a Cancel button under the plot gives control back at once; the job's late result is discarded.

## 3.3.0

- **Figures in the lab's house style (Figure Studio's):** the "Review" palette and Figure Studio's Light/Dark colours, DejaVu Sans with bold axis titles and tick labels, an open frame, outward ticks, a horizontal grid only and a frameless legend — on screen and in every PNG/SVG/PDF export.
- **Accessibility (WCAG 2.2 AA), from a UX/accessibility review:**
  - Visible keyboard focus on buttons, inputs, check boxes, radio buttons and table items.
  - Input and check-box outlines that meet 3:1 contrast.
  - Accent-coloured text (selected tabs, link-style buttons) at 4.5:1 or better in both themes.
  - Readable section headings in the side bar.
  - Labels tied to their inputs (Alt+letter focuses the field; screen readers announce it).
- **Peaks from the keyboard:** type a wavenumber and press Add (or Enter) to add a peak; select a peak in the Peaks table and press Delete to remove it.
- **Dialogs keep your input:** a mistake (e.g. crystallinity regions that are not "18-24") is shown in the dialog, which stays open with the field selected.
- **XRD:** crystallinity regions in the house colours, with visible edges.
- **ⓘ buttons** say what they explain (tooltip and screen-reader name).
- **FTIR:** dark-theme band markers in Review colours that keep 5:1 on the dark plot.
- **Keyboard:** Esc ends peak picking wherever the focus is; Tab leaves tables instead of cycling inside them; the plot toolbar (zoom, pan, save) is reachable with Tab; every caption is tied to its input on every page.
- **Every dialog checks its numbers** before closing and keeps your input on a mistake.
- **Cards numbered in order** (1 Processing … 6 Calculations); XRD's "Sensitivity" is now "Minimum peak size (higher = fewer)", as on the FTIR page.
- Revert, Clear peaks and Remove say "Ctrl+Z to undo"; the peak-entry box follows the spectrum's range.

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
- **More reference cards (database 4.5, 293 materials):**
  - 56 new cards: 40 metal oxides, hydroxides, battery oxides and spinel ferrites (Co3O4, NiCo2O4, Mn3O4, Mn2O3, Cu2O, hematite, magnetite, maghemite, goethite, α/β-Ni(OH)2, Co(OH)2, NiFe-LDH, anatase, rutile, In2O3, β-Ga2O3, Y2O3, La2O3, Nb2O5, Gd2O3, m-HfO2, SrTiO3, α/γ-Al2O3, boehmite, gibbsite, brucite, LiCoO2, LiMn2O4, NMC111, LiNi0.5Mn1.5O4 (ordered and disordered), Li4Ti5O12, Li2MnO3, and Zn/Co/Ni/Mn/Cu ferrites) and 16 polymers (α- and β-PVDF, PVDF-HFP, polythiophene, P3HT, PSS-Na, branched PEI, polybutadiene, LDPE, PBAT, PHBV, chitosan, sodium alginate, P4VP, polydopamine, SEBS).
  - Each band was read from Crossref-checked sources; the evidence per band is in docs/FTIR_DATABASE_ADDITIONS.md. Low-confidence cards show a "verify" warning.
  - The "Check a suspected material" list can be browsed by group: polymers, metal oxides & hydroxides, hydrogels, salts, minerals, organics, elements.
  - The Excel report has a References sheet, and Library › Reference database shows the selected card's references.
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
