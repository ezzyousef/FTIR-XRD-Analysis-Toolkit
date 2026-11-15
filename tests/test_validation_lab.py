"""Validation laboratory: manifest checks, train/test isolation, metrics computed by hand.
The spectra here are synthetic (drawn from the database's own band tables), so they test the
computation and the plumbing only -- they say nothing about how well the matcher identifies
real samples (see validation_lab.DISCLAIMER)."""
import csv
import math
import os

import numpy as np
import pytest

import ftir_analysis
import ftir_matching
import validation_lab as vl

DB = ftir_analysis.load_database(os.path.join(os.path.dirname(__file__), "..", "database", "ftir_reference_db.json"))
X = np.arange(4000.0, 599.0, -2.0)


def entry(name):
    return ftir_analysis.find_entry(DB, name)


def write_spectrum(path, names):
    y = 0.01 + sum(ftir_matching.synthetic_reference_spectrum(entry(n), X) for n in names) * 0.5
    y = y + np.random.default_rng(abs(hash(path)) % 2**32).normal(0, 0.002, len(X))
    with open(path, "w", encoding="utf-8") as f:
        f.write("wavenumber,absorbance\n" + "".join(f"{a:.1f},{b:.6f}\n" for a, b in zip(X, y)))


def write_manifest(tmp_path, rows):
    p = tmp_path / "manifest.csv"
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "label", "split", "mode", "sample_id"])
        w.writerows(rows)
    return str(p)


# ------------------------------------------------------------------ pure metrics, by hand
def R(truth, top1, tier="Strong", ranked=None):
    truth = list(truth)
    confident = tier in vl.CONFIDENT_TIERS
    correct = (top1 == vl.NO_MATCH) if not truth else (top1 in truth)
    ranked = ranked or ([top1] if top1 != vl.NO_MATCH else [])
    return {"file": "f", "truth": truth, "ood": not truth, "top1": top1, "ranked": ranked, "tier": tier,
            "score": 0.7, "correct": correct, "in_top_k": correct or bool(set(ranked) & set(truth)),
            "false_positive": confident and not correct and top1 != vl.NO_MATCH}


def test_metrics_match_a_hand_count():
    results = [R(["A"], "A"), R(["A"], "A"), R(["A"], "B"), R(["B"], "B"), R([], "B"), R([], vl.NO_MATCH, "Weak")]
    s = vl.summarise(results)
    assert s["top1_accuracy"] == pytest.approx(4 / 6)
    assert s["n_false_positive"] == 2 and s["n_ood"] == 2 and s["ood_false_positive_rate"] == pytest.approx(0.5)
    m = vl.per_class_metrics(results)
    # A: tp 2, fp 0, fn 1. B: tp 1, fp 2 (one A sample, one out-of-library), fn 0.
    assert (m["A"]["tp"], m["A"]["fp"], m["A"]["fn"]) == (2, 0, 1)
    assert m["A"]["precision"] == 1.0 and m["A"]["recall"] == pytest.approx(2 / 3)
    assert m["A"]["f1"] == pytest.approx(0.8)
    assert (m["B"]["tp"], m["B"]["fp"], m["B"]["fn"]) == (1, 2, 0) and m["B"]["precision"] == pytest.approx(1 / 3)
    cm = vl.confusion_matrix(results)
    assert cm["A"] == {"A": 2, "B": 1} and cm[vl.NO_MATCH] == {"B": 1, vl.NO_MATCH: 1}


def test_wilson_interval_known_values():
    # 8 of 10: Wilson 95 % interval 0.490-0.943 (from the closed form)
    lo, hi = vl.wilson_interval(8, 10)
    p, n, z = 0.8, 10, 1.96
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    assert (lo, hi) == pytest.approx((c - h, c + h))
    assert lo == pytest.approx(0.490, abs=1e-3) and hi == pytest.approx(0.943, abs=1e-3)


def test_label_parsing():
    assert vl.parse_label("A + B") == frozenset({"A", "B"})
    for ood in ("", "none", "Unknown"):
        assert vl.parse_label(ood) == frozenset()


# ------------------------------------------------------------------ manifest and isolation
def test_manifest_is_strict(tmp_path):
    write_spectrum(str(tmp_path / "a.csv"), ["Polyethylene (PE)"])
    with pytest.raises(vl.ManifestError, match="split"):
        vl.load_manifest(write_manifest(tmp_path, [("a.csv", "Polyethylene (PE)", "validation", "absorbance", "s1")]))
    with pytest.raises(vl.ManifestError, match="not found"):
        vl.load_manifest(write_manifest(tmp_path, [("missing.csv", "X", "test", "absorbance", "s1")]))
    with pytest.raises(vl.ManifestError, match="Line 2 has 6"):
        vl.load_manifest(write_manifest(tmp_path, [("a.csv", "X", "test", "absorbance", "s1", "extra")]))


def test_train_test_leak_is_refused(tmp_path):
    write_spectrum(str(tmp_path / "a.csv"), ["Polyethylene (PE)"])
    (tmp_path / "copy.csv").write_bytes((tmp_path / "a.csv").read_bytes())
    items = vl.load_manifest(write_manifest(tmp_path, [("a.csv", "Polyethylene (PE)", "train", "absorbance", "s1"),
                                                       ("copy.csv", "Polyethylene (PE)", "test", "absorbance", "s2")]))
    with pytest.raises(vl.ManifestError, match="leak"):
        vl.check_isolation(items)
    write_spectrum(str(tmp_path / "b.csv"), ["Polypropylene (PP)"])
    items = vl.load_manifest(write_manifest(tmp_path, [("a.csv", "Polyethylene (PE)", "train", "absorbance", "S"),
                                                       ("b.csv", "Polypropylene (PP)", "test", "absorbance", "S")]))
    with pytest.raises(vl.ManifestError, match="sample S"):
        vl.check_isolation(items)


# ------------------------------------------------------------------ end to end on synthetic spectra
def test_full_run_reports_metrics_sensitivity_and_warnings(tmp_path):
    names = ["Polystyrene (PS)", "Poly(methyl methacrylate) (PMMA)", "Polycarbonate (PC)"]
    rows = []
    for i, n in enumerate(names):
        write_spectrum(str(tmp_path / f"test{i}.csv"), [n])
        rows.append((f"test{i}.csv", n, "test", "absorbance", f"T{i}"))
        write_spectrum(str(tmp_path / f"train{i}.csv"), [n])
        rows.append((f"train{i}.csv", n, "train", "absorbance", f"R{i}"))
    write_spectrum(str(tmp_path / "typo.csv"), [names[0]])
    rows.append(("typo.csv", "Polystyrene (typo)", "test", "absorbance", "T9"))
    items = vl.load_manifest(write_manifest(tmp_path, rows))
    rep = vl.run_validation(items, DB, tolerances=(10.0, 20.0), shifts=(0.0, 30.0))
    assert rep["n_test"] == 4 and rep["n_train"] == 3 and rep["tuned_on_train"]
    assert rep["tolerance"] in (10.0, 20.0)
    assert rep["unknown_labels"] == ["Polystyrene (typo)"]
    # synthetic spectra of the database's own bands: the three real labels are found
    by_file = {r["file"]: r for r in rep["results"]}
    assert all(by_file[f"test{i}.csv"]["correct"] for i in range(3))
    assert set(rep["tolerance_sensitivity"]) == {10.0, 20.0} and set(rep["shift_sensitivity"]) == {0.0, 30.0}
    # a 30 cm-1 shift must not do better than no shift
    assert rep["shift_sensitivity"][30.0] <= rep["shift_sensitivity"][0.0]
    md = vl.report_markdown(rep)
    assert "screening score, not an identification probability" in md and "Polystyrene (typo)" in md


def test_out_of_library_sample_counts_a_confident_answer_as_false_positive(tmp_path):
    db = {k: (list(v) if isinstance(v, list) else v) for k, v in DB.items()}
    # remove polystyrene from the library, then present a polystyrene spectrum labelled out-of-library
    db["polymers"] = [e for e in db["polymers"] if e["name"] != "Polystyrene (PS)"]
    write_spectrum(str(tmp_path / "ps.csv"), ["Polystyrene (PS)"])
    items = vl.load_manifest(write_manifest(tmp_path, [("ps.csv", "none", "test", "absorbance", "U1")]))
    rep = vl.run_validation(items, db, tolerances=(10.0,), shifts=(0.0,))
    r = rep["results"][0]
    assert r["ood"]
    assert r["false_positive"] == (r["tier"] in vl.CONFIDENT_TIERS)
    assert r["correct"] == (r["top1"] == vl.NO_MATCH)
