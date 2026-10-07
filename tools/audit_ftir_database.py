"""
Audit the FTIR reference database: structure, label vocabulary, citations, band/assignment
plausibility and entries that a peak list cannot tell apart.

    python tools/audit_ftir_database.py              # print the report
    python tools/audit_ftir_database.py --write      # also write docs/FTIR_DATABASE_AUDIT.md

Errors (exit code 1) are structural problems that would break or mislead the matcher.
Notes are things a curator should look at; they are not necessarily wrong.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "modules"))

import ftir_analysis  # noqa: E402
import ftir_matching  # noqa: E402

DB_PATH = os.path.join(ROOT, "database", "ftir_reference_db.json")
REPORT_PATH = os.path.join(ROOT, "docs", "FTIR_DATABASE_AUDIT.md")
STRENGTHS = {"very strong", "strong", "medium-strong", "medium", "weak-medium", "weak", "n/a"}
SHAPES = {"broad", "very broad", "sharp", "doublet"}
# (pattern in the assignment, low, high): a band so labelled should overlap this region.
# Deliberately loose -- only gross typos (e.g. a C=O stretch at 1270 instead of 1720) trip it.
PLAUSIBLE = [
    (r"\bC=O stretch", 1550, 1870),
    (r"\bO-H stretch", 2400, 3750),
    (r"\bN-H stretch", 3000, 3550),
    (r"\bC-H stretch", 2700, 3320),
    (r"C≡N stretch", 2000, 2300),
    (r"\bamide I\b", 1580, 1720),
    (r"\bamide II\b", 1480, 1640),
]


def canonical_intensity(label):
    toks = [t.strip() for t in str(label).split(",") if t.strip()]
    strength = [t for t in toks if t in STRENGTHS]
    shape = sorted(t for t in toks if t not in STRENGTHS)
    return ", ".join(strength + shape)


def audit(db):
    errors, notes = [], []
    refs = {r["id"] for r in db.get("_meta", {}).get("references", [])}
    names = Counter()
    entries = []
    for cat in ftir_analysis.MATERIAL_CATEGORIES:
        for e in db.get(cat, []):
            entries.append(e)
            names[e.get("name", "")] += 1
            where = f"{e.get('name', '?')} [{cat}]"
            for key in ("name", "category", "source", "peaks"):
                if not e.get(key):
                    errors.append(f"{where}: missing '{key}'")
            cited = re.findall(r"[a-z]+\d{4}|\bnist\b|\bsdbs\b|\bicdd\b|\bcod\b", e.get("source", ""))
            for c in cited:
                if c not in refs:
                    errors.append(f"{where}: cites '{c}', which is not in _meta.references")
            if not cited:
                errors.append(f"{where}: source names no reference id")
            seen = set()
            for p in e.get("peaks", []):
                lo, hi = p.get("range", [None, None])
                if lo is None or hi is None or lo > hi:
                    errors.append(f"{where}: bad range {p.get('range')}")
                    continue
                if tuple(p["range"]) in seen:
                    errors.append(f"{where}: duplicate band {p['range']}")
                seen.add(tuple(p["range"]))
                label = p.get("intensity", "")
                toks = [t.strip() for t in str(label).split(",") if t.strip()]
                if any(t not in STRENGTHS | SHAPES for t in toks) or sum(t in STRENGTHS for t in toks) != 1:
                    errors.append(f"{where}: intensity '{label}' is not in the vocabulary")
                elif canonical_intensity(label) != label:
                    errors.append(f"{where}: intensity '{label}' should read '{canonical_intensity(label)}'")
                if (lo, hi) == (0, 0):
                    continue
                if lo < 350:
                    notes.append(f"{where}: band {p['range']} is in the far-IR, below most instruments' range")
                if hi - lo > 600:
                    notes.append(f"{where}: band {p['range']} is {hi - lo} cm-1 wide; it will match almost anything there")
                a = p.get("assignment", "")
                if re.search("overtone|combination", a, re.I):
                    continue
                for pat, mn, mx in PLAUSIBLE:
                    if re.search(pat, a, re.I) and (hi < mn or lo > mx):
                        notes.append(f"{where}: '{a}' at {p['range']} is outside the usual {mn}-{mx} cm-1")
            n_bands = sum(ftir_matching.is_matchable(p) for p in e.get("peaks", []))
            if 0 < n_bands <= ftir_matching.FEW_BANDS:
                notes.append(f"{where}: only {n_bands} band(s) -- matches to it can never exceed Moderate")
    for n, k in names.items():
        if k > 1:
            errors.append(f"material name '{n}' appears {k} times (names must be unique)")
    for f in db.get("functional_groups", []):
        if canonical_intensity(f.get("intensity", "")) != f.get("intensity", ""):
            errors.append(f"functional group {f.get('name')}: intensity '{f.get('intensity')}' not canonical")
    twins = ftir_matching.look_alikes(entries)
    pairs = sorted({tuple(sorted((a, b))) for a, bs in twins.items() for b in bs})
    return errors, notes, pairs, entries


def report(db, errors, notes, pairs, entries):
    meta = db.get("_meta", {})
    bands = [p for e in entries for p in e["peaks"] if ftir_matching.is_matchable(p)]
    lines = [f"# FTIR reference database audit (version {meta.get('version', '?')})", "",
             "Generated by `python tools/audit_ftir_database.py --write`. No band positions are checked "
             "against the literature here -- that needs the cited sources; this audit checks structure, "
             "vocabulary, citations and internal consistency.", "",
             f"- {len(entries)} materials, {len(bands)} matchable bands, "
             f"{len(db.get('functional_groups', []))} functional-group correlations, "
             f"{len(meta.get('references', []))} references",
             f"- Errors: **{len(errors)}**", f"- Notes for a curator: {len(notes)}",
             f"- Look-alike pairs (bands overlap >= {ftir_matching.LOOK_ALIKE_OVERLAP:.0%} both ways): {len(pairs)}", ""]
    if errors:
        lines += ["## Errors", ""] + [f"- {e}" for e in errors] + [""]
    lines += ["## Notes", ""] + ([f"- {n}" for n in notes] or ["- none"]) + [""]
    lines += ["## Look-alike entries", "",
              "A peak list cannot separate these pairs, so the app lists them next to any strong match. "
              "Where a pair is chemically unrelated (e.g. a polymer and a salt), the entries' band lists are "
              "probably too generic and are the first candidates for curation against the cited sources.", ""]
    lines += [f"- {a} ↔ {b}" for a, b in pairs] + [""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    with open(DB_PATH, encoding="utf-8") as f:
        db = json.load(f)
    errors, notes, pairs, entries = audit(db)
    text = report(db, errors, notes, pairs, entries)
    print(text)
    if args.write:
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.write(text)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
