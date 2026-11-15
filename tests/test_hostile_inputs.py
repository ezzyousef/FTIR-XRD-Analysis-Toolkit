"""Hostile and malformed files for every importer: each must load correctly or refuse with a
clear message. None may return values that are not in the file, or silently drop data."""
import codecs

import numpy as np
import pytest

import file_readers as fr

ROWS = [(4000.0 - 2.0 * i, round(0.1 + 0.01 * i, 3)) for i in range(20)]
CSV = "wavenumber,absorbance\n" + "".join(f"{x:.1f},{y:.3f}\n" for x, y in ROWS)
XY = "".join(f"{10 + 0.02 * i:.2f} {100 + i}\n" for i in range(30))


def write(tmp_path, name, data):
    p = tmp_path / name
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8", newline="")
    return str(p)


# ------------------------------------------------------------------ empty and binary
@pytest.mark.parametrize("name", ["e.csv", "e.txt", "e.xy", "e.dpt", "e.jdx", "e.uxd", "e.ras", "e.xrdml", "e.raw"])
def test_empty_file_is_refused_and_says_empty(tmp_path, name):
    path = write(tmp_path, name, b"")
    reader = fr.read_ftir_any if name.endswith((".jdx", ".dpt")) else fr.read_any
    with pytest.raises(ValueError, match="(?i)empty"):
        reader(path)


@pytest.mark.parametrize("name", ["b.csv", "b.jdx", "b.uxd", "b.ras"])
def test_binary_file_is_refused_as_binary(tmp_path, name):
    rng = np.random.default_rng(1)
    path = write(tmp_path, name, bytes(rng.integers(0, 256, 4000, dtype=np.uint8)) + b"\x00" * 50)
    reader = fr.read_ftir_any if name.endswith(".jdx") else fr.read_any
    with pytest.raises(ValueError, match="(?i)binary"):
        reader(path)


def test_garbage_bruker_raw_is_refused(tmp_path):
    with pytest.raises(ValueError):
        fr.read_any(write(tmp_path, "g.raw", b"RAW1.01" + b"\xff" * 300))
    with pytest.raises(ValueError):
        fr.read_any(write(tmp_path, "t.raw", b"RAW1.01"))          # truncated header


# ------------------------------------------------------------------ encodings
@pytest.mark.parametrize("codec", ["utf-16", "utf-16-be", "utf-8-sig"])
def test_unicode_with_bom_loads_the_same_values(tmp_path, codec):
    bom = {"utf-16": b"", "utf-16-be": codecs.BOM_UTF16_BE, "utf-8-sig": b""}[codec]
    path = write(tmp_path, "u.csv", bom + CSV.encode(codec))
    r = fr.read_ftir_any(path)
    assert np.allclose(r.x, [x for x, _ in ROWS]) and np.allclose(r.y, [y for _, y in ROWS])


def test_utf16_jcamp_uxd_ras(tmp_path):
    jdx = ("##TITLE=t\n##JCAMP-DX=5.01\n##XUNITS=1/CM\n##YUNITS=ABSORBANCE\n##NPOINTS=5\n"
           "##XYPOINTS=(XY..XY)\n1000,2\n1001,3\n1002,4\n1003,5\n1004,6\n##END=\n")
    assert list(fr.read_ftir_any(write(tmp_path, "u.jdx", jdx.encode("utf-16"))).y) == [2, 3, 4, 5, 6]
    uxd = "; UXD\n_2THETACOUNTS\n" + XY
    assert len(fr.read_any(write(tmp_path, "u.uxd", uxd.encode("utf-16"))).x) == 30
    ras = "*RAS_DATA_START\n*RAS_INT_START\n" + XY + "*RAS_INT_END\n*RAS_DATA_END\n"
    assert len(fr.read_any(write(tmp_path, "u.ras", ras.encode("utf-16"))).x) == 30


# ------------------------------------------------------------------ ragged rows
def test_first_row_wider_than_the_rest_is_refused_with_its_line(tmp_path):
    # Before the fix "1,2,3,4,5" became a data point at x = 1 that is not in the spectrum.
    path = write(tmp_path, "r.csv", "x,y\n1,2,3,4,5\n" + CSV.split("\n", 1)[1])
    with pytest.raises(ValueError, match="line 2"):
        fr.read_ftir_any(path)


def test_mid_file_row_wider_than_the_rest_is_refused_with_its_line(tmp_path):
    lines = CSV.splitlines()
    lines.insert(8, "3987.0,0.5,0.7")
    with pytest.raises(ValueError, match="line 9"):
        fr.read_ftir_any(write(tmp_path, "m.csv", "\n".join(lines) + "\n"))


def test_consistent_extra_columns_load_with_a_warning(tmp_path):
    text = "".join(f"{x:.1f},{y:.3f},{2 * y:.3f}\n" for x, y in ROWS)
    r = fr.read_ftir_any(write(tmp_path, "3.csv", text))
    assert np.allclose(r.y, [y for _, y in ROWS])
    assert "3 values per row" in r.metadata["warning"]


def test_ambiguous_decimal_comma_with_comma_separator_is_flagged(tmp_path):
    # "4000,5,0,25" could be 4000.5;0.25 or four numbers: never silently pick one.
    text = "".join(f"{int(x)},5,0,{i + 10}\n" for i, (x, _) in enumerate(ROWS))
    r = fr.read_ftir_any(write(tmp_path, "dc.csv", text))
    assert "4 values per row" in r.metadata["warning"]


def test_decimal_comma_with_semicolons_tabs_and_spaces(tmp_path):
    for sep in (";", "\t", " "):
        text = "".join(f"{x:.1f}{sep}{y:.3f}\n".replace(".", ",") for x, y in ROWS)
        r = fr.read_ftir_any(write(tmp_path, "d.csv", text))
        assert np.allclose(r.y, [y for _, y in ROWS]), sep
        assert "warning" not in r.metadata


# ------------------------------------------------------------------ NaN, inf, huge lines
@pytest.mark.parametrize("token", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_non_finite_rows_are_dropped_and_reported_not_truncating_the_file(tmp_path, token):
    lines = CSV.splitlines()
    lines[6] = f"3990.0,{token}"                       # file line 7
    r = fr.read_ftir_any(write(tmp_path, "n.csv", "\n".join(lines) + "\n"))
    assert len(r.x) == 19 and np.isfinite(r.y).all()  # before: only 14 rows (the longest block) survived
    assert "line 7" in r.metadata["warning"] and "1 row" in r.metadata["warning"]


@pytest.mark.parametrize("name, text", [
    ("n.uxd", "_2THETACOUNTS\n" + XY.replace("103\n", "nan\n")),
    ("n.ras", "*RAS_INT_START\n" + XY.replace("103\n", "inf\n") + "*RAS_INT_END\n"),
])
def test_non_finite_values_in_xrd_text_formats(tmp_path, name, text):
    r = fr.read_any(write(tmp_path, name, text))
    assert len(r.x) == 29 and np.isfinite(r.y).all() and "non-finite" in r.metadata["warning"]


def test_non_finite_values_in_xrdml(tmp_path):
    text = ('<?xml version="1.0"?><xrdMeasurements xmlns="http://www.xrdml.com/XRDMeasurement/1.5">'
            '<xrdMeasurement><scan><dataPoints><positions axis="2Theta" unit="deg">'
            '<startPosition>10</startPosition><endPosition>10.5</endPosition></positions>'
            '<counts unit="counts">10 20 NaN 40 50 60</counts></dataPoints></scan></xrdMeasurement></xrdMeasurements>')
    r = fr.read_any(write(tmp_path, "n.xrdml", text))
    assert len(r.x) == 5 and np.isfinite(r.y).all() and r.x[3] == pytest.approx(10.4)


def test_scattered_numeric_blocks_warn_the_user(tmp_path):
    text = CSV + "Peak table\n1700,0.8\n1650,0.4\n"
    r = fr.read_ftir_any(write(tmp_path, "b.csv", text))
    assert len(r.x) == 20 and "ignored" in r.metadata["warning"]


def test_huge_line_does_not_break_parsing(tmp_path):
    r = fr.read_ftir_any(write(tmp_path, "h.csv", "comment " + "9" * 2_000_000 + "\n" + CSV))
    assert len(r.x) == 20


def test_oversized_file_is_refused_before_reading(tmp_path, monkeypatch):
    monkeypatch.setattr(fr, "MAX_FILE_BYTES", 100)
    with pytest.raises(ValueError, match="(?i)too large"):
        fr.read_ftir_any(write(tmp_path, "big.csv", CSV))


# ------------------------------------------------------------------ XML and JCAMP specifics
def test_malformed_xrdml_gives_a_value_error(tmp_path):
    with pytest.raises(ValueError, match="(?i)xml"):
        fr.read_any(write(tmp_path, "bad.xrdml", "<xrdMeasurements><scan>"))


def test_xml_entity_expansion_is_refused(tmp_path):
    lol = ('<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa">'
           + "".join(f'<!ENTITY {chr(98 + i)} "{("&" + chr(97 + i) + ";") * 10}">' for i in range(8))
           + ']><xrdMeasurements><dataPoints><counts>&i;</counts></dataPoints></xrdMeasurements>')
    with pytest.raises(ValueError):
        fr.read_any(write(tmp_path, "lol.xrdml", lol))


def test_jcamp_micrometre_axis_is_converted_to_wavenumber(tmp_path):
    jdx = ("##TITLE=t\n##JCAMP-DX=5.01\n##XUNITS=MICROMETERS\n##YUNITS=ABSORBANCE\n##NPOINTS=5\n"
           "##XYPOINTS=(XY..XY)\n2.5,1\n5,2\n10,3\n20,4\n25,5\n##END=\n")
    r = fr.read_ftir_any(write(tmp_path, "um.jdx", jdx))
    assert np.allclose(r.x, [4000.0, 2000.0, 1000.0, 500.0, 400.0])     # nu = 10^4 / lambda(um)
    assert list(r.y) == [1, 2, 3, 4, 5] and "CM" in r.x_label.upper() and "converted" in r.metadata["warning"]


def test_jcamp_dif_y_check_value_is_not_counted_twice(tmp_path):
    # JCAMP-DX: in DIF form the last ordinate of a line is repeated as the first ordinate of
    # the next line (Y-value check). Values: 10 12 15 14 | 14 16 18 -> 6 points.
    jdx = ("##TITLE=t\n##JCAMP-DX=5.01\n##XUNITS=1/CM\n##YUNITS=ABSORBANCE\n##FIRSTX=1000\n##LASTX=1005\n"
           "##NPOINTS=6\n##XYDATA=(X++(Y..Y))\n1000 A0KLj\n1003 A4KK\n##END=\n")
    r = fr.read_ftir_any(write(tmp_path, "dif.jdx", jdx))
    assert list(r.y) == [10, 12, 15, 14, 16, 18]
    assert r.x[0] == pytest.approx(1000.0) and r.x[-1] == pytest.approx(1005.0)


def test_jcamp_dif_y_check_mismatch_is_refused(tmp_path):
    jdx = ("##TITLE=t\n##XUNITS=1/CM\n##FIRSTX=1000\n##LASTX=1005\n##NPOINTS=6\n"
           "##XYDATA=(X++(Y..Y))\n1000 A0KLj\n1003 A9KK\n##END=\n")
    with pytest.raises(ValueError, match="(?i)check"):
        fr.read_ftir_any(write(tmp_path, "bad.jdx", jdx))


def test_jcamp_bad_header_number_is_a_value_error(tmp_path):
    jdx = "##TITLE=t\n##XFACTOR=abc\n##XYPOINTS=(XY..XY)\n1,2\n2,3\n3,4\n4,5\n5,6\n##END=\n"
    with pytest.raises(ValueError, match="XFACTOR"):
        fr.read_ftir_any(write(tmp_path, "h.jdx", jdx))


def test_jcamp_firstx_is_an_actual_value_when_xfactor_is_not_one(tmp_path):
    # JCAMP-DX 4.24: FIRSTX/LASTX are actual abscissae; the X starting each data line is raw
    # and is multiplied by XFACTOR. Raw 2000 x 0.5 = 1000 = FIRSTX.
    jdx = ("##TITLE=t\n##XUNITS=1/CM\n##XFACTOR=0.5\n##YFACTOR=1\n##FIRSTX=1000\n##LASTX=1004\n##NPOINTS=5\n"
           "##XYDATA=(X++(Y..Y))\n2000 1 2 3 4 5\n##END=\n")
    r = fr.read_ftir_any(write(tmp_path, "xf.jdx", jdx))
    assert np.allclose(r.x, [1000, 1001, 1002, 1003, 1004])
