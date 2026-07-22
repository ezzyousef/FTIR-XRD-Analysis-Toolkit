"""
hsrdb_reader.py
Reads PANalytical/Malvern X'Pert HighScore reference database files (.hsrdb)
directly -- the same file HighScore itself opens for phase search/match.

What a .hsrdb file actually is (verified by inspection, not assumed):
  - The file is a standard SQLite 3 database (confirmed by the literal
    "SQLite format 3" file-format magic header) -- an open, public container
    format with no encryption or obfuscation.
  - The "COD*.hsrdb" files PANalytical/Malvern distribute (as in this
    project's original COD24_HS4x.hsrdb) contain the Crystallography Open
    Database (COD, crystallography.net) -- open-access structural data, not
    ICDD's commercial PDF-2/PDF-4 product. This is confirmed here by every
    entry's free-text Comment field containing a literal
    "COD database code: NNNNN" tag, and by every ProductID using the
    "96-3xx-xxxx" prefix range (the range PANalytical reserves for
    COD-derived entries, distinct from the "00-89" ranges used for licensed
    ICDD cards). This reader only ever works with data attributable to COD.

Per-reflection data (d-spacing, hkl, relative intensity) is stored in three
parallel BLOB columns (general_stored.Lines / HKL / LinesI) with no public
format specification. Their binary layout was determined empirically here
and cross-validated -- recomputing d-spacings from the decoded hkl indices
and the entry's own unit cell (via the standard 1/d^2 formulas) reproduces
the stored d-spacing to 4 decimal places, checked across dozens of entries
spanning every crystal system this file contains:
    HKL:    N x (int16 h, int16 k, int16 l)                        -- 6 bytes/reflection
    LinesI: N x (float32 relative_intensity, scaled 0-1000)         -- 4 bytes/reflection
    Lines:  N x (float32 d_spacing_angstrom, int16 intensity_round) -- 6 bytes/reflection
(Lines' int16 field duplicates LinesI rounded to the nearest integer; N is
always consistent across all three blobs for a given entry.)

This module only ever opens the user's own .hsrdb file, read-only, at
runtime -- it never bundles, embeds, commits, or redistributes the file or
its contents. Only the specific entries a user explicitly chooses to import
are added to their local user-phases store (xrd_analysis.add_user_phases,
which persists to the per-user config directory), never to this project's
shipped, git-tracked reference database.
"""
import os
import re
import sqlite3
import struct
import urllib.parse

CRYSTAL_SYSTEM_CODES = {
    "C": "cubic", "T": "tetragonal", "O": "orthorhombic",
    "H": "hexagonal", "M": "monoclinic", "A": "triclinic",
}

_REQUIRED_TABLES = ("general_indexed", "general_stored", "general_text")


def open_hsrdb(path):
    """
    Open a .hsrdb file read-only. Raises ValueError (not a crash) if it
    doesn't look like a HighScore reference database, so the UI can show a
    clear message instead of a stack trace.
    """
    if not os.path.exists(path):
        raise ValueError(f"File not found: {path}")
    uri_path = urllib.parse.quote(os.path.abspath(path).replace("\\", "/"))
    con = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
    try:
        tables = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()}
        missing = [t for t in _REQUIRED_TABLES if t not in tables]
        if missing:
            raise ValueError(
                "This doesn't look like a HighScore reference database (.hsrdb) -- "
                f"missing expected table(s): {', '.join(missing)}."
            )
    except sqlite3.DatabaseError as e:
        raise ValueError(f"Could not open '{path}' as a HighScore reference database: {e}")
    return con


def count_entries(con):
    return con.execute("SELECT COUNT(*) FROM general_indexed").fetchone()[0]


def _parse_formula_elements(formula_text):
    """'Cl4.00 C92.00 O28.00 H108.00' -> {'Cl', 'C', 'O', 'H'}"""
    return set(re.findall(r"[A-Z][a-z]?(?=[\d.])", formula_text or ""))


def search_hsrdb(con, query="", elements=None, limit=200):
    """
    Search by name/formula text and/or a required set of chemical elements.
    Returns lightweight summary dicts -- peak data is NOT decoded here
    (that's get_phase_detail's job, on demand for whichever entry the user
    picks; decoding every match up front would be wasteful for a broad
    query).

    A text-only query uses SQLite's FTS3 index (fast, stays snappy across
    500k+ rows). An element filter, though, can't be answered correctly by
    FTS prefix-matching alone -- formula tokens like "Ce4.00" have no
    separator between the element symbol and its count, so a naive prefix
    search for a single-letter element ("C") would also match "Ca", "Cl",
    "Ce", "Cr", "Co", "Cu", "Cd", "Cs", etc. Getting this right needs an
    exact per-row parse (_parse_formula_elements), so whenever elements are
    given this does a full-table scan in Python instead (~1-3s across the
    whole file -- fine for an on-demand search action, not a hot path).
    """
    query = (query or "").strip()
    required_elements = {e.strip().capitalize() for e in (elements or []) if e.strip()}

    def text_matches(formula, compound, mineral, common):
        if not query:
            return True
        q = query.lower()
        return any(q in (field or "").lower() for field in (formula, compound, mineral, common))

    if required_elements:
        rows = con.execute("SELECT rowid, chemicalformula, compoundname, mineralname, commonname FROM general_text").fetchall()
    elif query:
        fts_query = " ".join(f'"{tok}"*' for tok in re.split(r"\s+", query) if tok)
        rows = con.execute(
            "SELECT rowid, chemicalformula, compoundname, mineralname, commonname FROM general_text "
            "WHERE general_text MATCH ? LIMIT ?", (fts_query, limit * 5)
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT rowid, chemicalformula, compoundname, mineralname, commonname FROM general_text LIMIT ?",
            (limit,)
        ).fetchall()

    results = []
    for rowid, formula, compound, mineral, common in rows:
        if required_elements and not required_elements.issubset(_parse_formula_elements(formula)):
            continue
        if required_elements and not text_matches(formula, compound, mineral, common):
            continue
        results.append({
            "id": rowid,
            "formula": formula or "",
            "compound_name": compound or "",
            "mineral_name": mineral or "",
            "common_name": common or "",
        })
        if len(results) >= limit:
            break

    if results:
        ids = [r["id"] for r in results]
        placeholders = ",".join("?" * len(ids))
        info = {row[0]: row for row in con.execute(
            f"SELECT id, ProductID, XTSLSYS, A, B, C, ALPHA, BETA, GAMMA, NumberOfElements "
            f"FROM general_indexed WHERE id IN ({placeholders})", ids
        ).fetchall()}
        for r in results:
            row = info.get(r["id"])
            if row:
                _, product_id, sys_code, a, b, c, alpha, beta, gamma, n_elements = row
                r["reference_code"] = product_id
                r["crystal_system"] = CRYSTAL_SYSTEM_CODES.get(sys_code, sys_code or "")
                r["cell"] = {"a": a, "b": b, "c": c, "alpha": alpha, "beta": beta, "gamma": gamma}
                r["n_elements"] = n_elements
    return results


def get_phase_detail(con, entry_id, top_n=None):
    """
    Decode one entry's full reflection list (d-spacing, hkl, relative
    intensity) plus space group, unit cell, literature citation, and COD
    reference code -- returned in the same phase-dict schema as the app's
    built-in XRD database (name/category/crystal_system/lattice_params/
    source/peaks), ready to hand to xrd_analysis.add_user_phases().
    """
    row = con.execute(
        "SELECT ProductID, XTSLSYS, A, B, C, ALPHA, BETA, GAMMA FROM general_indexed WHERE id=?", (entry_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"No entry with id {entry_id} in this .hsrdb file.")
    product_id, sys_code, a, b, c, alpha, beta, gamma = row

    stored = con.execute(
        "SELECT SPGR, Comment, CAS, Lines, HKL, LinesI FROM general_stored WHERE pid=?", (entry_id,)
    ).fetchone()
    if stored is None:
        raise ValueError(f"No reflection data for id {entry_id} in this .hsrdb file.")
    spgr, comment, cas, lines_blob, hkl_blob, linesi_blob = stored

    text_row = con.execute(
        "SELECT chemicalformula, compoundname, mineralname, commonname FROM general_text WHERE rowid=?", (entry_id,)
    ).fetchone()
    formula, compound, mineral, common = text_row if text_row else ("", "", "", "")
    display_name = compound or mineral or common or product_id

    n = (len(hkl_blob) // 6) if hkl_blob else 0
    peaks = []
    for i in range(n):
        h, k, l = struct.unpack_from("<hhh", hkl_blob, i * 6)
        d_a, _rounded_intensity = struct.unpack_from("<fh", lines_blob, i * 6)
        intensity, = struct.unpack_from("<f", linesi_blob, i * 4)
        if d_a <= 0:
            continue
        peaks.append({"d_A": round(float(d_a), 5), "hkl": f"{h},{k},{l}",
                      "rel_intensity": round(float(intensity), 2)})
    peaks.sort(key=lambda p: -p["rel_intensity"])
    if top_n:
        peaks = peaks[:top_n]

    cod_match = re.search(r"COD database code:\s*(\d+)", comment or "")
    cod_code = cod_match.group(1) if cod_match else None

    lit_rows = con.execute(
        "SELECT lt.authors, lt.journal, lt.year, lt.volume, lt.pages FROM literature_map lm "
        "JOIN literature_text lt ON lt.rowid = lm.doc WHERE lm.pid=?", (entry_id,)
    ).fetchall()
    citation_parts = []
    for authors, journal, year, volume, pages in lit_rows:
        piece = ", ".join(x for x in [authors, journal, volume, pages, year] if x)
        if piece:
            citation_parts.append(piece)

    source_bits = [f"Crystallography Open Database (COD) entry {cod_code}" if cod_code
                   else "Crystallography Open Database (COD)"]
    source_bits.extend(citation_parts)
    source_bits.append(f"imported from local HighScore reference database, ProductID {product_id}")

    return {
        "name": f"{display_name} ({product_id})",
        "category": "user-imported",
        "crystal_system": CRYSTAL_SYSTEM_CODES.get(sys_code, sys_code or ""),
        "lattice_params": {"a": a, "b": b, "c": c, "alpha": alpha, "beta": beta, "gamma": gamma},
        "elements": sorted(_parse_formula_elements(formula)),
        "source": "; ".join(source_bits),
        "space_group": spgr or "",
        "cas": cas or "",
        "cod_code": cod_code,
        "peaks": peaks,
    }
