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
    "Uses the sample widths β (after instrument correction) of the ticked "
    "peaks; reports D and ε with their standard errors from the "
    "least-squares line, and R² (low R² is normal when the line is flat, "
    "i.e. no strain). Strip Kα2 first: an unresolved doublet mimics strain.\n\n"
    "Source: Williamson, G.K. & Hall, W.H., Acta Metallurgica, 1953, 1(1), "
    "22-31. Needs 3+ peaks for a meaningful fit; a non-positive intercept "
    "means size isn't resolvable from this data (reported as such). Assumes "
    "uniform strain and isotropic broadening."
)

PERCENT_CRYSTALLINITY = (
    "%Xc = Area(crystalline peaks) / [Area(crystalline) + Area(amorphous halo)] × 100\n\n"
    "Area-under-curve method: you choose which 2θ regions are "
    "'crystalline' and which are the 'amorphous halo'. The app integrates "
    "the RAW pattern minus a straight baseline drawn across the outer ends "
    "of all regions (so instrument background is not counted), and draws "
    "the regions on the plot.\n\n"
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
    "In plain words: each material gets a match score from three questions.\n"
    "  1. Are its bands -- especially the strong ones -- present in your spectrum, close to\n"
    "     the expected position?\n"
    "  2. Does it explain most of your strong peaks in its region?\n"
    "  3. Could this many hits happen by luck, given how many peaks you detected and how\n"
    "     many materials were searched?\n"
    "Strong, well-placed, consistent hits score high; a long band list matched by scattered\n"
    "noise scores low. The score is a SCREENING score, not the probability that the\n"
    "identification is correct. Tiers: Strong >= 0.60, Moderate >= 0.40, Weak >= 0.20,\n"
    "otherwise Poor. Strong also needs: no missing strong band, more than two bands, and a\n"
    "margin of 0.10 over every other candidate (otherwise it shows as a 'close call').\n"
    "'Look-alikes' are database entries whose band tables nearly coincide (e.g. PA11/PA12,\n"
    "Na2CO3/K2CO3): a peak list cannot tell them apart, so read such a match as the family.\n"
    "Peaks in the CO2 region and very narrow lines in the water-vapour regions are ignored.\n\n"
    "The details (Weighted evidence, the default):\n"
    "  w   band weight from its intensity label: very strong / strong 1.0, medium-strong 0.8,\n"
    "      medium 0.6, weak-medium 0.45, weak 0.3, unlabelled 0.5. Broad bands get twice the\n"
    "      tolerance.\n"
    "  s   position score: 1 inside the band range, exp(-0.5*(d/sigma)^2) outside it with\n"
    "      sigma = tolerance/2, and 0 beyond the tolerance.\n"
    "  Each of your peaks supports at most one band of a material (optimal one-to-one\n"
    "  assignment). A strong band matched only by a weak peak counts 0.6.\n"
    "  F = sum(w*s, found bands) / sum(w, all bands)   -- how much of the reference is seen\n"
    "  R = prominence of your peaks it explains / all prominence in its band region\n"
    "                                                  -- how much of your sample it explains\n"
    "  P = probability of at least this many band hits by coincidence, from the density of\n"
    "      the peaks this material does NOT claim within +/-150 cm-1 of each band. Peaks count\n"
    "      in proportion to their strength (full weight from 5 % of the strongest peak), so\n"
    "      noise is little evidence and nothing jumps at a threshold.\n"
    "  Pf = 1 - (1 - P)^min(M, 20) for the M materials searched (shown as 'Chance p')\n"
    "  U = 1 - 0.5 * (share of your strong peaks left unexplained outside its band region)\n"
    "  A sharp peak (FWHM < 40 cm-1) counts 0.3 for a broad band.\n"
    "  Match score = F^0.6 * R^0.4 * min(1, -log10(Pf)/2) * U\n\n"
    "Coverage (legacy): score = found bands / matchable bands (earlier versions).\n\n"
    "Analyse as mixture (always Weighted evidence): accept the best material if it scores\n"
    ">= 0.35, mark the peaks it explains, rank again judging candidates on the peaks still\n"
    "unexplained (shared bands may support both); up to 3 components.\n"
    "'Share of peak intensity' is the fraction of summed peak prominence assigned to a\n"
    "component -- NOT a concentration.\n\n"
    "Pattern r: correlation between your spectrum and a synthetic spectrum drawn from the\n"
    "reference bands; shown for information only.\n\n"
    "Limits: the weights and thresholds are engineering choices for this database (literature\n"
    "band ranges, not measured spectra). They were tested on simulated spectra only and are\n"
    "NOT yet validated on lab spectra of known materials. In simulation, when the true\n"
    "material was removed from the database the top hit was still Strong in about a quarter\n"
    "of cases -- almost always a chemical relative (docs/FTIR_MATCHING_PLAN.md).\n"
    "Checking both directions follows forward/backward library searching (Lavine et al.,\n"
    "Talanta 2016); a high match score alone can still be a wrong identification (Kozloski\n"
    "et al., Microplastics and Nanoplastics 2024).\n\n"
    "Always confirm anything consequential against a certified reference spectrum (NIST\n"
    "WebBook, SDBS) or an expert. Library > Sources & references lists the literature each\n"
    "entry's ranges come from."
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
    "The clipping window is given in degrees 2θ (converted to points from "
    "the step size), so the result does not depend on the step. About 2-3x "
    "the widest peak's FWHM: narrower eats into broad peaks, wider leaves "
    "background under them. SNIP also removes an amorphous halo, so % "
    "crystallinity always works on the raw pattern.\n\n"
    "Source: Ryan et al., Nucl. Instrum. Methods B 34 (1988) 396; Morháč "
    "et al., Nucl. Instrum. Methods A 401 (1997) 113."
)

XRD_KALPHA2_STRIPPING = (
    "A Cu tube emits Kα1 and Kα2; every reflection is a doublet separated by\n"
    "Δ2θ = 2·tanθ·(λ2 − λ1)/λ1 (radians), growing with angle. Left in, the\n"
    "unresolved doublet widens peaks more at high angle, which shrinks Scherrer\n"
    "sizes and mimics strain in Williamson–Hall.\n\n"
    "Rachinger correction, applied point by point from low angle:\n"
    "  I1(2θ) = I(2θ) − R · I1(2θ − Δ2θ),  R = I(Kα2)/I(Kα1) ≈ 0.5\n"
    "Subtract the background first; use Cu Ka1 as the wavelength afterwards.\n"
    "Only Cu values are pre-filled; for other anodes enter Kα2 from your\n"
    "instrument documentation. Leaves small residues where the doublet ratio\n"
    "deviates from R.\n\n"
    "Source: Rachinger, W.A., J. Sci. Instrum. 25 (1948) 254."
)

XRD_INSTRUMENT_PROFILE = (
    "Every diffractometer adds its own width b to each peak. The sample's\n"
    "width β is recovered from the measured width B:\n"
    "  Gaussian profiles:   β = √(B² − b²)\n"
    "  Lorentzian profiles: β = B − b\n"
    "Peaks not measurably broader than the instrument (B ≤ 1.05 b) get no\n"
    "size; peaks narrower than b are flagged as probable noise.\n\n"
    "The instrument width varies with angle (Caglioti):\n"
    "  b² = U·tan²θ + V·tanθ + W\n"
    "Measure a line-profile standard (e.g. LaB6 or Si) with the same optics,\n"
    "fit its peaks, and use 'Refine profile from this pattern', or type a\n"
    "constant FWHM. Without it, sizes are lower bounds and errors are largest\n"
    "for large crystallites (> ~100 nm).\n\n"
    "Source: Caglioti, G., Paoletti, A. & Ricci, F.P., Nucl. Instrum. 3 (1958)\n"
    "223; quadrature/linear subtraction as in Klug & Alexander and Cullity &\n"
    "Stock (textbook treatments)."
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
    from ui_common import show_formula
    show_formula(parent, title, text)
