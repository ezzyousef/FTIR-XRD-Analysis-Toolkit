"""
formula_sources.py
Condensed formula + citation text shown by the "Formula & Source" info
buttons next to each calculation tool -- the one-click traceability this
toolkit's design brief requires: every computed number should show its
source. These are standard, widely-published equations (not proprietary
or paper-specific conventions), cited to the standard textbooks named in
the database bibliography (see Help > Data Sources & References).
"""

BRAGG_LAW = (
    "nλ = 2d·sin(θ)\n\n"
    "d = nλ / (2·sinθ)\n\n"
    "θ is HALF the measured peak position (you enter 2θ; the app "
    "halves it internally). n is the diffraction order (n=1 used here).\n\n"
    "Source: Cullity & Stock, Elements of X-Ray Diffraction, 3rd ed., "
    "Prentice Hall, 2001, Ch. 3. Standard, exact relation -- no "
    "approximation involved."
)

SCHERRER_EQUATION = (
    "τ = Kλ / (β·cosθ)\n\n"
    "τ = apparent crystallite size (nm)\n"
    "K = shape factor (0.9 default here; ranges ~0.62-2.08 depending on "
    "assumed crystallite shape)\n"
    "β = FWHM peak broadening, in radians\n"
    "θ = half the peak's 2θ position\n\n"
    "Source: Cullity & Stock, Elements of X-Ray Diffraction, 3rd ed., 2001, "
    "Ch. 9. Caveats: reports SIZE-broadening only (does not separate "
    "strain -- use Williamson-Hall for that), and is NOT corrected for "
    "instrumental broadening (rigorous work subtracts a standard "
    "reference's broadening in quadrature first)."
)

WILLIAMSON_HALL = (
    "β·cosθ = Kλ/D + 4ε·sinθ\n\n"
    "Plotting y=βcosθ vs x=4sinθ across several peaks and fitting a "
    "straight line separates size broadening (from the intercept, giving "
    "crystallite size D) from strain broadening (from the slope, giving "
    "microstrain ε) -- unlike the single-peak Scherrer equation, which "
    "conflates the two.\n\n"
    "Source: Williamson, G.K. & Hall, W.H., Acta Metallurgica, 1953, 1(1), "
    "22-31. Needs 3+ peaks for a meaningful fit; a non-positive intercept "
    "means size isn't resolvable from this data (reported as such)."
)

PERCENT_CRYSTALLINITY = (
    "%Xc = Area(crystalline peaks) / [Area(crystalline) + Area(amorphous halo)] × 100\n\n"
    "Area-under-curve method: you choose which 2θ regions are "
    "'crystalline' and which are the 'amorphous halo'.\n\n"
    "Source: standard XRD crystallinity methodology (e.g. Cullity & Stock, "
    "2001). This is inherently method- and region-choice-dependent -- "
    "different software/analysts will get different numbers on the same "
    "raw pattern. Always report which regions you used alongside the "
    "result."
)

CUBIC_LATTICE_PARAMETER = (
    "1/d² = (h²+k²+l²)/a²\n\n"
    "a = d·√(h²+k²+l²)\n\n"
    "Source: standard cubic-system interplanar-spacing relation (Cullity "
    "& Stock, 2001, Ch. 2 / Appendix). ONLY valid for cubic crystal "
    "systems -- tetragonal, hexagonal, orthorhombic, monoclinic, and "
    "triclinic systems each need a different (more complex) formula."
)

ITERATIVE_LATTICE_REFINEMENT = (
    "Q = 1/d² expressed per crystal system:\n"
    "  Cubic:         Q = (h²+k²+l²)/a²\n"
    "  Tetragonal:    Q = (h²+k²)/a² + l²/c²\n"
    "  Hexagonal:     Q = (4/3)(h²+hk+k²)/a² + l²/c²\n"
    "  Orthorhombic:  Q = h²/a² + k²/b² + l²/c²\n\n"
    "Refines the lattice parameter(s) by nonlinear least squares "
    "(Levenberg-Marquardt) across ALL indexed peaks simultaneously, "
    "instead of computing 'a' from a single peak -- this averages down "
    "measurement noise and gives a real, statistically meaningful "
    "uncertainty on each parameter. After each fit, peaks whose residual "
    "exceeds your outlier threshold (a robust median-absolute-deviation "
    "scale, not a plain standard deviation, so one bad peak can't inflate "
    "its own exclusion threshold) are dropped and the fit is REPEATED -- "
    "iterating until no further peaks are excluded. This is what catches a "
    "peak that was assigned the wrong (h,k,l) index.\n\n"
    "Source: standard least-squares unit-cell refinement methodology, e.g. "
    "Cullity & Stock, Elements of X-Ray Diffraction, 3rd ed., 2001, Ch. 11 "
    "(Precise Lattice-Parameter Measurements); the underlying single-peak "
    "relations are the same standard interplanar-spacing formulas as the "
    "Cubic Lattice Parameter tool, extended here to tetragonal/hexagonal/"
    "orthorhombic and to multi-peak least squares. Requires each peak to "
    "already be correctly indexed (h,k,l) by you -- this refines the cell "
    "given the indexing, it does not do the indexing itself."
)

BEER_LAMBERT = (
    "A = ε·l·c   →   c = A / (ε·l)\n\n"
    "A = absorbance (dimensionless)\n"
    "ε = molar absorptivity (L·mol⁻¹·cm⁻¹)\n"
    "l = path length (cm)\n"
    "c = concentration (mol/L)\n\n"
    "Source: standard Beer-Lambert law, e.g. Pavia, Lampman, Kriz, Vyvyan, "
    "Introduction to Spectroscopy, 5th ed., Cengage, 2015. Assumes a "
    "known, accurate molar absorptivity for your specific analyte/band -- "
    "the result is only as good as that input."
)

TRANSMITTANCE_ABSORBANCE = (
    "A = 2 - log10(%T)      %T = 10^(2-A)\n\n"
    "Standard relation between absorbance and percent transmittance used "
    "throughout IR spectroscopy.\n\n"
    "Source: Pavia, Lampman, Kriz, Vyvyan, Introduction to Spectroscopy, "
    "5th ed., Cengage, 2015."
)

FTIR_DATABASE_MATCHING = (
    "Screening method: each detected peak is compared against every "
    "reference material's published peak ranges (+/- your tolerance). "
    "Score = (# reference peaks matched) / (# matchable reference peaks) "
    "for that material.\n\n"
    "This is a HEURISTIC screening tool, not definitive identification -- "
    "always confirm anything consequential against a certified reference "
    "spectrum (NIST WebBook, SDBS) or an expert. See Help > Data Sources "
    "& References for exactly which literature each entry's ranges come "
    "from."
)

XRD_PHASE_MATCHING = (
    "Screening method: each detected peak's 2θ is converted to a "
    "d-spacing via Bragg's law (wavelength-independent), then compared "
    "against each reference phase's strongest published d-spacings (+/- "
    "your % tolerance). Score is intensity-weighted coverage of the "
    "reference lines.\n\n"
    "This is a HEURISTIC screening tool, not definitive phase "
    "identification -- always confirm against a certified ICDD PDF-2/"
    "PDF-4 card for anything consequential. See Help > Data Sources & "
    "References for the literature behind the built-in phases."
)

PEAK_FITTING = (
    "Gaussian:    y = h·exp(-4ln2·(x-x0)²/FWHM²) + offset\n"
    "Lorentzian:  y = h·(FWHM/2)² / ((x-x0)²+(FWHM/2)²) + offset\n"
    "Pseudo-Voigt: η·Lorentzian + (1-η)·Gaussian\n\n"
    "Fit by nonlinear least squares (scipy.optimize.curve_fit) within a "
    "window around each detected peak's seed position. R² is reported "
    "so you can judge fit quality -- a low R² usually means overlapping "
    "peaks or too narrow/wide a fit window.\n\n"
    "Source: standard peak-shape functions used throughout spectroscopy/"
    "diffraction line-profile analysis (e.g. Pavia et al., 2015; Cullity "
    "& Stock, 2001)."
)


def show_formula_dialog(parent, title, text):
    from ttkbootstrap.dialogs import Messagebox
    Messagebox.show_info(text, title, parent=parent)
