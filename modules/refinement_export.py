"""
refinement_export.py
Hand a diffraction pattern to an external refinement program (GSAS-II, FullProf, TOPAS, ...).

This toolkit does not do Rietveld refinement and claims none. What it offers is the input such
programs need: a plain three-column .xye file (2theta in degrees, intensity, standard
uncertainty) plus a provenance file with the wavelength, source file digest and processing.
The uncertainty is sqrt(counts) for raw counting data (Poisson); for data that are no longer
raw counts (background-subtracted, normalised, stripped of Kalpha2) the caller must say so,
and the file then uses the uncertainty the caller supplies.

Running GSAS-II or FullProf from this app is NOT implemented: both are separate installs with
their own licences, and no benchmark data set was available to verify an adapter numerically.
`find_refinement_programs()` only reports whether GSAS-II's Python package is importable.
"""
import importlib.util
import os

import numpy as np


def poisson_sigma(counts):
    """sqrt(counts), with 1 for zero or negative counts (the usual convention, so weights stay finite)."""
    c = np.asarray(counts, dtype=float)
    return np.sqrt(np.where(c > 1.0, c, 1.0))


def write_xye(path, two_theta, intensity, sigma=None, raw_counts=True):
    """Write 2theta / I / sigma, ascending 2theta, no header (the most widely readable form).
    raw_counts=False requires an explicit sigma: sqrt(I) is wrong for processed data."""
    tt = np.asarray(two_theta, dtype=float)
    y = np.asarray(intensity, dtype=float)
    if tt.shape != y.shape or tt.ndim != 1 or len(tt) < 2:
        raise ValueError("two_theta and intensity must be 1-D arrays of the same length.")
    label = "sqrt(counts)" if sigma is None else "given"
    if sigma is None:
        if not raw_counts:
            raise ValueError("Processed data need their own uncertainties; sqrt(I) only holds for raw counts.")
        sigma = poisson_sigma(y)
    s = np.asarray(sigma, dtype=float)
    if s.shape != y.shape or np.any(~np.isfinite(s)) or np.any(s <= 0):
        raise ValueError("Uncertainties must be finite and positive, one per point.")
    ok = np.isfinite(tt) & np.isfinite(y)
    order = np.argsort(tt[ok])
    rows = np.column_stack([tt[ok][order], y[ok][order], s[ok][order]])
    with open(path, "w", encoding="ascii", newline="\n") as f:
        for a, b, c in rows:
            f.write(f"{a:.5f} {b:.6g} {c:.6g}\n")
    return {"path": str(path), "points": int(len(rows)), "sigma": label}


def read_xye(path):
    data = np.loadtxt(path, ndmin=2)
    if data.shape[1] < 3:
        raise ValueError("An .xye file has three columns.")
    return data[:, 0], data[:, 1], data[:, 2]


def export_for_refinement(path, two_theta, intensity, wavelength_a, source_path=None, processing=(),
                          raw_counts=True, sigma=None, app_name="FTIR & XRD Analysis Toolkit", app_version=""):
    """.xye plus '<path>.provenance.json' (wavelength, processing, source digest)."""
    info = write_xye(path, two_theta, intensity, sigma=sigma, raw_counts=raw_counts)
    try:
        from labkit.io import Provenance
        prov = Provenance(app_name, app_version, method="Pattern exported for external refinement (.xye)",
                          parameters={"wavelength_A": float(wavelength_a), "processing": list(processing),
                                      "uncertainty": "sqrt(counts)" if sigma is None else "supplied by the user"},
                          notes="No refinement was performed by this application.")
        if source_path and os.path.isfile(source_path):
            prov.add_source(source_path)
        info["provenance"] = str(prov.write_beside(path))
    except ImportError:
        info["provenance"] = None
    return info


def find_refinement_programs():
    """Whether known refinement packages are importable in this Python. Nothing is run."""
    return {"GSAS-II (GSASII package)": importlib.util.find_spec("GSASII") is not None}
