"""
validation_lab.py
Validation laboratory for FTIR database matching: run the matcher on a user-supplied set of
MEASURED spectra of known materials and mixtures, and report how often it is right.

The app ships no reference spectra and this module never makes any up. The user supplies a
manifest (CSV) that lists their own spectra with what each sample really is:

    file,label,split,mode,sample_id,notes
    spectra/pe_film_01.csv,Polyethylene (PE),test,absorbance,PE-01,
    spectra/blend_03.csv,Polyethylene (PE)+Polypropylene (PP),test,absorbance,BL-03,
    spectra/unknown_resin.csv,,test,transmittance,UR-1,not in the library

  file       path relative to the manifest
  label      the true material name(s) as written in the database, '+' between components of a
             mixture; empty, "none" or "unknown" for a material that is NOT in the library
             (out-of-distribution: the right answer is "no confident match")
  split      "train" or "test". Settings (the tolerance) may be tuned on train only; every
             reported metric comes from test. A file or sample id in both splits is refused.
  mode       "absorbance" (default) or "transmittance"

Reported: top-1 / top-k accuracy, confusion matrix, per-class precision / recall / F1, false
positives (a confident answer that is wrong, or any confident answer for an out-of-library
sample), and sensitivity to the matching tolerance and to a systematic peak shift.

Interpretation: the match score is a screening score, not a probability. These metrics
describe this matcher on THIS test set only; a handful of spectra per class gives wide
confidence intervals (shown as Wilson 95 % intervals). Synthetic spectra (as in the unit
tests) check that the computation is right; they do not validate the chemistry.
"""
import csv
import hashlib
import math
import os
from collections import Counter, defaultdict

try:
    import ftir_analysis
    import ftir_matching
    import file_readers
except ImportError:  # pragma: no cover - package import
    from modules import ftir_analysis, ftir_matching, file_readers

NO_MATCH = "(no confident match)"
OOD_LABELS = {"", "none", "unknown", "not in library", "ood"}
CONFIDENT_TIERS = ("Strong", "Moderate")
MANIFEST_COLUMNS = ("file", "label", "split", "mode", "sample_id", "notes")
DISCLAIMER = ("The match score is a screening score, not an identification probability. These figures describe "
              "this matcher on this test set only. Synthetic spectra check the computation, not the chemistry.")


class ManifestError(ValueError):
    pass


def parse_label(text):
    """Set of true component names; empty set = out of library."""
    text = (text or "").strip()
    if text.lower() in OOD_LABELS:
        return frozenset()
    return frozenset(p.strip() for p in text.split("+") if p.strip())


def load_manifest(path):
    """Read and check a manifest. Strict: unknown split/mode values, ragged rows, missing files
    and a header without 'file' and 'label' are refused with the line number."""
    base = os.path.dirname(os.path.abspath(path))
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise ManifestError("The manifest is empty.")
    header = [h.strip().lower() for h in rows[0]]
    if "file" not in header or "label" not in header:
        raise ManifestError("The manifest needs a header row with at least 'file' and 'label' columns.")
    items = []
    for lineno, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        if len(row) > len(header):
            raise ManifestError(f"Line {lineno} has {len(row)} values but the header has {len(header)}.")
        rec = dict(zip(header, [c.strip() for c in row] + [""] * (len(header) - len(row))))
        split = (rec.get("split") or "test").lower()
        if split not in ("train", "test"):
            raise ManifestError(f"Line {lineno}: split must be 'train' or 'test', not {rec.get('split')!r}.")
        mode = (rec.get("mode") or "absorbance").lower()
        if mode not in ("absorbance", "transmittance"):
            raise ManifestError(f"Line {lineno}: mode must be 'absorbance' or 'transmittance'.")
        file_path = rec["file"]
        if not file_path:
            raise ManifestError(f"Line {lineno}: no file given.")
        full = file_path if os.path.isabs(file_path) else os.path.join(base, file_path)
        if not os.path.isfile(full):
            raise ManifestError(f"Line {lineno}: file not found: {file_path}")
        items.append({"line": lineno, "file": full, "label": parse_label(rec.get("label")), "split": split,
                      "mode": mode, "sample_id": rec.get("sample_id", ""), "notes": rec.get("notes", "")})
    if not items:
        raise ManifestError("The manifest lists no spectra.")
    return items


def _digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check_isolation(items):
    """Refuse a train/test leak: the same file content, or the same sample id, in both splits."""
    seen = defaultdict(set)
    for it in items:
        seen[("sha256", _digest(it["file"]))].add(it["split"])
        if it.get("sample_id"):
            seen[("sample", it["sample_id"])].add(it["split"])
    leaks = [f"{kind} {key[:12] if kind == 'sha256' else key}" for (kind, key), splits in seen.items()
             if len(splits) > 1]
    if leaks:
        raise ManifestError("Train/test leak: " + "; ".join(leaks) + " appear(s) in both splits.")
    return True


def check_labels(items, database):
    """Names in the manifest that are not database entries (typos would otherwise count as
    out-of-library samples)."""
    names = {e["name"] for c in ftir_analysis.MATERIAL_CATEGORIES for e in database.get(c, [])}
    return sorted({n for it in items for n in it["label"] if n not in names})


# ------------------------------------------------------------------------------- running
def default_peaks(x, y, mode):
    """The detection the app uses by default: noise floor on, CO2 region skipped."""
    return ftir_analysis.detect_peaks(x, y, prominence_frac=0.02, mode=mode, noise_floor=True,
                                      exclude_regions=[ftir_analysis.CO2_REGION])


def shift_peaks(peaks, shift_cm1):
    return [dict(p, x=p["x"] + shift_cm1) for p in peaks]


def predict(peaks, database, tolerance, spectral_range=None, top_k=3):
    """Ranked candidate names and the top candidate's tier."""
    ranked = ftir_analysis.match_peaks_to_database(peaks, database, tolerance=tolerance,
                                                    spectral_range=spectral_range)
    return {"ranked": [r["name"] for r in ranked[:max(top_k, 1)]],
            "tier": ranked[0]["tier"] if ranked else "None",
            "score": float(ranked[0]["confidence"]) if ranked else 0.0}


def evaluate_item(item, database, tolerance=10.0, shift_cm1=0.0, top_k=3, reader=None, peak_finder=None):
    reader = reader or file_readers.read_ftir_any
    peak_finder = peak_finder or default_peaks
    data = reader(item["file"])
    peaks = shift_peaks(peak_finder(data.x, data.y, item["mode"]), shift_cm1)
    rng = (float(min(data.x)), float(max(data.x)))
    p = predict(peaks, database, tolerance, spectral_range=rng, top_k=top_k)
    confident = p["tier"] in CONFIDENT_TIERS
    top1 = p["ranked"][0] if (p["ranked"] and confident) else NO_MATCH
    truth = item["label"]
    if not truth:
        correct = top1 == NO_MATCH
    else:
        correct = top1 in truth
    return {"file": os.path.basename(item["file"]), "sample_id": item.get("sample_id", ""),
            "truth": sorted(truth), "ood": not truth, "top1": top1, "ranked": p["ranked"], "tier": p["tier"],
            "score": p["score"], "correct": bool(correct),
            "in_top_k": bool((not truth and top1 == NO_MATCH) or (truth and set(p["ranked"][:top_k]) & truth)),
            "false_positive": bool(confident and not correct), "n_peaks": len(peaks)}


# ------------------------------------------------------------------------------- metrics
def wilson_interval(k, n, z=1.96):
    """95 % Wilson score interval for a proportion k/n."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def truth_class(result):
    """One class per sample for the confusion matrix: the single component, the '+'-joined
    mixture, or NO_MATCH for an out-of-library sample."""
    return " + ".join(result["truth"]) if result["truth"] else NO_MATCH


def confusion_matrix(results):
    """{true class: {predicted: count}}. A mixture predicted as one of its components counts
    on that component's column (the matcher's top-1 names one material)."""
    cm = defaultdict(Counter)
    for r in results:
        cm[truth_class(r)][r["top1"]] += 1
    return {k: dict(v) for k, v in cm.items()}


def per_class_metrics(results):
    """Precision, recall and F1 per predicted/true material. A prediction is a true positive
    for class c when c is the top-1 and c is in the sample's truth."""
    classes = sorted({c for r in results for c in r["truth"]} | {r["top1"] for r in results if r["top1"] != NO_MATCH})
    out = {}
    for c in classes:
        tp = sum(1 for r in results if r["top1"] == c and c in r["truth"])
        fp = sum(1 for r in results if r["top1"] == c and c not in r["truth"])
        fn = sum(1 for r in results if c in r["truth"] and r["top1"] != c)
        precision = tp / (tp + fp) if tp + fp else float("nan")
        recall = tp / (tp + fn) if tp + fn else float("nan")
        f1 = 2 * precision * recall / (precision + recall) if tp else (0.0 if (tp + fp) and (tp + fn) else float("nan"))
        out[c] = {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}
    return out


def summarise(results):
    n = len(results)
    k1 = sum(r["correct"] for r in results)
    kk = sum(r["in_top_k"] for r in results)
    ood = [r for r in results if r["ood"]]
    fps = [r for r in results if r["false_positive"]]
    return {"n": n, "top1_accuracy": k1 / n if n else float("nan"), "top1_ci95": wilson_interval(k1, n),
            "topk_accuracy": kk / n if n else float("nan"), "n_ood": len(ood),
            "ood_false_positive_rate": (sum(r["false_positive"] for r in ood) / len(ood)) if ood else float("nan"),
            "n_false_positive": len(fps),
            "false_positive_warnings": [f"{r['file']}: confident '{r['top1']}' ({r['tier']}, {r['score']:.2f}) "
                                        f"but the sample is {truth_class(r)}" for r in fps]}


# ------------------------------------------------------------------------------- the laboratory
def run_validation(items, database, tolerance=10.0, top_k=3, tolerances=(5.0, 10.0, 15.0, 20.0),
                   shifts=(-8.0, -4.0, 0.0, 4.0, 8.0), tune_on_train=True, reader=None, peak_finder=None):
    """Full validation run. If tune_on_train and the manifest has train items, the tolerance
    with the best train top-1 accuracy is used for the test metrics (ties: the value closest
    to `tolerance`). Sensitivity sweeps run on the test split."""
    check_isolation(items)
    train = [it for it in items if it["split"] == "train"]
    test = [it for it in items if it["split"] == "test"]
    if not test:
        raise ManifestError("The manifest has no 'test' items: nothing to report metrics on.")

    def run(subset, tol, shift=0.0):
        return [evaluate_item(it, database, tol, shift, top_k, reader, peak_finder) for it in subset]

    chosen, train_scan = float(tolerance), {}
    if tune_on_train and train:
        for tol in tolerances:
            train_scan[float(tol)] = summarise(run(train, tol))["top1_accuracy"]
        best = max(train_scan.values())
        chosen = min((t for t, a in train_scan.items() if a == best), key=lambda t: abs(t - tolerance))
    results = run(test, chosen)
    report = {"tolerance": chosen, "tuned_on_train": bool(tune_on_train and train), "train_scan": train_scan,
              "n_train": len(train), "n_test": len(test), "top_k": top_k, "results": results,
              "summary": summarise(results), "confusion": confusion_matrix(results),
              "per_class": per_class_metrics(results), "unknown_labels": check_labels(items, database),
              "tolerance_sensitivity": {float(t): summarise(run(test, t))["top1_accuracy"] for t in tolerances},
              "shift_sensitivity": {float(s): summarise(run(test, chosen, s))["top1_accuracy"] for s in shifts},
              "disclaimer": DISCLAIMER}
    return report


def _pct(v):
    return "n/a" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{100 * v:.0f} %"


def report_markdown(report):
    s = report["summary"]
    lo, hi = s["top1_ci95"]
    lines = ["# FTIR matching validation report", "", f"> {report['disclaimer']}", "",
             f"Test spectra: {report['n_test']} (train: {report['n_train']}). Tolerance: ±{report['tolerance']:g} cm⁻¹"
             + (" (chosen on the train split)" if report["tuned_on_train"] else "") + ".", "",
             f"- Top-1 accuracy: {_pct(s['top1_accuracy'])} (95 % CI {_pct(lo)}–{_pct(hi)})",
             f"- Top-{report['top_k']} accuracy: {_pct(s['topk_accuracy'])}",
             f"- Confident wrong answers (false positives): {s['n_false_positive']}",
             f"- Out-of-library samples: {s['n_ood']}, given a confident answer: {_pct(s['ood_false_positive_rate'])}"]
    if report["unknown_labels"]:
        lines += ["", "**Labels not found in the database** (check spelling): " + ", ".join(report["unknown_labels"])]
    if s["false_positive_warnings"]:
        lines += ["", "## False-positive warnings", ""] + [f"- {w}" for w in s["false_positive_warnings"]]
    lines += ["", "## Per class", "", "| Class | TP | FP | FN | Precision | Recall | F1 |", "|---|---|---|---|---|---|---|"]
    for c, m in report["per_class"].items():
        lines.append(f"| {c} | {m['tp']} | {m['fp']} | {m['fn']} | {_pct(m['precision'])} | {_pct(m['recall'])} | "
                     f"{_pct(m['f1'])} |")
    lines += ["", "## Confusion (true → predicted top-1)", ""]
    for t, row in sorted(report["confusion"].items()):
        lines.append(f"- {t}: " + ", ".join(f"{p} × {n}" for p, n in sorted(row.items(), key=lambda kv: -kv[1])))
    lines += ["", "## Sensitivity (test split, top-1 accuracy)", "",
              "Tolerance: " + ", ".join(f"±{t:g} → {_pct(a)}" for t, a in report["tolerance_sensitivity"].items()),
              "", "Systematic peak shift: " + ", ".join(f"{s_:+g} cm⁻¹ → {_pct(a)}"
                                                       for s_, a in report["shift_sensitivity"].items()),
              "", "## Per spectrum", "", "| File | Truth | Top-1 | Tier | Score | Correct |", "|---|---|---|---|---|---|"]
    for r in report["results"]:
        lines.append(f"| {r['file']} | {truth_class(r)} | {r['top1']} | {r['tier']} | {r['score']:.2f} | "
                     f"{'yes' if r['correct'] else 'NO'} |")
    return "\n".join(lines) + "\n"
