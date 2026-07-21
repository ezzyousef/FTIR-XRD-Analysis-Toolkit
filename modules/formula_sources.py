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

SECOND_DERIVATIVE_PEAK_DETECTION = (
    "Peaks in the original spectrum correspond to local minima of the "
    "(smoothed) second derivative -- because d^2/dx^2 of a peak-shaped band "
    "is most negative at its own center, even a shoulder riding on a "
    "stronger neighboring band gets its own minimum. Detecting maxima of "
    "-d^2y/dx^2 therefore resolves overlapping/shouldered bands that plain "
    "peak-picking on the raw spectrum merges into one broad peak.\n\n"
    "More sensitive to noise than ordinary peak-picking (differentiation "
    "amplifies noise even after smoothing) -- use it when you have reason "
    "to expect overlapping bands, not as a blanket default.\n\n"
    "Source: Susi & Byler, Appl. Spectrosc. 37 (1983) 130 -- second-"
    "derivative resolution enhancement, standard in protein/polymer FTIR "
    "band analysis."
)

ATR_CORRECTION = (
    "Penetration depth: dp(ν) = λ / [2π·n₁·√(sin²θ - (n₂/n₁)²)]  ∝  1/ν\n\n"
    "In ATR sampling the effective pathlength (penetration depth) shrinks "
    "as wavenumber increases, so raw ATR spectra under-represent "
    "high-wavenumber bands (C-H/O-H stretches) relative to the fingerprint "
    "region compared to a transmission spectrum. This correction multiplies "
    "absorbance by wavenumber (relative to a reference wavenumber) to "
    "remove that bias -- the same 'advanced ATR correction' offered by "
    "OMNIC/OPUS.\n\n"
    "Does NOT correct for anomalous dispersion (refractive-index changes "
    "near strong bands), which needs a full Kramers-Kronig transform.\n\n"
    "Source: Harrick, Internal Reflection Spectroscopy, 1967; Socrates, "
    "Infrared and Raman Characteristic Group Frequencies, 3rd ed., Wiley, "
    "2001, Appendix (ATR crystal refractive indices)."
)

DERIVATIVE_SPECTROSCOPY = (
    "1st/2nd derivative computed by Savitzky-Golay differentiation (local "
    "polynomial fit, differentiated analytically) rather than naive finite "
    "differencing, to avoid amplifying noise.\n\n"
    "2nd-derivative peaks point downward at the same position as the "
    "original band center and are narrower -- useful for resolving "
    "overlapping/shouldered bands and removing sloping baselines.\n\n"
    "Source: Savitzky & Golay, Anal. Chem. 36 (1964) 1627; standard "
    "derivative-spectroscopy feature of OMNIC/OPUS."
)

NORMALIZATION_METHODS = (
    "Max: divide by the maximum |intensity| (peak -> 1.0).\n"
    "Min-Max: rescale the full range to [0, 1].\n"
    "Area: divide by the total integrated |absorbance| area (useful when "
    "comparing spectra recorded at different concentrations/pathlengths).\n"
    "Vector (L2): divide by the Euclidean norm of the whole spectrum -- the "
    "standard chemometrics preprocessing step before PCA/PLS or spectral "
    "library search.\n\n"
    "Source: Bro & Smilde, 'Centering and scaling in component analysis', "
    "J. Chemometrics 17 (2003); standard preprocessing options in commercial "
    "FTIR software."
)

XRD_BACKGROUND_SUBTRACTION = (
    "SNIP (Statistics-sensitive Non-linear Iterative Peak-clipping): the "
    "pattern is transformed with the LLS (log-log-sqrt) operator, which "
    "compresses peak amplitudes far more than the background, then clipped "
    "against the local 2-point average for increasing window widths. Narrow "
    "peaks get clipped down to background level; the slowly-varying "
    "background survives. The result is inverse-transformed and subtracted.\n\n"
    "Works directly on the raw pattern -- no need to manually pick "
    "'background-only' 2θ regions.\n\n"
    "Source: Ryan et al., Nucl. Instrum. Methods B 34 (1988) 396; Morháč "
    "et al., Nucl. Instrum. Methods A 401 (1997) 113. Used by PANalytical "
    "HighScore and Bruker DIFFRAC.EVA."
)

XRD_UNIT_CONVERTER = (
    "2θ ↔ d-spacing via Bragg's Law: d = nλ/(2·sinθ)\n"
    "2θ ↔ Q (scattering vector) via: Q = 4π·sinθ/λ\n\n"
    "Q is the wavelength-independent axis used by PDF/total-scattering "
    "software, letting patterns collected at different X-ray wavelengths be "
    "compared directly.\n\n"
    "Source: Cullity & Stock, Elements of X-Ray Diffraction, 3rd ed., "
    "Prentice Hall, 2001; Warren, X-Ray Diffraction, Dover, 1990."
)


def show_formula_dialog(parent, title, text):
    from ttkbootstrap.dialogs import Messagebox
    Messagebox.show_info(text, title, parent=parent)
