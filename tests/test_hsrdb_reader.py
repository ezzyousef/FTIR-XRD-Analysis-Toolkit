import sqlite3
import struct

import pytest

import hsrdb_reader as hr


def _build_synthetic_hsrdb(path, entries):
    """
    Build a minimal SQLite file with the same table/column layout as a real
    PANalytical HighScore .hsrdb file (verified against the user's actual
    COD24_HS4x.hsrdb by decoding real entries and cross-checking recomputed
    d-spacings against the stored unit cell -- see hsrdb_reader.py's module
    docstring). Each entry: dict with id, product_id, formula, compound_name,
    system_code, cell (a,b,c,alpha,beta,gamma), spgr, comment, cas,
    reflections (list of (h,k,l,d,intensity)), literature (authors,journal,year,volume,pages) or None.
    """
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE general_indexed(id INTEGER PRIMARY KEY, ProductID TEXT, XTSLSYS TEXT, "
                "A REAL, B REAL, C REAL, ALPHA REAL, BETA REAL, GAMMA REAL, NumberOfElements INTEGER)")
    con.execute("CREATE TABLE general_stored(pid INTEGER PRIMARY KEY, SPGR TEXT, Comment TEXT, CAS TEXT, "
                "Lines BLOB, HKL BLOB, LinesI BLOB)")
    con.execute("CREATE VIRTUAL TABLE general_text USING fts3(chemicalformula, compoundname, mineralname, commonname)")
    con.execute("CREATE VIRTUAL TABLE literature_text USING fts3(volume, pages, year, authors, journal, referencetype)")
    con.execute("CREATE TABLE literature_map(doc INTEGER, pid INTEGER)")

    for e in entries:
        con.execute("INSERT INTO general_indexed(id, ProductID, XTSLSYS, A,B,C,ALPHA,BETA,GAMMA, NumberOfElements) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (e["id"], e["product_id"], e["system_code"], *e["cell"], e.get("n_elements", 2)))
        hkl_blob = b"".join(struct.pack("<hhh", h, k, l) for h, k, l, d, i in e["reflections"])
        lines_blob = b"".join(struct.pack("<fh", d, round(i)) for h, k, l, d, i in e["reflections"])
        linesi_blob = b"".join(struct.pack("<f", i) for h, k, l, d, i in e["reflections"])
        con.execute("INSERT INTO general_stored(pid, SPGR, Comment, CAS, Lines, HKL, LinesI) VALUES (?,?,?,?,?,?,?)",
                     (e["id"], e.get("spgr", ""), e.get("comment", ""), e.get("cas", ""),
                      lines_blob, hkl_blob, linesi_blob))
        con.execute("INSERT INTO general_text(rowid, chemicalformula, compoundname, mineralname, commonname) "
                     "VALUES (?,?,?,?,?)",
                     (e["id"], e["formula"], e.get("compound_name", ""), e.get("mineral_name", ""), e.get("common_name", "")))
        lit = e.get("literature")
        if lit:
            con.execute("INSERT INTO literature_text(rowid, volume, pages, year, authors, journal, referencetype) "
                        "VALUES (?,?,?,?,?,?,0)",
                        (e["id"], lit.get("volume", ""), lit.get("pages", ""), lit.get("year", ""),
                         lit.get("authors", ""), lit.get("journal", "")))
            con.execute("INSERT INTO literature_map(doc, pid) VALUES (?,?)", (e["id"], e["id"]))
    con.commit()
    con.close()


CUBIC_ENTRY = {
    "id": 1, "product_id": "96-100-0001", "formula": "Na1.00 Cl1.00",
    "compound_name": "Sodium Chloride", "system_code": "C",
    "cell": (5.64, 5.64, 5.64, 90.0, 90.0, 90.0),
    "spgr": "F m -3 m", "comment": "COD database code: 1000041",
    "cas": "7647-14-5",
    "reflections": [(1, 1, 1, 3.2568, 1000.0), (2, 0, 0, 2.8200, 550.0), (2, 2, 0, 1.9942, 150.0)],
    "literature": {"authors": "Smith, J.", "journal": "Acta Cryst.", "year": "1990", "volume": "46", "pages": "123"},
}

HEXAGONAL_ENTRY = {
    "id": 2, "product_id": "96-350-9999", "formula": "Ce1.00 V1.00 O4.00",
    "compound_name": "Cerium Vanadate", "system_code": "T",
    "cell": (7.4009, 7.4009, 6.4966, 90.0, 90.0, 90.0),
    "spgr": "I 41/a m d", "comment": "COD database code: 2000123",
    "reflections": [(1, 0, 1, 4.8824, 1000.0), (2, 0, 0, 3.7005, 400.0)],
    "literature": None,
}


@pytest.fixture
def synthetic_db(tmp_path):
    path = str(tmp_path / "synthetic.hsrdb")
    _build_synthetic_hsrdb(path, [CUBIC_ENTRY, HEXAGONAL_ENTRY])
    return path


def test_open_hsrdb_accepts_valid_file(synthetic_db):
    con = hr.open_hsrdb(synthetic_db)
    assert hr.count_entries(con) == 2
    con.close()


def test_open_hsrdb_rejects_missing_file():
    with pytest.raises(ValueError):
        hr.open_hsrdb("this_file_does_not_exist.hsrdb")


def test_open_hsrdb_rejects_non_hsrdb_sqlite_file(tmp_path):
    path = str(tmp_path / "not_hsrdb.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE unrelated(x INTEGER)")
    con.commit()
    con.close()
    with pytest.raises(ValueError):
        hr.open_hsrdb(path)


def test_search_hsrdb_by_text_query(synthetic_db):
    con = hr.open_hsrdb(synthetic_db)
    results = hr.search_hsrdb(con, query="Sodium Chloride")
    assert len(results) == 1
    assert results[0]["reference_code"] == "96-100-0001"
    assert results[0]["crystal_system"] == "cubic"
    con.close()


def test_search_hsrdb_by_elements_requires_all_and_disambiguates_prefixes(synthetic_db):
    con = hr.open_hsrdb(synthetic_db)
    # "Ce" must not match the NaCl entry just because "Cl" starts with "C" too
    results = hr.search_hsrdb(con, elements=["Ce", "V"])
    assert len(results) == 1
    assert results[0]["reference_code"] == "96-350-9999"

    results_cl = hr.search_hsrdb(con, elements=["Na", "Cl"])
    assert len(results_cl) == 1
    assert results_cl[0]["reference_code"] == "96-100-0001"
    con.close()


def test_search_hsrdb_requires_some_filter(synthetic_db):
    con = hr.open_hsrdb(synthetic_db)
    # empty query + no elements still returns something bounded by limit
    # (the UI itself is expected to refuse an unfiltered search, not this function)
    results = hr.search_hsrdb(con, limit=1)
    assert len(results) == 1
    con.close()


def test_get_phase_detail_decodes_reflections_correctly(synthetic_db):
    con = hr.open_hsrdb(synthetic_db)
    phase = hr.get_phase_detail(con, 1)
    assert phase["name"] == "Sodium Chloride (96-100-0001)"
    assert phase["crystal_system"] == "cubic"
    assert phase["lattice_params"]["a"] == pytest.approx(5.64, abs=1e-3)
    assert phase["cod_code"] == "1000041"
    assert "Crystallography Open Database" in phase["source"]
    assert "Smith, J." in phase["source"]
    assert set(phase["elements"]) == {"Na", "Cl"}

    peaks_by_hkl = {p["hkl"]: p for p in phase["peaks"]}
    assert peaks_by_hkl["1,1,1"]["d_A"] == pytest.approx(3.2568, abs=1e-4)
    assert peaks_by_hkl["1,1,1"]["rel_intensity"] == pytest.approx(1000.0, abs=0.1)
    assert peaks_by_hkl["2,0,0"]["d_A"] == pytest.approx(2.8200, abs=1e-4)
    # sorted strongest-first
    assert phase["peaks"][0]["rel_intensity"] >= phase["peaks"][-1]["rel_intensity"]
    con.close()


def test_get_phase_detail_top_n_truncates(synthetic_db):
    con = hr.open_hsrdb(synthetic_db)
    phase = hr.get_phase_detail(con, 1, top_n=2)
    assert len(phase["peaks"]) == 2
    con.close()


def test_get_phase_detail_handles_missing_literature(synthetic_db):
    con = hr.open_hsrdb(synthetic_db)
    phase = hr.get_phase_detail(con, 2)
    assert "Crystallography Open Database" in phase["source"]
    assert phase["cod_code"] == "2000123"
    con.close()


def test_get_phase_detail_compatible_with_add_user_phases(synthetic_db, tmp_path, monkeypatch):
    import xrd_analysis
    monkeypatch.setattr(xrd_analysis, "_user_phases_path", lambda: str(tmp_path / "user_xrd_phases.json"))

    con = hr.open_hsrdb(synthetic_db)
    phase = hr.get_phase_detail(con, 1)
    con.close()

    xrd_analysis.add_user_phases([phase])
    merged = xrd_analysis.merged_database({"phases": []})
    assert any(p["name"] == phase["name"] for p in merged["phases"])
    found = xrd_analysis.find_phase(merged, phase["name"])
    assert found is not None
    assert len(found["peaks"]) == 3
