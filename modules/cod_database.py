"""
cod_database.py
Reads this project's own bundled COD-derived reference database
(database/cod_reference.sqlite): ~511,000 phases extracted from the
Crystallography Open Database via a PANalytical/Malvern HighScore .hsrdb
file, built once by scripts/build_cod_database.py (see that script and
modules/hsrdb_reader.py for exactly how the source data was decoded and
validated, and where it comes from).

This file is NOT committed to git (see .gitignore) -- it's a ~1GB+ build
artifact shipped only inside the installed application (via app.spec's
datas list / the Inno Setup installer), not tracked in git history.

Every query here is a lazy, indexed SQLite lookup -- the file is never
loaded into memory, so bundling ~511,000 phases doesn't slow down app
startup or inflate memory use the way the small hand-curated built-in
database (loaded as a JSON dict) would if it were anywhere near this size.
"""
import os
import re
import sqlite3
import urllib.parse

_connection_cache = {}


def is_available(path):
    return bool(path) and os.path.exists(path)


def open_db(path):
    """Open (or reuse a cached) read-only connection to the bundled database."""
    if not os.path.exists(path):
        raise ValueError(f"File not found: {path}")
    path = os.path.abspath(path)
    if path in _connection_cache:
        return _connection_cache[path]
    uri_path = urllib.parse.quote(path.replace("\\", "/"))
    con = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True, check_same_thread=False)
    try:
        tables = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')").fetchall()}
        if not {"phases", "peaks"}.issubset(tables):
            raise ValueError(
                f"This doesn't look like this project's COD reference database -- "
                f"missing expected table(s) in {path}."
            )
    except sqlite3.DatabaseError as e:
        raise ValueError(f"Could not open '{path}': {e}")
    _connection_cache[path] = con
    return con


def count_phases(con):
    return con.execute("SELECT COUNT(*) FROM phases").fetchone()[0]


def _row_to_summary(row):
    (pid, name, ref_code, category, system, a, b, c, alpha, beta, gamma,
     spgr, elements, cod_code, source, n_peaks) = row
    els = elements.split(",") if elements else []
    return {
        "id": pid, "name": name, "reference_code": ref_code, "category": category,
        "crystal_system": system, "cell": {"a": a, "b": b, "c": c, "alpha": alpha, "beta": beta, "gamma": gamma},
        "space_group": spgr, "elements": els,
        "cod_code": cod_code, "source": source, "n_peaks": n_peaks,
        # field names mirrored from hsrdb_reader's search_hsrdb/get_phase_detail
        # output, so ui_common.HsrdbImportDialog can browse either this
        # bundled database or a raw external .hsrdb file with the same code.
        "compound_name": name, "mineral_name": "", "common_name": "", "formula": ",".join(els),
    }


def search(con, query="", elements=None, category=None, limit=200):
    """
    Search the bundled database by name/formula text and/or a required set
    of chemical elements, optionally restricted to one auto-classified
    category (see scripts/build_cod_database.py's guess_category -- a
    browsing convenience, not an authoritative label). Returns phase summary
    dicts (no peak list -- call get_phase for that).

    A text-only query uses the FTS3 index (fast across 511k+ rows). An
    element filter can't be answered correctly by FTS prefix-matching alone
    -- a naive "C*" prefix would also match "Ca"/"Cl"/"Ce"/"Cr"/... since
    they all start with the same letter -- so whenever elements are given
    this reads the (cheap, indexed-by-category) id+elements+category columns
    for every row and checks the exact element set in Python. That full pass
    over 511k rows takes ~1-3s -- fine for an on-demand search, not a hot path.
    """
    query = (query or "").strip()
    required_elements = {e.strip().capitalize() for e in (elements or []) if e.strip()}

    if required_elements:
        sql = "SELECT id, name, reference_code, category, crystal_system, elements FROM phases"
        params = []
        if category:
            sql += " WHERE category=?"
            params.append(category)
        candidates = con.execute(sql, params).fetchall()
        results = []
        q = query.lower()
        for pid, name, ref_code, cat, system, elements_str in candidates:
            els = set((elements_str or "").split(","))
            if not required_elements.issubset(els):
                continue
            if q and q not in (name or "").lower():
                continue
            results.append(pid)
            if len(results) >= limit:
                break
        if not results:
            return []
        placeholders = ",".join("?" * len(results))
        rows = con.execute(f"SELECT * FROM phases WHERE id IN ({placeholders})", results).fetchall()
        by_id = {r[0]: r for r in rows}
        return [_row_to_summary(by_id[pid]) for pid in results if pid in by_id]

    if query:
        fts_query = " ".join(f'"{tok}"*' for tok in re.split(r"\s+", query) if tok)
        ids = [row[0] for row in con.execute(
            "SELECT phase_id FROM phases_fts WHERE phases_fts MATCH ? LIMIT ?",
            (fts_query, limit * 5)
        ).fetchall()]
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        sql = f"SELECT * FROM phases WHERE id IN ({placeholders})"
        params = list(ids)
        if category:
            sql += " AND category=?"
            params.append(category)
        sql += " LIMIT ?"
        params.append(limit)
        return [_row_to_summary(row) for row in con.execute(sql, params).fetchall()]

    sql = "SELECT * FROM phases"
    params = []
    if category:
        sql += " WHERE category=?"
        params.append(category)
    sql += " LIMIT ?"
    params.append(limit)
    return [_row_to_summary(row) for row in con.execute(sql, params).fetchall()]


def get_phase(con, phase_id, top_n=None):
    """Full phase dict (name/category/crystal_system/lattice_params/elements/source/peaks), same schema as the built-in database."""
    row = con.execute("SELECT * FROM phases WHERE id=?", (phase_id,)).fetchone()
    if row is None:
        return None
    summary = _row_to_summary(row)
    peak_rows = con.execute(
        "SELECT d_A, hkl, rel_intensity FROM peaks WHERE phase_id=? ORDER BY rel_intensity DESC", (phase_id,)
    ).fetchall()
    peaks = [{"d_A": d, "hkl": hkl, "rel_intensity": inten} for d, hkl, inten in peak_rows]
    if top_n:
        peaks = peaks[:top_n]
    return {
        "name": summary["name"],
        "category": summary["category"],
        "crystal_system": summary["crystal_system"],
        "lattice_params": summary["cell"],
        "elements": summary["elements"],
        "source": summary["source"],
        "peaks": peaks,
    }


def match_by_peaks(con, peaks, d_tolerance_pct=1.5, top_n_ref_peaks=10, categories=None, max_results=50,
                    strongest_line_threshold=800, max_seed_peaks=8, max_candidates=4000):
    """
    Match observed peaks (dicts with 'd_A', optionally 'y'/'intensity') against
    the bundled ~511,000-phase database.

    A naive "any peak within tolerance" search doesn't work at this scale:
    common d-spacings (e.g. ~3.4 A) coincidentally fall within 1% of *several
    hundred thousand* peak rows across the whole database (measured directly:
    ~475,000 of ~15M peak rows for one such value), so tallying "how many
    observed peaks land near ANY reference peak" makes almost everything look
    like a plausible candidate and is also far too slow (Python would have to
    process each of those rows).

    Instead this uses the standard Hanawalt search-index strategy real XRD
    software uses for exactly this problem: a phase is only considered a
    candidate if one of ITS strongest lines (rel_intensity >= threshold, i.e.
    the phase's own dominant reflection(s)) coincides with one of the
    strongest OBSERVED peaks. That is both the fast query (an index on
    (rel_intensity, d_A) makes it near-instant) and the physically meaningful
    filter (if a phase's dominant Bragg reflection isn't present at all in
    your pattern, that phase essentially can't be present). Full scoring
    against every observed peak happens only for the (much smaller) set of
    phases that pass this gate.

    Returns results in the exact same schema as xrd_analysis.match_xrd_phases
    (name/category/score/matched_count/total_reference_peaks/matches), so
    every UI piece that already consumes that schema (match-detail panel,
    plot overlay, CSV export, lattice-refinement auto-fill) works unchanged
    regardless of whether a result came from the small built-in database or
    this bundled one.
    """
    seed_peaks = sorted(peaks, key=lambda p: -(p.get("y") or p.get("intensity") or 0))[:max_seed_peaks]
    if not seed_peaks:
        return []

    votes = {}  # phase_id -> number of seed peaks whose strongest line it matched
    for p in seed_peaks:
        d_obs = p.get("d_A")
        if not d_obs or d_obs <= 0:
            continue
        lo, hi = d_obs * (1 - d_tolerance_pct / 100), d_obs * (1 + d_tolerance_pct / 100)
        rows = con.execute(
            "SELECT DISTINCT phase_id FROM peaks INDEXED BY idx_peaks_intensity_d "
            "WHERE rel_intensity >= ? AND d_A BETWEEN ? AND ?",
            (strongest_line_threshold, lo, hi)
        ).fetchall()
        for (phase_id,) in rows:
            votes[phase_id] = votes.get(phase_id, 0) + 1

    if not votes:
        return []

    # prefer phases whose strongest line matched MULTIPLE strong observed
    # peaks (much stronger evidence than matching just one), only falling
    # back to single-vote candidates if nothing scored higher
    max_votes = max(votes.values())
    candidate_ids = [pid for pid, v in votes.items() if v == max_votes]
    if len(candidate_ids) < max_results and max_votes > 1:
        candidate_ids = [pid for pid, v in votes.items() if v >= max(1, max_votes - 1)]
    candidate_ids = candidate_ids[:max_candidates]

    # batch-fetch phase rows + all their peaks (SQLite host-parameter limit
    # is 999 by default, so chunk defensively at 500)
    phases_by_id = {}
    peaks_by_phase = {}
    for chunk_start in range(0, len(candidate_ids), 500):
        chunk = candidate_ids[chunk_start:chunk_start + 500]
        placeholders = ",".join("?" * len(chunk))
        for row in con.execute(f"SELECT * FROM phases WHERE id IN ({placeholders})", chunk).fetchall():
            phases_by_id[row[0]] = row
        for phase_id, d_a, hkl, inten in con.execute(
            f"SELECT phase_id, d_A, hkl, rel_intensity FROM peaks WHERE phase_id IN ({placeholders})", chunk
        ).fetchall():
            peaks_by_phase.setdefault(phase_id, []).append((d_a, hkl, inten))

    required_categories = set(categories) if categories else None
    results = []
    for phase_id in candidate_ids:
        row = phases_by_id.get(phase_id)
        if row is None:
            continue
        summary = _row_to_summary(row)
        if required_categories and summary["category"] not in required_categories:
            continue
        ref_peaks = sorted(peaks_by_phase.get(phase_id, []), key=lambda t: -t[2])
        n_ref = min(len(ref_peaks), top_n_ref_peaks) if top_n_ref_peaks else len(ref_peaks)
        ref_peaks = ref_peaks[:n_ref] if top_n_ref_peaks else ref_peaks

        # reference-peak-outer-loop (mirrors xrd_analysis.match_xrd_phases):
        # each reference line can match at most one observed peak, so two
        # observed peaks can't both "claim" the same reference line.
        matches = []
        for d_a, hkl, inten in ref_peaks:
            tol = d_a * d_tolerance_pct / 100
            best_obs = None
            best_dist = None
            for p in peaks:
                d_obs = p.get("d_A")
                if not d_obs or d_obs <= 0:
                    continue
                dist = abs(d_obs - d_a)
                if dist <= tol and (best_dist is None or dist < best_dist):
                    best_dist, best_obs = dist, d_obs
            if best_obs is not None:
                matches.append({
                    "reference": {"d_A": d_a, "hkl": hkl, "rel_intensity": inten},
                    "observed_d_A": best_obs,
                    "delta_d_A": best_obs - d_a,
                })
        if not matches:
            continue
        score = len(matches) / n_ref if n_ref else 0.0
        results.append({
            "name": summary["name"],
            "category": summary["category"],
            "crystal_system": summary["crystal_system"],
            "score": min(score, 1.0),
            "matched_count": len(matches),
            "total_reference_peaks": n_ref,
            "source": summary["source"],
            "matches": matches,
            "cod_phase_id": phase_id,
        })

    results.sort(key=lambda r: (r["matched_count"], r["score"]), reverse=True)
    return results[:max_results]


# Aliases so ui_common.HsrdbImportDialog can use this module interchangeably
# with hsrdb_reader.py (same function names, same summary dict shape) --
# letting the same "search + import" dialog browse either the bundled
# database or a raw external .hsrdb file without any dialog-side branching.
open_hsrdb = open_db
count_entries = count_phases
search_hsrdb = search
get_phase_detail = get_phase
