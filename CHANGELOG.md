# Changelog

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
