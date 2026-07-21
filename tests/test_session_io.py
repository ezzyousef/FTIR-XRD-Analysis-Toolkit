import numpy as np
import pytest

import session_io


def test_save_and_load_session_round_trip(tmp_path):
    path = tmp_path / "test.ftirxrd"
    state = {
        "tab": "ftir",
        "mode": "absorbance",
        "traces": [{
            "label": "sample.csv",
            "x": np.array([1.0, 2.0, 3.0]),
            "y": np.array([0.1, 0.9, 0.2]),
            "peaks": [{"x": 2.0, "y": 0.9}],
        }],
    }
    session_io.save_session(str(path), state)
    loaded = session_io.load_session(str(path))
    assert loaded["_format"] == "ftir_xrd_toolkit_session"
    assert loaded["tab"] == "ftir"
    assert loaded["traces"][0]["x"] == [1.0, 2.0, 3.0]
    assert loaded["traces"][0]["peaks"][0]["y"] == 0.9


def test_load_session_rejects_foreign_json(tmp_path):
    path = tmp_path / "not_a_session.json"
    path.write_text('{"some_other_format": true}', encoding="utf-8")
    with pytest.raises(ValueError):
        session_io.load_session(str(path))
