import csv
from types import SimpleNamespace

import numpy as np

import ui_common


def _fake_trace(label, x, y):
    return SimpleNamespace(label=label, x=np.asarray(x, dtype=float), y=np.asarray(y, dtype=float))


def test_export_originlab_csv_single_trace(tmp_path):
    tab = SimpleNamespace(
        traces=[_fake_trace("spec1.csv", [1.0, 2.0, 3.0], [10.0, 20.0, 30.0])],
        x_label="Wavenumber (cm-1)", y_label="Absorbance",
    )
    path = tmp_path / "out.csv"
    ui_common.AnalysisTabBase.export_originlab_csv(tab, str(path))

    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["spec1.csv X", "spec1.csv Y"]
    assert rows[1] == ["Wavenumber (cm-1)", "Absorbance"]
    assert rows[2] == ["1.0", "10.0"]
    assert rows[4] == ["3.0", "30.0"]


def test_export_originlab_csv_multiple_traces_padded(tmp_path):
    tab = SimpleNamespace(
        traces=[
            _fake_trace("short", [1.0, 2.0], [5.0, 6.0]),
            _fake_trace("long", [1.0, 2.0, 3.0], [7.0, 8.0, 9.0]),
        ],
        x_label="2theta (deg)", y_label="Intensity",
    )
    path = tmp_path / "out2.csv"
    ui_common.AnalysisTabBase.export_originlab_csv(tab, str(path))

    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["short X", "short Y", "long X", "long Y"]
    assert rows[1] == ["2theta (deg)", "Intensity", "2theta (deg)", "Intensity"]
    # the shorter trace's row is padded with blanks past its own length
    last_row = rows[-1]
    assert last_row[0] == "" and last_row[1] == ""
    assert last_row[2] == "3.0" and last_row[3] == "9.0"
