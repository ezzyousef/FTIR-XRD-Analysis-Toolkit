"""A table view for long data: only the visible cells are ever formatted.

`ResultTable` (widgets.py) creates one item per cell, which is right for a few hundred result
rows. A spectrum or a logged run has 10^5 to 10^6 rows: `DataTable` shows those through a model,
so opening it costs the same for ten rows or ten million.

    table = DataTable(accessible_name="Measured data")
    table.set_data(["Time [s]", "Torque [%]"], [times, torque])     # sequences or numpy arrays, by column
"""
from __future__ import annotations

import math
from typing import Any, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import QAbstractItemView, QTableView

from ..figure import format_number
from ..units import split_label


class ColumnTableModel(QAbstractTableModel):
    """Read-only model over equal-length columns. Values are formatted on demand."""

    def __init__(self, headers: Sequence[str] = (), columns: Sequence[Sequence[Any]] = (), digits: int = 6, parent=None):
        super().__init__(parent)
        self._digits = digits
        self._headers: list[str] = []
        self._columns: list[Sequence[Any]] = []
        self.set_data(headers, columns)

    def set_data(self, headers: Sequence[str], columns: Sequence[Sequence[Any]]) -> None:
        if len(headers) != len(columns):
            raise ValueError(f"{len(headers)} headers for {len(columns)} columns")
        lengths = {len(c) for c in columns}
        if len(lengths) > 1:
            raise ValueError(f"columns have different lengths: {sorted(lengths)}")
        self.beginResetModel()
        self._headers, self._columns = list(headers), list(columns)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 - Qt naming
        return 0 if parent.isValid() or not self._columns else len(self._columns[0])

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._columns)

    def text(self, row: int, column: int) -> str:
        value = self._columns[column][row]
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if math.isnan(number):
            return ""                       # missing data is shown as an empty cell, never as "nan"
        return format_number(number, self._digits)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole):
            return self.text(index.row(), index.column())
        if role == Qt.ItemDataRole.TextAlignmentRole:
            numeric = not isinstance(self._columns[index.column()][index.row()], str)
            return int((Qt.AlignmentFlag.AlignRight if numeric else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole and self.text(index.row(), index.column()) == "":
            return "Missing value"
        return None

    def headerData(self, section: int, orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self._headers):
            if role == Qt.ItemDataRole.DisplayRole:
                return self._headers[section]
            if role == Qt.ItemDataRole.AccessibleTextRole:
                label, unit = split_label(self._headers[section])
                return f"{label}, in {unit}" if unit else label
        if orientation == Qt.Orientation.Vertical and role == Qt.ItemDataRole.DisplayRole:
            return str(section + 1)
        return None


class DataTable(QTableView):
    """Keyboard-friendly, screen-reader-named table for long data. Ctrl+C copies the selection
    as tab-separated text (with headers), ready for Excel or Origin."""

    def __init__(self, accessible_name: str = "Data table", digits: int = 6, parent=None):
        super().__init__(parent)
        self._model = ColumnTableModel(digits=digits, parent=self)
        self.setModel(self._model)
        self.setAccessibleName(accessible_name)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setTabKeyNavigation(False)          # Tab leaves the table; arrows move inside it
        self.setWordWrap(False)
        self.verticalHeader().setDefaultSectionSize(26)
        self.horizontalHeader().setStretchLastSection(True)

    def set_data(self, headers: Sequence[str], columns: Sequence[Sequence[Any]]) -> None:
        self._model.set_data(headers, columns)
        rows = self._model.rowCount()
        self.setAccessibleDescription(f"{rows} rows, {len(headers)} columns: {', '.join(headers)}")
        self.fit_columns()

    def fit_columns(self, sample_rows: int = 200, padding: int = 28) -> None:
        """Make every column wide enough for its full header and a sample of its values, without
        measuring all rows (which would make a million-row table slow to open)."""
        header_fm = self.horizontalHeader().fontMetrics()
        cell_fm = self.fontMetrics()
        rows = min(sample_rows, self._model.rowCount())
        for c in range(self._model.columnCount()):
            title = self._model.headerData(c, Qt.Orientation.Horizontal) or ""
            widest = header_fm.horizontalAdvance(title)
            for r in range(rows):
                widest = max(widest, cell_fm.horizontalAdvance(self._model.text(r, c)))
            self.setColumnWidth(c, widest + padding)

    def selection_as_text(self, with_headers: bool = True) -> str:
        indexes = sorted(self.selectedIndexes(), key=lambda i: (i.row(), i.column()))
        if not indexes:
            return ""
        cols = sorted({i.column() for i in indexes})
        by_row: dict[int, dict[int, str]] = {}
        for i in indexes:
            by_row.setdefault(i.row(), {})[i.column()] = self._model.text(i.row(), i.column())
        lines = ["\t".join(self._model.headerData(c, Qt.Orientation.Horizontal) for c in cols)] if with_headers else []
        lines += ["\t".join(cells.get(c, "") for c in cols) for _, cells in sorted(by_row.items())]
        return "\n".join(lines)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.matches(QKeySequence.StandardKey.Copy):
            text = self.selection_as_text()
            if text:
                QGuiApplication.clipboard().setText(text)
            event.accept()
            return
        super().keyPressEvent(event)
