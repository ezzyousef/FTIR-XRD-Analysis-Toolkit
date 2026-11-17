# Implementation plan: repository 04 (as executed)

The milestones below follow the brief's order. Each one was committed separately, and the full suite was run on each commit in a clean worktree.

| Milestone | Scope | Design choice (smallest maintainable) | Acceptance | Commit |
|---|---|---|---|---|
| labkit | 1.1.0 → 1.2.0 | `sync.py --apply --test` (backup in `.labkit-backup/`, git-ignored) | 288 passed inside the sync | `578f404` |
| A | Equation oracles, hostile files, fixes | Tests compute expected values with `math` only. Readers share one `_read_text` (BOM, binary sniff, size cap) and `_finite_rows`. Refuse rather than guess | 36 oracle + 41 hostile tests; each fix failed first | `c01f789` |
| B | Validation laboratory (feature 1) | A pure module plus CLI. The manifest is the user's data. Metrics are hand-checkable. No ML training: "train" only tunes the tolerance | 7 tests incl. hand-counted precision/recall, Wilson CI, leak refusal | `0300f92` |
| C | Global fit, uncertainty, recipes, batch (feature 2) | `scipy.optimize.least_squares` with bounds and robust loss. Errors from J^T J. Recipes reuse the button functions | 11 tests incl. Monte Carlo σ check, spike robustness | `5f45a53` |
| D | XRD tools, refinement export, evidence (features 3–5) | No built-in reference values. Cards and certificates come from the user. Verdicts are capped at "consistent". `.xye` export only, no engine | 17 tests incl. Monte Carlo propagation, HTML escaping, no-network | `7923f4a` |
| E | GUI wiring, preferences, cursor, thinning (feature 6) | One `workbench.py` of menu actions using the existing dialogs. QSettings for preferences. Min/max thinning for drawing only | 7 GUI tests in one window (10 s); no shortcut clash | `00fc221` |
| F | Fit band on the plot, provenance beside peak CSVs, version 3.4.0, CHANGELOG, README, these docs | | 291 passed | final commit |

## Trade-offs considered

- **Refinement adapter.** Calling GSAS-II needs its own install and a licence check, and a numerical benchmark against a known refinement. None of these was available offline, so the app exports `.xye` plus provenance and runs no refinement. This avoids any claim of a home-made Rietveld engine.
- **Phase identification.** Scraping ICDD/COD is ruled out. Card files are user-supplied, and the card's name, source and licence notes travel with the result.
- **Validation without data.** Making up "reference spectra" would violate the brief. The laboratory is the instrument; the owner's spectra are the input.
- **Ragged rows.** Refusing them, as in supercap_suite, was chosen over silently dropping the extra values, which hides errors. Consistently wide files still load, with a warning.
