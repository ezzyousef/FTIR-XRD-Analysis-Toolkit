import sqlite3

import pytest

import cod_database as cd


def _build_synthetic_cod_db(path, phases):
    """
    Build a tiny SQLite file with the exact schema scripts/build_cod_database.py
    produces (phases/peaks/phases_fts), so tests don't depend on the real
    ~1.6GB bundled database. Each phase: dict with id, name, reference_code,
    category, crystal_system, cell (a,b,c,alpha,beta,gamma), space_group,
    elements (list), cod_code, source, peaks (list of (d_A, hkl, rel_intensity)).
    """
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE phases (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, reference_code TEXT, category TEXT,
        crystal_system TEXT, a REAL, b REAL, c REAL, alpha REAL, beta REAL, gamma REAL,
        space_group TEXT, elements TEXT, cod_code TEXT, source TEXT, n_peaks_total INTEGER
    )""")
    con.execute("CREATE TABLE peaks (phase_id INTEGER, d_A REAL, hkl TEXT, rel_intensity REAL)")
    con.execute("CREATE VIRTUAL TABLE phases_fts USING fts3(phase_id UNINDEXED, name, elements, formula)")

    for p in phases:
        els = ",".join(p["elements"])
        con.execute("INSERT INTO phases VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            p["id"], p["name"], p["reference_code"], p["category"], p["crystal_system"],
            *p["cell"], p.get("space_group", ""), els, p.get("cod_code", ""), p.get("source", ""),
            len(p["peaks"]),
        ))
        for d_a, hkl, inten in p["peaks"]:
            con.execute("INSERT INTO peaks VALUES (?,?,?,?)", (p["id"], d_a, hkl, inten))
        con.execute("INSERT INTO phases_fts (phase_id, name, elements, formula) VALUES (?,?,?,?)",
                    (p["id"], p["name"], els, p.get("formula", els)))
    con.execute("CREATE INDEX idx_peaks_phase ON peaks(phase_id)")
    con.execute("CREATE INDEX idx_peaks_d ON peaks(d_A)")
    con.execute("CREATE INDEX idx_peaks_intensity_d ON peaks(rel_intensity, d_A)")
    con.commit()
    con.close()


QUARTZ = {
    "id": 1, "name": "Quartz", "reference_code": "96-100-0001", "category": "oxide_or_mineral",
    "crystal_system": "hexagonal", "cell": (4.998, 4.998, 5.460, 90.0, 90.0, 120.0),
    "space_group": "P 32 2 1", "elements": ["Si", "O"], "cod_code": "1100019",
    "source": "Crystallography Open Database (COD) entry 1100019; Wright, A F, Lehmann, M S, 1981",
    "peaks": [(3.39188, "1,0,1", 1000.0), (4.32839, "1,0,0", 187.1), (1.84332, "1,1,2", 176.1),
              (1.56714, "2,1,1", 82.5), (1.39293, "2,0,3", 80.44)],
}

NACL = {
    "id": 2, "name": "Sodium Chloride", "reference_code": "96-200-0001", "category": "halide_salt",
    "crystal_system": "cubic", "cell": (5.64, 5.64, 5.64, 90.0, 90.0, 90.0),
    "space_group": "F m -3 m", "elements": ["Na", "Cl"], "cod_code": "1000041",
    "source": "Crystallography Open Database (COD) entry 1000041",
    "peaks": [(3.2568, "1,1,1", 1000.0), (2.8200, "2,0,0", 550.0), (1.9942, "2,2,0", 150.0)],
}

CEVO4 = {
    "id": 3, "name": "Cerium Vanadate", "reference_code": "96-350-9999", "category": "oxide_or_mineral",
    "crystal_system": "tetragonal", "cell": (7.4009, 7.4009, 6.4966, 90.0, 90.0, 90.0),
    "space_group": "I 41/a m d", "elements": ["Ce", "V", "O"], "cod_code": "2000123",
    "source": "Crystallography Open Database (COD) entry 2000123",
    "peaks": [(4.8824, "1,0,1", 1000.0), (3.7005, "2,0,0", 400.0)],
}


@pytest.fixture
def synthetic_db(tmp_path):
    path = str(tmp_path / "synthetic_cod.sqlite")
    _build_synthetic_cod_db(path, [QUARTZ, NACL, CEVO4])
    return path


def test_open_db_accepts_valid_file(synthetic_db):
    con = cd.open_db(synthetic_db)
    assert cd.count_phases(con) == 3


def test_open_db_rejects_missing_file():
    with pytest.raises(ValueError):
        cd.open_db("does_not_exist.sqlite")


def test_open_db_rejects_wrong_schema(tmp_path):
    path = str(tmp_path / "wrong.sqlite")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE unrelated(x INTEGER)")
    con.commit()
    con.close()
    with pytest.raises(ValueError):
        cd.open_db(path)


def test_search_by_text_query(synthetic_db):
    con = cd.open_db(synthetic_db)
    results = cd.search(con, query="quartz")
    assert len(results) == 1
    assert results[0]["name"] == "Quartz"
    assert results[0]["crystal_system"] == "hexagonal"


def test_search_by_elements_disambiguates_prefixes(synthetic_db):
    con = cd.open_db(synthetic_db)
    # "Ce" must not match NaCl just because "Cl" also starts with "C"
    results = cd.search(con, elements=["Ce", "V"])
    assert len(results) == 1
    assert results[0]["name"] == "Cerium Vanadate"

    results_nacl = cd.search(con, elements=["Na", "Cl"])
    assert len(results_nacl) == 1
    assert results_nacl[0]["name"] == "Sodium Chloride"


def test_search_by_category(synthetic_db):
    con = cd.open_db(synthetic_db)
    results = cd.search(con, category="halide_salt")
    assert len(results) == 1
    assert results[0]["name"] == "Sodium Chloride"


def test_get_phase_returns_full_peak_list(synthetic_db):
    con = cd.open_db(synthetic_db)
    phase = cd.get_phase(con, 1)
    assert phase["name"] == "Quartz"
    assert phase["lattice_params"]["a"] == pytest.approx(4.998)
    assert len(phase["peaks"]) == 5
    assert phase["peaks"][0]["rel_intensity"] == pytest.approx(1000.0)  # sorted strongest-first


def test_get_phase_top_n_truncates(synthetic_db):
    con = cd.open_db(synthetic_db)
    phase = cd.get_phase(con, 1, top_n=2)
    assert len(phase["peaks"]) == 2


def test_match_by_peaks_ranks_true_match_first(synthetic_db):
    con = cd.open_db(synthetic_db)
    observed = [{"d_A": d, "y": inten} for d, hkl, inten in QUARTZ["peaks"]]
    matches = cd.match_by_peaks(con, observed, d_tolerance_pct=1.0, top_n_ref_peaks=10)
    assert matches
    assert matches[0]["name"] == "Quartz"
    assert matches[0]["cod_phase_id"] == 1
    assert matches[0]["matched_count"] == 5


def test_match_by_peaks_no_match_returns_empty(synthetic_db):
    con = cd.open_db(synthetic_db)
    # a d-spacing that matches nothing in this tiny synthetic database
    matches = cd.match_by_peaks(con, [{"d_A": 99.0, "y": 100}], d_tolerance_pct=1.0)
    assert matches == []


def test_match_by_peaks_respects_category_filter(synthetic_db):
    con = cd.open_db(synthetic_db)
    observed = [{"d_A": d, "y": inten} for d, hkl, inten in QUARTZ["peaks"]]
    matches = cd.match_by_peaks(con, observed, d_tolerance_pct=1.0, categories=["halide_salt"])
    assert all(m["category"] == "halide_salt" for m in matches)
    assert not any(m["name"] == "Quartz" for m in matches)


def test_hsrdb_reader_compatible_aliases_exist(synthetic_db):
    # ui_common.HsrdbImportDialog uses these names interchangeably with
    # hsrdb_reader.py -- make sure the alias surface stays intact.
    con = cd.open_hsrdb(synthetic_db)
    assert cd.count_entries(con) == 3
    results = cd.search_hsrdb(con, query="quartz")
    assert len(results) == 1
    assert "compound_name" in results[0] and "formula" in results[0]
    phase = cd.get_phase_detail(con, results[0]["id"])
    assert phase["name"] == "Quartz"


def test_get_phase_detail_compatible_with_add_user_phases(synthetic_db, tmp_path, monkeypatch):
    import xrd_analysis
    monkeypatch.setattr(xrd_analysis, "_user_phases_path", lambda: str(tmp_path / "user_xrd_phases.json"))

    con = cd.open_db(synthetic_db)
    phase = cd.get_phase(con, 3)  # CeVO4
    xrd_analysis.add_user_phases([phase])
    merged = xrd_analysis.merged_database({"phases": []})
    found = xrd_analysis.find_phase(merged, phase["name"])
    assert found is not None
    assert len(found["peaks"]) == 2
