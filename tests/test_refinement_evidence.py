"""Refinement export (.xye), the FTIR+XRD evidence record, and the no-hidden-network rule."""
import ast
import json
import math
import os
import socket

import numpy as np
import pytest

import evidence
import refinement_export as rx
from trace_model import Trace

MODULES = os.path.join(os.path.dirname(__file__), "..", "modules")


# ------------------------------------------------------------------ .xye
def test_xye_round_trip_with_poisson_sigma(tmp_path):
    tt = np.array([30.0, 10.0, 20.0])
    counts = np.array([400.0, 0.0, 100.0])
    info = rx.write_xye(tmp_path / "p.xye", tt, counts)
    x, y, s = rx.read_xye(tmp_path / "p.xye")
    assert list(x) == [10.0, 20.0, 30.0] and list(y) == [0.0, 100.0, 400.0]
    assert list(s) == [1.0, 10.0, 20.0] and info["sigma"] == "sqrt(counts)"


def test_xye_refuses_sqrt_sigma_for_processed_data(tmp_path):
    with pytest.raises(ValueError, match="raw counts"):
        rx.write_xye(tmp_path / "p.xye", [1.0, 2.0], [3.0, 4.0], raw_counts=False)
    with pytest.raises(ValueError, match="positive"):
        rx.write_xye(tmp_path / "p.xye", [1.0, 2.0], [3.0, 4.0], sigma=[1.0, 0.0])
    info = rx.write_xye(tmp_path / "p.xye", [1.0, 2.0], [3.0, 4.0], sigma=[0.5, 0.5], raw_counts=False)
    assert info["sigma"] == "given"


def test_export_for_refinement_writes_provenance(tmp_path):
    src = tmp_path / "raw.xy"
    src.write_text("10 1\n", encoding="utf-8")
    info = rx.export_for_refinement(tmp_path / "out.xye", [10.0, 10.02], [5.0, 9.0], 1.5406, source_path=str(src),
                                    processing=["none"], app_version="t")
    if info["provenance"]:                       # labkit >= 1.2.0
        prov = json.loads(open(info["provenance"], encoding="utf-8").read())
        assert prov["parameters"]["wavelength_A"] == 1.5406 and prov["sources"][0]["file"] == "raw.xy"
        assert "No refinement" in prov["notes"]


def test_refinement_program_detection_runs_nothing():
    found = rx.find_refinement_programs()
    assert set(found) == {"GSAS-II (GSASII package)"} and isinstance(found["GSAS-II (GSASII package)"], bool)


# ------------------------------------------------------------------ evidence record
def traces():
    f = Trace("film.csv", [4000, 400], [0, 1], "#000", metadata={"path": "C:/secret/folder/film.csv",
                                                               "processing": ["Baseline (linear)"]})
    f.peaks = [{"x": 1720.04, "prominence": 0.5, "fwhm_cm1": 14.0, "assignment": "C=O stretch"},
               {"x": 2919.9, "prominence": 0.3, "fwhm_cm1": 20.0, "manual": True}]
    f.matches = [{"name": "Polyethylene Terephthalate (PET)", "tier": "Moderate", "confidence": 0.52,
                  "matched_count": 5, "total_reference_peaks": 7, "source": "Socrates 2001"}]
    x = Trace("powder.xy", [10, 80], [0, 1], "#000", metadata={"path": "powder.xy"})
    x.peaks = [{"two_theta": 30.0, "intensity": 900.0, "fwhm_deg": 0.2, "assignment": "<script>alert(1)</script>"}]
    return f, x


def test_record_links_both_techniques_and_round_trips(tmp_path):
    f, x = traces()
    rec = evidence.build_record("S-01", f, x, wavelength_a=1.5406, assumptions=["Cu Kα1 only"], app_version="3.4.0",
                                xrd_results={"Scherrer size (nm)": 16.9})
    assert rec["ftir"]["source_file"] == "film.csv"           # folder (may name a person) not stored
    assert rec["xrd"]["peaks"][0]["d_A"] == pytest.approx(1.5406 / (2 * math.sin(math.radians(15))), abs=1e-5)
    assert rec["ftir"]["candidates"][0]["tier"] == "Moderate"
    p = tmp_path / "s.json"
    evidence.save_record(rec, p)
    assert evidence.load_record(p) == json.loads(json.dumps(rec))
    (tmp_path / "bad.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        evidence.load_record(tmp_path / "bad.json")


def test_record_needs_an_id_and_some_data():
    with pytest.raises(ValueError, match="ID"):
        evidence.build_record(" ", *traces())
    with pytest.raises(ValueError, match="Load"):
        evidence.build_record("S", None, None)


def test_html_report_escapes_values_and_states_the_caveats(tmp_path):
    f, x = traces()
    html_text = evidence.render_html(evidence.build_record("S<1>", f, x, wavelength_a=1.5406))
    assert "<script>" not in html_text and "&lt;script&gt;" in html_text
    assert "not the probability" in html_text and "cannot establish its identity" in html_text
    assert "http" not in html_text.replace("http://www.w3.org", "")      # no external resources
    one_sided = evidence.render_html(evidence.build_record("S2", f, None))
    assert "No XRD pattern linked" in one_sided


# ------------------------------------------------------------------ no hidden data transmission
NETWORK_MODULES = {"socket", "urllib", "urllib3", "requests", "http", "httpx", "ftplib", "smtplib", "aiohttp",
                   "websocket", "websockets", "telnetlib", "xmlrpc"}


def test_no_module_imports_a_network_library():
    offenders = []
    for name in os.listdir(MODULES):
        if not name.endswith(".py"):
            continue
        tree = ast.parse(open(os.path.join(MODULES, name), encoding="utf-8").read())
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            offenders += [f"{name}: {m}" for m in mods if m.split(".")[0] in NETWORK_MODULES]
    assert offenders == []


def test_loading_and_analysing_opens_no_connection(tmp_path, monkeypatch):
    import file_readers
    import ftir_analysis
    calls = []
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: calls.append(a))
    p = tmp_path / "s.csv"
    xs = np.arange(4000.0, 399.0, -2.0)
    p.write_text("".join(f"{a},{0.1 + 0.5 * math.exp(-((a - 1700) / 10) ** 2)}\n" for a in xs), encoding="utf-8")
    r = file_readers.read_ftir_any(str(p))
    db = ftir_analysis.load_database(os.path.join(MODULES, "..", "database", "ftir_reference_db.json"))
    peaks = ftir_analysis.detect_peaks(r.x, r.y, noise_floor=True)
    ftir_analysis.match_peaks_to_database(peaks, db)
    assert calls == []
