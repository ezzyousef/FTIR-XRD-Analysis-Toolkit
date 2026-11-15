"""Regression tests for the independent Codex review of the 3.4 upgrade
(AI_Engineering_Knowledge_Base/reports/codex/04-ftir-upgrade-review.md). Each uses the
concrete input from the review and failed on 9ad6ace."""
import math

import numpy as np
import pytest

import file_readers as fr
import ftir_analysis as fa
import xrd_tools as xt


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8", newline="")
    return str(p)


JDX_HEAD = "##TITLE=t\n##JCAMP-DX=5.01\n##XUNITS=1/CM\n##YUNITS=ABSORBANCE\n"


# 1 (High) JCAMP-DX line-leading X values must match the axis
def test_jcamp_corrupt_line_x_is_refused(tmp_path):
    jdx = JDX_HEAD + "##FIRSTX=1000\n##LASTX=1005\n##NPOINTS=6\n##XYDATA=(X++(Y..Y))\n1000 A0KLj\n9999 A4KK\n##END=\n"
    with pytest.raises(ValueError, match="(?i)x-value check|abscissa"):
        fr.read_ftir_any(write(tmp_path, "bad_x.jdx", jdx))


def test_jcamp_correct_line_x_with_dif_overlap_and_plain_lines_load(tmp_path):
    dif = JDX_HEAD + "##FIRSTX=1000\n##LASTX=1005\n##NPOINTS=6\n##XYDATA=(X++(Y..Y))\n1000 A0KLj\n1003 A4KK\n##END=\n"
    assert list(fr.read_ftir_any(write(tmp_path, "ok.jdx", dif)).y) == [10, 12, 15, 14, 16, 18]
    plain = (JDX_HEAD + "##FIRSTX=4000\n##LASTX=3990\n##NPOINTS=6\n##XYDATA=(X++(Y..Y))\n"
             "4000 1 2 3\n3994 4 5 6\n##END=\n")
    r = fr.read_ftir_any(write(tmp_path, "plain.jdx", plain))
    assert list(r.y) == [1, 2, 3, 4, 5, 6] and r.x[3] == pytest.approx(3994.0)
    shifted = plain.replace("3994 4 5 6", "3980 4 5 6")
    with pytest.raises(ValueError, match="(?i)x-value check|abscissa"):
        fr.read_ftir_any(write(tmp_path, "shifted.jdx", shifted))


# 2 (Medium) XYPOINTS: FIRSTX/LASTX are physical values; data pairs are scaled by XFACTOR
def test_jcamp_xypoints_with_xfactor_and_physical_firstx(tmp_path):
    jdx = (JDX_HEAD + "##XFACTOR=0.5\n##FIRSTX=1000\n##LASTX=1004\n##NPOINTS=5\n##XYPOINTS=(XY..XY)\n"
           "2000,1\n2002,2\n2004,3\n2006,4\n2008,5\n##END=\n")
    r = fr.read_ftir_any(write(tmp_path, "xyp.jdx", jdx))
    assert np.allclose(r.x, [1000, 1001, 1002, 1003, 1004]) and list(r.y) == [1, 2, 3, 4, 5]


def test_jcamp_xypoints_at_the_wrong_position_is_refused(tmp_path):
    # same span as declared, but 500 cm-1 away: span-only checks missed it
    jdx = (JDX_HEAD + "##FIRSTX=1500\n##LASTX=1504\n##NPOINTS=5\n##XYPOINTS=(XY..XY)\n"
           "1000,1\n1001,2\n1002,3\n1003,4\n1004,5\n##END=\n")
    with pytest.raises(ValueError, match="FIRSTX"):
        fr.read_ftir_any(write(tmp_path, "pos.jdx", jdx))


# 3 (Medium) multi-digit DUP counts
def test_jcamp_multi_digit_dup_count():
    # A0 = 10, J = +1, T0 = DUP count 20: the +1 step appears 20 times -> 10, 11, ..., 30
    x, vals = fr._jcamp_decode_asdf_line("1000 A0JT0")
    assert vals == [float(v) for v in range(10, 31)]
    _, flat = fr._jcamp_decode_asdf_line("0 E0S2")          # 50 repeated 12 times in total (S2 = 12)
    assert flat == [50.0] * 12


# 4 (Medium) delimited rows must match the header width
def test_rows_wider_than_the_header_are_refused(tmp_path):
    text = "x,y\n" + "".join(f"{i},NaN,{10 * i}\n" for i in range(1, 6))
    with pytest.raises(ValueError, match="header"):
        fr.read_ftir_any(write(tmp_path, "w.csv", text))


def test_rows_narrower_than_the_rest_are_refused(tmp_path):
    rows = [f"{4000 - 2 * i},{0.1 + 0.01 * i:.3f},{0.2:.3f}" for i in range(10)]
    rows[4] = "3992,0.140"
    with pytest.raises(ValueError, match="line 5"):
        fr.read_ftir_any(write(tmp_path, "n.csv", "\n".join(rows) + "\n"))


def test_header_and_rows_of_equal_width_still_load(tmp_path):
    text = "x;y;z\n" + "".join(f"{i},5;{i},25;1\n" for i in range(1, 7))
    r = fr.read_ftir_any(write(tmp_path, "ok.csv", text))
    assert r.x[0] == pytest.approx(1.5) and r.y[0] == pytest.approx(1.25)


# 5 (Medium) derivatives on non-uniform axes
def test_derivative_on_a_micrometre_converted_axis():
    x = 10000.0 / np.linspace(2.5, 25.0, 31)        # uneven in cm-1, as after a MICROMETERS import
    d1 = fa.derivative_spectrum(x, x.copy(), order=1)
    assert np.allclose(d1, 1.0, atol=1e-9)
    y = 2e-6 * x ** 2
    d2 = fa.derivative_spectrum(x, y, order=2)
    assert np.allclose(d2, 4e-6, rtol=1e-6)
    assert "actual" in fa.derivative_method(x)


def test_derivative_across_a_gap_from_dropped_rows():
    x = np.delete(np.arange(400.0, 1200.0, 2.0), np.arange(100, 110))   # 10 NaN rows removed
    y = 3e-6 * x ** 3
    d1 = fa.derivative_spectrum(x, y, order=1, window_length=15, polyorder=3)
    assert np.allclose(d1, 9e-6 * x ** 2, rtol=1e-6)


# 6 (Medium) displacement calibration must be identifiable
def test_displacement_calibration_rejects_a_single_angle():
    d = 1.5406 / (2 * math.sin(math.radians(15)))
    with pytest.raises(ValueError, match="(?i)angle"):
        xt.calibrate([30.1, 30.1], [d, d], 1.5406, displacement=True)


def test_displacement_calibration_warns_on_narrow_coverage():
    lam = 1.5406
    true = [28.0, 30.0, 32.0]
    d = [lam / (2 * math.sin(math.radians(t / 2))) for t in true]
    cal = xt.calibrate([t + 0.02 for t in true], d, lam, displacement=True)
    assert cal["warnings"] and "coverage" in cal["warnings"][0]
    wide = [20.0, 50.0, 90.0, 120.0]
    d = [lam / (2 * math.sin(math.radians(t / 2))) for t in wide]
    assert xt.calibrate([t + 0.02 for t in wide], d, lam, displacement=True)["warnings"] == []
