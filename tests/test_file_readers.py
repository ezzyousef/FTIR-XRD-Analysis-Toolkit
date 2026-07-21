import pytest

import file_readers as fr


def test_jcamp_decode_sqz_dup_matches_published_example():
    # External ground-truth example from the JCAMP-DX literature (pseudo-digit
    # table): "50 50 50 50" encodes as SQZ 'E' (=5) + plain '0' + DUP 'V' (=4).
    x, vals = fr._jcamp_decode_asdf_line("1000 E0V")
    assert x == 1000.0
    assert vals == [50.0, 50.0, 50.0, 50.0]


def test_jcamp_decode_difdup_continues_the_ramp():
    # DIFDUP: absolute 1000, then DIF '+2' (K), then DUP 'U' (=3) repeats
    # that SAME delta 2 more times -- continuing a linear ramp, not
    # flat-repeating the value (the standard "DIFDUP" compression form).
    x, vals = fr._jcamp_decode_asdf_line("0 1000KU")
    assert vals == [1000.0, 1002.0, 1004.0, 1006.0]


def test_jcamp_decode_plain_and_dif_chain():
    x, vals = fr._jcamp_decode_asdf_line("100 1 2 3 4")
    assert vals == [1.0, 2.0, 3.0, 4.0]

    # DIF-only chain: 10, +2->12, +3->15, -1->14
    x2, vals2 = fr._jcamp_decode_asdf_line("0 10K L j")
    assert vals2 == [10.0, 12.0, 15.0, 14.0]


def test_read_jcampdx_xydata_end_to_end(tmp_path):
    content = (
        "##TITLE=Test Spectrum\n"
        "##JCAMP-DX=5.01\n"
        "##XUNITS=1/CM\n"
        "##YUNITS=TRANSMITTANCE\n"
        "##FIRSTX=4000\n"
        "##LASTX=3600\n"
        "##NPOINTS=5\n"
        "##XFACTOR=1\n"
        "##YFACTOR=1\n"
        "##XYDATA=(X++(Y..Y))\n"
        "4000 100 J K L M\n"
        "##END=\n"
    )
    path = tmp_path / "test.jdx"
    path.write_text(content, encoding="utf-8")

    result = fr.read_jcampdx(str(path))
    assert len(result.x) == 5
    assert list(result.y) == [100.0, 101.0, 103.0, 106.0, 110.0]
    assert result.x[0] == pytest.approx(4000.0)
    assert result.x[-1] == pytest.approx(3600.0)
    assert result.x_label == "1/CM"
    assert result.y_label == "TRANSMITTANCE"
    assert result.confidence == "high"


def test_read_jcampdx_xypoints_variant(tmp_path):
    content = (
        "##TITLE=Simple Points Test\n"
        "##XUNITS=1/CM\n"
        "##YUNITS=ABSORBANCE\n"
        "##XYPOINTS=(XY..XY)\n"
        "4000,0.1 3900,0.2 3800,0.15\n"
        "##END=\n"
    )
    path = tmp_path / "test2.jdx"
    path.write_text(content, encoding="utf-8")

    result = fr.read_jcampdx(str(path))
    assert list(result.x) == [4000.0, 3900.0, 3800.0]
    assert list(result.y) == [0.1, 0.2, 0.15]


def test_read_jcampdx_rejects_npoints_mismatch(tmp_path):
    content = (
        "##FIRSTX=4000\n##LASTX=3600\n##NPOINTS=99\n"
        "##XYDATA=(X++(Y..Y))\n4000 100 J K L M\n##END=\n"
    )
    path = tmp_path / "bad.jdx"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="NPOINTS"):
        fr.read_jcampdx(str(path))


def test_read_jcampdx_requires_a_data_block(tmp_path):
    path = tmp_path / "empty.jdx"
    path.write_text("##TITLE=Nothing here\n##END=\n", encoding="utf-8")
    with pytest.raises(ValueError):
        fr.read_jcampdx(str(path))


def test_read_ftir_any_dispatches_jdx_and_generic(tmp_path):
    jdx_content = (
        "##FIRSTX=10\n##LASTX=12\n##NPOINTS=3\n"
        "##XYDATA=(X++(Y..Y))\n10 1 2 3\n##END=\n"
    )
    jdx_path = tmp_path / "spec.jdx"
    jdx_path.write_text(jdx_content, encoding="utf-8")
    result = fr.read_ftir_any(str(jdx_path))
    assert list(result.y) == [1.0, 2.0, 3.0]

    csv_path = tmp_path / "spec.csv"
    csv_path.write_text("1,2\n2,3\n3,4\n4,5\n5,6\n", encoding="utf-8")
    result2 = fr.read_ftir_any(str(csv_path))
    assert len(result2.x) == 5

    with pytest.raises(ValueError):
        fr.read_ftir_any(str(tmp_path / "spec.unknownext"))


def test_read_ftir_any_dispatches_dpt(tmp_path):
    # Bruker OPUS ASCII export format: comma-separated wavenumber,absorbance, no header.
    dpt_path = tmp_path / "spec.dpt"
    dpt_path.write_text("4000.0,0.010\n3999.5,0.011\n3999.0,0.012\n3998.5,0.013\n3998.0,0.014\n", encoding="utf-8")
    result = fr.read_ftir_any(str(dpt_path))
    assert len(result.x) == 5
    assert result.x[0] == pytest.approx(4000.0)
    assert result.y[-1] == pytest.approx(0.014)
