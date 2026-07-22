"""
build_cod_database.py
One-time build tool: extracts every entry from a PANalytical/Malvern
HighScore reference database (.hsrdb) file into this project's own compact,
permanent, bundled SQLite database (database/cod_reference.sqlite), so the
app has full COD (Crystallography Open Database) phase coverage without
needing the user's original .hsrdb file (which is 7+ GB and specific to
their machine) to stay around.

Every phase in the source file is kept -- nothing is dropped by compound.
Per-phase reflections are capped to the strongest N lines (default 40):
the source file stores every computed reflection (178 on average, some
phases have 1000+), but matching/screening only ever needs the strongest
lines anyway (this mirrors match_xrd_phases' own top_n_ref_peaks logic and
the built-in database's existing convention), and keeping every last weak
line for 500,000+ phases is not a reasonable size trade for a bundled,
git-tracked file.

See modules/hsrdb_reader.py for how the source .hsrdb binary layout was
determined and validated -- this script reuses that exact decode logic.

Usage:
    python scripts/build_cod_database.py <path-to-.hsrdb> [--limit N] [--top-n 40]
"""
import argparse
import os
import re
import sqlite3
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "modules"))
import hsrdb_reader as hr


ORGANIC_ONLY_ELEMENTS = {"H", "C", "N", "O", "S", "P", "F", "Cl", "Br", "I", "Na", "K", "Si"}


def guess_category(elements, formula_text):
    els = set(elements)
    if not els:
        return "unknown"
    if len(els) == 1:
        return "element"
    has_c = "C" in els
    has_h = "H" in els
    # crude heuristic, browsing convenience only (not authoritative -- same
    # caveat this toolkit already applies to every other automated label):
    # a compound with both C and H and more than a couple of other light
    # elements is almost always organic/metal-organic; pure metal-anion
    # compounds (oxide/halide/sulfate/etc, no C-H skeleton) are "inorganic".
    if has_c and has_h and len(els) <= 8:
        return "organic"
    if has_c and has_h:
        return "organic"
    if "O" in els and not has_c:
        return "oxide_or_mineral"
    if els & {"F", "Cl", "Br", "I"} and not has_c:
        return "halide_salt"
    return "inorganic"


def build(hsrdb_path, out_path, top_n=40, limit=None, progress_every=20000):
    con_src = hr.open_hsrdb(hsrdb_path)
    total = hr.count_entries(con_src)
    if limit:
        total = min(total, limit)
    print(f"Source file has {hr.count_entries(con_src):,} entries; processing {total:,}.")

    if os.path.exists(out_path):
        os.remove(out_path)
    con_out = sqlite3.connect(out_path)
    con_out.execute("""CREATE TABLE phases (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        reference_code TEXT,
        category TEXT,
        crystal_system TEXT,
        a REAL, b REAL, c REAL, alpha REAL, beta REAL, gamma REAL,
        space_group TEXT,
        elements TEXT,
        cod_code TEXT,
        source TEXT,
        n_peaks_total INTEGER
    )""")
    con_out.execute("CREATE TABLE peaks (phase_id INTEGER, d_A REAL, hkl TEXT, rel_intensity REAL)")
    con_out.execute("CREATE VIRTUAL TABLE phases_fts USING fts3(phase_id UNINDEXED, name, elements, formula)")

    t0 = time.time()
    n_written = 0
    n_skipped = 0
    peaks_buffer = []
    phases_buffer = []
    fts_buffer = []

    for entry_id in range(1, total + 1):
        try:
            idx_row = con_src.execute(
                "SELECT ProductID, XTSLSYS, A,B,C,ALPHA,BETA,GAMMA FROM general_indexed WHERE id=?", (entry_id,)
            ).fetchone()
            if idx_row is None:
                n_skipped += 1
                continue
            phase = hr.get_phase_detail(con_src, entry_id, top_n=top_n)
        except Exception as e:
            n_skipped += 1
            continue

        if not phase["peaks"]:
            n_skipped += 1
            continue

        text_row = con_src.execute(
            "SELECT chemicalformula FROM general_text WHERE rowid=?", (entry_id,)
        ).fetchone()
        formula = text_row[0] if text_row else ""

        product_id, sys_code, a, b, c, alpha, beta, gamma = idx_row
        category = guess_category(phase["elements"], formula)

        phases_buffer.append((
            entry_id, phase["name"], product_id, category, phase["crystal_system"],
            a, b, c, alpha, beta, gamma, phase["space_group"], ",".join(phase["elements"]),
            phase["cod_code"], phase["source"], len(phase["peaks"]),
        ))
        for p in phase["peaks"]:
            peaks_buffer.append((entry_id, p["d_A"], p["hkl"], p["rel_intensity"]))
        fts_buffer.append((entry_id, phase["name"], ",".join(phase["elements"]), formula))
        n_written += 1

        if len(phases_buffer) >= 5000:
            con_out.executemany(
                "INSERT INTO phases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", phases_buffer)
            con_out.executemany("INSERT INTO peaks VALUES (?,?,?,?)", peaks_buffer)
            con_out.executemany("INSERT INTO phases_fts (phase_id, name, elements, formula) VALUES (?,?,?,?)", fts_buffer)
            con_out.commit()
            phases_buffer.clear()
            peaks_buffer.clear()
            fts_buffer.clear()

        if entry_id % progress_every == 0:
            elapsed = time.time() - t0
            rate = entry_id / elapsed
            eta = (total - entry_id) / rate if rate > 0 else 0
            print(f"  {entry_id:,}/{total:,}  ({rate:.0f}/s, ETA {eta/60:.1f} min, written={n_written:,}, skipped={n_skipped:,})", flush=True)

    if phases_buffer:
        con_out.executemany("INSERT INTO phases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", phases_buffer)
        con_out.executemany("INSERT INTO peaks VALUES (?,?,?,?)", peaks_buffer)
        con_out.executemany("INSERT INTO phases_fts (phase_id, name, elements, formula) VALUES (?,?,?,?)", fts_buffer)
        con_out.commit()

    print("Building indexes...", flush=True)
    con_out.execute("CREATE INDEX idx_peaks_phase ON peaks(phase_id)")
    con_out.execute("CREATE INDEX idx_peaks_d ON peaks(d_A)")
    con_out.execute("CREATE INDEX idx_phases_category ON phases(category)")
    con_out.commit()

    print("Vacuuming...", flush=True)
    con_out.execute("VACUUM")
    con_out.close()
    con_src.close()

    elapsed = time.time() - t0
    size_mb = os.path.getsize(out_path) / (1024 * 1024)
    print(f"\nDone in {elapsed/60:.1f} min. Wrote {n_written:,} phases, skipped {n_skipped:,}.")
    print(f"Output file: {out_path}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("hsrdb_path")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "database", "cod_reference.sqlite"))
    ap.add_argument("--top-n", type=int, default=40)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    build(args.hsrdb_path, args.out, top_n=args.top_n, limit=args.limit)
