"""
Validation laboratory from the command line: run the FTIR matcher on YOUR measured spectra of
known materials, listed in a manifest CSV (see modules/validation_lab.py for the columns), and
write a Markdown report with accuracy, confusion matrix, precision/recall, false-positive
warnings and tolerance / peak-shift sensitivity.

    python tools/validate_ftir_matching.py manifest.csv [--out report.md] [--tolerance 10] [--top-k 3]

Nothing leaves the computer. The match score is a screening score, not a probability.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "modules"))

import ftir_analysis  # noqa: E402
import validation_lab  # noqa: E402

DB_PATH = os.path.join(HERE, "..", "database", "ftir_reference_db.json")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("manifest")
    ap.add_argument("--out", help="Markdown report path (default: print)")
    ap.add_argument("--json", help="also write the full result as JSON")
    ap.add_argument("--tolerance", type=float, default=10.0)
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--no-tune", action="store_true", help="do not choose the tolerance on the train split")
    a = ap.parse_args(argv)
    db = ftir_analysis.load_database(DB_PATH)
    items = validation_lab.load_manifest(a.manifest)
    report = validation_lab.run_validation(items, db, tolerance=a.tolerance, top_k=a.top_k, tune_on_train=not a.no_tune)
    md = validation_lab.report_markdown(report)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"wrote {a.out}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(md)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
